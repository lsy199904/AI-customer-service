import tempfile
import time
import unittest
from pathlib import Path
from app.core import Service, Settings, APIError

class RetentionTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.service=Service(Settings(secret='x'*40, db=str(Path(self.tmp.name)/'chat.db'),retrieval_backend='lexical',retention_days=7,purge_days=0))
        self.addCleanup(self.service.close)
        self.actor={'tenant_id':'t','sub':'u'}
        self.sid=self.service.create(self.actor,{})['session_id']
        with self.service.db:
            self.service.db.execute('UPDATE sessions SET updated=? WHERE id=?',(time.time()-10*86400,self.sid))
    def exists(self):
        return self.service.db.execute('SELECT COUNT(*) FROM sessions WHERE id=?',(self.sid,)).fetchone()[0]
    def test_hidden_but_preserved_by_default(self):
        with self.assertRaises(APIError):self.service.owned(self.actor,self.sid)
        self.assertTrue(self.service.prune_sessions()['cleanup_disabled'])
        self.assertEqual(self.exists(),1)
    def test_manual_cutoff_independent_of_visibility(self):
        self.service.prune_sessions(days=30)
        self.assertEqual(self.exists(),1)
        self.assertEqual(self.service.prune_sessions(days=7)['deleted_sessions'],1)
        self.assertEqual(self.exists(),0)
    def test_automatic_cleanup_can_be_enabled(self):
        self.service.config.purge_days=7
        self.assertEqual(self.service.prune_sessions()['deleted_sessions'],1)
    def test_refuses_cleanup_inside_visible_window(self):
        with self.assertRaises(ValueError):self.service.prune_sessions(days=1)
        self.assertEqual(self.exists(),1)
