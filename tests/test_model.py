import json
import unittest
from unittest.mock import patch
import httpx
from langchain_core.messages import AIMessage,AIMessageChunk
from app.core import Model,Settings

class PlainTextModelTests(unittest.TestCase):
 def setUp(self):
  self.model=Model(Settings(retrieval_backend='lexical',model='test-model',model_key='test-key'))
  self.evidence=[{'id':'KB-001','title':'安全审计','content':'每周一生成报告'}]
 def test_plain_text_answer_no_json_or_repair(self):
  with patch.object(self.model,'_complete_request',return_value='1. 打开安全审计。\n2. 下载报告。') as calls:
   result=self.model.answer('安全审计流程',[],self.evidence,{'_media':[{'id':'hub-08','title':'安全审计'}]})
  self.assertEqual(calls.call_count,1);self.assertTrue(result['answerable'])
  self.assertEqual(result['citation_ids'],['KB-001']);self.assertEqual(result['image_ids'],['hub-08'])
  messages=calls.call_args.args[0]
  self.assertIn('只输出给用户阅读的答案正文',messages[0]['content'])
  self.assertNotIn('KB-001',messages[-1]['content'])
 def test_old_response_format_env_is_ignored(self):
  sent=[]
  def handler(request):
   sent.append(json.loads(request.content))
   return httpx.Response(200,json={'id':'mock','object':'chat.completion','created':0,'model':'test-model','choices':[{'index':0,'finish_reason':'stop','message':{'role':'assistant','content':'直接回答正文。'}}]})
  with httpx.Client(transport=httpx.MockTransport(handler),trust_env=False) as client,patch('app.transport.client',return_value=client),patch.dict('os.environ',{'MODEL_RESPONSE_FORMAT':'json_object'}):
   result=self.model.answer('安全审计流程',[],self.evidence,{})
  self.assertEqual(result['answer'],'直接回答正文。');self.assertNotIn('response_format',sent[0]);self.assertEqual(len(sent),1)
 def test_stream_calls_callback_before_model_finishes(self):
  seen=[];stages=[]
  class Backend:
   def stream(self,messages):
    yield AIMessageChunk(content='第一段')
    stages.append(list(seen))
    yield AIMessageChunk(content='，第二段。',response_metadata={'finish_reason':'stop'})
   def invoke(self,messages):raise AssertionError('stream must not invoke')
  with patch('langchain.chat_models.init_chat_model',return_value=Backend()):
   result=self.model.answer('安全审计流程',[],self.evidence,{'_on_delta':seen.append})
  self.assertEqual(stages,[['第一段']]);self.assertEqual(seen,['第一段','，第二段。'])
  self.assertEqual(result['answer'],'第一段，第二段。')
 def test_failure_is_not_retried(self):
  with patch.object(self.model,'_complete_request',side_effect=httpx.ReadTimeout('timeout')) as calls:
   with self.assertRaises(httpx.ReadTimeout):self.model.answer('安全审计流程',[],self.evidence,{})
  self.assertEqual(calls.call_count,1)
 def test_cancel_closes_upstream_generator(self):
  closed=[]
  class Backend:
   def stream(self,messages):
    try:
     yield AIMessageChunk(content='开始')
     raise AssertionError('cancelled generator should not continue')
    finally:closed.append(True)
  from app.workflow import RequestCancelled
  def cancel(text):raise RequestCancelled()
  with patch('langchain.chat_models.init_chat_model',return_value=Backend()):
   with self.assertRaises(RequestCancelled):self.model.answer('安全审计流程',[],self.evidence,{'_on_delta':cancel})
  self.assertEqual(closed,[True])
 def test_empty_transport_response_is_error(self):
  class Backend:
   def invoke(self,messages):return AIMessage(content='')
  with patch('langchain.chat_models.init_chat_model',return_value=Backend()):
   with self.assertRaises(RuntimeError):self.model.answer('安全审计流程',[],self.evidence,{})

 def test_actual_langchain_stream_uses_plain_text_stream_protocol(self):
  sent=[];seen=[]
  def handler(request):
   sent.append(json.loads(request.content))
   chunks=[]
   for i,text in enumerate(['你好','，请查看报告。']):
    payload={'id':'stream-test','object':'chat.completion.chunk','created':0,'model':'test-model','choices':[{'index':0,'delta':{'content':text},'finish_reason':'stop' if i else None}]}
    chunks.append('data: '+json.dumps(payload)+'\n\n')
   return httpx.Response(200,text=''.join(chunks)+'data: [DONE]\n\n',headers={'content-type':'text/event-stream'})
  with httpx.Client(transport=httpx.MockTransport(handler),trust_env=False) as client,patch('app.transport.client',return_value=client):
   result=self.model.answer('安全审计流程',[],self.evidence,{'_on_delta':seen.append})
  self.assertEqual(result['answer'],''.join(seen));self.assertEqual(len(seen),2)
  self.assertTrue(sent[0]['stream']);self.assertNotIn('response_format',sent[0]);self.assertEqual(len(sent),1)
