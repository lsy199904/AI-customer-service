"""Policy regression: real storage, rolling enterprise quota and bounded retrieval."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import tempfile
import threading
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.core import Settings,Service,APIError,issue_token
from app.rag import RAGSettings
from app.server import create_app
from app.deadlines import run,remaining,RetrievalTimeout
SECRET='policy-test-secret-abcdefghijklmnopqrstuvwxyz'
A={'tenant_id':'company','sub':'a'}
B={'tenant_id':'company','sub':'b'}
C={'tenant_id':'other','sub':'a'}

class Policies(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory()
  self.c=Settings(retrieval_backend='lexical',secret=SECRET,db=str(Path(self.temp.name)/'chat.db'))
  self.s=Service(self.c);self.sid=self.s.create(A,{})['session_id']
 def tearDown(self):self.s.close();self.temp.cleanup()
 def test_defaults_and_validation(self):
  with patch.dict(os.environ,{},clear=True):
   c=Settings();rag=RAGSettings()
   self.assertEqual((c.retention_days,c.context_rounds,c.requests_per_minute,c.retrieval_timeout),(7,20,20,15))
   self.assertEqual(rag.min_similarity,.75)
  for key,value in [('retention_days',0),('context_rounds',0),('requests_per_minute',0),('retrieval_timeout',float('nan'))]:
   c=Settings(secret=SECRET,**{key:value})
   with self.assertRaises(ValueError):c.validate()
 def test_enterprise_quota_rolling_window(self):
  with patch('app.core.time.time',return_value=1000.):
   for i in range(20):self.s.rate(A if i%2 else B)
   with self.assertRaises(APIError) as e:self.s.rate(B)
   self.assertEqual((e.exception.status,e.exception.code),(429,'tenant_rate_limited'))
   self.s.rate(C)
  with patch('app.core.time.time',return_value=1020.):
   with self.assertRaises(APIError):self.s.rate(A) # calendar minute changes are irrelevant
  with patch('app.core.time.time',return_value=1060.):self.s.rate(B)
 def test_quota_shared_between_service_instances(self):
  other=Service(self.c)
  try:
   def attempt(i):
    try:(self.s if i%2 else other).rate(A if i%3 else B);return True
    except APIError:return False
   with ThreadPoolExecutor(max_workers=8) as pool:self.assertEqual(sum(pool.map(attempt,range(30))),20)
  finally:other.close()
 def test_create_does_not_count_and_cached_retry_does_not_count(self):
  self.c.requests_per_minute=1
  with TestClient(create_app(self.c,service=self.s)) as client:
   headers={'Authorization':'Bearer '+issue_token(SECRET,A['tenant_id'],A['sub'])}
   for _ in range(3):self.assertEqual(client.post('/v1/sessions',headers=headers,json={}).status_code,201)
   body={'message':'你好','request_id':'quota-cache-001'};url='/v1/sessions/'+self.sid+'/messages'
   first=client.post(url,headers=headers,json=body);self.assertEqual(first.status_code,200)
   self.assertEqual(client.post(url,headers=headers,json=body).json(),first.json())
   self.assertEqual(client.post(url,headers=headers,json={**body,'request_id':'quota-cache-002'}).status_code,429)
 def test_context_twenty_rounds_history_is_not_truncated(self):
  calls=[]
  class Fake:
   def answer(self,q,h,e,c):calls.append(h);return {'answerable':True,'answer':'您好！','citation_ids':[],'image_ids':[]}
  self.c.mode='llm';self.c.requests_per_minute=100;self.s.model=Fake()
  for i in range(24):self.s.chat(A,self.sid,{'message':'你好','request_id':'context-round-%03d'%i})
  self.assertEqual([len(h) for h in calls[:3]],[0,2,4]);self.assertEqual(len(calls[-1]),40)
  self.assertEqual(len(self.s.history(A,self.sid)['items']),48)
  self.assertEqual(len(self.s.context_history(A,self.sid)),40)
 def test_idle_segment_is_not_reintroduced(self):
  self.s.chat(A,self.sid,{'message':'你好','request_id':'idle-segment-001'})
  with self.s.db:
   self.s.db.execute('UPDATE messages SET created=?',(time.time()-2000,))
   self.s.db.execute('UPDATE sessions SET updated=?',(time.time()-2000,))
  self.s.chat(A,self.sid,{'message':'你好','request_id':'idle-segment-002'})
  self.assertEqual(len(self.s.context_history(A,self.sid)),2)
  self.assertEqual(len(self.s.history(A,self.sid)['items']),4)
 def test_retention_hides_expired_and_prunes_with_checkpoint(self):
  from app.workflow import RequestCancelled
  self.s.chat(A,self.sid,{'message':'你好','request_id':'retention-001'})
  old=time.time()-8*86400
  with self.s.db:self.s.db.execute('UPDATE messages SET created=?',(old,))
  self.assertEqual(self.s.history(A,self.sid)['items'],[])
  with self.assertRaises(APIError) as expired_error:self.s.chat(A,self.sid,{'message':'你好','request_id':'retention-001'})
  self.assertEqual(expired_error.exception.code,'request_expired')
  self.s.chat(A,self.sid,{'message':'你好','request_id':'retention-002'})
  expired=self.s.create(B,{})['session_id'];cancel=threading.Event();cancel.set()
  with self.assertRaises(RequestCancelled):self.s.chat(B,expired,{'message':'你好','request_id':'retention-cancel'},cancelled=cancel)
  run_id=self.s.db.execute('SELECT id FROM workflow_runs WHERE session=?',(expired,)).fetchone()[0]
  with self.s.db:self.s.db.execute('UPDATE sessions SET updated=? WHERE id=?',(old,expired))
  with self.assertRaises(APIError):self.s.history(B,expired)
  self.assertEqual(self.s.sessions(B)['items'],[])
  self.s.active.add(expired)
  result=self.s.prune_sessions();self.assertEqual(result['skipped_busy'],1)
  self.s.active.remove(expired);result=self.s.prune_sessions()
  self.assertEqual(result['deleted_sessions'],1)
  self.assertEqual(len(self.s.history(A,self.sid)['items']),2)
  self.assertFalse(self.s._workflow.graph.get_state({'configurable':{'thread_id':run_id}}).values)
  self.assertTrue(self.s.knowledge.rows)
 def test_shutdown_waits_for_running_cleanup(self):
  entered=threading.Event();release=threading.Event();closed=threading.Event();errors=[]
  original_close=self.s.close
  def cleanup():
   entered.set();release.wait(3);return {'batch_full':False,'skipped_busy':0}
  def close():closed.set();original_close()
  def lifespan():
   try:
    with TestClient(create_app(self.c,service=self.s)):pass
   except Exception as error:errors.append(error)
  with patch.object(self.s,'prune_sessions',side_effect=cleanup),patch.object(self.s,'close',side_effect=close):
   thread=threading.Thread(target=lifespan);thread.start()
   try:
    self.assertTrue(entered.wait(2));self.assertFalse(closed.wait(.05))
   finally:release.set();thread.join(4)
   self.assertFalse(thread.is_alive());self.assertTrue(closed.is_set());self.assertFalse(errors)
 def test_timeout_returns_without_late_generation_or_extra_lookup(self):
  entered=threading.Event();release=threading.Event();finished=threading.Event()
  def slow(*args):
   entered.set()
   try:release.wait(3);return {'evidence':[],'retrieval':{}}
   finally:finished.set()
  class Never:
   def answer(self,*args):raise AssertionError('LLM must not run after retrieval timeout')
  self.c.mode='llm';self.c.retrieval_timeout=.05;self.s.model=Never()
  try:
   with patch('app.chains.retrieve',side_effect=slow),patch('app.workflow.recommended_questions',return_value=['如何开发票']) as recommend:
    start=time.monotonic();result=self.s.chat(A,self.sid,{'message':'如何开发票','request_id':'timeout-policy-001'})
    self.assertLess(time.monotonic()-start,1)
    self.assertEqual(result['reason'],'retrieval_timeout');self.assertTrue(recommend.call_args.kwargs['sensitive'])
    self.assertEqual(result['status'],'suggestions');self.assertFalse(result['handoff']);self.assertFalse(result['images'])
    self.assertTrue(entered.is_set())
  finally:release.set();finished.wait(3)

class DeadlineContracts(unittest.TestCase):
 def test_nested_stages_share_one_budget(self):
  limits=[]
  def phases():
   limits.append(remaining(30));time.sleep(.04)
   limits.append(remaining(30));return run(lambda:time.sleep(.08),15)
  started=time.monotonic()
  with self.assertRaises(RetrievalTimeout):run(phases,.08)
  self.assertLess(time.monotonic()-started,.5)
  self.assertLess(limits[1],limits[0]-.02)
  time.sleep(.08) # allow the synthetic timed-out worker to exit
 def test_nested_budget_never_increases(self):
  self.assertLessEqual(run(lambda:run(lambda:remaining(100),100),.1),.1)

class Configuration(unittest.TestCase):
 def test_apply_preserves_secrets_and_backs_up(self):
  path=Path(__file__).resolve().parents[1]/'scripts/configure_policies.py'
  spec=importlib.util.spec_from_file_location('policy_config',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  with tempfile.TemporaryDirectory() as temp:
   module.ROOT=Path(temp);env=module.ROOT/'.env'
   original='AUTH_SECRET=private-value\nMODEL_NAME=Qwen/Qwen3-32B\nSEMANTIC_MIN_SIMILARITY=0.45\nSEMANTIC_MIN_SIMILARITY=0.4\nAPP_DB_PASSWORD=private-db\n'
   env.write_text(original);output=io.StringIO()
   with contextlib.redirect_stdout(output):module.main();module.main()
   text=env.read_text();self.assertIn('AUTH_SECRET=private-value',text);self.assertIn('APP_DB_PASSWORD=private-db',text)
   for key,value in module.POLICIES.items():self.assertEqual(text.count(key+'='),1);self.assertIn(key+'='+value,text)
   backups=list(module.ROOT.glob('backups/*/env.before'));self.assertEqual(len(backups),2)
   self.assertIn(original,[p.read_text() for p in backups]);self.assertEqual(env.stat().st_mode&0o777,0o600)
   self.assertNotIn('private-value',output.getvalue());self.assertNotIn('private-db',output.getvalue())
