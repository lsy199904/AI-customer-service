"""Explicit original lists protect the requested category, never invent an answer."""
from pathlib import Path
import tempfile
import shutil
import unittest
from app.source_lists import extract_lists,explicit_list_request
from app.retrieval import title_text,lexical_ranking
from app.rag import RAGSettings,ingest_documents,SemanticKnowledge
from tests.test_wechat_pdfs import ROOT,LocalEmbedding

class SourceListTests(unittest.TestCase):
 def test_actual_article_lists_are_quoted_not_generated(self):
  from app.ingestion import parse_document
  path=next((ROOT/'knowledge_sources').glob('SmartTITU网站*.pdf'));row=parse_document(path).chunks[0]
  values=extract_lists(row['content'])
  self.assertEqual(values[0]['items'],['便捷管控','经济实惠','安全可信'])
  for question in ['SmartTITU的三大核心价值是什么？','27. SmartTITU 的三大核心价值是什么？','请介绍SmartTITU三大核心价值','SmartTITU的核心价值有哪些？','核心价值是什么？']:
   self.assertTrue(explicit_list_request(question,row))
 def test_generic_other_product_and_mismatched_count_are_not_promoted(self):
  row={'title':'Acme平台','content':'Acme围绕可靠服务、便捷管理、经济实惠三大核心价值提供服务。'}
  self.assertTrue(explicit_list_request('Acme三大核心价值是什么？',row))
  self.assertFalse(explicit_list_request('Other的三大核心价值是什么？',row))
  self.assertFalse(explicit_list_request('Acme有多少计费方式？',row))
  self.assertEqual(extract_lists('Acme包括可靠、便捷三大核心价值。'),[])
 def test_copied_question_number_is_not_a_product_version(self):
  self.assertEqual(title_text('27. SmartTITU三大核心价值'),'SmartTITU三大核心价值')
  self.assertEqual(title_text('3.5版本部署说明'),'3.5版本部署说明')
 def test_literal_list_survives_unrelated_high_rerank_without_lowering_threshold(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);source=root/'sources';source.mkdir()
   shutil.copyfile(next((ROOT/'knowledge_sources').glob('SmartTITU网站*.pdf')),source/'website.pdf')
   (source/'old.md').write_text('# SmartTITU的五个统一\n统一接入、统一计量、统一运营等相关平台能力。')
   config=RAGSettings(index_path=str(root/'index.db'),source_dir=str(source),database_url='',vector_backend='sqlite',pdf_media_enabled=False,rerank_enabled=False,http_origins=('http://127.0.0.1:11434',),min_similarity=.6)
   embed=LocalEmbedding();ingest_documents(config,embedder=embed)
   config.rerank_enabled=True;config.rerank_url='http://127.0.0.1:11434/v1/rerank';config.rerank_min_score=.6
   class Rank:
    def rank(self,q,docs):return sorted([(i,.05 if '便捷管控' in text and '三大核心价值' in text else .95) for i,text in enumerate(docs)],key=lambda r:r[1],reverse=True)
   report=SemanticKnowledge(config,embed,Rank()).assess('27. SmartTITU的三大核心价值是什么？')
   self.assertTrue(report['matched']);self.assertEqual(report['selection_policy'],'unique_title')
   self.assertEqual(len(report['hits']),1);self.assertEqual(report['hits'][0][1]['source_file'],'website.pdf')
   self.assertIn('便捷管控',report['hits'][0][1]['content'])
   chosen=next(d for d in report['_candidate_decisions'] if d['selected'])
   self.assertEqual(chosen['title_match_type'],'explicit_source_list');self.assertEqual(report['rerank_threshold'],.6)
