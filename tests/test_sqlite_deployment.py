"""Exercise the deployment wrapper with an isolated Docker command recorder."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest
ROOT=Path(__file__).resolve().parents[1]

class SQLiteDeployment(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name)
  (self.root/'scripts').mkdir();(self.root/'bin').mkdir()
  shutil.copy2(ROOT/'scripts/sqlite.sh',self.root/'scripts/sqlite.sh')
  shutil.copy2(ROOT/'compose.sqlite.yaml',self.root/'compose.sqlite.yaml')
  self.original='DATABASE_URL=postgresql://unchanged/assistant\nVECTOR_BACKEND=milvus\nMODEL_NAME=keep-model\n'
  (self.root/'.env').write_text(self.original)
  (self.root/'bin/uname').write_text('#!/bin/sh\necho Linux\n')
  (self.root/'bin/docker').write_text('''#!/usr/bin/env python3
import json,os,sys
from pathlib import Path
args=sys.argv[1:]
with open(os.environ['DOCKER_RECORD'],'a') as stream:stream.write(json.dumps(args)+'\\n')
if args[:2]==['image','inspect']:raise SystemExit(int(os.environ.get('IMAGE_MISSING','0')))
if args[-2:]==['config','--images']:print(os.environ.get('SQLITE_APP_IMAGE','ai_customer-assistant:enterprise'))
''')
  for p in (self.root/'bin').iterdir():p.chmod(0o755)
  self.env={**os.environ,'PATH':str(self.root/'bin')+os.pathsep+os.environ['PATH'],'DOCKER_RECORD':str(self.root/'record')}
 def tearDown(self):self.temp.cleanup()
 def run_script(self,*args):return subprocess.run(['sh',str(self.root/'scripts/sqlite.sh'),*args],env=self.env,text=True,capture_output=True)
 def calls(self):return [json.loads(line) for line in (self.root/'record').read_text().splitlines()]
 def test_start_reuses_local_image_and_never_pulls_or_builds(self):
  result=self.run_script('start');self.assertEqual(result.returncode,0,result.stderr)
  calls=self.calls();self.assertEqual(calls[1],['image','inspect','ai_customer-assistant:enterprise'])
  self.assertEqual(calls[-1][-7:],['up','-d','--no-deps','--pull','never','--force-recreate','assistant'])
  self.assertTrue(all('build' not in c and 'pull' not in c and 'down' not in c for c in calls))
  self.assertTrue(all(str(self.root/'compose.sqlite.yaml') in c for c in calls if c[0]=='compose'))
  self.assertEqual((self.root/'.env').read_text(),self.original)
 def test_missing_local_image_stops_without_start_or_pull(self):
  self.env['IMAGE_MISSING']='1';result=self.run_script('start')
  self.assertEqual(result.returncode,2);self.assertIn('未找到本地镜像',result.stderr)
  self.assertFalse(any('up' in c for c in self.calls()))
 def test_custom_image_and_existing_data_preserved(self):
  self.env['SQLITE_APP_IMAGE']='my-local-assistant:tested'
  (self.root/'var').mkdir();(self.root/'var/assistant.db').write_bytes(b'preserved database')
  result=self.run_script('start');self.assertEqual(result.returncode,0,result.stderr)
  self.assertEqual(self.calls()[1],['image','inspect','my-local-assistant:tested'])
  self.assertEqual((self.root/'var/assistant.db').read_bytes(),b'preserved database')
 def test_diagnostics_forward_flags(self):
  self.assertEqual(self.run_script('doctor','--models').returncode,0)
  self.assertEqual(self.calls()[-1][-6:],['exec','assistant','python','manage.py','doctor','--models'])
 def test_missing_env_fails_without_docker(self):
  (self.root/'.env').unlink();result=self.run_script('start')
  self.assertEqual(result.returncode,2);self.assertFalse((self.root/'record').exists())
