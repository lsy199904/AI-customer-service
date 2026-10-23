"""RAG lifecycle and protocol checks use controlled model doubles, not quality claims."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import zipfile
from app.ingestion import parse_document
from app.rag import (RAGSettings,DocumentStore,SemanticKnowledge,ingest_documents,
                     EmbeddingClient,RerankerClient,RAGError,normalized_vector)

class Embed:
 def __init__(self):self.calls=[]
 def embed(self,texts):
  self.calls.extend(texts)
  return [[0,1] if '计费' in t else [1,0] for t in texts]

class LifecycleTests(unittest.TestCase):
 def setUp(self):
  self.tmp=tempfile.TemporaryDirectory();self.root=Path(self.tmp.name);self.sources=self.root/'sources';self.sources.mkdir()
  self.c=RAGSettings(index_path=str(self.root/'rag.sqlite3'),source_dir=str(self.sources),rerank_enabled=False,http_origins=('http://127.0.0.1:11434',),min_similarity=.5)
  self.e=Embed();self.path=self.sources/'账号.md';self.path.write_text('# 企业开户\n联系客户经理，由运营团队创建企业账号。\n',encoding='utf-8')
 def tearDown(self):self.tmp.cleanup()
 def ingest(self,**kw):return ingest_documents(self.c,embedder=self.e,**kw)
 def test_incremental_update_history_and_rollback(self):
  first=self.ingest();doc=first['documents'][0];rev=doc['current_revision'];store=DocumentStore(self.c.index_path)
  old_id=next(iter(SemanticKnowledge(self.c,self.e).rows));raw=self.path.read_bytes();count=len(self.e.calls)
  self.assertEqual(self.ingest()['unchanged'],1);self.assertEqual(len(self.e.calls),count)
  self.path.write_text('# 企业开户\n联系新的客户经理办理。\n',encoding='utf-8');self.assertEqual(self.ingest()['updated'],1)
  self.assertEqual(len(store.revisions(doc['id'])),2);self.assertEqual(store.download(doc['id'],rev)[1],raw)
  self.assertIn('运营团队',store.get(old_id)['content'])
  store.activate(doc['id'],rev);self.assertEqual(next(iter(SemanticKnowledge(self.c,self.e).rows)),old_id)
 def test_inactive_does_not_resurrect(self):
  d=self.ingest()['documents'][0];s=DocumentStore(self.c.index_path);s.deactivate(d['id'])
  self.assertEqual(self.ingest()['inactive_skipped'],1);self.assertFalse(SemanticKnowledge(self.c,self.e).rows)
  s.activate(d['id'],d['current_revision']);self.assertTrue(SemanticKnowledge(self.c,self.e).rows)
 def test_missing_files_never_silently_delete(self):
  self.ingest();self.path.unlink()
  with self.assertRaises(ValueError):self.ingest()
  self.assertTrue(SemanticKnowledge(self.c,self.e).rows)
  (self.sources/'新文档.txt').write_text('新文档内容',encoding='utf-8')
  with self.assertRaises(ValueError):self.ingest(rebuild=True)
 def test_failed_batch_keeps_previous_version(self):
  before=self.ingest()['documents'];self.path.write_text('# 企业开户\n新流程需要重新审核。',encoding='utf-8')
  (self.sources/'新增.md').write_text('# 另一主题\n新产品介绍。',encoding='utf-8')
  class Broken:
   def embed(self,texts):raise RAGError('unavailable')
  with self.assertRaises(RAGError):ingest_documents(self.c,embedder=Broken())
  self.assertEqual(DocumentStore(self.c.index_path).documents(),before)
 def test_semantic_query_has_no_keyword_gate_and_reranks(self):
  (self.sources/'费用.md').write_text('# 计费\n计费按用量。',encoding='utf-8');self.ingest()
  k=SemanticKnowledge(self.c,self.e);r=k.assess('start onboarding')
  self.assertTrue(r['matched']);self.assertEqual(r['hits'][0][1]['title'],'企业开户')
  class Outside:
   def embed(self,t):return [[-1,0]]
  self.assertFalse(SemanticKnowledge(self.c,Outside()).assess('unrelated')['matched'])
  self.c.rerank_enabled=True;self.c.rerank_url='http://127.0.0.1:11434/v1/rerank';self.c.min_similarity=0
  class Rank:
   def rank(self,q,docs):return [(1,.9),(0,.1)]
  r=SemanticKnowledge(self.c,self.e,Rank()).assess('start onboarding')
  self.assertEqual(r['method'],'hybrid_rrf_rerank');self.assertEqual(r['hits'][0][1]['title'],'计费')
 def test_configuration_change_requires_rebuild(self):
  d=self.ingest()['documents'][0];self.c.embedding_revision='v2'
  with self.assertRaises(ValueError):self.ingest()
  with self.assertRaises(RAGError):SemanticKnowledge(self.c,self.e).assess('hello')
  self.ingest(rebuild=True)
  with self.assertRaises(ValueError):DocumentStore(self.c.index_path).activate(d['id'],d['current_revision'])
 def test_dimension_mismatch_does_not_publish(self):
  self.ingest();self.path.write_text('新资料正文',encoding='utf-8')
  class Other:
   def embed(self,t):return [[1,0,0] for _ in t]
  with self.assertRaises(RAGError):ingest_documents(self.c,embedder=Other())
 def test_unchanged_chunk_reuses_embeddings(self):
  self.ingest();count=len(self.e.calls)
  self.path.write_text(self.path.read_text()+'\n来源：修订来源。',encoding='utf-8');self.assertEqual(self.ingest()['updated'],1)
  self.assertEqual(len(self.e.calls),count)
 def test_file_symlink_rejected(self):
  (self.sources/'链接.md').symlink_to(self.path)
  with self.assertRaises(ValueError):self.ingest()

class ParserAndProtocolTests(unittest.TestCase):
 def test_curated_word(self):
  p=Path(__file__).resolve().parent.parent/'knowledge_sources/SmartTITU客户问答.docx'
  if not p.exists():self.skipTest('Deployment knowledge Word supplied separately')
  result=parse_document(p);self.assertTrue(result.chunks)
  self.assertTrue(result.chunks[0]['source_references'])
  self.assertNotIn('来源:',result.chunks[0]['content'])
 def test_docx_numeric_style_ids(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'numeric.docx'
   ns='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
   with zipfile.ZipFile(p,'w') as z:
    z.writestr('word/styles.xml',f'<w:styles xmlns:w="{ns}"><w:style w:styleId="31"><w:name w:val="Title"/></w:style><w:style w:styleId="4"><w:name w:val="heading 2"/></w:style></w:styles>')
    z.writestr('word/document.xml',f'<w:document xmlns:w="{ns}"><w:body><w:p><w:pPr><w:pStyle w:val="31"/></w:pPr><w:r><w:t>测试标题</w:t></w:r></w:p><w:p><w:pPr><w:pStyle w:val="4"/></w:pPr><w:r><w:t>问题1 注册</w:t></w:r></w:p><w:p><w:r><w:t>注册回答</w:t></w:r></w:p><w:p><w:pPr><w:pStyle w:val="4"/></w:pPr><w:r><w:t>问题3 计费</w:t></w:r></w:p><w:p><w:r><w:t>计费回答</w:t></w:r></w:p></w:body></w:document>')
   result=parse_document(p)
   self.assertEqual(result.title,'测试标题');self.assertEqual([c['title'] for c in result.chunks],['问题1 注册','问题3 计费'])
 def test_docx_tables(self):
  with tempfile.TemporaryDirectory() as t:
   p=Path(t)/'table.docx'
   with zipfile.ZipFile(p,'w') as z:z.writestr('word/document.xml','<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:tbl><w:tr><w:tc><w:p><w:r><w:t>产品</w:t></w:r></w:p></w:tc></w:tr><w:tr><w:tc><w:p><w:r><w:t>Hub</w:t></w:r></w:p></w:tc></w:tr></w:tbl></w:body></w:document>')
   self.assertIn('产品: Hub',parse_document(p).chunks[0]['content'])
 def test_ollama_and_openai(self):
  c=RAGSettings()
  with patch('app.rag.post_json',return_value={'embeddings':[[3,4]]}) as call:
   self.assertEqual(EmbeddingClient(c).embed(['hi']),[[.6,.8]]);self.assertFalse(call.call_args.args[1]['truncate'])
  c.embedding_provider='openai'
  with patch('app.rag.post_json',return_value={'data':[{'index':1,'embedding':[0,1]},{'index':0,'embedding':[1,0]}]}):
   self.assertEqual(EmbeddingClient(c).embed(['a','b']),[[1,0],[0,1]])
 def test_invalid_model_vectors_and_rerank(self):
  for v in ([0,0],[float('nan')],[True],[]):
   with self.assertRaises(RAGError):normalized_vector(v)
  c=RAGSettings()
  with patch('app.rag.post_json',return_value={'results':[{'index':0,'relevance_score':.8},{'index':0,'relevance_score':.7}]}):
   with self.assertRaises(RAGError):RerankerClient(c).rank('q',['a','b'])
 def test_endpoint_allowlist(self):
  from app.rag import validate_endpoint
  with self.assertRaises(ValueError):validate_endpoint('http://example.com/api',('http://example.com',))
  with self.assertRaises(ValueError):validate_endpoint('http://127.0.0.1:11434/api',())
  validate_endpoint('http://qwen3-reranker-4b:8001/v1/rerank',('http://qwen3-reranker-4b:8001',))
  validate_endpoint('http://host.docker.internal:11434/api/embed',('http://host.docker.internal:11434',))


class SemanticHTTPTests(unittest.TestCase):
 def test_customer_flow_and_versioned_download_auth(self):
  import threading
  import urllib.request
  import urllib.error
  from app.core import Settings,issue_token
  from app.server import create_server
  secret='test-secret-abcdefghijklmnopqrstuvwxyz-0123456789'
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);source=root/'sources';source.mkdir();(source/'开户.md').write_text('# 企业开户\n联系客户经理开通。',encoding='utf-8')
   c=RAGSettings(index_path=str(root/'rag.sqlite3'),source_dir=str(source),rerank_enabled=False,http_origins=('http://127.0.0.1:11434',))
   embed=Embed();ingest_documents(c,embedder=embed)
   with patch('app.rag.RAGSettings',return_value=c):server=create_server(Settings(retrieval_backend='semantic',mode='extractive',db=str(root/'chat.db'),secret=secret),port=0)
   server.service.knowledge.embedder=embed
   thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
   url='http://127.0.0.1:'+str(server.server_port);token=issue_token(secret,'company','user')
   def req(path,body=None,auth=True):
    h={'Content-Type':'application/json'}
    if auth:h['Authorization']='Bearer '+token
    request=urllib.request.Request(url+path,data=json.dumps(body).encode() if body is not None else None,headers=h)
    try:response=urllib.request.urlopen(request)
    except urllib.error.HTTPError as e:response=e
    with response:return response.status,response.read()
   try:
    _,raw=req('/v1/sessions',{});sid=json.loads(raw)['session_id'];path='/v1/sessions/'+sid+'/messages'
    count=len(embed.calls);_,raw=req(path,{'message':'你好','request_id':'greeting-001'});self.assertEqual(json.loads(raw)['retrieval']['method'],'skipped');self.assertEqual(len(embed.calls),count)
    _,raw=req(path,{'message':'start onboarding','request_id':'question-001'});answer=json.loads(raw)
    self.assertEqual(answer['status'],'answered');citation=answer['citations'][0];download=citation['download_url']
    self.assertEqual(req(download,auth=False)[0],401);self.assertEqual(req(download)[1],(source/'开户.md').read_bytes())
    self.assertEqual(req(citation['url'])[0],200)
    server.service.knowledge.store.deactivate(citation['document_id']);self.assertEqual(req(download)[0],200)
    _,raw=req(path,{'message':'退款规则是什么','request_id':'unknown-001'});answer=json.loads(raw)
    self.assertTrue(answer['handoff']);self.assertIsNone(answer['contact']['wechat_qr_url'])
   finally:server.shutdown();thread.join();server.server_close();server.service.db.close()

if __name__=='__main__':unittest.main()
