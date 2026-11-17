"""Daily RAG admission is persistent, shared and independent of fixed FAQ answers."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch,Mock
from zoneinfo import ZoneInfo
from app.core import Settings,Service
from app.workflow import SupportWorkflow,Context

class GlobalRAGQuotaTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.config=Settings(secret='daily-quota-test-'+('x'*40),db=str(Path(self.temp.name)/'chat.db'),
                             retrieval_backend='lexical',global_rag_questions_per_day=2)
        self.service=Service(self.config);self.addCleanup(self.service.close)

    def test_quota_event_is_kept_in_compact_logs(self):
        from app.observability import compact_steps
        row={'事件':'global_rag_quota','级别':'INFO','详情':{'allowed':False,'limit':1000}}
        self.assertEqual(compact_steps([row]),[row])

    def test_defaults_and_validation(self):
        with patch.dict('os.environ',{},clear=True):self.assertEqual(Settings().global_rag_questions_per_day,1000)
        for value in (0,-1,10000001):
            self.config.global_rag_questions_per_day=value
            with self.assertRaises(ValueError):self.config.validate()

    def test_concurrent_connections_cannot_overshoot_and_restart_keeps_usage(self):
        other=Service(self.config)
        try:
            with ThreadPoolExecutor(max_workers=8) as pool:
                results=list(pool.map(lambda i:(self.service if i%2 else other).reserve_rag_quota(),range(20)))
            self.assertEqual(sum(results),2)
        finally:other.close()
        restarted=Service(self.config)
        try:self.assertFalse(restarted.reserve_rag_quota())
        finally:restarted.close()

    def test_beijing_midnight_resets_without_deleting_previous_counter(self):
        before=datetime(2026,11,17,23,59,59,tzinfo=ZoneInfo('Asia/Shanghai')).timestamp()
        with patch('app.core.time.time',return_value=before):
            self.assertTrue(self.service.reserve_rag_quota());self.assertTrue(self.service.reserve_rag_quota())
            self.assertFalse(self.service.reserve_rag_quota())
        with patch('app.core.time.time',return_value=before+1):self.assertTrue(self.service.reserve_rag_quota())
        self.assertEqual(self.service.db.execute('SELECT COUNT(*) FROM global_rag_daily_limits').fetchone()[0],2)

    def test_exhaustion_blocks_before_query_resolution_or_any_model(self):
        for _ in range(2):self.service.reserve_rag_quota()
        workflow=object.__new__(SupportWorkflow);workflow.service=self.service
        with patch('app.query_context.resolve',side_effect=AssertionError('model-assisted resolution invoked')):
            result=workflow.retrieve({'question':'注册流程','history':[]},SimpleNamespace(context=Context()))
        self.assertEqual(result['reason'],'global_daily_limit')
        self.assertEqual(result['answer'],'请稍后重试，您仍可查看常见问题或选择相关问题获取解答。如需进一步帮助，请联系人工客服：4008841883，help@china-entercom.net。')
        self.assertEqual(result['evidence'],[])

    def test_http_equivalent_chat_is_global_cached_and_faq_still_works(self):
        self.config.global_rag_questions_per_day=1
        a={'tenant_id':'tenant-a','sub':'alice'};b={'tenant_id':'tenant-b','sub':'bob'}
        sa=self.service.create(a,{})['session_id'];sb=self.service.create(b,{})['session_id']
        # Let the first admitted RAG request finish locally without external APIs.
        self.service.model=Mock();self.service.model.answer.side_effect=AssertionError('external LLM')
        first=self.service.chat(a,sa,{'message':'注册流程','request_id':'daily-first-request'})
        self.assertEqual(self.service.db.execute('SELECT SUM(used) FROM global_rag_daily_limits').fetchone()[0],1)
        self.assertEqual(self.service.chat(a,sa,{'message':'注册流程','request_id':'daily-first-request'}),first)
        blocked=self.service.chat(b,sb,{'message':'企业认证流程','request_id':'daily-blocked-request'})
        self.assertEqual(blocked['reason'],'global_daily_limit')
        faq=self.service.faq.rows['faq-05']
        fixed=self.service.chat(b,sb,{'message':faq['question'],'faq_id':faq['id'],'request_id':'daily-faq-request'})
        self.assertEqual(fixed['reason'],'standard_faq')
        self.assertEqual(self.service.db.execute('SELECT SUM(used) FROM global_rag_daily_limits').fetchone()[0],1)
        self.service.model.answer.assert_not_called()

if __name__=='__main__':unittest.main()
