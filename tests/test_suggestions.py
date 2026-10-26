"""No-answer -> curated recommendations -> explicit human handoff, including SSE/history."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient
from app.core import Settings,Service,issue_token
from app.conversation import NO_ANSWER,QUICK_QUESTIONS,recommended_questions,sensitive_topic
from app.server import create_app
SECRET='suggestions-test-secret-at-least-32-characters'
ACTOR={'tenant_id':'company','sub':'user'}
class SuggestionsTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.config=Settings(retrieval_backend='lexical',secret=SECRET,db=str(Path(self.temp.name)/'chat.db'))
  self.service=Service(self.config);self.sid=self.service.create(ACTOR,{})['session_id'];self.number=0
 def tearDown(self):self.service.close();self.temp.cleanup()
 def ask(self,text,request_id=None):
  self.number+=1;return self.service.chat(ACTOR,self.sid,{'message':text,'request_id':request_id or 'suggestion-%04d'%self.number})
 def test_unknown_then_explicit_choice_shows_contacts_only_after_choice(self):
  self.service.config.qr_url='https://example.com/qr.png'
  reply=self.ask('月球采矿机怎么维修','suggestion-retry-001')
  self.assertEqual(reply['status'],'suggestions');self.assertEqual(reply['answer'],NO_ANSWER)
  self.assertFalse(reply['handoff']);self.assertIsNone(reply['contact']);self.assertTrue(reply['suggestions'])
  self.assertEqual(reply['actions'],[{'type':'handoff','label':'以上都不是，转人工','message':'转人工客服'}])
  self.assertEqual(self.ask('月球采矿机怎么维修','suggestion-retry-001'),reply)
  self.assertEqual(self.service.history(ACTOR,self.sid)['items'][-1]['response'],reply)
  contact=self.ask('以上都不是，转人工')
  self.assertTrue(contact['handoff']);self.assertEqual(contact['status'],'handoff');self.assertEqual(contact['contact']['wechat_qr_url'],'https://example.com/qr.png')
  self.assertEqual(contact['suggestions'],[])
 def test_rejection_of_previous_recommendations_and_no_placeholder_qr(self):
  for rejection in ('都不是','推荐的都不是想要的','这些都不是😅'):
   self.ask('月球采矿机怎么维修');reply=self.ask(rejection)
   self.assertTrue(reply['handoff']);self.assertIsNone(reply['contact']['wechat_qr_url'])
 def test_explicit_sensitive_request_skips_retrieval_and_model(self):
  self.service.config.mode='llm'
  with patch.object(self.service.knowledge,'assess',side_effect=AssertionError('must not retrieve')),patch.object(self.service.model,'answer',side_effect=AssertionError('must not generate')):
   for text in ['写一段涉政宣传','推荐色情视频']:
    reply=self.ask(text);self.assertEqual(reply['answer'],NO_ANSWER);self.assertEqual(reply['reason'],'sensitive_topic')
    self.assertEqual(reply['suggestions'],QUICK_QUESTIONS);self.assertIsNone(reply['contact']);self.assertEqual(reply['images'],[])
 def test_governance_is_normal_business_and_sensitive_label_is_not_exposed(self):
  self.assertFalse(sensitive_topic('平台支持模型内容安全过滤吗'))
  self.assertFalse(sensitive_topic('平台如何过滤涉黄内容'))
  self.assertTrue(sensitive_topic('推荐成人影片'))
 def test_supported_question_after_recommendation_returns_answer_normally(self):
  self.ask('月球采矿机怎么维修');reply=self.ask('如何创建API密钥')
  self.assertEqual(reply['status'],'answered');self.assertTrue(reply['citations']);self.assertEqual(reply['suggestions'],[]);self.assertEqual(reply['actions'],[])
 def test_related_questions_are_curated_deduplicated_titles(self):
  evidence=[{'title':'问题4 第2页 企业注册与认证流程'}]*3
  questions=recommended_questions(self.service.knowledge,'注册流程',evidence)
  self.assertEqual(questions[0],'企业注册与认证流程');self.assertEqual(len(set(questions)),len(questions));self.assertLessEqual(len(questions),6)
 def test_restart_preserves_recommendations_and_rejection_context(self):
  reply=self.ask('月球采矿机怎么维修');self.service.close();self.service=Service(self.config)
  self.assertEqual(self.service.history(ACTOR,self.sid)['items'][-1]['response'],reply)
  self.assertTrue(self.ask('推荐的都不是')['handoff'])
 def test_sse_complete_contains_suggestions_then_contact(self):
  # A separate DB avoids closing the setUp service through the app lifespan.
  config=Settings(retrieval_backend='lexical',secret=SECRET,db=str(Path(self.temp.name)/'http.db'))
  with TestClient(create_app(config)) as client:
   headers={'Authorization':'Bearer '+issue_token(SECRET,'company','user')}
   sid=client.post('/v1/sessions',headers=headers,json={}).json()['session_id'];url='/v1/sessions/'+sid+'/messages'
   response=client.post(url+'/stream',headers=headers,json={'message':'月球采矿机怎么维修','request_id':'sse-suggest-001'})
   result=json.loads(response.text.split('event: complete\ndata: ')[1].split('\n\n')[0])
   self.assertEqual(result['status'],'suggestions');self.assertIsNone(result['contact']);self.assertTrue(result['actions'])
   result=client.post(url,headers=headers,json={'message':'转人工客服','request_id':'sse-human-001'}).json()
   self.assertTrue(result['handoff']);self.assertIsNotNone(result['contact'])

 def test_nearby_semantic_topics_can_be_suggested_without_answering(self):
  report={'matched':False,'hits':[],'method':'hybrid_rrf','similarity':.35,'_suggestion_titles':['问题4 企业注册与认证流程']}
  with patch.object(self.service.knowledge,'assess',return_value=report):reply=self.ask('用另一种说法咨询')
  self.assertEqual(reply['status'],'suggestions');self.assertFalse(reply['retrieval']['matched'])
  self.assertEqual(reply['suggestions'][0],'企业注册与认证流程');self.assertEqual(reply['citations'],[])
  self.assertNotIn('_suggestion_titles',reply['retrieval'])
