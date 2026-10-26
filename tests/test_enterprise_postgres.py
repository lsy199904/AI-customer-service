"""Optional real PostgreSQL test. Creates/drops its OWN random database only.
Set SMARTTITU_TEST_POSTGRES_URL to a test server role with CREATEDB and CREATEROLE permissions.
No production database is modified; no external model is called.
"""
import os
import secrets
import tempfile
import threading
import unittest
import uuid
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import patch
from app.core import Settings,Service,APIError
from app.rag import RAGSettings,DocumentStore,ingest_documents
from app.migration import migrate,export_sqlite
from app.storage import close_knowledge_pools

@unittest.skipUnless(os.getenv('SMARTTITU_TEST_POSTGRES_URL'),'optional real PostgreSQL test')
class PostgresIntegration(unittest.TestCase):
 def test_migration_history_versions_idempotency_cross_instance_lock(self):
  import psycopg
  from psycopg import sql
  from psycopg.conninfo import conninfo_to_dict,make_conninfo
  parent=os.environ['SMARTTITU_TEST_POSTGRES_URL'];name='smarttitu_test_'+uuid.uuid4().hex
  admin=psycopg.connect(parent,autocommit=True);admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
  role='app_'+uuid.uuid4().hex;password=secrets.token_urlsafe(24)
  admin.execute(sql.SQL('CREATE ROLE {} LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE PASSWORD {}').format(sql.Identifier(role),sql.Literal(password)))
  admin.execute(sql.SQL('GRANT CONNECT, CREATE ON DATABASE {} TO {}').format(sql.Identifier(name),sql.Identifier(role)))
  params=conninfo_to_dict(parent);params['dbname']=name;params['user']=role;params['password']=password;url=make_conninfo(**params)
  # Settings expects a PostgreSQL URL, while psycopg also supports keyword DSNs.
  from urllib.parse import quote
  url='postgresql://'+quote(params.get('user',''),safe='')+'@/'+name+'?host='+quote(params.get('host','localhost'),safe='')+'&port='+params.get('port','5432')
  if params.get('password'):url+='&password='+quote(params['password'],safe='')
  services=[]
  try:
   with tempfile.TemporaryDirectory() as temp:
    root=Path(temp);src=root/'sources';src.mkdir();(src/'manual.md').write_text('# 企业开户\n手机号注册后申请企业认证。')
    actor={'tenant_id':'company','sub':'user'};config=Settings(retrieval_backend='lexical',secret='postgres-integration-secret-32-characters',db=str(root/'chat.db'))
    legacy=Service(config);sid=legacy.create(actor,{})['session_id'];body={'message':'你好','request_id':'migrated-request-001'}
    reply=legacy.chat(actor,sid,body);legacy.close()
    rag=RAGSettings(index_path=str(root/'rag.db'),source_dir=str(src),database_url='',rerank_enabled=False,http_origins=('http://127.0.0.1:11434',))
    class Embed:
     def embed(self,texts):return [[1.,0.] for _ in texts]
    ingest_documents(rag,embedder=Embed());doc=DocumentStore(rag.index_path,'').documents()[0]
    original=DocumentStore(rag.index_path,'').download(doc['id'],doc['current_revision'])
    config.database_url=url;rag.database_url=url
    with patch('app.rag.RAGSettings',return_value=rag):
     report=migrate(config,root/'chat.db',root/'rag.db',root/'backup')
     migrate(config,root/'chat.db',root/'rag.db',root/'backup2')
    self.assertEqual(report['migration'],'complete');self.assertEqual((root/'backup/assistant.sqlite3').stat().st_mode&0o777,0o600)
    store=DocumentStore(rag.index_path,url);self.assertEqual(store.download(doc['id'],doc['current_revision']),original)
    with ThreadPoolExecutor(max_workers=2) as executor:a,b=list(executor.map(lambda _:Service(config),range(2)))
    services.extend([a,b])
    self.assertEqual(a.chat(actor,sid,body),reply);self.assertEqual(len(b.history(actor,sid)['items']),2)
    entered=threading.Event();release=threading.Event()
    class Slow:
     def answer(self,q,h,e,c):
      entered.set();release.wait(5);return {'answerable':True,'answer':'您好！','citation_ids':[],'image_ids':[]}
    a.config.mode='llm';a.model=Slow()
    with ThreadPoolExecutor(max_workers=1) as executor:
     future=executor.submit(a.chat,actor,sid,{'message':'你好','request_id':'parallel-request-001'})
     try:
      self.assertTrue(entered.wait(4))
      with self.assertRaises(APIError) as error:b.chat(actor,sid,{'message':'你好','request_id':'parallel-request-002'})
      self.assertEqual(error.exception.code,'session_busy')
     finally:release.set()
     self.assertEqual(future.result(timeout=5)['status'],'answered')
    export_sqlite(config,root/'export')
    restored=Service(Settings(retrieval_backend='lexical',secret=config.secret,db=str(root/'export/assistant.db')))
    self.assertEqual(len(restored.history(actor,sid)['items']),4);restored.close()
    self.assertEqual(DocumentStore(root/'export/rag.sqlite3','').download(doc['id'],doc['current_revision']),original)
    b.delete(actor,sid);self.assertEqual(b.db.execute('SELECT COUNT(*) FROM workflow_runs').fetchone()[0],0)
  finally:
   for service in services:service.close()
   close_knowledge_pools()
   admin.execute(sql.SQL('DROP DATABASE {} WITH (FORCE)').format(sql.Identifier(name)))
   admin.execute(sql.SQL('DROP ROLE {}').format(sql.Identifier(role)));admin.close()
