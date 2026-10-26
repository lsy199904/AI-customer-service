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
