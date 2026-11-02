"""Advisory grounding, short title navigation and read-only configuration provenance."""
import json
import math
import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest.mock import patch
from app.grounding import unsupported_literals
from app.retrieval import title_signals
from app.retrieval_config import inspect
from app.rag import RAGSettings,SemanticKnowledge,ingest_documents
from app.core import Model
from app import observability as ops
from tests import test_live_stream as stream

class TitleAliasTests(unittest.TestCase):
 def test_operation_product_abbreviation_does_not_widen_to_troubleshooting(self):
  titles=['问题57 附录-安装MetalLB负载均衡器','故障排查','安装MetalLB前置条件','安装MetalLBPro负载均衡器']
  for query in ('如何安装MetalLB','安装MetalLB','怎么安装MetalLB','MetalLB怎么安装','安装MetalLB步骤'):
   signals=title_signals(query,titles)
   self.assertTrue(signals[0]['strong']);self.assertEqual(signals[0]['kind'],'operation_product_alias')
   self.assertFalse(any(s['strong'] for s in signals[1:]))
  for query in ('配置MetalLB','MetalLB安装失败','安装Metal','安装MetalLBPro其他组件','安装负载均衡器','安装'):
   self.assertFalse(title_signals(query,[titles[0]])[0]['strong'],query)
  self.assertTrue(title_signals('如何安装Redis',['安装Redis数据库'])[0]['strong'])
 def test_reported_low_rerank_case_and_point_six_gate_both_keep_unique_title(self):
  class Embed:
   def embed(self,texts):return [[.7062,math.sqrt(1-.7062**2)] for _ in texts]
  class Query:
   def embed(self,texts):return [[1,0] for _ in texts]
  class Rank:
   def rank(self,q,docs):return [(i,.3733) for i in range(len(docs))]
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);sources=root/'sources';sources.mkdir()
   (sources/'manual.md').write_text('# 问题57 附录-安装MetalLB负载均衡器\n安装控制器，再创建IPAddressPool与L2Advertisement。')
   config=RAGSettings(index_path=str(root/'index'),source_dir=str(sources),min_similarity=.6,rerank_enabled=False,http_origins=('http://127.0.0.1:11434',))
   ingest_documents(config,embedder=Embed());config.rerank_enabled=True;config.rerank_url='http://127.0.0.1:11434/v1/rerank'
   kb=SemanticKnowledge(config,Query(),Rank())
   for threshold in (0.0,.6):
    config.rerank_min_score=threshold;result=kb.assess('如何安装MetalLB',diagnostics=True)
    self.assertTrue(result['matched']);self.assertEqual(result['similarity'],.7062)
    self.assertEqual(result['hits'][0][0],.3733);self.assertEqual(result['rerank_threshold'],threshold)
    self.assertEqual(result['_candidate_decisions'][0]['title_match_type'],'operation_product_alias')
    self.assertIn('问题57',result['hits'][0][1]['title'])

class WarningDetailsTests(unittest.TestCase):
 def test_concrete_text_reason_and_evidence_are_logged_without_marking_request_failed(self):
  evidence=[{'id':'install','title':'安装MetalLB','content':'先安装控制器，再创建地址池。','revision':'rev1'}]
  text='执行 `kubectl apply -f example.yaml`，地址池192.168.1.0/24，版本v0.13.7。'
  issues=unsupported_literals(text,evidence)
  address=next(v for v in issues if v['kind']=='address')
  self.assertEqual(address['text'],'192.168.1.0/24');self.assertIn('地址池',address['answer_excerpt'])
  self.assertEqual(address['evidence_ids'],['install']);self.assertTrue(address['reason'])
  with patch.object(ops._log,'log') as logged,patch.object(ops._log,'info') as finished:
   with ops.capture_request():
    ops.grounding_warning(issues,evidence)
    ops.event('chat_completed',outcome='answered',reason='knowledge')
  warning=next(c for c in logged.call_args_list if c.args[1]=='generation_grounding_warning')
  fields=warning.kwargs['extra']['operation_fields']
  self.assertEqual(fields['evidence'][0]['content'],evidence[0]['content']);self.assertTrue(fields['warning_only'])
  document=finished.call_args.kwargs['extra']['operation_document']
  self.assertEqual(document['输出']['状态'],'answered');self.assertNotIn('失败节点',document['输出'])
 def test_secrets_are_redacted_but_literal_warning_details_remain(self):
  with patch.dict(os.environ,{'MODEL_API_KEY':'private-model-secret'}),patch.object(ops,'event') as logged:
   ops.grounding_warning([{'kind':'code','text':'key=private-model-secret 192.168.1.0/24'}],[])
  self.assertNotIn('private-model-secret',str(logged.call_args));self.assertIn('192.168.1.0/24',str(logged.call_args))

