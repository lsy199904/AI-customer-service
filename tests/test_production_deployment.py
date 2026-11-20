"""Offline deployment safety tests: no cloud access, database writes or paid API calls."""
import importlib.util
import json
import os
from pathlib import Path
import sys
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT/'scripts'))
if not (ROOT/'scripts/kubernetes.py').is_file():
    raise unittest.SkipTest('本部署分支已移除旧Kubernetes Python执行器；使用现有声明式K8s配置')
import kubernetes as deployment
from app import cloud


def configuration():
    return {'K8S_CONTEXT':'test-cluster','K8S_NAMESPACE':'test-ns','K8S_APP_NAME':'assistant',
            'K8S_PVC_NAME':'assistant-var','DEPLOYMENT_ID':'isolated-deployment',
            'ASSISTANT_IMAGE':'registry.example.com/team/assistant:one','APP_PORT':'8201',
            'AUTH_SECRET':'private-signing-key','DATABASE_URL':'postgresql://app:private@pg/test',
            'MILVUS_URI':'https://milvus.example.com','MILVUS_TOKEN':'private-milvus',
            'MILVUS_DATABASE':'test','MODEL_API_KEY':'private-model','PG_ADMIN_URL':'should-never-reach-app'}


class ManifestTests(unittest.TestCase):
    def test_build_requires_explicit_company_registry_and_version(self):
        for image in ('smarttitu-assistant:default','someone/assistant:one','registry.example.com/team:latest','registry.example.com/team'):
            with self.assertRaises(ValueError):deployment.validate_image(image)
        deployment.validate_image('registry.example.com/team/assistant:20261116-01')

    def test_app_and_jobs_share_persistent_var_without_host_network_or_database_containers(self):
        v=configuration();deploy,service,pvc=deployment.manifest(v)
        spec=deploy['spec']['template']['spec']
        self.assertEqual(deploy['spec']['replicas'],1)
        self.assertEqual(deploy['spec']['strategy']['type'],'Recreate')
        self.assertEqual(len(spec['containers']),1)
        self.assertNotIn('hostNetwork',spec)
        self.assertEqual(service['spec']['selector']['smarttitu-role'],'app')
        self.assertEqual(spec['automountServiceAccountToken'],False)
        self.assertEqual(spec['volumes'][0]['persistentVolumeClaim']['claimName'],v['K8S_PVC_NAME'])
        self.assertEqual(spec['containers'][0]['volumeMounts'][0]['mountPath'],'/srv/assistant/var')
        self.assertEqual(service['spec']['ports'][0]['port'],80)
        self.assertEqual(pvc['spec']['resources']['requests']['storage'],'20Gi')
        self.assertNotIn('private',json.dumps([deploy,service,pvc]))

    def test_secrets_never_enter_configmap_or_admin_credentials_in_app(self):
        cm,secret=deployment.configuration(configuration())
        self.assertNotIn('private',json.dumps(cm))
        self.assertIn('AUTH_SECRET',secret['stringData'])
        self.assertNotIn('PG_ADMIN_URL',secret['stringData'])
        self.assertNotIn('PG_ADMIN_URL',cm['data'])
        self.assertEqual(cm['data']['HOST'],'0.0.0.0')
        self.assertEqual(cm['data']['PORT'],'8201')

    def test_wrong_deployment_cannot_be_overwritten(self):
        k=deployment.Kubernetes(configuration())
        with patch.object(k,'get',return_value={'metadata':{'labels':{'smarttitu-deployment':'other'}}}):
            with self.assertRaisesRegex(ValueError,'不属于'):k.ownership('deployment','assistant')

    def test_job_failure_prevents_application_start(self):
        for failed in (False,True):
            calls=[]
            class FakeKube:
                def __init__(self,v):pass
                def ensure_namespace(self):calls.append('namespace')
                def ownership(self,*a):return True
                def pause(self):calls.append('pause')
                def apply(self,obj):calls.append(obj['kind'])
                def job(self,command):
                    calls.append('job')
                    self_command=' '.join(command)
                    self_test.assertIn('initialize',self_command)
                    self_test.assertLess(self_command.index('initialize'),self_command.index('ingest'))
                    if failed:raise RuntimeError('job failed')
                def run(self,*a):calls.append(a[0])
            self_test=self
            with patch.object(deployment,'settings',return_value=configuration()),patch.object(deployment,'Kubernetes',FakeKube),patch.object(sys,'argv',['production','deploy']):
                if failed:
                    with self.assertRaises(RuntimeError):deployment.main()
                else:deployment.main()
            self.assertLess(calls.index('pause'),calls.index('job'))
            self.assertEqual('Deployment' in calls,not failed)
            self.assertEqual('rollout' in calls,not failed)

    def test_cloud_job_uses_temporary_admin_secret_and_always_removes_it(self):
        v=configuration();k=deployment.Kubernetes(v);applied=[];commands=[]
        with patch.object(k,'apply',side_effect=applied.append),patch.object(k,'get',return_value={'status':{'failed':1}}),patch.object(k,'run',side_effect=lambda *a,**kw:commands.append(a)):
            with self.assertRaises(RuntimeError):k.job(['python','-m','app.cloud'],{'PG_ADMIN_URL':'private'})
        self.assertEqual(applied[0]['kind'],'Secret')
        spec=applied[1]['spec']['template']['spec']
        self.assertNotIn('volumes',spec)
        self.assertEqual(applied[1]['spec']['template']['metadata']['labels']['smarttitu-role'],'maintenance')
        self.assertEqual(len(spec['containers'][0]['envFrom']),1)
        self.assertIn(('delete','job'),[c[:2] for c in commands])
        self.assertIn(('delete','secret'),[c[:2] for c in commands])

    def test_same_names_remain_stable_between_versions(self):
        a=configuration();b={**a,'ASSISTANT_IMAGE':'registry.example.com/team/assistant:two'}
        self.assertEqual(deployment.labels(a),deployment.labels(b))
        self.assertNotEqual(deployment.labels(a),deployment.labels({**b,'DEPLOYMENT_ID':'different'}))

    def test_image_contains_knowledge_and_dockerignore_does_not_exclude_it(self):
        self.assertIn('COPY knowledge_sources ./knowledge_sources',(ROOT/'Dockerfile').read_text())
        self.assertNotIn('knowledge_sources',(ROOT/'.dockerignore').read_text().splitlines())
        self.assertTrue((ROOT/'knowledge_sources/SmartTITU客户问答.docx').is_file())


