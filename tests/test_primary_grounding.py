"""Regression for explicit chapters being displaced by incidental mentions/history."""
from pathlib import Path
import math
import tempfile
import unittest
from unittest.mock import patch
from app.rag import RAGSettings,SemanticKnowledge,ingest_documents
from app.core import Model,Settings
from app.grounding import unsupported_literals,citation_ids
from app.conversation import suggestion_sources,recommended_selection

class Embedding:
 def embed(self,texts):
  values=[]
  for text in texts:
   score=.7464 if text.startswith('附录-安装MetalLB') else .524 if text.startswith('快速部署') else .5083 if text.startswith('故障排查') else .4695
   values.append([score,math.sqrt(1-score*score)])
  return values
class Query:
 def embed(self,texts):return [[1,0] for _ in texts]
class Rerank:
 def rank(self,q,docs):return sorted([(i,.49035 if d.startswith('附录-安装MetalLB') else .7148) for i,d in enumerate(docs)],key=lambda r:-r[1])

class PrimaryTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();root=Path(self.temp.name);self.sources=root/'sources';self.sources.mkdir()
  self.path=self.sources/'manual.md'
  self.path.write_text('# 问题57 附录-安装MetalLB负载均衡器\n安装MetalLB负载均衡器，先准备配置，再执行安装。\n# 问题52 快速部署-验证与访问\n检查MetalLB负载均衡器的访问地址。\n# 问题56 故障排查\n检查MetalLB负载均衡器状态。\n# 问题47 部署前准备-前置条件\n部署前需要MetalLB负载均衡器。\n')
  self.c=RAGSettings(index_path=str(root/'rag.db'),source_dir=str(self.sources),min_similarity=.6,rerank_enabled=False,http_origins=('http://127.0.0.1:11434',))
  ingest_documents(self.c,embedder=Embedding())
  self.c.rerank_enabled=True;self.c.rerank_url='http://127.0.0.1:11434/v1/rerank';self.c.rerank_min_score=.6
  self.k=SemanticKnowledge(self.c,Query(),Rerank())
 def tearDown(self):self.temp.cleanup()
 def test_explicit_chapter_retained_before_rerank_gate(self):
  for q in ['安装MetalLB负载均衡器','附录-安装MetalLB负载均衡器','如何安装MetalLB负载均衡器','请问安装MetalLB负载均衡器步骤']:
   with self.subTest(q=q):
    r=self.k.assess(q,diagnostics=True)
    self.assertTrue(r['matched']);self.assertEqual(len(r['hits']),1)
    self.assertIn('问题57',r['hits'][0][1]['title']);self.assertTrue(r['title_matched'])
    selected=[d for d in r['_candidate_decisions'] if d['selected']]
    self.assertEqual(selected[0]['reason'],'selected_primary_title');self.assertTrue(selected[0]['rerank_gate_bypassed'])
    self.assertEqual(r['similarity_knowledge_id'],selected[0]['id'])
    self.assertEqual(len(r['_candidate_decisions']),4)
 def test_semantic_gate_unchanged_without_explicit_title(self):
  class Low:
   def rank(self,q,docs):return [(i,.49) for i in range(len(docs))]
  self.k.reranker=Low()
  r=self.k.assess('负载均衡组件的地址访问异常')
  self.assertFalse(r['matched']);self.assertEqual(r['reason'],'all_below_rerank_threshold')
  self.assertTrue(all(d['reason']=='below_rerank_threshold' for d in r['_candidate_decisions'] if d.get('rerank_score') is not None))
 def test_recommended_click_uses_current_active_source(self):
  rows=list(self.k.rows.values());install=next(r for r in rows if '问题57' in r['title'])
  bindings=suggestion_sources(self.k,['附录-安装MetalLB负载均衡器'])
  history=[{'role':'assistant','response':{'suggestion_sources':bindings}}]
  q,key=recommended_selection(self.k,'附录-安装MetalLB负载均衡器',history)
  self.assertEqual(key,install['id']);self.assertTrue(self.k.assess(q,preferred_id=key)['matched'])
  self.k.store.deactivate(install['document_id'])
  self.assertEqual(recommended_selection(self.k,q,history),(q,None));self.assertFalse(self.k.assess(q)['matched'])
 def test_duplicate_titles_are_not_arbitrarily_protected(self):
  (self.sources/'duplicate.md').write_text('# 附录-安装MetalLB负载均衡器\n另一个产品版本的安装。')
  ingest_documents(self.c,embedder=Embedding())
  class Low:
   def rank(self,q,docs):return [(i,.49) for i in range(len(docs))]
  self.k.reranker=Low();r=self.k.assess('安装MetalLB负载均衡器')
  self.assertTrue(r['title_ambiguous']);self.assertFalse(r['matched'])
 def test_not_product_specific_and_failure_question_not_forced(self):
  from app.retrieval import title_signals
  self.assertTrue(title_signals('如何安装Redis','问题1 附录-安装Redis'.split('|'))[0]['strong'])
  self.assertFalse(title_signals('MetalLB安装失败',['附录-安装MetalLB负载均衡器'])[0]['strong'])

class GroundingTests(unittest.TestCase):
 def test_unsupported_commands_version_address_and_url_rejected(self):
  evidence=[{'id':'k','title':'安装','content':'安装MetalLB v0.13.12，先准备配置。'}]
  for answer in ['运行 `kubectl apply -f metallb.yaml`','使用 v0.13.7','分配192.168.1.240/30','下载https://example.com/install.yaml','```yaml\naddresses:\n- 192.168.1.240/30\n```']:
   with self.subTest(answer=answer):self.assertTrue(unsupported_literals(answer,evidence))
  self.assertFalse(unsupported_literals('使用 v0.13.12，先准备配置。',evidence))
 def test_supported_current_commands_pass_and_stage_is_scoped(self):
  e=[{'id':'k','content':'先准备配置。\n运行 kubectl apply -f metallb.yaml\nhttps://example.com/x'}]
  self.assertFalse(unsupported_literals('运行 `kubectl apply -f metallb.yaml`',e))
  self.assertTrue(unsupported_literals('运行 `kubectl apply -f metallb.yaml`',e,{'stage_evidence':'先准备配置。'}))
 def test_historical_assistant_commands_never_enter_prompt(self):
  model=Model(Settings(retrieval_backend='lexical'))
  evidence=[{'id':'k','title':'安装','content':'准备配置。'}]
  history=[{'role':'user','content':'旧问题'},{'role':'assistant','content':'kubectl apply -f old.yaml'}]
  with patch.object(model,'complete',return_value='先准备配置。') as call:
   model.answer('然后呢',history,evidence,{'_resolved_question':'安装MetalLB负载均衡器 然后呢'})
  messages=call.call_args.args[0]
  self.assertEqual(len(messages),2);self.assertNotIn('old.yaml',str(messages));self.assertIn('安装MetalLB',messages[-1]['content'])
 def test_citations_do_not_include_incidental_chapters(self):
  e=[{'id':'install','content':'执行安装流程，配置地址池。'},{'id':'audit','content':'查看安全审计报告与日志。'}]
  self.assertEqual(citation_ids('执行安装流程，配置地址池。',e),['install'])

 def test_multiple_followups_keep_user_topic_without_assistant_facts(self):
  from app.conversation import contextual_query
  history=[{'role':'user','content':'安装MetalLB负载均衡器'},{'role':'assistant','content':'旧错误命令'},
           {'role':'user','content':'然后呢'},{'role':'assistant','content':'另一段旧命令'}]
  self.assertEqual(contextual_query('还有呢',history),'安装MetalLB负载均衡器 还有呢')
