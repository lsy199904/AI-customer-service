"""Enterprise contracts use synthetic knowledge and isolated temporary storage."""
import json
import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.core import Settings,Service,issue_token,APIError
from app.server import create_app
from app.tools import ToolRegistry,BusinessTool,ToolContext
from app.workflow import RequestCancelled
from app.storage import postgres_sql
SECRET='enterprise-test-secret-at-least-32-characters'
ACTOR={'tenant_id':'company','sub':'user'}

class EnterpriseContracts(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.config=Settings(retrieval_backend='lexical',secret=SECRET,db=str(Path(self.temp.name)/'chat.db'))
 def tearDown(self):self.temp.cleanup()
 def test_checkpoint_resume_and_idempotency(self):
  service=Service(self.config);sid=service.create(ACTOR,{})['session_id'];body={'message':'你好','request_id':'resume-request-001'}
  cancel=threading.Event();cancel.set()
  with self.assertRaises(RequestCancelled):service.chat(ACTOR,sid,body,cancelled=cancel)
  self.assertEqual(service.history(ACTOR,sid)['items'],[])
  service.close();service=Service(self.config)
  result=service.chat(ACTOR,sid,body)
  self.assertEqual(result['status'],'answered');self.assertEqual(service.chat(ACTOR,sid,body),result)
  self.assertEqual(len(service.history(ACTOR,sid)['items']),2)
  self.assertEqual(service.db.execute('SELECT status FROM workflow_runs').fetchone()[0],'complete')
  service.delete(ACTOR,sid);self.assertEqual(service.db.execute('SELECT COUNT(*) FROM workflow_runs').fetchone()[0],0)
  service.close()
 def test_cancelled_request_cannot_change_question(self):
  service=Service(self.config);sid=service.create(ACTOR,{})['session_id'];cancel=threading.Event();cancel.set()
  with self.assertRaises(RequestCancelled):service.chat(ACTOR,sid,{'message':'你好','request_id':'conflict-request-001'},cancelled=cancel)
  with self.assertRaises(APIError) as error:service.chat(ACTOR,sid,{'message':'谢谢','request_id':'conflict-request-001'})
  self.assertEqual(error.exception.code,'request_id_conflict');service.close()
 def test_sse_auth_events_history_and_metrics(self):
  with TestClient(create_app(self.config)) as client:
   headers={'Authorization':'Bearer '+issue_token(SECRET,'company','user')}
   sid=client.post('/v1/sessions',headers=headers,json={}).json()['session_id'];url='/v1/sessions/'+sid+'/messages/stream'
   body={'message':'你好','request_id':'stream-request-001'}
   self.assertEqual(client.post(url,json=body).status_code,401)
   response=client.post(url,headers=headers,json=body)
   self.assertEqual(response.status_code,200);self.assertIn('event: status',response.text);self.assertIn('event: complete',response.text)
   frame=response.text.split('event: complete\ndata: ')[1].split('\n\n')[0];result=json.loads(frame)
   self.assertEqual(result['status'],'answered');self.assertNotIn('thinking',response.text)
   self.assertEqual(len(client.get('/v1/sessions/'+sid+'/messages',headers=headers).json()['items']),2)
   other={'Authorization':'Bearer '+issue_token(SECRET,'another','user')}
   self.assertEqual(client.post(url,headers=other,json=body).status_code,404)
   self.assertEqual(client.get('/metrics').status_code,401)
   with patch.dict('os.environ',{'OPERATIONS_TOKEN':'a'*40}):self.assertEqual(client.get('/metrics',headers={'X-Operations-Token':'a'*40}).status_code,200)
 def test_tool_identity_and_write_boundary(self):
  registry=ToolRegistry();ctx=ToolContext('company','user','session','request')
  with self.assertRaises(LookupError):registry.invoke('balance',{'question':'余额'},ctx)
  registry.register(BusinessTool('balance','查询余额',lambda identity,question:{'answer':identity.tenant_id+'余额'},lambda identity:identity.tenant_id=='company'))
  self.assertEqual(registry.invoke('balance',{'question':'余额'},ctx)['answer'],'company余额')
  with self.assertRaises(Exception):registry.invoke('balance',{'question':'余额','tenant_id':'forged'},ctx)
  with self.assertRaises(PermissionError):registry.invoke('balance',{'question':'余额'},ToolContext('evil','user','s','r'))
  with self.assertRaises(ValueError):registry.register(BusinessTool('pay','支付',None,None,True))
 def test_sql_literals_and_placeholders(self):
  translated=postgres_sql("SELECT rowid,user FROM messages WHERE role='user' AND session=?")
  self.assertIn("role='user'",translated);self.assertIn('seq,"user"',translated);self.assertTrue(translated.endswith('session=%s'))
