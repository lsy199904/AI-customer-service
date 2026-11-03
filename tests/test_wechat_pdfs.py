"""Public PDFs: verify real parsing and isolated ingestion, not model accuracy.

Original bytes are published unchanged. Tests use controlled local embeddings;
no production PostgreSQL/Milvus or model endpoints are contacted.
"""
import hashlib
import re
import zipfile
from pathlib import Path
import shutil
import tempfile
import unittest
from pypdf import PdfReader
from app.ingestion import clean_pdf_text,parse_document
from app.rag import RAGSettings,DocumentStore,ingest_documents

ROOT=Path(__file__).resolve().parent.parent
ARTICLES={
 '中企通信成功通过中国信通院首批Token聚合服务平台能力评估.pdf':(7,4,'3b1cb0a0ac0dd9d36bc89d6256a9920a4cb0c1c92b0346bdfb56016dce0894a5',
    ['中国信通院','Token 聚合服务平台','六大能力域']),
 '企业级五大安全可信Token应用场景，看这一篇就够了！.pdf':(9,6,'2ee60f951ff2391f0a52568d6da9d9bb6b4eadf0889933655bdf03068cae5fe2',
    ['私有化部署','云端Token安全服务','精细化Token管理服务','终端Agent管控服务','AICC']),
 'SmartTITU网站上线，三大核心价值助力企业安全、高效、低成本用好大模型！.pdf':(8,4,'0881fdfdf77ab12738ecfc52325456f63ca16915c585bf2ebe3bf68dbf495d6d',
    ['便捷管控','经济实惠','安全可信','4006-517-550']),
}

class LocalEmbedding:
 def __init__(self):self.calls=[]
 def embed(self,texts):
  self.calls.extend(texts)
  return [[1.,float(len(t)%7+1),float(len(t)%11+1)] for t in texts]

