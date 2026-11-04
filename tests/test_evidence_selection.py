import json
import tempfile
from pathlib import Path
import unittest
from unittest.mock import patch
from app.evidence_selection import EvidenceSelector,model_options
from app.rag import RAGSettings,SemanticKnowledge,ingest_documents
from app.observability import compact_steps

class Embed:
 def embed(self,texts):return [[1.,0.] for _ in texts]
class Model:
 def __init__(self):self.calls=[];self.invalid=False
 def complete(self,messages):
  self.calls.append(messages);assert model_options()['timeout']==5.
  data=json.loads(messages[-1]['content'])
  result=[]
  for row in data['candidates']:
   if '成功通过中国信通院' in row['content']:
    result.append({'id':row['id'],'support':'direct','quote':'不存在的内容' if self.invalid else 'SmartTITU成功通过中国信通院Token聚合服务平台能力评估。','reason':'正文明确说明平台通过的评估。'})
  return json.dumps({'evidence':result},ensure_ascii=False)
class Rank:
 def rank(self,q,docs):
  return sorted([(i,.78 if '成功通过中国信通院' in d else .95 if '适合用户' in d else .9) for i,d in enumerate(docs)],key=lambda x:x[1],reverse=True)

class SelectionTests(unittest.TestCase):
 def setUp(self):
  self.t=tempfile.TemporaryDirectory();root=Path(self.t.name);source=root/'sources';source.mkdir()
  (source/'article.md').write_text('# 平台评估报道\nSmartTITU成功通过中国信通院Token聚合服务平台能力评估。\n# SmartTITU适合用户\n适合企业开发者、管理者及政企机构。\n# 产品简介\nSmartTITU提供企业AI经营平台。\n# 平台功能\n支持模型接入和计费。')
  self.cfg=RAGSettings(index_path=str(root/'index.db'),source_dir=str(source),database_url='',vector_backend='sqlite',rerank_enabled=False,http_origins=('http://127.0.0.1:11434',),min_similarity=.6)
  self.embed=Embed();ingest_documents(self.cfg,embedder=self.embed)
  self.cfg.rerank_enabled=True;self.cfg.rerank_url='http://127.0.0.1:11434/v1/rerank';self.cfg.rerank_min_score=.6
  self.k=SemanticKnowledge(self.cfg,self.embed,Rank());self.model=Model();self.k.evidence_selector=EvidenceSelector(self.model)
 def tearDown(self):self.t.cleanup()
 def test_retrieved_specific_evidence_survives_misleading_top_three(self):
  for q in ['34. SmartTITU通过了中国信通院的什么评估？','SmartTITU获得了哪种平台能力评估？','中国信通院对SmartTITU做过什么测评？']:
   r=self.k.assess(q)
   self.assertTrue(r['matched']);self.assertEqual(r['selection_policy'],'semantic_evidence')
   self.assertEqual(len(r['hits']),1);self.assertEqual(r['hits'][0][1]['title'],'平台评估报道')
   self.assertEqual(self.cfg.context_k,3);self.assertEqual(self.cfg.rerank_min_score,.6)
   self.assertTrue(any(x['reason']=='not_selected_by_semantic_evidence' for x in r['_candidate_decisions']))
 def test_invalid_quote_and_model_failure_use_query_coverage_fallback(self):
  self.model.invalid=True;r=self.k.assess('通过了什么评估？');self.assertEqual(r['selection_policy'],'query_coverage_fallback')
  with patch.object(self.model,'complete',side_effect=TimeoutError()):
   r=self.k.assess('通过了什么评估？');self.assertEqual(len(r['hits']),1)
  self.assertIsNone(model_options())
 def test_real_question_survives_semantic_selector_timeout(self):
  with patch.object(self.model,'complete',side_effect=TimeoutError()):
   report=self.k.assess('SmartTITU通过了中国信通院的什么评估？')
  self.assertEqual(report['selection_policy'],'query_coverage_fallback')
  self.assertTrue(report['matched'])
  self.assertEqual([x[1]['title'] for x in report['hits']],['平台评估报道'])
  self.assertEqual(report['_configuration']['RERANK_MIN_SCORE']['effective'],.6)
  self.assertIsNone(model_options())
 def test_no_support_is_no_hit_and_no_threshold_bypass(self):
  self.model.complete=lambda messages:'{"evidence":[]}'
  r=self.k.assess('通过了什么评估？');self.assertFalse(r['matched']);self.assertEqual(r['reason'],'no_supporting_evidence')
  self.cfg.rerank_min_score=.99;self.model.calls=[]
  r=self.k.assess('通过了什么评估？');self.assertFalse(r['matched']);self.assertEqual(self.model.calls,[])
 def test_direct_title_path_preserves_metallb_style_navigation_without_extra_call(self):
  r=self.k.assess('SmartTITU适合用户');self.assertTrue(r['matched']);self.assertEqual(self.model.calls,[])
 def test_compact_log_keeps_selections_rejections_and_errors_not_duplicate_content(self):
  rows=[{'事件':'model_request_started','级别':'INFO','详情':{}},
        {'事件':'retrieval_candidates','级别':'INFO','详情':{'candidates':[{'id':str(i),'title':'topic','selected':i==0,'bm25':i,'reason':'outside_context_limit'} for i in range(20)]}},
        {'事件':'generation_grounding_warning','级别':'WARNING','详情':{'unsupported_text':'specific warning'}},
        {'事件':'stream_failed','级别':'ERROR','详情':{'error_code':'connection'}}]
  compact=compact_steps(rows);self.assertEqual(len(compact),3)
  self.assertEqual(len(compact[0]['详情']['candidates']),5);self.assertEqual(compact[0]['详情']['candidate_count'],20)
  self.assertEqual(compact[-1]['事件'],'stream_failed')

 def test_compact_content_log_retains_input_output_without_full_model_payload(self):
  from app import observability as ops
  with patch.dict('os.environ',{'LOG_DEBUG_CONTENT':'true','LOG_TRACE_DETAIL':'compact'}),patch.object(ops._debug_log,'handlers',[object()]),patch.object(ops._debug_log,'info') as emit:
   trace=ops.RequestTrace();trace.snapshot('chat_input',{'question':'客户问题'})
   trace.snapshot('model_input',{'messages':'不应出现在精简日志里的提示词'})
   trace.snapshot('chat_output',{'response':{'answer':'最终回答','citations':[],'images':[],'retrieval':{'full':'internal'}}})
   trace.record('chat_completed',{'outcome':'answered'});trace.finish()
   doc=emit.call_args.kwargs['extra']['operation_document']
   self.assertEqual(doc['输入']['问题'],'客户问题');self.assertEqual(doc['输出']['最终响应']['answer'],'最终回答')
   self.assertNotIn('不应出现在',json.dumps(doc,ensure_ascii=False));self.assertNotIn('retrieval',doc['输出']['最终响应'])

 def test_invalid_id_duplicate_and_whitespace_quote_cannot_replace_evidence(self):
  for payload in [ {'evidence':[{'id':'not-a-candidate','support':'direct','quote':'x','reason':'x'}]},
                   {'evidence':[{'id':'x','support':'direct','quote':'   ','reason':'x'}]},
                   {'evidence':'wrong type'} ]:
   self.model.complete=lambda messages,payload=payload:json.dumps(payload)
   self.assertEqual(self.k.assess('通过了什么评估？')['selection_policy'],'query_coverage_fallback')
 def test_multiple_supported_sources_can_remain_up_to_context_limit(self):
  def choose(messages):
   data=json.loads(messages[-1]['content'])
   return json.dumps({'evidence':[{'id':r['id'],'support':'partial','quote':r['content'],'reason':'支持问题的一个方面'} for r in data['candidates'][:3]]})
  self.model.complete=choose
  report=self.k.assess('介绍平台的用户和功能')
  self.assertEqual(len(report['hits']),3);self.assertEqual(report['selection_policy'],'semantic_evidence')

