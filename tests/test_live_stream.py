"""Real HTTP proves first text arrives before generation ends; no timing-only assertion."""
import json
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
import httpx
from app.core import Model,Settings,issue_token
from app.server import create_server

SECRET='live-stream-test-secret-abcdefghijklmnopqrstuvwxyz'

class LiveStreamTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory()
  config=Settings(retrieval_backend='lexical',mode='llm',secret=SECRET,db=str(Path(self.temp.name)/'chat.db'),model='test-model',model_key='test-key')
  self.server=create_server(config,port=0,model=Model(config))
  self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
  self.client=httpx.Client(base_url='http://127.0.0.1:'+str(self.server.server_port),headers={'Authorization':'Bearer '+issue_token(SECRET,'tenant','user')},timeout=10,trust_env=False)
  self.sid=self.client.post('/v1/sessions',json={}).json()['session_id']
 def tearDown(self):
  self.client.close();self.server.shutdown();self.thread.join(timeout=10);self.server.server_close();self.server.service.close();self.temp.cleanup()
 def frames(self,response):
  kind=None
  for line in response.iter_lines():
   if line.startswith('event: '):kind=line[7:]
   elif line.startswith('data: '):yield kind,json.loads(line[6:])
 def test_first_text_arrives_before_generation_finishes_and_retry_is_cached(self):
  release=threading.Event();finished=threading.Event();calls=[]
  def generate(model,messages,on_delta=None):
   calls.append(True);on_delta('第一段，')
   if not release.wait(5):raise RuntimeError('first delta was buffered')
   on_delta('第二段。');finished.set();return '第一段，第二段。'
  try:
   with patch.object(Model,'_complete_request',generate):
    with self.client.stream('POST',f'/v1/sessions/{self.sid}/messages/stream',json={'message':'429错误怎么办','request_id':'live-stream-123'}) as response:
     chunks=[];result=None
     for kind,payload in self.frames(response):
      if kind=='delta':
       chunks.append(payload['text'])
       if len(chunks)==1:
        self.assertFalse(finished.is_set());self.assertEqual(payload['text'],'第一段，');release.set()
      if kind=='complete':result=payload
    self.assertEqual(''.join(chunks),'第一段，第二段。');self.assertEqual(result['answer'],'第一段，第二段。');self.assertTrue(result['citations'])
    retry=self.client.post(f'/v1/sessions/{self.sid}/messages',json={'message':'429错误怎么办','request_id':'live-stream-123'})
    self.assertEqual(retry.json()['answer'],result['answer']);self.assertEqual(len(calls),1)
  finally:release.set()
 def test_many_chunks_not_dropped_or_duplicated(self):
  def generate(model,messages,on_delta=None):
   for i in range(160):on_delta(str(i)+'，')
   return ''.join(str(i)+'，' for i in range(160))
  with patch.object(Model,'_complete_request',generate):
   with self.client.stream('POST',f'/v1/sessions/{self.sid}/messages/stream',json={'message':'429错误怎么办','request_id':'live-stream-many'}) as response:
    frames=list(self.frames(response))
  delta=''.join(data['text'] for kind,data in frames if kind=='delta')
  result=next(data for kind,data in frames if kind=='complete')
  self.assertEqual(delta,result['answer']);self.assertEqual(len([kind for kind,_ in frames if kind=='delta']),160)
 def test_partial_upstream_failure_finishes_with_clear_final_result(self):
  def generate(model,messages,on_delta=None):
   on_delta('尚未生成完整的文字')
   raise httpx.ReadTimeout('upstream stopped')
  with patch.object(Model,'_complete_request',generate):
   with self.client.stream('POST',f'/v1/sessions/{self.sid}/messages/stream',json={'message':'429错误怎么办','request_id':'live-stream-fail'}) as response:
    frames=list(self.frames(response))
  self.assertTrue(any(kind=='delta' for kind,_ in frames))
  result=next(data for kind,data in frames if kind=='complete')
  self.assertEqual(result['reason'],'model_unavailable');self.assertEqual(result['images'],[])