class WechatPDFTests(unittest.TestCase):
 def test_original_bytes_pages_and_core_text_are_preserved(self):
  for name,(pages,count,digest,terms) in ARTICLES.items():
   with self.subTest(article=name):
    path=ROOT/'knowledge_sources'/name;parsed=parse_document(path)
    self.assertEqual(hashlib.sha256(path.read_bytes()).hexdigest(),digest)
    self.assertEqual(parsed.sha256,digest);self.assertEqual(parsed.raw,path.read_bytes())
    self.assertEqual(len(parsed.chunks),count)
    self.assertTrue(all(1<=p<=pages for c in parsed.chunks for p in c['source_pages']))
    body='\n'.join(c['title']+'\n'+c['content'] for c in parsed.chunks)
    for term in terms:self.assertIn(re.sub(r'\s+','',term),re.sub(r'\s+','',body))
    self.assertNotIn('https://mp.weixin.qq.com/s?',body)
    self.assertTrue(all(any('https://mp.weixin.qq.com/s?' in ref for ref in c['source_references']) for c in parsed.chunks))
    self.assertTrue(all(not c['image_ids'] for c in parsed.chunks))
    for c in parsed.chunks:
     self.assertIn('PDF物理第',c['source_locator']);self.assertNotRegex(c['title'],r'第\d+页');self.assertTrue(c['recommended_question'])
 def test_business_sections_survive_while_print_furniture_is_removed(self):
  path=ROOT/'knowledge_sources'/'企业级五大安全可信Token应用场景，看这一篇就够了！.pdf'
  chunks=parse_document(path).chunks
  self.assertEqual([c['title'] for c in chunks[1:]],['私有化部署','云端 Token 安全服务','精细化 Token 管理服务','终端 Agent 管控服务','极高安全要求的 Token 服务'])
  private=chunks[1]
  self.assertEqual(private['source_pages'],[2])
  self.assertIn('数据不出域',private['content']);self.assertIn('国产信创环境',private['content'])
  self.assertNotIn('云端 Token 安全服务',private['content'])
  for c in chunks:
   self.assertNotRegex(c['content'],r'2026/11/3|https://mp|往期推荐|\d/9')
   self.assertNotIn('中信国际电讯智信词元平台荣获',c['content'])

 def test_pdf_spacing_cleanup_preserves_latin_commands_and_line_boundaries(self):
  self.assertEqual(clean_pdf_text('私 有 化 部 署\nToken service API Key 192.168.1.1'),
                   '私有化部署\nToken service API Key 192.168.1.1')
  self.assertEqual(clean_pdf_text('企业 认证需要 12 位密码'), '企业认证需要 12 位密码')

 def test_pdf_parser_upgrade_updates_only_pdf_revisions(self):
  from dataclasses import replace
  from unittest.mock import patch
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);source=root/'sources';source.mkdir()
   (source/'existing.md').write_text('# 原有知识\n原有业务内容。')
   for name in ARTICLES:shutil.copyfile(ROOT/'knowledge_sources'/name,source/name)
   config=RAGSettings(index_path=str(root/'index.sqlite3'),source_dir=str(source),database_url='',vector_backend='sqlite',pdf_media_enabled=False,rerank_enabled=False,http_origins=('http://127.0.0.1:11434',))
   def old_parser(path,*args):
    parsed=parse_document(path,*args)
    return replace(parsed,parser_revision='pdf-cjk-spacing-v1') if Path(path).suffix=='.pdf' else parsed
   embed=LocalEmbedding()
   with patch('app.rag.parse_document',side_effect=old_parser):before=ingest_documents(config,embedder=embed)
   previous={d['path']:d for d in before['documents']}
   result=ingest_documents(config,embedder=embed)
   self.assertEqual((result['updated'],result['unchanged']),(3,1))
   for doc in result['documents']:
    self.assertEqual(doc['id'],previous[doc['path']]['id'])
    if doc['path'].endswith('.pdf'):self.assertNotEqual(doc['current_revision'],previous[doc['path']]['current_revision'])
    else:self.assertEqual(doc['current_revision'],previous[doc['path']]['current_revision'])

 def test_incremental_public_pdf_ingestion_keeps_existing_word(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);source=root/'sources';source.mkdir()
   # A tiny independent Word stands in for any existing operator-managed Word.
   with zipfile.ZipFile(source/'existing.docx','w') as archive:
    archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>现有知识内容不得因追加PDF而被替换。</w:t></w:r></w:p></w:body></w:document>')
   config=RAGSettings(index_path=str(root/'index.sqlite3'),source_dir=str(source),database_url='',vector_backend='sqlite',pdf_media_enabled=False,rerank_enabled=False,http_origins=('http://127.0.0.1:11434',))
   embed=LocalEmbedding();first=ingest_documents(config,embedder=embed)
   existing=first['documents'][0];revision=existing['current_revision']
   for name in ARTICLES:shutil.copyfile(ROOT/'knowledge_sources'/name,source/name)
   result=ingest_documents(config,embedder=embed)
   self.assertEqual((result['updated'],result['unchanged'],result['chunks']),(3,1,14))
   store=DocumentStore(config.index_path,database_url='')
   documents=store.documents();self.assertEqual(len(documents),4)
   self.assertEqual(next(r for r in documents if r['id']==existing['id'])['current_revision'],revision)
   _,rows=store.snapshot();self.assertEqual(len(rows),15)
   for name in ARTICLES:
    record=next(d for d in documents if d['path']==name)
    self.assertEqual(store.download(record['id'],record['current_revision'])[1],(source/name).read_bytes())
    chunks=[r for r,_ in rows if r['source_file']==name]
    self.assertEqual(len(chunks),ARTICLES[name][1]);self.assertTrue(all(r['source_pages'] for r in chunks))
   before=len(embed.calls);repeat=ingest_documents(config,embedder=embed)
   self.assertEqual((repeat['updated'],repeat['unchanged']),(0,4));self.assertEqual(len(embed.calls),before)
