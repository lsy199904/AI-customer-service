import json
import unittest
from unittest.mock import patch
from app.core import Model,Settings

class ModelContractTests(unittest.TestCase):
 def invoke(self,result,context=None):
  self.sent=None
  outer=self
  import httpx
  def handler(request):
   outer.sent=json.loads(request.content)
   return httpx.Response(200,json={'id':'mock-completion','object':'chat.completion','created':0,'model':'test-model','choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':json.dumps(result)}}]})
  client=httpx.Client(transport=httpx.MockTransport(handler))
  c=Settings(retrieval_backend='lexical',model='test-model',model_key='test-key')
  with client,patch('app.transport.client',return_value=client):
   return Model(c).answer('如何计费',[],[{'id':'KB-001','content':'按量计费'}],context or {})
 def test_success(self):
  r=self.invoke({'answerable':True,'answer':'按量计费','citation_ids':['KB-001']})
  self.assertTrue(r['answerable']);self.assertEqual(self.sent['model'],'test-model')
 def test_forged_source(self):
  with self.assertRaises(ValueError):self.invoke({'answerable':True,'answer':'答','citation_ids':['KB-forged']})
 def test_missing_citations(self):
  with self.assertRaises(ValueError):self.invoke({'answerable':True,'answer':'答','citation_ids':[]})
 def test_bad_schema(self):
  with self.assertRaises(ValueError):self.invoke({'answerable':'true','answer':'答','citation_ids':['KB-001']})
 def test_abstain(self):
  self.assertFalse(self.invoke({'answerable':False,'answer':'不足','citation_ids':[]})['answerable'])

 def test_conversation_does_not_require_citations(self):
  result=self.invoke({'answerable':True,'answer':'您好,我是SmartTITU智能客服','citation_ids':[]},{'_intent':'greeting'})
  self.assertTrue(result['answerable'])
  self.assertIn('SmartTITU',self.sent['messages'][0]['content'])
 def test_unregistered_image_id_rejected(self):
  with self.assertRaises(ValueError):self.invoke({'answerable':True,'answer':'图片','citation_ids':['KB-001'],'image_ids':['invented']})
 def test_registered_image_id_allowed(self):
  result=self.invoke({'answerable':True,'answer':'产品标识','citation_ids':[],'image_ids':['logo']},{'_intent':'image','_media':[{'id':'logo','title':'标识'}]})
  self.assertEqual(result['image_ids'],['logo'])

class ModelRecoveryTests(unittest.TestCase):
 def setUp(self):
  self.model=Model(Settings(retrieval_backend='lexical',model='test-model',model_key='test-key'))
  self.evidence=[{'id':'KB-001','content':'每周一生成安全报告'}]
  self.good=json.dumps({'answerable':True,'answer':'每周一生成安全报告','citation_ids':['KB-001'],'image_ids':['hub-08']})
  self.context={'_media':[{'id':'hub-08','title':'安全审计'}]}
 def answer(self):return self.model.answer('安全审计流程',[],self.evidence,self.context)
 def test_logged_failure_shape_recovers_once(self):
  broken='{"answerable":true,"answer":"安全审计流程\\nimage_ids":["hub-08"],"citation_ids":["KB-001"],"image_ids":["hub-08"]}'
  with patch.object(self.model,'_complete_request',side_effect=[broken,self.good]) as complete:
   result=self.answer()
  self.assertEqual(result['citation_ids'],['KB-001']);self.assertEqual(complete.call_count,2)
  self.assertIn('invalid_response',complete.call_args.args[0][-1]['content'])
 def test_repeated_failure_is_bounded(self):
  from app.core import AnswerValidationError
  with patch.object(self.model,'_complete_request',return_value='invalid') as complete:
   with self.assertRaises(AnswerValidationError):self.answer()
  self.assertEqual(complete.call_count,2)
 def test_repaired_forged_citation_still_rejected(self):
  with patch.object(self.model,'_complete_request',side_effect=['invalid',self.good.replace('KB-001','KB-forged')]) as complete:
   with self.assertRaises(ValueError):self.answer()
  self.assertEqual(complete.call_count,2)
 def test_semantic_failure_does_not_retry(self):
  with patch.object(self.model,'_complete_request',return_value=self.good.replace('hub-08','unregistered')) as complete:
   with self.assertRaises(ValueError):self.answer()
  self.assertEqual(complete.call_count,1)
 def test_duplicate_keys_rejected_and_repaired(self):
  duplicate=self.good[:-1]+',"image_ids":["hub-08"]}'
  with patch.object(self.model,'_complete_request',side_effect=[duplicate,self.good]) as complete:
   self.assertTrue(self.answer()['answerable'])
  self.assertEqual(complete.call_count,2)
 def test_transport_failure_does_not_retry(self):
  with patch.object(self.model,'_complete_request',side_effect=TimeoutError) as complete:
   with self.assertRaises(TimeoutError):self.answer()
  self.assertEqual(complete.call_count,1)
 def test_json_mode_and_unsupported_fallback(self):
  import httpx
  sent=[]
  def handler(request):
   sent.append(json.loads(request.content))
   if 'response_format' in sent[-1]:return httpx.Response(400,json={'error':{'message':'response_format is not supported','type':'invalid_request_error'}})
   return httpx.Response(200,json={'id':'mock','object':'chat.completion','created':0,'model':'test-model','choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':self.good}}]})
  with httpx.Client(transport=httpx.MockTransport(handler)) as client,patch('app.transport.client',return_value=client):
   self.assertTrue(self.answer()['answerable'])
  self.assertEqual(sent[0]['response_format'],{'type':'json_object'});self.assertNotIn('response_format',sent[1]);self.assertEqual(len(sent),2)

 def test_unrelated_bad_request_is_not_retried(self):
  import httpx
  sent=[]
  def handler(request):
   sent.append(request)
   return httpx.Response(400,json={'error':{'message':'unknown model','type':'invalid_request_error'}})
  with httpx.Client(transport=httpx.MockTransport(handler)) as client,patch('app.transport.client',return_value=client):
   with self.assertRaises(Exception):self.answer()
  self.assertEqual(len(sent),1)
