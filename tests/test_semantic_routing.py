import json
import unittest
from types import SimpleNamespace
from unittest.mock import Mock,patch
from app.query_context import interpret

class SemanticRoutingTests(unittest.TestCase):
    def model(self,intent='knowledge',kind='independent',question='错误的旧问题',clarification=''):
        return Mock(complete=Mock(return_value=json.dumps(dict(intent=intent,kind=kind,question=question,clarification=clarification,evidence='帮我' if intent=='action' else ''),ensure_ascii=False)))

    def test_current_independent_question_cannot_be_replaced(self):
        q='帮我创建一个API Key，并替我把账单付掉。'
        model=self.model('action')
        self.assertEqual(interpret(model,q,[{'role':'user','content':'提前开票最高多少'}])['question'],q)
        self.assertEqual(model.complete.call_count,2)

    def test_subjectless_followup_cannot_invent_context(self):
        result=interpret(self.model(kind='followup',question='提前开票能多次申请吗'),'是否能多次申请',[])
        self.assertEqual(result['kind'],'clarify')
        self.assertEqual(result['question'],'是否能多次申请')

    def test_history_and_new_topic_classification(self):
        for intent,q in [('history','概括一下咱们聊到现在的事情'),('knowledge','开票流程是什么')]:
            result=interpret(self.model(intent),q,[{'role':'user','content':'注册流程'}])
            self.assertEqual(result['intent'],intent)
            self.assertEqual(result['question'],q)

    def test_invalid_output_is_rejected(self):
        with self.assertRaises(ValueError):interpret(self.model('execute_payment'),'付账单',[])
        with self.assertRaises(ValueError):interpret(self.model(kind='clarify'),'这个怎么弄',[])

    def test_route_uses_model_even_for_unmatched_recall_wording(self):
        from app.workflow import SupportWorkflow,Context
        workflow=object.__new__(SupportWorkflow)
        workflow.service=SimpleNamespace(config=SimpleNamespace(mode='llm',min_similarity=.6),model=self.model('history'))
        values=workflow.route({'question':'概括一下咱们聊到现在的事情','history':[]},SimpleNamespace(context=Context()))
        self.assertEqual(values['intent'],'history')
        self.assertEqual(values['interpretation']['kind'],'independent')

    def test_parse_failure_preserves_original_without_old_topic(self):
        from app.workflow import SupportWorkflow,Context
        workflow=object.__new__(SupportWorkflow)
        workflow.service=SimpleNamespace(config=SimpleNamespace(mode='llm',min_similarity=.6),model=Mock(complete=Mock(return_value='bad json')),knowledge=SimpleNamespace(rows={}))
        q='API Key如何创建'
        with patch('app.assistance.plan',return_value={}):
            values=workflow.route({'question':q,'history':[{'role':'user','content':'开票'}]},SimpleNamespace(context=Context()))
        self.assertEqual(values['interpretation']['question'],q)
        self.assertEqual(values['interpretation']['kind'],'unavailable')

    def test_legacy_action_label_uses_knowledge_branch(self):
        import tempfile
        from pathlib import Path
        from app.core import Service,Settings
        with tempfile.TemporaryDirectory() as directory:
            service=Service(Settings(secret='x'*40,db=str(Path(directory)/'chat.db'),retrieval_backend='lexical'))
            try:
                actor={'tenant_id':'test','sub':'visitor'};sid=service.create(actor,{})['session_id']
                service.config.mode='llm';service.model=self.model('action')
                report={'evidence':[],'retrieval':{'matched':False,'hits':[]}}
                with patch('app.chains.retrieve',return_value=report) as retrieve:
                    result=service.chat(actor,sid,{'message':'帮我创建API Key并支付账单','request_id':'semantic-action-test'})
                retrieve.assert_called_once()
                self.assertEqual(result['citations'],[])
                self.assertNotIn('不能直接替您执行',result['answer'])
                self.assertEqual(service.model.complete.call_count,2)
            finally:service.close()

    def test_retrieval_reuses_interpretation_without_second_model_parse(self):
        import tempfile
        from pathlib import Path
        from app.core import Service,Settings
        with tempfile.TemporaryDirectory() as directory:
            service=Service(Settings(secret='x'*40,db=str(Path(directory)/'chat.db'),retrieval_backend='lexical'))
            try:
                actor={'tenant_id':'test','sub':'visitor'};sid=service.create(actor,{})['session_id']
                service.config.mode='llm';service.model=self.model('knowledge')
                found={'evidence':[],'candidates':[],'retrieval':{'matched':False,'similarity':0.,'threshold':.6,'hits':[]}}
                with patch('app.query_context.resolve',side_effect=AssertionError('duplicate parse')),patch('app.chains.retrieve',return_value=found),patch('app.assistance.plan',return_value={}):
                    service.chat(actor,sid,{'message':'注册流程是什么','request_id':'semantic-reuse-test'})
                service.model.complete.assert_called_once()
            finally:service.close()

if __name__=='__main__':unittest.main()