class ConfigurationTests(unittest.TestCase):
 def test_environment_zero_overrides_file_point_six_without_modifying_either(self):
  with tempfile.TemporaryDirectory() as t,patch.dict(os.environ,{'RERANK_MIN_SCORE':'0.0'},clear=True):
   path=Path(t)/'.env';text='MODEL_API_KEY=private-key\nRERANK_MIN_SCORE=0.6\n';path.write_text(text)
   report=inspect(RAGSettings(),path);value=report['thresholds']['RERANK_MIN_SCORE']
   self.assertEqual(value['effective'],0);self.assertEqual(value['code_default'],.6)
   self.assertEqual(value['source'],'process_environment');self.assertFalse(value['file_matches_effective'])
   self.assertEqual(path.read_text(),text);self.assertEqual(os.environ['RERANK_MIN_SCORE'],'0.0')
   self.assertNotIn('private-key',json.dumps(report))
 def test_default_and_duplicate_file_values_are_distinguishable(self):
  with tempfile.TemporaryDirectory() as t,patch.dict(os.environ,{},clear=True):
   path=Path(t)/'.env';path.write_text('RERANK_MIN_SCORE=0.6\nRERANK_MIN_SCORE=0.0\n')
   data=inspect(RAGSettings(),path)['thresholds']['RERANK_MIN_SCORE']
   self.assertEqual(data['source'],'code_default');self.assertTrue(data['duplicate_file_entries'])
   self.assertEqual(len(data['file_entries']),2)

class AdvisoryHTTPTests(unittest.TestCase):
 setUp=stream.LiveStreamTests.setUp
 tearDown=stream.LiveStreamTests.tearDown
 frames=stream.LiveStreamTests.frames
 def knowledge(self):
  row={'id':'install','title':'问题57 附录-安装MetalLB负载均衡器','source_file':'manual.docx','image_ids':[],
       'content':'手册给出MetalLB v0.13.12。先安装控制器，再创建IPAddressPool和L2Advertisement。地址池应使用实际环境中未占用的地址。'}
  self.server.service.knowledge.assess=lambda q:{'matched':True,'hits':[(.3733,row,.7062)],'method':'hybrid_rrf_rerank','threshold':.6,'rerank_threshold':0.0,'similarity':.7062}
 def test_known_install_steps_stream_without_inventing_ip_or_yaml(self):
  self.knowledge();release=threading.Event();done=threading.Event();prompts=[]
  def generate(model,messages,on_delta=None):
   prompts.append(messages);on_delta('先安装控制器，')
   if not release.wait(3):raise AssertionError('first tokens were buffered')
   on_delta('再创建IPAddressPool和L2Advertisement。资料未提供具体安装命令和YAML，请结合目标环境确认。');done.set()
   return '先安装控制器，再创建IPAddressPool和L2Advertisement。资料未提供具体安装命令和YAML，请结合目标环境确认。'
  try:
   with patch.object(Model,'_complete_request',generate):
    with self.client.stream('POST',f'/v1/sessions/{self.sid}/messages/stream',json={'message':'如何安装MetalLB','request_id':'install-known-steps'}) as response:
     frames=[]
     for kind,data in self.frames(response):
      frames.append((kind,data))
      if kind=='delta' and not done.is_set():release.set()
   result=next(data for kind,data in frames if kind=='complete')
   self.assertEqual(result['status'],'answered');self.assertTrue(result['citations'])
   self.assertEqual(result['answer'],''.join(d['text'] for k,d in frames if k=='delta'))
   self.assertNotIn('192.168.1.0/24',result['answer']);self.assertNotIn('```',result['answer'])
   self.assertIn('不能因为缺少局部细节',prompts[0][0]['content']);self.assertIn('禁止为补全答案自行编写',prompts[0][0]['content'])
  finally:release.set()
 def test_checker_exception_is_advisory_too(self):
  self.knowledge()
  def generate(model,messages,on_delta=None):
   if on_delta:on_delta('先安装控制器。')
   return '先安装控制器。'
  with patch.object(Model,'_complete_request',generate),patch('app.grounding.unsupported_literals',side_effect=ValueError('check failed')):
   response=self.client.post(f'/v1/sessions/{self.sid}/messages/stream',json={'message':'如何安装MetalLB','request_id':'checker-only-warning'})
  result=json.loads(response.text.split('event: complete\ndata: ')[1].split('\n\n')[0])
  self.assertEqual(result['answer'],'先安装控制器。');self.assertTrue(result['citations']);self.assertEqual(result['status'],'answered')