class FallbackRegressionTests(unittest.TestCase):
 def candidate(self,key,body,score=.9):
  return {'row':{'id':key,'title':key,'content':body},'score':score,'lexical':1.}
 def test_timeout_keeps_assessment_evidence_over_generic_product_introductions(self):
  from app.evidence_selection import fallback_evidence
  rows=[self.candidate('generic'+str(i),'SmartTITU为政企用户提供模型管理和计费服务。') for i in range(3)]
  rows.append(self.candidate('assessment','中企通信SmartTITU成功通过中国信通院首批Token聚合服务平台能力评估。',.74))
  for q in ['SmartTITU通过了中国信通院的什么评估？','中国信通院对SmartTITU做过什么评估？']:
   selected,policy=fallback_evidence(q,rows,3)
   self.assertEqual(policy,'query_coverage_fallback');self.assertEqual([x['row']['id'] for x in selected],['assessment'])
 def test_focused_excerpt_is_short_original_and_covers_late_evidence(self):
  from app.evidence_selection import focused_excerpt
  body='通用平台介绍。'*250+'成功通过中国信通院Token聚合服务平台能力评估。'+'附加介绍。'*200
  excerpt=focused_excerpt('通过中国信通院什么评估',body)
  self.assertLessEqual(len(excerpt),600);self.assertIn(excerpt,body);self.assertIn('中国信通院',excerpt)
 def test_fallback_preserves_multiple_supported_topics_and_never_adds_candidates(self):
  from app.evidence_selection import fallback_evidence
  rows=[self.candidate('registration','注册账号使用手机号短信验证码。'),self.candidate('authentication','企业认证需要公司名称及统一社会信用代码。')]+[self.candidate(str(i),'平台支持多模型。') for i in range(3)]
  selected,policy=fallback_evidence('注册账号和企业认证分别怎么做',rows,3)
  self.assertEqual({x['row']['id'] for x in selected},{'registration','authentication'})
  self.assertLessEqual(len(selected),3)

 def test_published_article_body_beats_logged_generic_word_candidates(self):
  from app.ingestion import parse_document
  from app.evidence_selection import fallback_evidence
  root=Path(__file__).resolve().parents[1]
  article=root/'knowledge_sources/中企通信成功通过中国信通院首批Token聚合服务平台能力评估.pdf'
  word=root/'knowledge_sources/SmartTITU客户问答.docx'
  if not article.exists() or not word.exists():self.skipTest('knowledge fixtures unavailable')
  rows=[];chunks=parse_document(word).chunks
  for n in [15,60,61]:
   row=next(x for x in chunks if x['title'].startswith('问题'+str(n)+' '))
   rows.append({'row':{**row,'id':'word-'+str(n)},'score':.83,'lexical':2.})
  for i,row in enumerate(parse_document(article).chunks):
   rows.append({'row':{**row,'id':'pdf-'+str(i)},'score':.74,'lexical':30.})
  selected,policy=fallback_evidence('SmartTITU通过了中国信通院的什么评估？',rows,3)
  self.assertEqual(policy,'query_coverage_fallback');self.assertTrue(selected)
  self.assertTrue(all(x['row']['id'].startswith('pdf-') for x in selected))

class ApiFallbackRegression(unittest.TestCase):
 def test_image_sdk_subject_beats_glossary_incidental_words(self):
  from app.evidence_selection import fallback_evidence
  from app.ingestion import parse_document
  from app.core import BASE
  chunks=parse_document(BASE/'knowledge_sources/SmartTITU客户问答.docx').chunks
  rows=[]
  for i,row in enumerate(chunks):
   if any(row['title'].startswith('问题'+str(n)+' ') for n in (73,181,182,188,266)):
    rows.append({'row':{**row,'id':str(i)},'score':.6,'lexical':1})
  selected,_=fallback_evidence('图像生成API的调用方式，openaI',rows,3)
  self.assertTrue(any('问题188 ' in c['row']['title'] for c in selected))
  self.assertFalse(any('问题73 ' in c['row']['title'] for c in selected))
