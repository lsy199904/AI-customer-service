"""Release initialization, retired entry and first-deploy phase regressions."""
import contextlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('configure_release', ROOT/'scripts/configure_release.py')
configuration = importlib.util.module_from_spec(spec)
spec.loader.exec_module(configuration)


class ReleaseDeploymentTests(unittest.TestCase):
    def prepare(self, root):
        shutil.copyfile(ROOT/'.env.example', root/'.env.example')
        with contextlib.redirect_stdout(io.StringIO()):
            configuration.initialize(root)
        return configuration.read(root/'.env')

    def test_init_generates_private_idempotent_independent_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory); a=self.prepare(root)
            self.assertGreaterEqual(len(a['AUTH_SECRET']),32)
            self.assertNotEqual(a['AUTH_SECRET'],a['POSTGRES_PASSWORD'])
            self.assertEqual((root/'.env').stat().st_mode & 0o777,0o600)
            self.assertIn('@127.0.0.1:55432/ai_customer',a['DATABASE_URL'])
            before=(root/'.env').read_bytes()
            with contextlib.redirect_stdout(io.StringIO()):configuration.initialize(root)
            self.assertEqual(before,(root/'.env').read_bytes())
            self.assertTrue((root/'deploy/generated/milvus-user.yaml').exists())

    def test_custom_ports_and_preexisting_model_settings_are_preserved(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            text=(ROOT/'.env.example').read_text().replace('POSTGRES_PORT=55432','POSTGRES_PORT=55433').replace('MILVUS_PORT=19530','MILVUS_PORT=19531').replace('MODEL_API_KEY=\n','MODEL_API_KEY=private-model-key\n')
            (root/'.env').write_text(text)
            self.prepare(root)
            values=configuration.read(root/'.env')
            self.assertIn(':55433/',values['DATABASE_URL'])
            self.assertEqual(values['MILVUS_URI'],'http://127.0.0.1:19531')
            self.assertEqual(values['MODEL_API_KEY'],'private-model-key')

    def test_mismatched_existing_database_cannot_be_silently_repointed(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);self.prepare(root)
            p=root/'.env';p.write_text(p.read_text().replace('POSTGRES_PORT=55432','POSTGRES_PORT=55433'))
            before=p.read_bytes()
            with self.assertRaisesRegex(ValueError,'DATABASE_URL'):configuration.initialize(root)
            self.assertEqual(before,p.read_bytes())

    def test_first_deploy_commands_do_not_start_app_before_ingestion(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'scripts').mkdir();(root/'bin').mkdir()
            shutil.copyfile(ROOT/'scripts/v3.sh',root/'scripts/v3.sh')
            (root/'.env').write_text('COMPOSE_PROJECT_NAME=test\n')
            docker=root/'bin/docker'
            docker.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$COMMAND_LOG"\n')
            docker.chmod(0o700)
            env={**os.environ,'PATH':str(root/'bin')+os.pathsep+os.environ['PATH'],'COMMAND_LOG':str(root/'commands')}
            for action in ['infrastructure','ingest','start']:
                subprocess.run(['sh',str(root/'scripts/v3.sh'),action],env=env,check=True)
            rows=(root/'commands').read_text().splitlines()
            self.assertIn('up -d --wait postgres etcd minio milvus',rows[0])
            self.assertIn('run --rm --no-deps -T assistant python manage.py ingest',rows[1])
            self.assertIn('up -d --wait --no-deps --force-recreate assistant',rows[2])
            self.assertTrue(all('down' not in row for row in rows))

    def test_legacy_demo_cannot_be_reenabled_or_access_existing_sessions(self):
        from app.core import Settings,issue_token,DEMO_TENANT
        from app.server import create_app
        from fastapi.testclient import TestClient
        with tempfile.TemporaryDirectory() as directory:
            config=Settings(secret='release-test-secret-abcdefghijklmnopqrstuvwxyz',
                db=str(Path(directory)/'chat.db'),retrieval_backend='lexical',
                mode='extractive',anonymous_widget_enabled=True)
            with patch.dict(os.environ,{'DEMO_AUTO_LOGIN':'true'}):
                with TestClient(create_app(config)) as client:
                    for path in ['/widget/demo','/widget/demo-auth','/widget/demo.js','/widget/demo.css']:
                        self.assertEqual(client.get('/smart-bot'+path).status_code,404)
                    token=issue_token(config.secret,DEMO_TENANT,'demo-'+32*'a')
                    self.assertEqual(client.get('/smart-bot/v1/sessions',headers={'Authorization':'Bearer '+token}).status_code,401)
                    self.assertNotIn('demo_auto_login',client.get('/smart-bot/widget/config').json())
