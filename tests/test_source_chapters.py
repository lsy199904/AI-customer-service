"""Source chapter labels preserve question identity, images and revision downloads."""
import tempfile
from pathlib import Path
import unittest
import zipfile
from app.ingestion import parse_document,split_sections
from app.rag import RAGSettings,ingest_documents,SemanticKnowledge
from app.core import Settings,Service

class SourceChapters(unittest.TestCase):
 def test_word_numeric_styles_keep_top_level_chapter_across_questions(self):
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/'manual.docx'
   with zipfile.ZipFile(path,'w') as z:
    z.writestr('word/styles.xml','<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:style w:styleId="3"><w:name w:val="heading 1"/></w:style><w:style w:styleId="4"><w:name w:val="heading 2"/></w:style></w:styles>')
    xml='<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body>'
    for style,text in [('3','常用外部链接'),('4','问题1 产品网页'),('', '查看产品网页。'),('3','业务流程'),('4','问题2 注册流程'),('', '手机号和验证码注册。'),('4','问题3 登录流程'),('', '旧ESP账号密码也可登录。')]:
     xml+='<w:p>'+('<w:pPr><w:pStyle w:val="'+style+'"/></w:pPr>' if style else '')+'<w:r><w:t>'+text+'</w:t></w:r></w:p>'
    z.writestr('word/document.xml',xml+'</w:body></w:document>')
   rows=parse_document(path).chunks
   self.assertEqual([c['section_title'] for c in rows],['常用外部链接','业务流程','业务流程'])
   self.assertEqual(rows[-1]['title'],'问题3 登录流程')
 def test_split_chunks_keep_chapter_sources_and_images(self):
  blocks=[{'text':'业务流程','heading':True,'level':1},{'text':'注册流程','heading':True,'level':2},
   {'text':'步骤。'*500,'heading':False,'locator':'段落1'},
   {'text':'来源：原始流程','heading':False},{'text':'配图：business-register','heading':False}]
  rows=split_sections(blocks,'用户手册',max_chars=200,overlap=20)
  self.assertGreater(len(rows),1)
  self.assertTrue(all(r['section_title']=='业务流程' and r['image_ids']==['business-register'] and r['source_references']==['来源：原始流程'] for r in rows))
 def test_citation_label_and_detail_after_ingest_and_restart(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);source=root/'sources';source.mkdir()
   (source/'manual.md').write_text('# 常用外部链接\n## 问题1 产品网页\n查看官网。\n# 11 业务流程\n## 问题2 注册流程\n手机号验证码注册。\n配图：business-register\n')
   class Embed:
    def embed(self,texts):return [[1.,0.] for _ in texts]
   rag=RAGSettings(source_dir=str(source),index_path=str(root/'rag.db'),rerank_enabled=False,http_origins=('http://127.0.0.1:11434',))
   ingest_documents(rag,embedder=Embed());config=Settings(retrieval_backend='lexical',secret='chapter-citation-test-secret-abcdefghijklmnopqrstuvwxyz',db=str(root/'chat.db'))
   for _ in range(2):
    config.retrieval_backend='lexical'
    service=Service(config);service.knowledge=SemanticKnowledge(rag,Embed());service.config.retrieval_backend='semantic'
    try:
     records=list(service.knowledge.rows.values())
     citations=[service.citation(row) for row in records]
     self.assertEqual([c['display_title'] for c in citations],['用户手册-常用外部链接','用户手册-业务流程'])
     self.assertEqual(citations[1]['title'],'问题2 注册流程')
     self.assertTrue(citations[1]['download_url'])
     detail=service.source(records[1]['id']);self.assertIn('验证码',detail['content'])
     self.assertEqual(detail['display_title'],'用户手册-业务流程')
    finally:service.close()
