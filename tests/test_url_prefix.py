"""Public prefix covers identity, SSE, history and static resources without models."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.core import Settings, authenticate
from app.server import create_app
from app.url_prefix import public_payload, external_prefix

SECRET='prefix-tests-secret-abcdefghijklmnopqrstuvwxyz'
class PrefixTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.app=create_app(Settings(secret=SECRET,db=str(Path(self.temp.name)/'chat.db'),
            retrieval_backend='lexical',mode='extractive',anonymous_widget_enabled=True,
            demo_auto_login=True,origins=('https://portal.example.com',),frame_origins=('https://portal.example.com',)))
        self.client=TestClient(self.app,base_url='https://assistant.example.com')
        self.client.__enter__()
    def tearDown(self):
        self.client.__exit__(None,None,None);self.temp.cleanup()
    def auth(self,client=None):
        return (client or self.client).post('/smart-bot/widget/anonymous-auth',json={})
    def test_prefixed_cookie_preserves_identity(self):
        first=self.auth();second=self.auth()
        self.assertEqual(first.status_code,200)
        self.assertIn('Path=/smart-bot/widget/anonymous-auth',first.headers['set-cookie'])
        a=authenticate(SECRET,first.json()['token']);b=authenticate(SECRET,second.json()['token'])
        self.assertEqual(a['sub'],b['sub'])
    def test_prefixed_sse_history_and_ownership(self):
        auth={'Authorization':'Bearer '+self.auth().json()['token']}
        self.assertEqual(self.client.get('/smart-bot/v1/bootstrap',headers=auth).status_code,200)
        sid=self.client.post('/smart-bot/v1/sessions',json={},headers=auth).json()['session_id']
        r=self.client.post(f'/smart-bot/v1/sessions/{sid}/messages/stream',headers=auth,
            json={'message':'你好','request_id':'prefix-greet-1234'})
        self.assertEqual(r.status_code,200);self.assertIn('event: delta',r.text);self.assertIn('event: complete',r.text)
        self.assertIn('你好',str(self.client.get(f'/smart-bot/v1/sessions/{sid}/messages',headers=auth).json()))
        with TestClient(self.app,base_url='https://assistant.example.com') as other:
            headers={'Authorization':'Bearer '+self.auth(other).json()['token']}
            self.assertEqual(other.get(f'/smart-bot/v1/sessions/{sid}/messages',headers=headers).status_code,404)
    def test_prefixed_assets_and_legacy_health(self):
        for path in ('/iframe-anonymous.js','/widget.js','/chatbot/anonymous','/widget/anonymous-frame.js','/widget/frame.css','/widget/demo','/widget/demo.js','/media/support-robot-b.png','/health','/ready'):
            self.assertEqual(self.client.get('/smart-bot'+path).status_code,200,path)
        self.assertEqual(self.client.get('/ready').status_code,200)
        html=self.client.get('/smart-bot/chatbot/anonymous').text
        self.assertIn('src="/smart-bot/widget.js"',html)
        self.assertIn('href="/smart-bot/widget/frame.css"',html)
    def test_json_and_sse_return_prefixed_links(self):
        auth={'Authorization':'Bearer '+self.auth().json()['token']}
        sid=self.client.post('/smart-bot/v1/sessions',json={},headers=auth).json()['session_id']
        result={'status':'answered','answer':'示例 /v1/responses',
            'images':[{'url':'/media/test.png'}],'citations':[{'url':'/v1/sources/test'}]}
        with patch.object(self.app.state.service,'chat',return_value=result):
            path=f'/smart-bot/v1/sessions/{sid}/messages'
            body={'message':'你好','request_id':'prefix-links-1234'}
            r=self.client.post(path,json=body,headers=auth)
            self.assertEqual(r.json()['images'][0]['url'],'/smart-bot/media/test.png')
            r=self.client.post(path+'/stream',json=body,headers=auth)
            self.assertIn('/smart-bot/media/test.png',r.text)
            self.assertIn('/smart-bot/v1/sources/test',r.text)
            self.assertIn('示例 /v1/responses',r.text)
    def test_prefix_preflight_and_errors(self):
        r=self.client.options('/smart-bot/v1/sessions',headers={'Origin':'https://portal.example.com'})
        self.assertEqual(r.status_code,204)
        self.assertEqual(self.client.get('/smart-bot/v1/sessions').status_code,401)
        self.assertEqual(self.client.get('/smart-bot/health',headers={'Origin':'https://evil.example'}).status_code,403)
    def test_link_rewriting_leaves_answers_and_external_urls_untouched(self):
        token=external_prefix.set('/smart-bot')
        try:
            source={'answer':'接口示例 /v1/responses','images':[{'url':'/media/test.png'}],
                'citations':[{'url':'/v1/sources/abc'}],'url':'https://example.com/v1/a'}
            out=public_payload(source)
            self.assertEqual(out['images'][0]['url'],'/smart-bot/media/test.png')
            self.assertEqual(out['citations'][0]['url'],'/smart-bot/v1/sources/abc')
            self.assertEqual(out['answer'],source['answer']);self.assertEqual(out['url'],source['url'])
            self.assertEqual(source['images'][0]['url'],'/media/test.png')
        finally:external_prefix.reset(token)
