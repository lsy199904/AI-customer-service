"""Threshold updates are explicit and start reloads env without changing project/port."""
from pathlib import Path
import importlib.util
import os
import tempfile
import unittest
from unittest.mock import patch

class V3ConfigurationTests(unittest.TestCase):
 def test_configuration_without_flags_preserves_env_and_explicit_flags_only_change_target(self):
  spec=importlib.util.spec_from_file_location('configure_retrieval',Path(__file__).resolve().parents[1]/'scripts/configure_retrieval.py')
  module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);path=root/'.env';original='AUTH_SECRET=private-test-value\nSEMANTIC_MIN_SIMILARITY=0.75\nRERANK_MIN_SCORE=0.6\nV3_PORT=18081\n'
   path.write_text(original)
   with patch.object(module,'ROOT',root),patch('sys.argv',['configure_retrieval.py']):module.main()
   self.assertEqual(path.read_text(),original)
   with patch.object(module,'ROOT',root),patch('sys.argv',['configure_retrieval.py','--rerank','0.55']):module.main()
   text=path.read_text();self.assertIn('RERANK_MIN_SCORE=0.55',text);self.assertIn('SEMANTIC_MIN_SIMILARITY=0.75',text)
   self.assertIn('AUTH_SECRET=private-test-value',text);self.assertEqual(path.stat().st_mode&0o777,0o600)
 def test_start_forces_recreation_and_forwards_threshold_arguments(self):
  import shutil,subprocess
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'scripts').mkdir();(root/'.env').write_text('V3_PORT=18081\n')
   script=Path(__file__).resolve().parents[1]/'scripts/v3.sh';shutil.copy2(script,root/'scripts/v3.sh')
   binaries=root/'bin';binaries.mkdir();log=root/'args'
   executable=binaries/'docker';executable.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARG_LOG"\n');executable.chmod(0o755)
   env={**os.environ,'PATH':str(binaries)+os.pathsep+os.environ['PATH'],'ARG_LOG':str(log)}
   subprocess.run(['sh',str(root/'scripts/v3.sh'),'start'],env=env,check=True)
   args=log.read_text().splitlines();self.assertIn('--force-recreate',args);self.assertIn('--no-deps',args)
   self.assertNotIn('down',args);self.assertNotIn('pull',args)

 def test_ingest_and_check_use_current_compose_service_without_fixed_container_name(self):
  import shutil,subprocess
  with tempfile.TemporaryDirectory() as t:
   root=Path(t);(root/'scripts').mkdir();(root/'.env').write_text('V3_PORT=18081\n')
   shutil.copy2(Path(__file__).resolve().parents[1]/'scripts/v3.sh',root/'scripts/v3.sh')
   binaries=root/'bin';binaries.mkdir();log=root/'args'
   exe=binaries/'docker';exe.write_text('#!/bin/sh\nprintf "%s\\n" "$@" > "$ARG_LOG"\n');exe.chmod(0o755)
   env={**os.environ,'PATH':str(binaries)+os.pathsep+os.environ['PATH'],'ARG_LOG':str(log)}
   for command,extra in [('ingest',[]),('ingest',['--rebuild']),('check',[])]:
    subprocess.run(['sh',str(root/'scripts/v3.sh'),command,*extra],env=env,check=True)
    args=log.read_text().splitlines()
    self.assertEqual(args[-(6+len(extra)):],['exec','-T','assistant','python','manage.py',command,*extra])
    self.assertFalse(any('ai_customer_v2-assistant-1' in a for a in args))

 def test_upgrade_uses_new_image_for_ingest_before_recreating_service(self):
  import shutil,subprocess
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);(root/'scripts').mkdir();(root/'.env').write_text('V3_PORT=18081\n')
   shutil.copy2(Path(__file__).resolve().parents[1]/'scripts/v3.sh',root/'scripts/v3.sh')
   binaries=root/'bin';binaries.mkdir();log=root/'args'
   exe=binaries/'docker';exe.write_text('#!/bin/sh\nprintf "%s " "$@" >> "$ARG_LOG"\nprintf "\\n" >> "$ARG_LOG"\n');exe.chmod(0o755)
   env={**os.environ,'PATH':str(binaries)+os.pathsep+os.environ['PATH'],'ARG_LOG':str(log)}
   subprocess.run(['sh',str(root/'scripts/v3.sh'),'upgrade'],env=env,check=True)
   lines=log.read_text().splitlines()
   self.assertEqual(len(lines),4)
   self.assertIn('build assistant',lines[0]);self.assertIn('run --rm --no-deps -T assistant python manage.py ingest',lines[1])
   self.assertIn('--force-recreate assistant',lines[2]);self.assertIn('python manage.py check',lines[3])
   self.assertFalse(any('down' in line or '--rebuild' in line for line in lines))
