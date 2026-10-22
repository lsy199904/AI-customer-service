import json
import os
from pathlib import Path
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from manage import init_env,load_env,backup_database

class ManageTests(unittest.TestCase):
 def test_init_no_overwrite(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'.env';init_env(p)
   secret=next(x.split('=',1)[1] for x in p.read_text().splitlines() if x.startswith('AUTH_SECRET='))
   self.assertGreaterEqual(len(secret),32)
   with self.assertRaises(FileExistsError):init_env(p)
 def test_parse_not_execute(self):
  with tempfile.TemporaryDirectory() as d,patch.dict(os.environ,{},clear=True):
   p=Path(d)/'.env';p.write_text('AUTH_SECRET="literal $(echo no) # keeps"\nANSWER_MODE=extractive # comment\nCORS_ORIGINS=\n')
   load_env(p);self.assertEqual(os.environ['AUTH_SECRET'],'literal $(echo no) # keeps');self.assertEqual(os.environ['ANSWER_MODE'],'extractive')
   os.environ['ANSWER_MODE']='llm';load_env(p);self.assertEqual(os.environ['ANSWER_MODE'],'llm')
 def test_invalid_env(self):
  with tempfile.TemporaryDirectory() as d:
   p=Path(d)/'.env';p.write_text('BAD value')
   with self.assertRaises(ValueError):load_env(p)
 def test_live_wal_backup(self):
  with tempfile.TemporaryDirectory() as d:
   db=Path(d)/'data.db';connection=sqlite3.connect(db)
   connection.executescript('PRAGMA journal_mode=WAL; CREATE TABLE chat(text); INSERT INTO chat VALUES("saved");')
   target=Path(d)/'backup.db';backup_database(db,target)
   read=sqlite3.connect(target)
   try:self.assertEqual(read.execute('SELECT text FROM chat').fetchone()[0],'saved')
   finally:read.close();connection.close()
   with self.assertRaises(ValueError):backup_database(db,target)