class CloudTests(unittest.TestCase):
    def test_pg_creates_only_missing_resources_and_never_resets_existing_password(self):
        for existing in (False, True):
            statements=[]
            class SQL(str):
                def format(self,*a):return SQL(super().format(*a))
            sql=types.SimpleNamespace(SQL=SQL,Identifier=lambda v:'"'+v+'"',Literal=lambda v:"'"+v+"'")
            class Connection:
                def __enter__(self):return self
                def __exit__(self,*a):pass
                def execute(self,query,params=None):
                    statements.append(str(query))
                    if 'current_user' in query:value=('admin',)
                    elif 'rolsuper' in query:value=(False,False,False) if existing else None
                    elif 'pg_get_userbyid' in query:value=('app',) if existing else None
                    else:value=(True,)
                    return types.SimpleNamespace(fetchone=lambda:value)
            def parse(value):
                return {'host':'pg','port':'5432','dbname':'postgres' if value=='admin-url' else 'business','user':'admin' if value=='admin-url' else 'app','password':'secret'}
            with patch.dict(sys.modules,{'psycopg':types.SimpleNamespace(connect=lambda **kw:Connection(),sql=sql),
                                       'psycopg.conninfo':types.SimpleNamespace(conninfo_to_dict=parse)}),patch.dict(os.environ,{'DATABASE_URL':'app-url','PG_ADMIN_URL':'admin-url','CLOUD_PREPARE_PG':'true'},clear=True):
                cloud.prepare_postgres()
            self.assertEqual(any('CREATE ROLE' in q for q in statements),not existing)
            self.assertEqual(any('CREATE DATABASE' in q for q in statements),not existing)
            self.assertFalse(any('ALTER' in q or 'DROP' in q for q in statements))

    def test_platform_assigned_milvus_database_needs_no_admin_api(self):
        calls=[]
        class Client:
            def __init__(self,**kw):calls.append(kw)
            def list_collections(self,**kw):calls.append('collections');return []
            def close(self):calls.append('closed')
        with patch.dict(sys.modules,{'pymilvus':types.SimpleNamespace(MilvusClient=Client)}),patch.dict(os.environ,{'MILVUS_URI':'https://endpoint','MILVUS_TOKEN':'app','MILVUS_DATABASE':'assigned','CLOUD_PREPARE_MILVUS':'false'},clear=True):cloud.prepare_milvus()
        self.assertEqual(calls[0]['db_name'],'assigned')
        self.assertEqual(calls[0]['token'],'app')
        self.assertEqual(len([c for c in calls if isinstance(c,dict)]),1)

    def test_optional_milvus_creation_is_idempotent(self):
        for exists in (False,True):
            calls=[]
            class Client:
                def __init__(self,**kw):pass
                def list_databases(self,**kw):return ['assigned'] if exists else []
                def create_database(self,**kw):calls.append(kw['db_name'])
                def list_collections(self,**kw):return []
                def close(self):pass
            with patch.dict(sys.modules,{'pymilvus':types.SimpleNamespace(MilvusClient=Client)}),patch.dict(os.environ,{'MILVUS_URI':'https://endpoint','MILVUS_TOKEN':'app','MILVUS_DATABASE':'assigned','MILVUS_ADMIN_TOKEN':'admin','CLOUD_PREPARE_MILVUS':'true'},clear=True):cloud.prepare_milvus()
            self.assertEqual(calls,[] if exists else ['assigned'])


if __name__=='__main__':unittest.main()
