"""Deployment wiring without starting Docker or touching live credentials."""
import contextlib
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parent.parent
spec=importlib.util.spec_from_file_location('configure_services',ROOT/'scripts/configure_existing_services.py')
configure=importlib.util.module_from_spec(spec);spec.loader.exec_module(configure)

class DeploymentTests(unittest.TestCase):
 def test_existing_services_preserve_auth_and_do_not_print_key(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);env=root/'.env';env.write_text('AUTH_SECRET=keep-original-secret\nANSWER_MODE=llm\nMODEL_BASE_URL=http://10.180.158.23:18080/v1\nMODEL_HTTP_ORIGINS=\n')
   info={'Config':{'Entrypoint':['vllm'],'Cmd':['--api-key','private-reranker-key']},'NetworkSettings':{'Networks':{'model-serving_model-net':{'IPAddress':'172.19.0.2'}}}}
   output=io.StringIO()
   with patch.object(configure,'ROOT',root),patch.object(configure,'inspect',return_value=info),contextlib.redirect_stdout(output):configure.main()
   content=env.read_text();self.assertIn('AUTH_SECRET=keep-original-secret',content);self.assertIn('ANSWER_MODE=llm',content)
   self.assertIn('http://10.180.158.23:18080',content);self.assertIn('private-reranker-key',content)
   self.assertNotIn('private-reranker-key',output.getvalue());self.assertEqual(env.stat().st_mode & 0o777,0o600)
 def test_missing_rerank_key_does_not_modify_config(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);env=root/'.env';env.write_text('AUTH_SECRET=original\n')
   with patch.object(configure,'ROOT',root),patch.object(configure,'inspect',return_value={'Config':{}}):
    with self.assertRaises(SystemExit):configure.main()
   self.assertEqual(env.read_text(),'AUTH_SECRET=original\n')
 def test_host_wrapper_passes_identity_and_project_without_docker(self):
  with tempfile.TemporaryDirectory(prefix='assistant deploy ') as temp:
   root=Path(temp);(root/'scripts').mkdir();(root/'bin').mkdir();(root/'.env').write_text('AUTH_SECRET=placeholder\n')
   shutil.copyfile(ROOT/'scripts/docker-host.sh',root/'scripts/docker-host.sh')
   # Fake only the OS probe and Docker CLI. The real script still derives UID/GID and paths.
   (root/'bin/uname').write_text('#!/bin/sh\nprintf Linux\n')
   (root/'bin/docker').write_text('#!/bin/sh\nprintf "uid=%s gid=%s\\n" "$ASSISTANT_UID" "$ASSISTANT_GID"\nprintf "%s\\n" "$@"\n')
   for p in (root/'bin').iterdir():p.chmod(0o755)
   env={**os.environ,'PATH':str(root/'bin')+os.pathsep+os.environ['PATH']}
   result=subprocess.run(['sh',str(root/'scripts/docker-host.sh'),'up','--build','-d'],cwd='/',env=env,capture_output=True,text=True,check=True)
   self.assertIn('uid='+str(os.getuid()),result.stdout);self.assertIn('gid='+str(os.getgid()),result.stdout)
   self.assertIn(str(root/'compose.host.yaml'),result.stdout);self.assertTrue(result.stdout.endswith('up\n--build\n-d\n'));self.assertTrue((root/'var').is_dir())
 def test_host_wrapper_rejects_missing_env(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);(root/'scripts').mkdir();(root/'bin').mkdir();shutil.copyfile(ROOT/'scripts/docker-host.sh',root/'scripts/docker-host.sh')
   (root/'bin/uname').write_text('#!/bin/sh\nprintf Linux\n');(root/'bin/uname').chmod(0o755)
   result=subprocess.run(['sh',str(root/'scripts/docker-host.sh'),'up'],env={**os.environ,'PATH':str(root/'bin')+os.pathsep+os.environ['PATH']},capture_output=True)
   self.assertEqual(result.returncode,2);self.assertFalse((root/'var').exists())

if __name__=='__main__':unittest.main()
