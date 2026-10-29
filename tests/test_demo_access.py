import json
from pathlib import Path
import tempfile
import unittest
from fastapi.testclient import TestClient
from app.core import Settings,issue_token,authenticate,DEMO_TENANT
from app.server import create_app

SECRET='demo-test-secret-abcdefghijklmnopqrstuvwxyz0123456789'

class DemoAccessTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.config=Settings(retrieval_backend='lexical',secret=SECRET,db=str(Path(self.temp.name)/'chat.db'),demo_auto_login=True)
  self.app=create_app(self.config);self.client=TestClient(self.app);self.client.__enter__()
 def tearDown(self):self.client.__exit__(None,None,None);self.temp.cleanup()
 def test_launcher_image_is_served_without_credentials(self):
  response=self.client.get('/media/support-robot.png')
  self.assertEqual(response.status_code,200)
  self.assertEqual(response.headers['content-type'],'image/png')
  self.assertTrue(response.content.startswith(b'\x89PNG\r\n\x1a\n'))
  self.assertEqual(self.client.head('/media/support-robot.png').status_code,200)
 def test_source_hides_internal_metadata(self):
  service=self.app.state.service
  key=next(iter(service.knowledge.rows))
  original=service.knowledge.rows[key]
  row={**original,'content':'正常操作步骤\n图片URL:https://raw.githubusercontent.com/private/image.png\n原文链接:https://private.example/manual.pdf','download_url':'/secret','source_references':['private'],'source_locator':'internal'}
  service.knowledge.rows[key]=row
  try:
   response=service.source(key)
   self.assertEqual(response['content'],'正常操作步骤')
   for field in ('download_url','document_url','source_locator','source_references'):self.assertNotIn(field,response)
  finally:service.knowledge.rows[key]=original
 def token(self,client=None):return (client or self.client).get('/widget/demo-auth').json()['token']
 def test_default_is_disabled_and_never_exposes_default_token(self):
  self.config.demo_auto_login=False
  self.assertEqual(self.client.get('/widget/demo-auth').status_code,404)
  self.assertFalse(self.client.get('/widget/config').json()['demo_auto_login'])
  self.assertEqual(self.client.get('/v1/bootstrap').status_code,401)
 def test_enabled_token_is_test_only_cookie_stable_and_not_cached(self):
  response=self.client.get('/widget/demo-auth?tenant_id=real-company&user=admin')
  token=response.json()['token'];claims=authenticate(SECRET,token)
  self.assertEqual(claims['tenant_id'],DEMO_TENANT);self.assertTrue(claims['sub'].startswith('demo-'))
  self.assertEqual(response.headers['cache-control'],'no-store')
  self.assertIn('HttpOnly',response.headers['set-cookie']);self.assertNotIn(SECRET,response.text)
  self.assertEqual(authenticate(SECRET,self.token())['sub'],claims['sub'])
 def test_browsers_are_isolated_and_cannot_read_real_user_sessions(self):
  first=self.token();a={'Authorization':'Bearer '+first}
  sid=self.client.post('/v1/sessions',json={},headers=a).json()['session_id']
  # The same app, but a different browser cookie jar.
  other=TestClient(self.app)
  try:
   second=self.token(other)
   self.assertNotEqual(authenticate(SECRET,first)['sub'],authenticate(SECRET,second)['sub'])
   denied=other.get('/v1/sessions/'+sid+'/messages',headers={'Authorization':'Bearer '+second})
   self.assertIn(denied.status_code,(403,404))
  finally:other.close()
  formal={'Authorization':'Bearer '+issue_token(SECRET,'real-company','real-user')}
  self.assertEqual(self.client.get('/v1/sessions',headers=formal).json()['items'],[])
 def test_formal_token_cannot_select_identity_at_demo_endpoint(self):
  response=self.client.get('/widget/demo-auth',headers={'Authorization':'Bearer '+issue_token(SECRET,'real-company','admin')})
  self.assertEqual(authenticate(SECRET,response.json()['token'])['tenant_id'],DEMO_TENANT)
 def test_disabling_rejects_existing_demo_bearers_but_keeps_formal_login(self):
  token=self.token();self.config.demo_auto_login=False
  self.assertEqual(self.client.get('/v1/bootstrap',headers={'Authorization':'Bearer '+token}).status_code,401)
  formal=issue_token(SECRET,'real-company','user')
  self.assertEqual(self.client.get('/v1/bootstrap',headers={'Authorization':'Bearer '+formal}).status_code,200)
 def test_config_helper_preserves_secrets_and_backs_up(self):
  import shutil,subprocess,sys
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);(root/'scripts').mkdir()
   shutil.copyfile('scripts/configure_demo_access.py',root/'scripts/configure_demo_access.py')
   (root/'.env').write_text('AUTH_SECRET=keep-private\nPORT=8100\nDEMO_AUTO_LOGIN=false\n')
   result=subprocess.run([sys.executable,str(root/'scripts/configure_demo_access.py'),'enable'],text=True,capture_output=True,check=True)
   self.assertIn('AUTH_SECRET=keep-private',(root/'.env').read_text());self.assertIn('DEMO_AUTO_LOGIN=true',(root/'.env').read_text())
   self.assertEqual((root/'.env').stat().st_mode&0o777,0o600);self.assertEqual(len(list((root/'backups').glob('*/env.before'))),1)
   self.assertNotIn('keep-private',result.stdout+result.stderr)
 def test_signed_identity_refresh_can_use_existing_demo_bearer(self):
  first=self.token();self.client.cookies.clear()
  second=self.client.get('/widget/demo-auth',headers={'Authorization':'Bearer '+first}).json()['token']
  self.assertEqual(authenticate(SECRET,first)['sub'],authenticate(SECRET,second)['sub'])
