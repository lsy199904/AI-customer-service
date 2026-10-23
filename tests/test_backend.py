import json
from pathlib import Path
import tempfile
import threading
import time
import unittest
import urllib.request
import urllib.error
from app.core import Settings,Service,APIError,issue_token,authenticate,Model
from app.server import create_server
SECRET='test-secret-abcdefghijklmnopqrstuvwxyz-0123456789'
A={'tenant_id':'a','sub':'one'}
B={'tenant_id':'b','sub':'one'}
C={'tenant_id':'a','sub':'two'}
class BackendTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.c=Settings(retrieval_backend='lexical',db=str(Path(self.tmp.name)/'db'),secret=SECRET)
  self.s=Service(self.c);self.sid=self.s.create(A,{'context':{'page_path':'/console'}})['session_id']
 def tearDown(self):self.s.db.close();self.tmp.cleanup()
 def ask(self,q,rid='request-001'):return self.s.chat(A,self.sid,{'message':q,'request_id':rid})
 def test_retrieval(self):
  self.assertEqual(len(self.s.knowledge.rows),134)
  for q,word in [('如何开通账号','开通'),('429错误怎么办','错误'),('平台怎么收费','计费')]:
   hits=self.s.knowledge.search(q);self.assertTrue(hits,q);self.assertIn(word,hits[0][1]['title'])
 def test_isolation(self):
  for actor in (B,C):
   for fn in (lambda:self.s.history(actor,self.sid),lambda:self.s.delete(actor,self.sid),lambda:self.s.chat(actor,self.sid,{'message':'你好','request_id':'request-123'})):
    with self.assertRaises(APIError) as cm:fn()
    self.assertEqual(cm.exception.status,404)
   self.assertEqual(self.s.sessions(actor)['items'],[])
 def test_auth(self):
  tok=issue_token(SECRET,'a','one');self.assertEqual(authenticate(SECRET,tok)['sub'],'one')
  for bad in (tok+'x','bad','a.b',''):
   with self.assertRaises(APIError):authenticate(SECRET,bad)
  with self.assertRaises(APIError):authenticate('wrong',tok)
 def test_identity_spoofing(self):
  with self.assertRaises(APIError):self.s.create(A,{'tenant_id':'other'})
  with self.assertRaises(APIError):self.s.create(A,{'context':{'role':'admin'}})
 def test_idempotency_delete(self):
  r=self.ask('平台如何计费?');self.assertEqual(r['status'],'answered');self.assertTrue(r['citations'])
  self.assertEqual(self.ask('平台如何计费?'),r);self.assertEqual(len(self.s.history(A,self.sid)['items']),2)
  with self.assertRaises(APIError):self.ask('别的问题')
  self.s.delete(A,self.sid);self.assertEqual(self.s.db.execute('SELECT count(*) FROM messages').fetchone()[0],0)
 def test_handoff(self):
  for i,q in enumerate(['量子土豆如何驾驶火星飞船','转人工客服','查询我的余额','你们的退款政策是什么']):
   r=self.ask(q,'fallback-%d'%i);self.assertTrue(r['handoff']);self.assertEqual(r['citations'],[]);self.assertIsNone(r['contact']['wechat_qr_url'])
 def test_llm_history(self):
  calls=[]
  class Fake:
   def answer(me,q,h,e,c):
    calls.append((q,h,e,c));return {'answerable':True,'answer':'请检查RPM和TPM。','citation_ids':[e[0]['id']]}
  self.s.config.mode='llm';self.s.model=Fake()
  self.ask('429错误怎么办','llm-00001');r=self.ask('这个怎么配置','llm-00002')
  self.assertEqual(r['status'],'answered');self.assertEqual(len(calls[1][1]),2)
  self.assertEqual(calls[0][3]['page_path'],'/console')
 def test_model_failure(self):
  class Broken:
   def answer(self,*args):raise ValueError('SECRET-UPSTREAM')
  self.s.config.mode='llm';self.s.model=Broken();r=self.ask('429错误怎么办')
  self.assertEqual(r['reason'],'model_unavailable');self.assertNotIn('SECRET',json.dumps(r))
 def test_rate_busy(self):
  self.c.requests_per_minute=1;self.s.rate(A)
  with self.assertRaises(APIError) as cm:self.s.rate(A)
  self.assertEqual(cm.exception.status,429);self.s.active.add(self.sid)
  with self.assertRaises(APIError):self.s.delete(A,self.sid)
 def test_idle(self):
  with self.s.db:self.s.db.execute('UPDATE sessions SET updated=?',(time.time()-2000,))
  self.assertTrue(self.s.sessions(A)['items'][0]['idle']);self.assertEqual(self.s.history(A,self.sid)['items'],[])
 def test_persistence(self):
  self.ask('如何开通账号');other=Service(self.c)
  try:self.assertEqual(len(other.history(A,self.sid)['items']),2)
  finally:other.db.close()
class HTTPTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.s=create_server(Settings(retrieval_backend='lexical',db=str(Path(self.tmp.name)/'db'),secret=SECRET,origins=('https://console.example.com',)),port=0)
  self.t=threading.Thread(target=self.s.serve_forever,daemon=True);self.t.start()
  self.url='http://127.0.0.1:'+str(self.s.server_port);self.tok=issue_token(SECRET,'a','one')
 def tearDown(self):self.s.shutdown();self.t.join();self.s.server_close();self.s.service.db.close();self.tmp.cleanup()
 def req(self,path,method='GET',data=None,auth=True,headers=None):
  h={'Content-Type':'application/json'}
  if auth:h['Authorization']='Bearer '+self.tok
  h.update(headers or {})
  r=urllib.request.Request(self.url+path,method=method,data=json.dumps(data).encode() if data is not None else None,headers=h)
  try:resp=urllib.request.urlopen(r)
  except urllib.error.HTTPError as e:resp=e
  with resp:return resp.status,json.loads(resp.read())
 def test_end_to_end(self):
  self.assertEqual(self.req('/health',auth=False)[0],200);self.assertEqual(self.req('/v1/bootstrap',auth=False)[0],401)
  self.assertEqual(self.req('/v1/bootstrap',headers={'Origin':'https://evil.example'})[0],403)
  status,r=self.req('/v1/sessions','POST',{'context':{'page_title':'控制台'}});self.assertEqual(status,201);sid=r['session_id']
  status,r=self.req('/v1/sessions/'+sid+'/messages','POST',{'message':'429错误怎么办','request_id':'http-00001'})
  self.assertEqual(status,200);self.assertTrue(r['citations']);self.assertEqual(self.req(r['citations'][0]['url'])[0],200)
  status,r=self.req('/v1/sessions/'+sid+'/messages');self.assertEqual(len(r['items']),2)
  self.assertEqual(self.req('/v1/sessions/'+sid,'DELETE')[0],200)
 def test_widget_assets_and_same_origin(self):
  for path,kind in [('/widget.js','javascript'),('/widget/demo','text/html'),('/widget/demo.js','javascript'),('/widget/demo.css','text/css'),('/media/smarttitu-logo.png','image/png')]:
   with urllib.request.urlopen(self.url+path) as r:
    self.assertEqual(r.status,200);self.assertIn(kind,r.headers['Content-Type']);self.assertTrue(r.read())
  self.assertEqual(self.req('/v1/sessions','POST',{},headers={'Origin':self.url})[0],201)
  self.assertEqual(self.req('/widget/../../app/core.py',auth=False)[0],401)
 def test_iframe_routes_and_csp(self):
  for route,kind in [('/chatbot','text/html'),('/widget/frame.js','javascript'),('/widget/frame.css','text/css'),('/iframe.js','javascript')]:
   with urllib.request.urlopen(self.url+route) as r:
    self.assertEqual(r.status,200);self.assertIn(kind,r.headers['Content-Type'])
    if route=='/chatbot':self.assertIn("frame-ancestors 'self'",r.headers['Content-Security-Policy'])
  self.s.service.config.frame_origins=('https://console.example.com',)
  with urllib.request.urlopen(self.url+'/chatbot') as r:
   self.assertTrue(r.headers['Content-Security-Policy'].endswith("frame-ancestors 'self' https://console.example.com"))
  with urllib.request.urlopen(self.url+'/widget/demo') as r:
   self.assertTrue(r.headers['Content-Security-Policy'].endswith("frame-ancestors 'none'"))
  self.assertEqual(self.req('/widget/config',auth=False)[1]['frame_origins'],['https://console.example.com'])
  self.assertEqual(self.req('/v1/sessions',auth=False)[0],401)
 def test_frame_origin_validation(self):
  for origin in ['*','https://example.com/path',"https://example.com;script-src",'https://example.com\nhttps://evil.test','https://user:pass@example.com']:
   with self.assertRaises(ValueError):Settings(secret=SECRET,frame_origins=(origin,)).validate()
  Settings(secret=SECRET,frame_origins=('https://console.example.com','http://localhost:3000')).validate()
 def test_validation(self):
  self.assertEqual(self.req('/v1/sessions','POST',{'tenant_id':'spoof'})[0],400);self.assertEqual(self.req('/missing')[0],404)
if __name__=='__main__':unittest.main()
