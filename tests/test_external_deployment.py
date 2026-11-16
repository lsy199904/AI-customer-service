"""Deployment isolation and orchestration tests; no live databases or paid API calls."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
spec = importlib.util.spec_from_file_location('configure_external', ROOT / 'scripts/configure_external.py')
configure = importlib.util.module_from_spec(spec); spec.loader.exec_module(configure)
from app.deployment import DeploymentError, check_database, namespace
from app.vectors import MilvusVectors


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        shutil.copy2(ROOT / '.env.external.example', self.root / '.env.external.example')

    def test_initialization_is_private_stable_and_does_not_connect(self):
        configure.initialize(self.root)
        before = configure.read_env(self.root / '.env')
        configure.initialize(self.root)
        after = configure.read_env(self.root / '.env')
        self.assertEqual(before, after)
        self.assertEqual((self.root / '.env').stat().st_mode & 0o777, 0o600)
        self.assertGreaterEqual(len(after['AUTH_SECRET']), 32)
        self.assertTrue(after['MILVUS_COLLECTION'].startswith('smarttitu_ext_'))

    def source(self):
        p = self.root / 'old.env'
        p.write_text("DATABASE_URL='postgresql://user:pw@127.0.0.1:5433/ai_customer?sslmode=require'\n"
                     "MODEL_BASE_URL='http://10.0.0.1:4001/v1'\nMODEL_NAME='Qwen3'\nMODEL_API_KEY='sk-$literal'\n"
                     "MILVUS_URI=http://127.0.0.1:19530\nMILVUS_TOKEN='root:pw'\n"
                     "AUTH_SECRET='old-secret'\nMILVUS_COLLECTION=smarttitu_knowledge\nV3_PORT=8200\n")
        return p

    def test_source_copy_changes_db_namespace_and_secret_but_keeps_api_settings(self):
        configure.initialize(self.root, self.source())
        v = configure.read_env(self.root / '.env')
        self.assertEqual(v['DATABASE_URL'], 'postgresql://user:pw@127.0.0.1:5433/ai_customer_external_test?sslmode=require')
        self.assertEqual(v['MODEL_API_KEY'], 'sk-$literal')
        self.assertNotEqual(v['AUTH_SECRET'], 'old-secret')
        self.assertNotEqual(v['MILVUS_COLLECTION'], 'smarttitu_knowledge')
        self.assertEqual(v['APP_PORT'], '8201')
        self.assertEqual(v['ANONYMOUS_COOKIE_SECURE'], 'false')

    def test_refuses_source_database_and_existing_env_overwrite(self):
        source = self.source()
        with self.assertRaises(ValueError):configure.initialize(self.root, source, 'ai_customer')
        self.assertFalse((self.root / '.env').exists())
        configure.initialize(self.root)
        previous = (self.root / '.env').read_bytes()
        with self.assertRaises(ValueError):configure.initialize(self.root, source)
        self.assertEqual(previous, (self.root / '.env').read_bytes())

    def test_env_never_executes_shell(self):
        p = self.root / 'literal.env'; p.write_text("VALUE='$(touch NEVER) $HOME'\n")
        self.assertEqual(configure.read_env(p)['VALUE'], '$(touch NEVER) $HOME')
        self.assertFalse((self.root / 'NEVER').exists())

    def test_missing_configuration_fails_before_docker(self):
        configure.initialize(self.root)
        with self.assertRaisesRegex(ValueError, 'DATABASE_URL'):
            configure.validate_local(self.root)


class CookieConfigurationTests(unittest.TestCase):
    def test_legacy_default_and_new_cookie_names_are_valid_and_separate(self):
        from app.core import Settings
        with patch.dict(os.environ, {}, clear=True):
            old = Settings(secret='x'*40,mode='extractive')
            self.assertEqual(old.anonymous_cookie_name, 'smarttitu_anonymous_visitor')
            old.validate()
        with patch.dict(os.environ, {'ANONYMOUS_COOKIE_NAME':'smarttitu_ext_test'}, clear=True):
            new = Settings(secret='y'*40,mode='extractive')
            new.validate()
            self.assertNotEqual(old.anonymous_cookie_name,new.anonymous_cookie_name)
        with patch.dict(os.environ, {'ANONYMOUS_COOKIE_NAME':'invalid;name'}, clear=True):
            with self.assertRaisesRegex(ValueError,'COOKIE_NAME'):
                Settings(secret='z'*40,mode='extractive').validate()


class FakeResult:
    def __init__(self, value):self.value = value
    def fetchone(self):return (self.value,)


class FakeConnection:
    def __init__(self, marker=None, metadata=None, tables=0, permitted=True):
        self.marker=marker; self.metadata=metadata; self.tables=tables; self.permitted=permitted
    def execute(self, sql):
        if 'to_regclass' in sql:return FakeResult(self.marker)
        if 'SELECT metadata' in sql:return FakeResult(self.metadata)
        if 'count(*)' in sql:return FakeResult(self.tables)
        if 'has_database_privilege' in sql:return FakeResult(self.permitted)
        raise AssertionError('Unexpected SQL: ' + sql)


class OwnershipTests(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ, {'DEPLOYMENT_ID':'new','MILVUS_URI':'http://localhost:19530',
                                        'MILVUS_COLLECTION':'test_unique','MILVUS_DATABASE':'default'})
        self.env.start();self.addCleanup(self.env.stop)
    def test_existing_unmarked_business_data_is_rejected(self):
        with self.assertRaises(DeploymentError):check_database(FakeConnection(tables=3))
    def test_other_deployment_marker_is_rejected(self):
        with self.assertRaises(DeploymentError):check_database(FakeConnection(marker='yes',metadata={'id':'old'}))
    def test_owned_deployment_can_be_repeated(self):
        self.assertTrue(check_database(FakeConnection(marker='yes',metadata=namespace())))
    def test_empty_database_is_allowed_but_requires_schema_permissions(self):
        self.assertFalse(check_database(FakeConnection()))
        with self.assertRaises(DeploymentError):check_database(FakeConnection(permitted=False))


class VectorConfigurationTests(unittest.TestCase):
    def config(self, kind='HNSW'):
        return types.SimpleNamespace(milvus_collection='unique',fingerprint='a'*64,
            milvus_uri='http://localhost:19530',milvus_token='token',milvus_database='tenant_db',milvus_index_type=kind)
    def test_named_database_is_passed_to_client(self):
        calls=[]
        module=types.SimpleNamespace(MilvusClient=lambda **kw:calls.append(kw) or object())
        with patch.dict(sys.modules, {'pymilvus':module}):
            MilvusVectors(self.config()).client
        self.assertEqual(calls[0]['db_name'], 'tenant_db')
    def test_index_options_and_search_params_follow_index_type(self):
        for kind in ['HNSW','AUTOINDEX']:
            captured={}
            class Index:
                def add_index(self, **kw):captured['index']=kw
            class Client:
                def has_collection(self,*a,**kw):return captured.get('created',False)
                def create_schema(self,**kw):return types.SimpleNamespace(add_field=lambda *a,**kw:None)
                def prepare_index_params(self):return Index()
                def create_collection(self,**kw):captured['created']=True
                def search(self,**kw):captured['search']=kw;return [[{'id':'one','distance':0.9}]]
            datatypes=types.SimpleNamespace(VARCHAR=1,FLOAT_VECTOR=2)
            with patch.dict(sys.modules, {'pymilvus':types.SimpleNamespace(DataType=datatypes)}):
                index=MilvusVectors(self.config(kind),Client());index.ensure(1024)
                index.search([0.1]*1024,[{'id':'one','document_id':'d','revision':'r'}],1)
            self.assertEqual(captured['index']['index_type'],kind)
            self.assertEqual(captured['index']['metric_type'],'COSINE')
            self.assertEqual('params' in captured['index'],kind=='HNSW')
            self.assertEqual('ef' in captured['search']['search_params']['params'],kind=='HNSW')


class OrchestrationTests(unittest.TestCase):
    def test_failed_initialize_or_ingest_never_starts_app(self):
        for failure in ['initialize','ingest','doctor',None]:
            with tempfile.TemporaryDirectory() as temp:
                root=Path(temp);(root/'scripts').mkdir();(root/'bin').mkdir()
                for name in ['external.sh','configure_external.py']:
                    shutil.copy2(ROOT/'scripts'/name,root/'scripts'/name)
                shutil.copy2(ROOT/'.env.external.example',root/'.env.external.example')
                configure.initialize(root)
                envfile=root/'.env';text=envfile.read_text()
                fills={'DATABASE_URL':'postgresql://u:p@localhost/newdb','MILVUS_URI':'http://localhost:19530',
                    'MILVUS_TOKEN':'key','MODEL_BASE_URL':'https://example.com/v1','MODEL_API_KEY':'key','MODEL_NAME':'m',
                    'EMBEDDING_URL':'https://example.com/v1/embeddings','EMBEDDING_MODEL':'e','EMBEDDING_API_KEY':'key',
                    'RERANK_URL':'https://example.com/v1/rerank','RERANK_MODEL':'r','RERANK_API_KEY':'key'}
                for key,val in fills.items():text=text.replace(key+'=\n',key+'='+val+'\n')
                envfile.write_text(text)
                log=root/'calls';docker=root/'bin/docker'
                docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\ncase "$*" in\n'
                    + ('  *"'+failure+'"*) exit 1;;\n' if failure else '')+'esac\nexit 0\n')
                docker.chmod(0o755)
                env={**os.environ,'PATH':str(root/'bin')+os.pathsep+str(Path(sys.executable).parent)+os.pathsep+os.environ['PATH'],'CALLS':str(log)}
                result=subprocess.run(['sh',str(root/'scripts/external.sh'),'deploy','--image','existing:test'],env=env,capture_output=True,text=True)
                calls=log.read_text() if log.exists() else ''
                if failure:
                    self.assertNotEqual(result.returncode,0,result.stdout+result.stderr)
                    self.assertNotIn('up -d',calls)
                else:
                    self.assertEqual(result.returncode,0,result.stdout+result.stderr)
                    self.assertLess(calls.index('app.deployment initialize'),calls.index('manage.py ingest'))
                    self.assertLess(calls.index('manage.py doctor'),calls.index('up -d'))
                    self.assertNotIn('infrastructure',calls)
                    self.assertIn('ASSISTANT_IMAGE=existing:test',envfile.read_text())


if __name__ == '__main__':unittest.main()
