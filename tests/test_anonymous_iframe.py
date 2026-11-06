"""Anonymous iframe identity and real API ownership, without any external models."""
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.core import Settings, authenticate, issue_token
from app.anonymous import COOKIE, TENANT, issue_cookie, read_cookie
from app.server import create_app

SECRET='anonymous-tests-secret-abcdefghijklmnopqrstuvwxyz'

class AnonymousIframeTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.config=Settings(secret=SECRET,db=str(Path(self.temp.name)/'chat.db'),
            retrieval_backend='lexical',mode='extractive',anonymous_widget_enabled=True,
            demo_auto_login=False,frame_origins=('https://portal.example.com',))
        self.app=create_app(self.config)
        self.client=TestClient(self.app,base_url='https://assistant.example.com')
        self.client.__enter__()
    def tearDown(self):
        self.client.__exit__(None,None,None);self.temp.cleanup()
    def token(self,client=None,**kwargs):
        return (client or self.client).post('/widget/anonymous-auth',json={},**kwargs).json()['token']
    def headers(self,token):return {'Authorization':'Bearer '+token}
    def test_cookie_stable_secure_and_no_secret_exposure(self):
        r=self.client.post('/widget/anonymous-auth',json={});a=r.json()['token']
        b=self.token()
        self.assertEqual(authenticate(SECRET,a)['sub'],authenticate(SECRET,b)['sub'])
        self.assertEqual(authenticate(SECRET,a)['tenant_id'],TENANT)
        for flag in ('HttpOnly','Secure','SameSite=none','Partitioned','Path=/widget/anonymous-auth'):
            self.assertIn(flag,r.headers['set-cookie'])
        self.assertEqual(r.headers['cache-control'],'no-store')
        self.assertNotIn(SECRET,r.text)
    def test_two_browsers_cannot_list_read_write_stream_or_delete_each_others_history(self):
        a=self.token();ha=self.headers(a)
        sid=self.client.post('/v1/sessions',json={},headers=ha).json()['session_id']
        response=self.client.post(f'/v1/sessions/{sid}/messages/stream',headers=ha,
            json={'message':'你好','request_id':'anonymous-greet-123'})
        self.assertIn('event: delta',response.text);self.assertIn('event: complete',response.text)
        self.assertIn('你好',str(self.client.get(f'/v1/sessions/{sid}/messages',headers=ha).json()))
        other=TestClient(self.app,base_url='https://assistant.example.com')
        try:
            b=self.token(other);hb=self.headers(b)
            self.assertNotEqual(authenticate(SECRET,a)['sub'],authenticate(SECRET,b)['sub'])
            self.assertEqual(other.get('/v1/sessions',headers=hb).json()['items'],[])
            for suffix in ('/messages','/messages/stream'):
                self.assertEqual(other.post(f'/v1/sessions/{sid}'+suffix,headers=hb,
                    json={'message':'你好','request_id':'anonymous-denied-123'}).status_code,404)
            self.assertEqual(other.get(f'/v1/sessions/{sid}/messages',headers=hb).status_code,404)
            self.assertEqual(other.delete(f'/v1/sessions/{sid}',headers=hb).status_code,404)
            formal=self.headers(issue_token(SECRET,'real-company','user'))
            self.assertEqual(other.get(f'/v1/sessions/{sid}/messages',headers=formal).status_code,404)
        finally:other.close()
    def test_bearer_renews_when_cookie_blocked_and_spoofed_id_cannot_choose_identity(self):
        a=self.token();self.client.cookies.clear()
        b=self.token(headers=self.headers(a))
        self.assertEqual(authenticate(SECRET,a)['sub'],authenticate(SECRET,b)['sub'])
        self.client.cookies.clear()
        r=self.client.post('/widget/anonymous-auth?visitor_id='+authenticate(SECRET,a)['sub'],
            json={'visitor_id':authenticate(SECRET,a)['sub']},headers=self.headers(a+'corrupt'))
        self.assertNotEqual(authenticate(SECRET,r.json()['token'])['sub'],authenticate(SECRET,a)['sub'])
    def test_foreign_or_demo_token_cannot_select_anonymous_identity(self):
        foreign=issue_token(SECRET,'real-company','admin')
        a=self.token(headers=self.headers(foreign))
        self.assertEqual(authenticate(SECRET,a)['tenant_id'],TENANT)
        self.assertNotEqual(authenticate(SECRET,a)['sub'],'admin')
    def test_disabled_rejects_issuance_and_existing_anonymous_but_formal_api_still_works(self):
        a=self.token();self.config.anonymous_widget_enabled=False
        self.assertEqual(self.client.post('/widget/anonymous-auth',json={}).status_code,404)
        self.assertEqual(self.client.get('/v1/bootstrap',headers=self.headers(a)).status_code,401)
        formal=self.headers(issue_token(SECRET,'real-company','user'))
        self.assertEqual(self.client.get('/v1/bootstrap',headers=formal).status_code,200)
    def test_original_credential_entry_unchanged_and_new_frame_is_embeddable(self):
        old=self.client.get('/chatbot');new=self.client.get('/chatbot/anonymous')
        self.assertIn('/widget/frame.js',old.text)
        self.assertIn('/widget/anonymous-frame.js',new.text)
        self.assertNotIn('id="login"',new.text)
        for response in (old,new):
            self.assertIn("frame-ancestors 'self' https://portal.example.com",response.headers['content-security-policy'])
        for url in ('/iframe.js','/iframe-anonymous.js','/widget/anonymous-frame.js'):
            self.assertEqual(self.client.get(url).status_code,200)
        self.assertEqual(self.client.get('/widget/demo-auth').status_code,404)
    def test_bad_origin_is_denied(self):
        self.assertEqual(self.client.post('/widget/anonymous-auth',json={},headers={'Origin':'https://evil.example'}).status_code,403)
    def test_tampering_expiry_and_http_cookie(self):
        identity='anon-'+'a'*32
        cookie=issue_cookie(SECRET,identity)
        self.assertEqual(read_cookie(SECRET,cookie),identity)
        self.assertIsNone(read_cookie(SECRET,cookie+'x'))
        with patch('app.anonymous.time.time',return_value=10**11):self.assertIsNone(read_cookie(SECRET,cookie))
        http=TestClient(self.app,base_url='http://assistant.example.com')
        try:
            r=http.post('/widget/anonymous-auth',json={})
            self.assertIn('SameSite=lax',r.headers['set-cookie'])
            self.assertNotIn('Secure',r.headers['set-cookie'])
        finally:http.close()

