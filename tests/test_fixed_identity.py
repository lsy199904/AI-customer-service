from tests.test_demo_access import DemoAccessTests, SECRET
from app.core import authenticate
from fastapi.testclient import TestClient

class FixedIdentityTests(DemoAccessTests):
 def fixed(self,client,user):
  response=client.post('/widget/user-auth',json={'user_id':user})
  self.assertEqual(response.status_code,200)
  return response.json()['token']
 def test_identity_shared_across_browsers_and_isolated(self):
  first=self.fixed(self.client,'test001')
  a={'Authorization':'Bearer '+first}
  sid=self.client.post('/v1/sessions',json={},headers=a).json()['session_id']
  with TestClient(self.app) as other:
   second=self.fixed(other,'test001')
   self.assertEqual(authenticate(SECRET,first)['sub'],authenticate(SECRET,second)['sub'])
   items=other.get('/v1/sessions',headers={'Authorization':'Bearer '+second}).json()['items']
   self.assertIn(sid,[x['session_id'] for x in items])
   third=self.fixed(other,'test002')
   response=other.get('/v1/sessions/'+sid+'/messages',headers={'Authorization':'Bearer '+third})
   self.assertEqual(response.status_code,404)
 def test_validation_and_disabled(self):
  for user in ['', 'x'*65,'a/b','a b',None]:
   self.assertEqual(self.client.post('/widget/user-auth',json={'user_id':user}).status_code,400)
  self.config.demo_auto_login=False
  self.assertEqual(self.client.post('/widget/user-auth',json={'user_id':'test001'}).status_code,404)
