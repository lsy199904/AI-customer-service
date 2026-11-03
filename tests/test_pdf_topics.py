"""Topic boundaries, natural recommendations and source labels, not LLM benchmarks."""
from pathlib import Path
import unittest
from app.ingestion import parse_document,split_sections
from app.pdf_topics import topics,enrich
from app.retrieval import lexical_ranking,fuse,lexical_query
from app.conversation import recommended_questions,suggestion_sources,recommended_selection
from app.image_policy import ImagePolicy
from app.core import Service

ROOT=Path(__file__).resolve().parent.parent

class TopicTests(unittest.TestCase):
 def test_numbered_topic_continues_over_page_breaks(self):
  blocks=topics([(1,'1. Deployment\nInstall the package.'),(2,'Continue installation.\n2. Verification\nCheck service health.')],'Manual')
  chunks=split_sections(blocks,'Manual')
  self.assertEqual([c['title'] for c in chunks],['Deployment','Verification'])
  self.assertEqual(chunks[0]['source_pages'],[1,2]);self.assertIn('Continue installation.',chunks[0]['content'])
  self.assertNotIn('Check service health.',chunks[0]['content'])
 def test_without_headings_uses_content_chunks_instead_of_page_chunks(self):
  blocks=topics([(1,'A sentence about installation.'),(2,'Another sentence about installation.')],'Manual')
  chunks=split_sections(blocks,'Manual')
  self.assertEqual(len(chunks),1);self.assertEqual(chunks[0]['source_pages'],[1,2])
  self.assertEqual(chunks[0]['title'],'Manual概览')
 def test_declared_pdf_outline_or_font_heading_is_respected(self):
  chunks=split_sections(topics([(1,'Deployment\nInstall the package.\nVerification\nCheck service health.')],'Manual',{'Deployment','Verification'}),'Manual')
  self.assertEqual([c['title'] for c in chunks],['Deployment','Verification'])
 def test_actual_pdf_font_headings_are_parsed_without_page_titles(self):
  import tempfile
  from pypdf import PdfWriter
  from pypdf.generic import DictionaryObject,NameObject,DecodedStreamObject
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/'manual.pdf';writer=PdfWriter();page=writer.add_blank_page(612,792)
   font=DictionaryObject({NameObject('/Type'):NameObject('/Font'),NameObject('/Subtype'):NameObject('/Type1'),NameObject('/BaseFont'):NameObject('/Helvetica')})
   page[NameObject('/Resources')]=DictionaryObject({NameObject('/Font'):DictionaryObject({NameObject('/F1'):writer._add_object(font)})})
   stream=DecodedStreamObject();stream.set_data(b'BT /F1 18 Tf 50 750 Td (Deployment) Tj /F1 12 Tf 0 -30 Td (Install the service and verify the installed package before starting the application.) Tj /F1 18 Tf 0 -60 Td (Verification) Tj /F1 12 Tf 0 -30 Td (Check service health and examine the startup log before accepting the deployment.) Tj ET')
   page[NameObject('/Contents')]=writer._add_object(stream)
   with path.open('wb') as out:writer.write(out)
   parsed=parse_document(path)
   self.assertEqual([c['title'] for c in parsed.chunks],['Deployment','Verification'])
   self.assertTrue(all(c['source_kind']=='pdf' for c in parsed.chunks))

 def test_long_topic_has_precise_chunk_pages(self):
  blocks=topics([(1,'1. Deployment\n'+'First page. '*30),(2,'Second page. '*30)],'Manual')
  chunks=split_sections(blocks,'Manual',max_chars=200,overlap=30)
  self.assertEqual(chunks[0]['source_pages'],[1]);self.assertEqual(chunks[-1]['source_pages'],[2])
  self.assertTrue(all(c['title']=='Deployment' for c in chunks))
 def test_cleaning_is_article_specific_not_global_truncation(self):
  chunks=split_sections(topics([(1,'Operational note.\n往期推荐\nImportant appendix.')],'Manual'),'Manual')
  self.assertIn('Important appendix.',chunks[0]['content'])
 def test_source_label_uses_topic_and_preserves_hidden_pages(self):
  service=object.__new__(Service)
  class Config:source_url=''
  service.config=Config()
  r={'id':'one','title':'私有化部署','section_title':'私有化部署','source_kind':'wechat','source_file':'article.pdf','source_pages':[1,2]}
  result=service.citation(r)
  self.assertEqual(result['display_title'],'公众号资料－私有化部署')
  self.assertNotIn('页',result['display_title']);self.assertEqual(result['pages'],[1,2])
  r['source_kind']='pdf';self.assertEqual(service.citation(r)['display_title'],'文档资料－私有化部署')
 def test_capability_question_cannot_accidentally_attach_diagram(self):
  proposed={'need_images':True,'reason':'visual_explanation','flow_ids':[],'multiple_flows':False,'image_ids':['overview']}
  for q in ['SmartTITU支持国产信创环境吗？','是否兼容国产环境？','有哪些安全可信Token应用场景？']:
   decision=ImagePolicy.guard(q,proposed)
   self.assertFalse(decision['need_images']);self.assertEqual(decision['reason'],'fact_only')
  self.assertTrue(ImagePolicy.guard('支持哪种方案，给我看看架构图？',proposed)['need_images'])

class ArticleRetrievalTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.rows=[]
  for path in (ROOT/'knowledge_sources').iterdir():
   if path.suffix not in {'.pdf','.docx'}:continue
   for i,c in enumerate(parse_document(path).chunks):
    cls.rows.append({**c,'id':path.stem+str(i),'source_file':path.name,'revision':'test'})
 def test_screenshot_queries_rank_direct_pdf_topics_and_enter_fusion(self):
  cases=[('SmartTITU有哪些安全可信Token应用场景？','企业级五大安全可信Token应用场景概览'),
         ('我们要求数据不出域，适合用哪种服务？','私有化部署'),
         ('SmartTITU支持国产信创环境吗？','私有化部署')]
  for query,title in cases:
   ranked=sorted(lexical_ranking(query,[(.1,r) for r in self.rows]),key=lambda s:s['lexical'],reverse=True)
   self.assertEqual(ranked[0]['row']['title'],title)
   self.assertTrue(ranked[0]['row']['source_file'].endswith('.pdf'))
   candidates=fuse(query,[(.1,r) for r in self.rows],.6,10)
   self.assertTrue(any(s['row']['title']==title for s in candidates))
 def test_natural_recommendation_is_bound_to_same_active_topic(self):
  class Knowledge:pass
  k=Knowledge();k.rows={r['id']:r for r in self.rows}
  private=next(r for r in self.rows if r['title']=='私有化部署')
  suggestions=recommended_questions(k,'数据不出域',evidence=[private])
  self.assertIn(private['recommended_question'],suggestions)
  self.assertTrue(all('第2页' not in q for q in suggestions))
  bindings=suggestion_sources(k,suggestions)
  binding=next(b for b in bindings if b['knowledge_id']==private['id'])
  history=[{'role':'assistant','response':{'suggestion_sources':bindings}}]
  self.assertEqual(recommended_selection(k,binding['question'],history),('私有化部署',private['id']))
  k.rows[private['id']]={**private,'revision':'new'}
  self.assertIsNone(recommended_selection(k,binding['question'],history)[1])
 def test_old_page_placeholders_are_not_suggested(self):
  class Knowledge:rows={'old':{'id':'old','title':'公众号文章 第2页','content':'','source_file':'article.pdf'}}
  self.assertNotIn('公众号文章 第2页',recommended_questions(Knowledge(),'数据不出域',related_titles=['公众号文章 第2页']))
 def test_lexical_normalization_does_not_rewrite_original_or_drop_domain_terms(self):
  self.assertEqual(lexical_query('我们要求数据不出域，适合用哪种服务？'),'数据不出域，')
  self.assertIn('企业认证',lexical_query('我们需要企业认证失败如何处理？'))
