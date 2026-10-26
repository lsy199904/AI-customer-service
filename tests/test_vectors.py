"""Milvus contracts and failed-publication safety with synthetic documents."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock,patch
from app.rag import RAGSettings,DocumentStore,ingest_documents
from app.vectors import MilvusVectors

class VectorContracts(unittest.TestCase):
 def config(self,root):return RAGSettings(source_dir=str(root/'sources'),index_path=str(root/'rag.db'),vector_backend='milvus',milvus_token='test-only-token',rerank_enabled=False,http_origins=('http://127.0.0.1:11434',))
 def test_revision_filter_and_untrusted_hits(self):
  c=MagicMock();c.has_collection.return_value=True
  c.search.return_value=[[{'id':'current','distance':.9},{'id':'unpublished','distance':1.}]]
  config=RAGSettings(milvus_token='test');index=MilvusVectors(config,c)
  records=[{'id':'current','document_id':'DOC-a','revision':'v1'}]
  self.assertEqual(index.search([1.,0.],records,12),{'current':.9})
  args=c.search.call_args.kwargs;self.assertEqual(args['consistency_level'],'Strong')
  self.assertIn('revision == "v1"',args['filter']);self.assertEqual(args['search_params']['metric_type'],'COSINE')
 def test_dimension_change_and_missing_collection_fail_closed(self):
  c=MagicMock();c.has_collection.return_value=True;c.describe_collection.return_value={'fields':[{'name':'vector','params':{'dim':1024}}]}
  index=MilvusVectors(RAGSettings(milvus_token='test'),c)
  with self.assertRaises(ValueError):index.ensure(2)
  c.has_collection.return_value=False
  with self.assertRaises(ValueError):index.search([1.,0.],[{'id':'a','document_id':'d','revision':'r'}],1)
 def test_failed_milvus_publication_preserves_active_relational_revision(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);(root/'sources').mkdir();path=root/'sources/manual.md';path.write_text('# 企业注册\n使用手机号注册。')
   config=self.config(root);vectors=MagicMock()
   class Embed:
    def embed(self,texts):return [[1.,0.] for _ in texts]
   with patch('app.vectors.MilvusVectors',return_value=vectors):ingest_documents(config,embedder=Embed())
   store=DocumentStore(config.index_path,'');before=store.snapshot();old=store.documents()[0]['current_revision']
   path.write_text('# 企业注册\n使用手机号注册，然后认证。')
   def fail(rows):
    self.assertEqual(store.documents()[0]['current_revision'],old)
    raise RuntimeError('simulated storage outage')
   vectors.upsert.side_effect=fail
   with patch('app.vectors.MilvusVectors',return_value=vectors):
    with self.assertRaises(RuntimeError):ingest_documents(config,embedder=Embed())
   self.assertEqual(store.snapshot(),before)

 def test_reactivate_stages_historical_vectors_before_switching_revision(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);(root/'sources').mkdir();path=root/'sources/manual.md';path.write_text('# 企业注册\n使用手机号注册。')
   config=self.config(root);index=MagicMock();index.config=config
   class Embed:
    def embed(self,texts):return [[1.,0.] for _ in texts]
   with patch('app.vectors.MilvusVectors',return_value=index):
    ingest_documents(config,embedder=Embed());store=DocumentStore(config.index_path,'');doc=store.documents()[0];old=doc['current_revision']
    path.write_text('# 企业注册\n请先注册再认证。');ingest_documents(config,embedder=Embed())
   current=store.documents()[0]['current_revision']
   def fail(rows):
    self.assertEqual(rows[0][0]['revision'],old)
    raise RuntimeError('simulated vector failure')
   index.upsert.side_effect=fail
   with self.assertRaises(RuntimeError):store.activate(doc['id'],old,index)
   self.assertEqual(store.documents()[0]['current_revision'],current)
   index.upsert.side_effect=None;store.activate(doc['id'],old,index)
   self.assertEqual(store.documents()[0]['current_revision'],old)
