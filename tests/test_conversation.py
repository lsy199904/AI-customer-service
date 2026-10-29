import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.core import Settings,Service,Knowledge,BASE,Model
from app.conversation import intent_of,retrieval_query,MediaCatalog

SECRET='test-secret-abcdefghijklmnopqrstuvwxyz-0123456789'
ACTOR={'tenant_id':'t','sub':'u'}
class ConversationTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.config=Settings(retrieval_backend='lexical',secret=SECRET,db=str(Path(self.tmp.name)/'db'))
  self.s=Service(self.config);self.sid=self.s.create(ACTOR,{})['session_id'];self.count=0
 def tearDown(self):self.s.db.close();self.tmp.cleanup()
 def ask(self,q):
  self.count+=1;return self.s.chat(ACTOR,self.sid,{'message':q,'request_id':'conversation-%04d'%self.count})
 def test_contact_questions_skip_retrieval_and_return_configured_contact(self):
  with patch.object(self.s.knowledge,'assess',side_effect=AssertionError('contact must not search')):
   for q in ('人工电话','客服电话是多少？','咨询电话','客服热线','客服邮箱','怎么获取人工联系方式'):
    result=self.ask(q)
    self.assertEqual(result['status'],'handoff')
    self.assertEqual(result['contact'],self.s.contact())
    self.assertEqual(result['citations'],[])
  self.assertEqual(intent_of('企业认证时填写的电话怎么修改'),'knowledge')
 def test_greeting_skips_retrieval(self):
  with patch.object(self.s.knowledge,'assess',side_effect=AssertionError('no search')):
   for q in ('你好','您好呀～','hello!','你是谁','你能做什么','谢谢你','再见'):
    r=self.ask(q);self.assertEqual(r['status'],'answered');self.assertFalse(r['handoff']);self.assertEqual(r['citations'],[])
    self.assertNotIn('未调用大模型',r['answer']);self.assertEqual(r['retrieval']['method'],'skipped')
 def test_llm_greeting_has_persona_no_evidence(self):
  calls=[]
  class Fake:
   def answer(self,q,h,e,c):
    calls.append((e,c));return {'answerable':True,'answer':'您好呀,我是SmartTITU的智能客服,有什么可以帮您?','citation_ids':[]}
  self.s.config.mode='llm';self.s.model=Fake()
  with patch.object(self.s.knowledge,'assess',side_effect=AssertionError('no search')):r=self.ask('你好')
  self.assertEqual(calls[0][0],[]);self.assertEqual(calls[0][1]['_intent'],'greeting');self.assertFalse(r['handoff'])
 def test_greeting_with_product_question_still_retrieves(self):
  r=self.ask('你好，如何开通账号?');self.assertEqual(r['intent'],'knowledge');self.assertTrue(r['citations'])
 def test_no_match_never_calls_llm_and_recommends_before_contact(self):
  self.s.config.mode='llm';self.s.config.qr_url='https://example.com/real-support.png'
  with patch.object(self.s.model,'answer',side_effect=AssertionError('generator must not run')) as call:
   for q in ('量子土豆如何驾驶火星飞船','平台支持月球采矿吗','你们的退款政策是什么'):
    r=self.ask(q);self.assertFalse(r['handoff']);self.assertEqual(r['status'],'suggestions');self.assertEqual(r['reason'],'no_knowledge');self.assertEqual(r['citations'],[])
    self.assertIsNone(r['contact']);self.assertTrue(r['suggestions']);self.assertEqual(r['actions'][0]['type'],'handoff')
   call.assert_not_called()
 def test_billing_to_failure_does_not_inherit_billing(self):
  self.ask('平台如何计费?');r=self.ask('我的token调用失败怎么办')
  self.assertTrue(r['citations']);self.assertIn('错误码',r['citations'][0]['title']);self.assertNotIn('模型倍率单价',r['answer'])
  self.assertGreaterEqual(r['retrieval']['similarity'],self.config.min_similarity)
 def test_llm_rejects_evidence_then_recommends(self):
  class Reject:
   def answer(self,*args):return {'answerable':False,'answer':'','citation_ids':[]}
  self.s.config.mode='llm';self.s.model=Reject();r=self.ask('如何开通账号?')
  self.assertEqual(r['reason'],'insufficient_evidence');self.assertFalse(r['handoff']);self.assertIsNone(r['contact']);self.assertTrue(r['suggestions'])
 def test_greeting_model_failure_is_friendly(self):
  self.s.config.mode='llm'
  with patch.object(self.s.model,'answer',side_effect=ValueError):r=self.ask('你好')
  self.assertFalse(r['handoff']);self.assertIn('SmartTITU',r['answer'])
 def test_media_reply(self):
  r=self.ask('给我产品logo图片')
  self.assertFalse(r['handoff']);self.assertEqual(r['images'][0]['id'],'smarttitu-logo');self.assertEqual(r['images'][0]['url'],'/media/smarttitu-logo.png')
  saved=self.s.history(ACTOR,self.sid)['items'][-1]['response'];self.assertEqual(saved['images'],r['images'])
 def test_missing_picture_recommends(self):
  r=self.ask('给我月球采矿机的图片');self.assertFalse(r['handoff']);self.assertEqual(r['status'],'suggestions');self.assertEqual(r['images'],[])
 def test_threshold(self):
  kb=Knowledge(BASE/'data/knowledge.jsonl',min_similarity=1)
  self.assertFalse(kb.assess('如何开通账号')['matched'])
  self.assertEqual(self.s.knowledge.search('你好'),[])
 def test_private_http_explicit_allowlist(self):
  base=dict(secret=SECRET,mode='llm',model_key='not-empty',model='Qwen/Qwen3-32B',model_url='http://10.180.158.23:18080/v1')
  with self.assertRaises(ValueError):Settings(retrieval_backend='lexical',**base).validate()
  Settings(retrieval_backend='lexical',**base,http_origins=('http://10.180.158.23:18080',)).validate()
  with self.assertRaises(ValueError):Settings(retrieval_backend='lexical',**{**base,'model_url':'http://8.8.8.8/v1'},http_origins=('http://8.8.8.8',)).validate()
 def test_media_catalog_refuses_untrusted_schemes(self):
  path=Path(self.tmp.name)/'media.json';path.write_text(json.dumps([{'id':'test','url':'javascript:alert(1)'}]))
  with self.assertRaises(ValueError):MediaCatalog(path,Path(self.tmp.name))
 def test_local_qr_must_be_registered(self):
  self.assertRaises(ValueError,Service,Settings(retrieval_backend='lexical',secret=SECRET,db=str(Path(self.tmp.name)/'other'),qr_url='/media/no-such-qr.png'))
