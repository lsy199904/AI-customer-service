"""Browser-free message bridge checks; Node is only a development test dependency."""
from pathlib import Path
import shutil
import subprocess
import unittest

class IframeBridgeTests(unittest.TestCase):
 def test_parent_and_child_bridge(self):
  self.run_script('test_iframe_bridge.js')
 def test_source_chapter_labels(self):
  self.run_script('test_source_chapters.js')
 def test_connection_deadlines(self):
  self.run_script('test_widget_connection.js')
 def run_script(self,name):
  node=shutil.which('node')
  if not node:
   bundled=Path('/Users/1272722735qq.com/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/bin/node')
   if bundled.exists():node=str(bundled)
  if not node:self.skipTest('Node.js not installed (development-only test)')
  root=Path(__file__).resolve().parent.parent
  subprocess.run([node,str(root/'tests'/name)],cwd=root,check=True,capture_output=True,text=True,timeout=15)