class AnonymousConfigurationTests(unittest.TestCase):
    def test_configuration_preserves_secrets_and_original_credentials(self):
        import importlib.util
        import sys
        import contextlib
        import io
        spec=importlib.util.spec_from_file_location('configure_anonymous','scripts/configure_anonymous.py')
        module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);env=root/'.env'
            env.write_text('AUTH_SECRET=private-secret\nMODEL_API_KEY=model-key\nDEMO_AUTO_LOGIN=false\nFRAME_ORIGINS=https://old.example\n')
            output=io.StringIO()
            with patch.object(module,'ROOT',root),patch.object(sys,'argv',['configure','enable','--origin','https://portal.example.com','--https-cookie']),contextlib.redirect_stdout(output):module.main()
            text=env.read_text()
            for original in ('AUTH_SECRET=private-secret','MODEL_API_KEY=model-key','DEMO_AUTO_LOGIN=false'):
                self.assertIn(original,text)
            self.assertIn('FRAME_ORIGINS=https://old.example,https://portal.example.com',text)
            self.assertIn('ANONYMOUS_WIDGET_ENABLED=true',text)
            self.assertIn('ANONYMOUS_COOKIE_SECURE=true',text)
            self.assertEqual(env.stat().st_mode&0o777,0o600)
            self.assertNotIn('private-secret',output.getvalue())
            self.assertEqual(len(list((root/'backups').glob('*/env.before'))),1)
            with patch.object(module,'ROOT',root),patch.object(sys,'argv',['configure','disable']),contextlib.redirect_stdout(output):module.main()
            self.assertIn('ANONYMOUS_WIDGET_ENABLED=false',env.read_text())
