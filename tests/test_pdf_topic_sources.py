import shutil
import subprocess
import unittest
from pathlib import Path

class TopicSourceUITests(unittest.TestCase):
 def test_customer_labels_and_history_do_not_show_page_placeholders(self):
  node=shutil.which('node')
  if not node:
   bundled=Path('/Users/1272722735qq.com/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
   if bundled.is_file():node=str(bundled)
  if not node:self.skipTest('Node runtime unavailable')
  subprocess.run([node,str(Path(__file__).with_suffix('.js'))],check=True,capture_output=True,text=True)
