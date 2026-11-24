import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock,patch
from app.query_context import context_timeout,interpret
from app.core import Service,Settings

class ContextTimeoutTests(unittest.TestCase):
    def test_timeout_default_override_and_validation(self):
        with patch.dict('os.environ',{},clear=True):self.assertEqual(context_timeout(),10.)
        with patch.dict('os.environ',{'QUERY_CONTEXT_TIMEOUT_SECONDS':'12'}):self.assertEqual(context_timeout(),12.)
        for value in ('nan','inf','0','61','bad'):
            with patch.dict('os.environ',{'QUERY_CONTEXT_TIMEOUT_SECONDS':value}):
                with self.assertRaises(ValueError):Settings().validate()

    def test_timeout_option_is_applied_and_contextvar_reset(self):
        from app.evidence_selection import model_options
        def complete(messages):
            self.assertEqual(model_options()['timeout'],12.)
            return json.dumps(dict(intent='knowledge',kind='independent',clarification=''))
        previous=model_options()
        with patch.dict('os.environ',{'QUERY_CONTEXT_TIMEOUT_SECONDS':'12'}):interpret(Mock(complete=complete),'注册流程',[])
        self.assertEqual(model_options(),previous)

    def test_classification_timeout_never_retrieves_subjectless_query(self):
        with tempfile.TemporaryDirectory() as directory:
            service=Service(Settings(secret='x'*40,db=str(Path(directory)/'chat.db'),retrieval_backend='lexical'))
            try:
                actor={'tenant_id':'test','sub':'visitor'};sid=service.create(actor,{})['session_id']
                service.chat(actor,sid,{'message':'提前开票最高多少？','request_id':'timeout-history-first'})
                service.config.mode='llm';service.model=Mock(complete=Mock(side_effect=TimeoutError()))
                with patch.object(service,'reserve_rag_quota',side_effect=AssertionError('must not retrieve')):
                    result=service.chat(actor,sid,{'message':'那这个额度可以多次申请吗？','request_id':'timeout-subjectless-second'})
                self.assertEqual(result['reason'],'clarification')
                self.assertIn('请稍后重试',result['answer'])
                self.assertNotIn('无法回答',result['answer'])
                self.assertEqual(result['citations'],[])
                self.assertEqual(len(service.context_history(actor,sid)),4)
            finally:service.close()

    def test_failed_followup_completion_also_skips_retrieval(self):
        with tempfile.TemporaryDirectory() as directory:
            service=Service(Settings(secret='x'*40,db=str(Path(directory)/'chat.db'),retrieval_backend='lexical'))
            try:
                actor={'tenant_id':'test','sub':'visitor'};sid=service.create(actor,{})['session_id']
                service.chat(actor,sid,{'message':'提前开票最高多少？','request_id':'resolution-history-first'})
                service.config.mode='llm';service.model=Mock(complete=Mock(side_effect=[
                    json.dumps(dict(intent='knowledge',kind='followup',clarification='')),TimeoutError()]))
                with patch.object(service,'reserve_rag_quota',side_effect=AssertionError('must not retrieve')):
                    result=service.chat(actor,sid,{'message':'那这个额度可以多次申请吗？','request_id':'resolution-subjectless-second'})
                self.assertEqual(result['reason'],'clarification')
                self.assertEqual(result['citations'],[])
            finally:service.close()

if __name__=='__main__':unittest.main()
