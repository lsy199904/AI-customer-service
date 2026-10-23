"""User-reported retrieval regressions, including intentionally misleading model scores."""
from pathlib import Path
import tempfile
import unittest
from app.rag import RAGSettings,SemanticKnowledge,ingest_documents
from app.retrieval import retrieval_text,topic
from app.core import customer_answer

class AdverseEmbedding:
 def embed(self,texts):
  # Deliberately favor feature sections over registration/overview; titles must still be recalled.
  return [[0,1] if '概况' in t or '注册与认证' in t else [1,0] for t in texts]

class AdverseReranker:
 def __init__(self):self.seen=[]
 def rank(self,query,documents):
  self.seen=documents
  return sorted([(i,.1 if '概况' in d or '注册与认证' in d else .99) for i,d in enumerate(documents)],key=lambda pair:pair[1],reverse=True)

class HybridRetrievalTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.sources=self.root/'sources';self.sources.mkdir()
  (self.sources/'customer.md').write_text('# 问题4 企业注册与认证流程\n手机号和验证码登录，填写企业资料，再完成企业认证。\n配图：enterprise-register\n原文链接：https://example.com/register\n# 问题10 第6页 TITU Hub概况\n聚合多模型，提供统一API接入、配额、限流、用量、计费、日志和安全审计。\n原文链接：https://example.com/hub\n# 问题16 TITU Edge概况\n企业侧资源与权限管理，支持本地部署。\n# 问题50 TITU Hub核心能力-聚合优选模型与模型内路由\n统一API网关对接不同供应商。\n# 问题51 TITU Hub核心能力-资源管理运营\n提供用量统计与操作追溯。\n',encoding='utf-8')
  self.config=RAGSettings(index_path=str(self.root/'rag.db'),source_dir=str(self.sources),rerank_enabled=False,http_origins=('http://127.0.0.1:11434',),min_similarity=.45)
  self.embed=AdverseEmbedding();ingest_documents(self.config,embedder=self.embed)
  self.rank=AdverseReranker();self.config.rerank_enabled=True;self.config.rerank_url='http://127.0.0.1:11434/v1/rerank'
  self.k=SemanticKnowledge(self.config,self.embed,self.rank)
 def tearDown(self):self.temp.cleanup()
 def test_audit_procedure_excludes_sandbox_even_with_adverse_reranking(self):
  path=self.sources/'audit.md'
  path.write_text('# 操作审计\n管理员打开操作审计，查看操作记录。\n# 安全审计\n打开安全审计菜单，查看报告。\n# 全栈安全-可信安全沙箱\n提供链路加密、隔离和操作审计。\n',encoding='utf-8')
  ingest_documents(self.config,embedder=self.embed)
  r=self.k.assess('安全审计流程')
  self.assertTrue(r['title_matched'])
  self.assertEqual([row['title'] for _,row,_ in r['hits']],['安全审计'])
 def test_quick_start_procedure_does_not_select_deployment_or_audit(self):
  (self.sources/'start.md').write_text('# 快速使用检查清单总结\n注册、认证、订购套餐、创建密钥。\n# 快速部署-执行部署\n部署容器。\n# 安全审计\n查看审计记录。\n',encoding='utf-8')
  ingest_documents(self.config,embedder=self.embed)
  r=self.k.assess('快速使用流程')
  self.assertEqual([row['title'] for _,row,_ in r['hits']],['快速使用检查清单总结'])
 def test_procedure_matching_does_not_capture_comparisons_or_generic_flow(self):
  from app.retrieval import title_matches
  titles=['安全审计','安全审计报告内容','全栈安全-可信安全沙箱']
  self.assertEqual(title_matches('安全审计流程',titles),[True,False,False])
  self.assertEqual(title_matches('流程',titles),[False,False,False])
  self.assertEqual(title_matches('安全审计与沙箱有什么区别',titles),[False,False,False])
 def test_registration_question_recovers_below_dense_threshold_and_returns_diagram(self):
  # Its vector scores zero against the query, mimicking the reported recall failure.
  class Query:
   def embed(me,texts):return [[1,0]]
  self.k.embedder=Query();r=self.k.assess('企业注册与认证流程是什么',diagnostics=True)
  self.assertTrue(r['matched']);self.assertTrue(r['title_matched'])
  self.assertEqual(len(r['hits']),1);self.assertIn('问题4',r['hits'][0][1]['title'])
  self.assertEqual(r['hits'][0][1]['image_ids'],['enterprise-register'])
  self.assertEqual(r['hits'][0][2],0)
 def test_hub_overview_is_not_replaced_by_core_features(self):
  r=self.k.assess('TITUHub概况',diagnostics=True)
  self.assertTrue(r['title_matched']);self.assertIn('问题10',r['hits'][0][1]['title'])
  self.assertFalse(any('核心能力' in row['title'] for _,row,_ in r['hits']))
  self.assertIn('reranked',r['_diagnostics'])
 def test_overview_paraphrases_focus_on_overview_not_features(self):
  for query in ['TITUHub是什么','介绍一下TITU Hub','TITU Hub的概况','TITUHub概况是什么呢']:
   r=self.k.assess(query)
   self.assertTrue(r['title_matched'],query)
   self.assertTrue(all('概况' in row['title'] for _,row,_ in r['hits']),query)
 def test_hub_and_edge_topics_are_distinct(self):
  r=self.k.assess('TITU Edge概况')
  self.assertEqual(len(r['hits']),1);self.assertIn('TITU Edge',r['hits'][0][1]['title'])
 def test_semantic_paraphrase_still_works_without_matching_words(self):
  # The backend remains semantic: no title/keyword match is required.
  r=self.k.assess('How do I onboard my organization?')
  self.assertTrue(r['matched']);self.assertFalse(r['title_matched'])
 def test_reranker_input_contains_no_source_urls(self):
  self.k.assess('TITUHub概况')
  self.assertTrue(self.rank.seen);self.assertFalse(any('https://' in value for value in self.rank.seen))
 def test_diagnostics_are_opt_in(self):
  self.assertNotIn('_diagnostics',self.k.assess('TITUHub概况'))
 def test_unrelated_query_is_not_rescued_by_generic_words(self):
  class Outside:
   def embed(me,texts):return [[-1,-1]]
  self.k.embedder=Outside()
  self.assertFalse(self.k.assess('月球采矿机怎么更换发动机')['matched'])
 def test_retrieval_cleaning_preserves_display_content(self):
  row={'title':'问题10 第6页 TITU Hub概况','content':'统一模型接入。\n原文链接：https://example.com/abc\n图片URL：https://example.com/image.png'}
  self.assertEqual(retrieval_text(row),'TITU Hub概况\n统一模型接入。')
  self.assertIn('https://',row['content'])
 def test_topic_normalizes_product_spacing_and_polite_suffix(self):
  self.assertEqual(topic('请问 TITUHub概况是什么？',question=True),topic('问题10 第6页 TITU Hub概况'))
 def test_internal_ids_are_not_displayed_as_prose(self):
  answer=customer_answer('支持统一接入（KB-0f567c3f2b830588627d13d2）。请查看 DOC-67437138c0483c13eaa9。')
  self.assertNotIn('KB-',answer);self.assertNotIn('DOC-',answer);self.assertIn('支持统一接入',answer)
