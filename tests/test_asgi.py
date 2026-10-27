import json
"""ASGI contracts and actual LangChain paths; no external models or production data."""
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from langchain_core.retrievers import BaseRetriever
from langsmith.run_helpers import get_tracing_context

from app.chains import KnowledgeRetriever,retrieve
from app.core import Settings,issue_token
from app.server import create_app

SECRET='asgi-test-secret-abcdefghijklmnopqrstuvwxyz-0123456789'

class FastAPIContracts(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.db=str(Path(self.temp.name)/'chat.db')
  self.settings=Settings(retrieval_backend='lexical',secret=SECRET,db=self.db,origins=('https://portal.example.com',),frame_origins=('https://portal.example.com',))
  self.app=create_app(self.settings);self.client=TestClient(self.app);self.client.__enter__()
  self.headers={'Authorization':'Bearer '+issue_token(SECRET,'company','user')}
 def tearDown(self):self.client.__exit__(None,None,None);self.temp.cleanup()
 def test_real_fastapi_lifecycle_and_head(self):
  self.assertIsInstance(self.app,FastAPI);self.assertTrue(self.app.state.ready)
  self.assertEqual(self.client.get('/ready').json(),{'status':'ready'})
  r=self.client.head('/health');self.assertEqual(r.status_code,200);self.assertEqual(r.content,b'')
  r=self.client.head('/chatbot');self.assertEqual(r.status_code,200);self.assertEqual(r.content,b'')
 def test_request_id_origin_and_error_envelope(self):
  r=self.client.get('/v1/sessions',headers={'Origin':'https://portal.example.com','X-Request-ID':'client-check-123'})
  self.assertEqual(r.status_code,401);self.assertEqual(r.headers['x-request-id'],'client-check-123')
  self.assertEqual(r.headers['access-control-allow-origin'],'https://portal.example.com')
  self.assertEqual(r.headers['cache-control'],'no-store');self.assertEqual(r.json()['error']['code'],'unauthorized')
  bad=self.client.get('/health',headers={'Origin':'https://evil.example'})
  self.assertEqual(bad.status_code,403);self.assertNotIn('access-control-allow-origin',bad.headers)
 def test_preflight_and_same_origin(self):
  r=self.client.options('/v1/sessions',headers={'Origin':'https://portal.example.com'})
  self.assertEqual(r.status_code,204);self.assertIn('X-Request-ID',r.headers['access-control-allow-headers'])
  self.assertEqual(self.client.get('/health',headers={'Origin':'http://testserver'}).status_code,200)
 def test_strict_body_validation_and_size_limit(self):
  self.assertEqual(self.client.post('/v1/sessions',headers=self.headers,json={'tenant_id':'forged'}).status_code,400)
  self.assertEqual(self.client.post('/v1/sessions',headers=self.headers,json=[]).status_code,400)
  r=self.client.post('/v1/sessions',headers={**self.headers,'Content-Type':'application/json'},content='{broken')
  self.assertEqual(r.status_code,400);self.assertEqual(r.json()['error']['code'],'invalid_json')
  r=self.client.post('/v1/sessions',headers={**self.headers,'Content-Type':'application/json'},content='x'*17000)
  self.assertEqual(r.status_code,413)
  r=self.client.post('/v1/sessions',headers={**self.headers,'Content-Type':'application/json','Content-Length':'1'},content='x'*17000)
  self.assertEqual(r.status_code,413)
 def test_content_type_and_declared_length(self):
  self.assertEqual(self.client.post('/v1/sessions',headers=self.headers,content='{}').status_code,415)
  r=self.client.post('/v1/sessions',headers={**self.headers,'Content-Type':'application/json','Content-Length':'9'},content='{}')
  self.assertEqual(r.status_code,400);self.assertEqual(r.json()['error']['code'],'invalid_length')
 def test_schema_requires_auth_and_describes_bearer(self):
  self.assertEqual(self.client.get('/openapi.json').status_code,401)
  r=self.client.get('/openapi.json',headers=self.headers);self.assertEqual(r.status_code,200)
  self.assertIn('HTTPBearer',r.json()['components']['securitySchemes'])
  self.assertIn('/v1/sessions/{sid}/messages',r.json()['paths'])
  self.assertNotIn('test-secret',r.text)
 def test_internal_errors_do_not_expose_upstream_text(self):
  with patch.object(self.app.state.service,'bootstrap',side_effect=RuntimeError('SECRET-UPSTREAM-TEXT')):
   with self.assertLogs('assistant.operations',level='ERROR') as logs:r=self.client.get('/v1/bootstrap',headers=self.headers)
  self.assertEqual(r.status_code,500);self.assertNotIn('SECRET',r.text)
  self.assertNotIn('SECRET',json.dumps([record.operation_fields for record in logs.records]));self.assertEqual(r.headers['x-request-id'],logs.records[0].operation_fields['http_request_id'])
 def test_slow_model_does_not_block_health_or_allow_duplicate_session(self):
  sid=self.client.post('/v1/sessions',json={},headers=self.headers).json()['session_id']
  entered=threading.Event();release=threading.Event();service=self.app.state.service
  class Slow:
   def answer(me,q,h,e,c):
    entered.set();release.wait(5)
    return {'answerable':True,'answer':'请检查调用限流。','citation_ids':[e[0]['id']]}
  service.config.mode='llm';service.model=Slow()
  def ask():return self.client.post('/v1/sessions/'+sid+'/messages',json={'message':'429错误怎么办','request_id':'slow-request-001'},headers=self.headers)
  with ThreadPoolExecutor(max_workers=1) as pool:
   future=pool.submit(ask)
   try:
    self.assertTrue(entered.wait(3))
    self.assertEqual(self.client.get('/health').status_code,200)
    r=self.client.post('/v1/sessions/'+sid+'/messages',json={'message':'429错误怎么办','request_id':'slow-request-002'},headers=self.headers)
    self.assertEqual(r.status_code,409);self.assertEqual(r.json()['error']['code'],'session_busy')
   finally:release.set()
   self.assertEqual(future.result(timeout=3).status_code,200)
 def test_shutdown_and_restart_keep_saved_history(self):
  sid=self.client.post('/v1/sessions',json={},headers=self.headers).json()['session_id']
  self.client.post('/v1/sessions/'+sid+'/messages',json={'message':'你好','request_id':'persist-request-001'},headers=self.headers)
  with TestClient(create_app(self.settings)) as second:
   self.assertEqual(len(second.get('/v1/sessions/'+sid+'/messages',headers=self.headers).json()['items']),2)
  self.assertFalse(second.app.state.ready)

 def test_chat_logs_distinguish_sessions_and_windows(self):
  first=self.client.post('/v1/sessions',json={},headers=self.headers).json()['session_id']
  second=self.client.post('/v1/sessions',json={},headers=self.headers).json()['session_id']
  with self.assertLogs('assistant.operations',level='INFO') as logs:
   for index,sid in enumerate((first,second)):
    rid='message-test-'+str(index)
    r=self.client.post('/v1/sessions/'+sid+'/messages',json={'message':'你好','request_id':rid},
      headers={**self.headers,'X-Request-ID':rid,'X-Widget-ID':'window-test-'+str(index)})
    self.assertEqual(r.status_code,200)
  rows=[r.operation_fields for r in logs.records if r.msg=='chat_completed']
  self.assertEqual(len(rows),2)
  self.assertEqual(rows[0]['user_ref'],rows[1]['user_ref'])
  self.assertNotEqual(rows[0]['session_ref'],rows[1]['session_ref'])
  self.assertNotEqual(rows[0]['window_id'],rows[1]['window_id'])
  self.assertTrue(all(r['http_request_id']==r['request_id'] for r in rows))
  self.assertNotIn('你好',json.dumps(rows,ensure_ascii=False))
 def test_stream_worker_preserves_http_correlation(self):
  sid=self.client.post('/v1/sessions',json={},headers=self.headers).json()['session_id']
  with self.assertLogs('assistant.operations',level='INFO') as logs:
   r=self.client.post('/v1/sessions/'+sid+'/messages/stream',json={'message':'你好','request_id':'stream-log-123'},
      headers={**self.headers,'X-Request-ID':'stream-log-123','X-Widget-ID':'window-stream-123'})
  self.assertEqual(r.status_code,200);self.assertIn('event: complete',r.text)
  completed=[r.operation_fields for r in logs.records if r.msg=='chat_completed'][0]
  self.assertEqual(completed['http_request_id'],'stream-log-123')
  self.assertEqual(completed['window_id'],'window-stream-123')
 def test_model_failures_are_classified_and_private(self):
  sid=self.client.post('/v1/sessions',json={},headers=self.headers).json()['session_id']
  class Broken:
   def answer(self,*args):raise ValueError('untrusted citations')
  service=self.app.state.service;service.config.mode='llm';service.model=Broken()
  with self.assertLogs('assistant.operations',level='INFO') as logs:
   r=self.client.post('/v1/sessions/'+sid+'/messages',json={'message':'429错误怎么办','request_id':'failure-log-123'},headers=self.headers)
  self.assertEqual(r.status_code,200);self.assertEqual(r.json()['reason'],'model_unavailable')
  error=[r.operation_fields for r in logs.records if r.msg=='generation_failed'][0]
  self.assertEqual(error['error_code'],'citation_validation')
  self.assertGreater(error['evidence_count'],0)
  self.assertNotIn('429错误怎么办',json.dumps([r.operation_fields for r in logs.records],ensure_ascii=False))

 def test_debug_nodes_capture_invalid_model_output_without_polluting_ops(self):
  import io,logging,os
  from zoneinfo import ZoneInfo
  from app import observability as ops
  from app.core import Model
  output=io.StringIO();handler=logging.StreamHandler(output)
  handler.setFormatter(ops.JSONFormatter(ZoneInfo('Asia/Shanghai')))
  old=list(ops._debug_log.handlers);oldlevel=ops._debug_log.level;propagate=ops._debug_log.propagate
  ops._debug_log.handlers=[handler];ops._debug_log.setLevel(logging.INFO);ops._debug_log.propagate=False
  try:
   sid=self.client.post('/v1/sessions',json={},headers=self.headers).json()['session_id']
   service=self.app.state.service;service.config.mode='llm';service.model=Model(service.config)
   with patch.dict(os.environ,{'LOG_DEBUG_CONTENT':'true'}),patch.object(Model,'_complete_request',return_value='INVALID-MODEL-JSON'):
    with self.assertLogs('assistant.operations',level='INFO') as logs:
     r=self.client.post('/v1/sessions/'+sid+'/messages/stream',json={'message':'429错误怎么办','request_id':'debug-nodes-123'},headers=self.headers)
   self.assertEqual(r.status_code,200);self.assertIn('event: complete',r.text)
   records=[json.loads(line) for line in output.getvalue().splitlines()]
   names=[row['event'] for row in records]
   for name in ('chat_input','retrieval_evidence','model_input','model_output','answer_validation_context','chat_output'):self.assertIn(name,names)
   raw=next(row for row in records if row['event']=='model_output')
   self.assertEqual(json.loads(raw['snapshot'])['text'],'INVALID-MODEL-JSON')
   normal=json.dumps([record.operation_fields for record in logs.records],ensure_ascii=False)
   self.assertNotIn('INVALID-MODEL-JSON',normal);self.assertNotIn('429错误怎么办',normal)
   stages=[record.msg for record in logs.records]
   self.assertIn('answer_validation_failed',stages);self.assertIn('final_validation_completed',stages)
   self.assertIn('response_ready',stages);self.assertIn('stream_completed',stages)
  finally:
   ops._debug_log.handlers=old;ops._debug_log.setLevel(oldlevel);ops._debug_log.propagate=propagate

class LangChainContracts(unittest.TestCase):
 def backend(self):
  class Knowledge:
   def assess(self,query):
    if get_tracing_context()['enabled'] is not False:raise AssertionError('customer tracing must be disabled')
    row={'id':'KB-'+query,'content':'内容 '+query,'title':query,'source_file':'客户.docx','source_pages':[2],'image_ids':['test-image']}
    return {'matched':True,'hits':[(.9,row,.8)],'method':'embedding_rerank','similarity':.8}
  return Knowledge()
 def test_retriever_and_chain_preserve_evidence_metadata(self):
  self.assertTrue(issubclass(KnowledgeRetriever,BaseRetriever))
  with patch.dict('os.environ',{'LANGSMITH_TRACING':'true'}):result=retrieve(self.backend(),'a')
  self.assertEqual(result['evidence'][0]['id'],'KB-a');self.assertEqual(result['evidence'][0]['image_ids'],['test-image'])
  self.assertEqual(result['retrieval']['method'],'embedding_rerank')
 def test_concurrent_reports_remain_isolated(self):
  with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(lambda q:retrieve(self.backend(),q),['a','b','c','d']))
  self.assertEqual([r['retrieval']['hits'][0][1]['id'] for r in results],['KB-a','KB-b','KB-c','KB-d'])
