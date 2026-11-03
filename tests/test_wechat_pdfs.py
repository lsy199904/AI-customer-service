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
 '中企通信成功通过中国信通院首批Token聚合服务平台能力评估.pdf':(7,8,'3b1cb0a0ac0dd9d36bc89d6256a9920a4cb0c1c92b0346bdfb56016dce0894a5',
    ['中国信通院','Token 聚合服务平台','六大能力域']),
 '企业级五大安全可信Token应用场景，看这一篇就够了！.pdf':(9,9,'2ee60f951ff2391f0a52568d6da9d9bb6b4eadf0889933655bdf03068cae5fe2',
    ['私有化部署','云端Token安全服务','精细化Token管理服务','终端Agent管控服务','AICC']),
 'SmartTITU网站上线，三大核心价值助力企业安全、高效、低成本用好大模型！.pdf':(8,8,'0881fdfdf77ab12738ecfc52325456f63ca16915c585bf2ebe3bf68dbf495d6d',
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
    self.assertEqual(sorted({p for c in parsed.chunks for p in c['source_pages']}),list(range(1,pages+1)))
    body='\n'.join(c['content'] for c in parsed.chunks)
    for term in terms:self.assertIn(re.sub(r'\s+','',term),re.sub(r'\s+','',body))
    self.assertIn('https://mp.weixin.qq.com/s?',body)
    self.assertTrue(all(not c['image_ids'] for c in parsed.chunks))
    for c in parsed.chunks:
     self.assertIn('PDF物理第',c['source_locator']);self.assertTrue(c['title'].startswith(path.stem))
 def test_every_text_page_is_covered_without_truncating_body(self):
  for name in ARTICLES:
   path=ROOT/'knowledge_sources'/name;parsed=parse_document(path)
   for number,page in enumerate(PdfReader(path).pages,1):
    text=clean_pdf_text(page.extract_text() or '')
    covered=[False]*len(text)
    for chunk in (c for c in parsed.chunks if number in c['source_pages']):
     content=chunk['content'];start=text.find(content)
     self.assertGreaterEqual(start,0,(name,number))
     covered[start:start+len(content)]=[True]*len(content)
    self.assertFalse(any(not included and not char.isspace() for char,included in zip(text,covered)),(name,number))
 def test_pdf_spacing_cleanup_preserves_latin_commands_and_line_boundaries(self):
  self.assertEqual(clean_pdf_text('私 有 化 部 署\nToken service API Key 192.168.1.1'),
                   '私有化部署\nToken service API Key 192.168.1.1')
  self.assertEqual(clean_pdf_text('企业 认证需要 12 位密码'), '企业认证需要 12 位密码')

 def test_incremental_public_pdf_ingestion_keeps_existing_word(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);source=root/'sources';source.mkdir()
   # A tiny independent Word stands in for any existing operator-managed Word.
   with zipfile.ZipFile(source/'existing.docx','w') as archive:
    archive.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>现有知识内容不得因追加PDF而被替换。</w:t></w:r></w:p></w:body></w:document>')
   config=RAGSettings(index_path=str(root/'index.sqlite3'),source_dir=str(source),database_url='',vector_backend='sqlite',rerank_enabled=False,http_origins=('http://127.0.0.1:11434',))
   embed=LocalEmbedding();first=ingest_documents(config,embedder=embed)
   existing=first['documents'][0];revision=existing['current_revision']
   for name in ARTICLES:shutil.copyfile(ROOT/'knowledge_sources'/name,source/name)
   result=ingest_documents(config,embedder=embed)
   self.assertEqual((result['updated'],result['unchanged'],result['chunks']),(3,1,25))
   store=DocumentStore(config.index_path,database_url='')
   documents=store.documents();self.assertEqual(len(documents),4)
   self.assertEqual(next(r for r in documents if r['id']==existing['id'])['current_revision'],revision)
   _,rows=store.snapshot();self.assertEqual(len(rows),26)
   for name in ARTICLES:
    record=next(d for d in documents if d['path']==name)
    self.assertEqual(store.download(record['id'],record['current_revision'])[1],(source/name).read_bytes())
    chunks=[r for r,_ in rows if r['source_file']==name]
    self.assertEqual(len(chunks),ARTICLES[name][1]);self.assertTrue(all(r['source_pages'] for r in chunks))
   before=len(embed.calls);repeat=ingest_documents(config,embedder=embed)
   self.assertEqual((repeat['updated'],repeat['unchanged']),(0,4));self.assertEqual(len(embed.calls),before)
