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
