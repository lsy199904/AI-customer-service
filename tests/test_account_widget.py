import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.core import Settings,authenticate
from app.server import create_app

class AccountWidgetTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.addCleanup(self.tmp.cleanup)
        self.secret='account-widget-secret-'+'x'*40
        self.app=create_app(Settings(secret=self.secret,db=str(Path(self.tmp.name)/'chat.db'),mode='extractive',retrieval_backend='lexical',anonymous_widget_enabled=True))
        self.client=TestClient(self.app);self.client.__enter__()
        self.addCleanup(self.client.__exit__,None,None,None)
        self.env=patch.dict(os.environ,{'WIDGET_TRUST_ACCOUNT_PARAMS':'true','WIDGET_ACCOUNT_TENANT':'portal-test'})
        self.env.start();self.addCleanup(self.env.stop)
    def auth(self,uid,name='测试账号'):
        r=self.client.post('/widget/account-auth',json={'userId':uid,'userName':name})
        self.assertEqual(r.status_code,200,r.text)
        return {'Authorization':'Bearer '+r.json()['token']}
    def test_cross_browser_same_id_recovers_history_but_other_id_cannot(self):
        a=self.auth('user-001');sid=self.client.post('/v1/sessions',json={},headers=a).json()['session_id']
        self.client.post(f'/v1/sessions/{sid}/messages',headers=a,json={'message':'你好','request_id':'account-greeting-001'})
        self.client.cookies.clear()
        renewed=self.auth('user-001','改名后的账号')
        sessions=self.client.get('/v1/sessions',headers=renewed).json()['items']
        self.assertTrue(any(s['session_id']==sid for s in sessions))
        self.assertEqual(self.client.get(f'/v1/sessions/{sid}/messages',headers=renewed).status_code,200)
        other=self.auth('user-002')
        self.assertEqual(self.client.get(f'/v1/sessions/{sid}/messages',headers=other).status_code,404)
        self.assertEqual(self.client.get('/v1/sessions',headers=other).json()['items'],[])
    def test_signed_account_for_logs_and_anonymous_separation(self):
        h=self.auth('user-001')
        claims=authenticate(self.secret,h['Authorization'][7:])
        self.assertEqual(claims['account'],'测试账号')
        self.assertEqual(claims['tenant_id'],'portal-test')
        anon=self.client.post('/widget/anonymous-auth',json={}).json()['token']
        self.assertNotEqual(authenticate(self.secret,anon)['tenant_id'],claims['tenant_id'])
    def test_disabled_and_invalid_input(self):
        with patch.dict(os.environ,{'WIDGET_TRUST_ACCOUNT_PARAMS':'false'}):
            self.assertEqual(self.client.post('/widget/account-auth',json={'userId':'a'}).status_code,403)
        for uid in ('','x'*129,' a','a\n'):
            self.assertGreaterEqual(self.client.post('/widget/account-auth',json={'userId':uid}).status_code,400)

    def test_event_subscription_requires_auth_and_closes_at_expiry(self):
        from app.core import issue_token
        self.assertEqual(self.client.get('/v1/events').status_code,401)
        token=issue_token(self.secret,'portal-test','user-001',1)
        response=self.client.get('/v1/events',headers={'Authorization':'Bearer '+token})
        self.assertEqual(response.status_code,200)
        self.assertIn('event: ready',response.text)
        self.assertEqual(response.headers['x-accel-buffering'],'no')

if __name__=='__main__':unittest.main()
