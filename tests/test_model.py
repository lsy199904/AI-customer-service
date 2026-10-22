import json
import unittest
from unittest.mock import patch
from app.core import Model,Settings

class ModelContractTests(unittest.TestCase):
 def invoke(self,result):
  self.sent=None
  outer=self
  class Response:
   def __enter__(self):return self
   def __exit__(self,*args):pass
   def read(self,n):return json.dumps({'choices':[{'message':{'content':json.dumps(result)}}]}).encode()
  class Opener:
   def open(self,req,timeout):outer.sent=json.loads(req.data);return Response()
  c=Settings(model='test-model',model_key='test-key')
  with patch('urllib.request.build_opener',return_value=Opener()):
   return Model(c).answer('如何计费',[],[{'id':'KB-001','content':'按量计费'}],{})
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
