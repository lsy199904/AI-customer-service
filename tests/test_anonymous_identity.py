import time
from unittest.mock import patch
from fastapi.testclient import TestClient
from tests.test_demo_access import DemoAccessTests,SECRET
from app.core import authenticate
from app.visitors import VISITOR_COOKIE,VISITOR_LIFETIME,issue_visitor_cookie,read_visitor_cookie

class AnonymousIdentityTests(DemoAccessTests):
 def test_same_browser_keeps_history_after_three_days(self):
  first=self.token();identity=authenticate(SECRET,first)['sub']
  sid=self.client.post('/v1/sessions',json={},headers={'Authorization':'Bearer '+first}).json()['session_id']
  cookie=self.client.cookies.get(VISITOR_COOKIE);now=time.time()
  with patch('time.time',return_value=now+3*86400):
   # Simulate returning after all API access credentials have expired.
   with TestClient(self.app) as returning:
    returning.cookies.set(VISITOR_COOKIE,cookie)
    response=returning.get('/widget/demo-auth');token=response.json()['token']
    self.assertEqual(authenticate(SECRET,token)['sub'],identity)
    self.assertIn('Max-Age=2592000',response.headers['set-cookie'])
    self.assertIn(sid,[s['session_id'] for s in returning.get('/v1/sessions',headers={'Authorization':'Bearer '+token}).json()['items']])
 def test_identity_survives_seven_day_message_retention(self):
  first=self.token();identity=authenticate(SECRET,first)['sub'];cookie=self.client.cookies.get(VISITOR_COOKIE);now=time.time()
  with patch('time.time',return_value=now+8*86400):
   self.assertEqual(read_visitor_cookie(SECRET,cookie),identity)
 def test_cookie_expiry_tampering_and_token_separation(self):
  identity='demo-'+'a'*32;now=time.time();cookie=issue_visitor_cookie(SECRET,identity)
  self.assertEqual(read_visitor_cookie(SECRET,cookie),identity)
  self.assertIsNone(read_visitor_cookie(SECRET,cookie[:-1]+('0' if cookie[-1]!='0' else '1')))
  with patch('time.time',return_value=now+VISITOR_LIFETIME+1):self.assertIsNone(read_visitor_cookie(SECRET,cookie))
  self.assertEqual(self.client.get('/v1/bootstrap',headers={'Authorization':'Bearer '+cookie}).status_code,401)
 def test_manual_identity_endpoint_removed_and_ui_has_no_id_form(self):
  self.assertIn(self.client.post('/widget/user-auth',json={'user_id':'someone'}).status_code,(401,404))
  html=self.client.get('/widget/demo').text
  self.assertNotIn('connection-form',html);self.assertNotIn('switch-user',html)
 def test_clearing_cookies_creates_new_visitor(self):
  first=authenticate(SECRET,self.token())['sub'];self.client.cookies.clear()
  self.assertNotEqual(authenticate(SECRET,self.token())['sub'],first)

 def test_old_v2_cookie_cannot_overwrite_established_v3_visitor(self):
  from app.core import issue_token,DEMO_TENANT
  first=authenticate(SECRET,self.token())['sub']
  self.client.cookies.set('smarttitu_demo_identity',issue_token(SECRET,DEMO_TENANT,'demo-'+'b'*32))
  self.assertEqual(authenticate(SECRET,self.token())['sub'],first)
