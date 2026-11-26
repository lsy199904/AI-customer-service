import json
import unittest
from types import SimpleNamespace
from app.query_context import resolve, local_query

class Resolver:
    def __init__(self, kind, question):
        self.result={'kind':kind,'question':question,'clarification':''}
    def complete(self, messages):
        self.messages=messages
        return json.dumps(self.result,ensure_ascii=False)

class HistoryTests(unittest.TestCase):
    def setUp(self):
        self.history=[{'role':'user','content':'提前开票最高多少？'},
                      {'role':'assistant','content':'最高2万元，且仅支持预开一次。'}]

    def test_subjectless_followup_receives_both_roles(self):
        model=Resolver('followup','提前开票是否能多次申请？')
        result=resolve(model,'是否能多次申请',self.history)
        self.assertEqual(result['question'],'提前开票是否能多次申请？')
        self.assertEqual(json.loads(model.messages[-1]['content'])['recent_messages'],self.history)

    def test_explicit_new_subject_is_preserved(self):
        model=Resolver('independent','注册流程')
        result=resolve(model,'开发票流程是什么？',[{'role':'user','content':'注册流程是什么？'},
                         {'role':'assistant','content':'先注册账号。'}])
        self.assertEqual(result['question'],'开发票流程是什么？')

    def test_only_recent_five_rounds_are_sent(self):
        history=self.history*7
        model=Resolver('followup','提前开票是否能多次申请？')
        resolve(model,'是否能多次申请',history)
        self.assertEqual(json.loads(model.messages[-1]['content'])['recent_messages'],history[-10:])

    def test_no_history_does_not_call_resolver(self):
        self.assertEqual(resolve(None,'开发票流程',[])['kind'],'independent')

    def test_local_fallback_handles_subjectless_request(self):
        self.assertEqual(local_query('是否能多次申请',self.history),'提前开票最高多少？ 是否能多次申请')

    def test_knowledge_generation_includes_history(self):
        from app.core import Model
        model=Model(SimpleNamespace(context_rounds=20))
        calls=[]
        model.complete=lambda messages,on_delta=None: calls.append(messages) or '仅支持预开一次。'
        model.answer('是否能多次申请',self.history*7,[],{'_intent':'knowledge'})
        self.assertEqual(len(calls[0]),12)
        self.assertEqual(calls[0][1]['content'],self.history[0]['content'])
        self.assertEqual(calls[0][-2]['content'],self.history[1]['content'])

class RecallTests(unittest.TestCase):
    def test_recall_routes_separately_from_business_followup(self):
        from app.conversation import intent_of
        for q in ('刚才我问了什么','我之前问过哪些问题','总结一下我们的对话',
                  '上一个问题是什么','我刚才的问题是什么','重复一下刚才的回答'):
            with self.subTest(q=q):self.assertEqual(intent_of(q),'history')
        for q in ('是否能多次申请','刚才说的提前开票怎么申请','开发票流程是什么'):
            with self.subTest(q=q):self.assertEqual(intent_of(q),'knowledge')

    def test_recall_prompt_uses_available_history_without_business_evidence(self):
        from app.core import Model
        from app.history_recall import PROMPT
        model=Model(SimpleNamespace(context_rounds=20))
        calls=[]
        model.complete=lambda messages,on_delta=None: calls.append(messages) or json.dumps({'answer':'你刚才问了是否能多次申请。','source_indexes':[10]})
        history=[{'role':'user','content':'是否能多次申请'},
                 {'role':'assistant','content':'提前开票仅支持一次。'}]*6
        result=model.answer('刚才我问了什么',history,[],{'_intent':'history'})
        self.assertEqual(calls[0][0]['content'],PROMPT)
        payload=json.loads(calls[0][-1]['content'])
        self.assertEqual(len(payload['previous_messages']),12)
        self.assertEqual(payload['current_request'],'刚才我问了什么')
        self.assertEqual(result['answer'],'你刚才问了是否能多次申请。')

class RecallWorkflowTests(unittest.TestCase):
    def test_recall_bypasses_retrieval_and_does_not_consume_rag_quota(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import Mock,patch
        from app.core import Settings,Service
        from app.workflow import SupportWorkflow
        with tempfile.TemporaryDirectory() as directory:
            service=Service(Settings(secret='x'*40,db=str(Path(directory)/'chat.db'),retrieval_backend='lexical'))
            try:
                actor={'tenant_id':'test','sub':'visitor'}
                sid=service.create(actor,{})['session_id']
                service.chat(actor,sid,{'message':'你好','request_id':'recall-greeting-request'})
                service.config.mode='llm'
                service.model=Mock()
                service.model.complete.side_effect=AssertionError('explicit recall must skip classification')
                service.model.answer.return_value={'answerable':True,'answer':'你刚才说了“你好”。','citation_ids':[],'image_ids':[]}
                with patch.object(service,'reserve_rag_quota',side_effect=AssertionError('recall must not retrieve')):
                    response=service.chat(actor,sid,{'message':'刚才我问了什么','request_id':'recall-history-request'})
                    summary=service.chat(actor,sid,{'message':'总结我的对话','request_id':'recall-summary-request'})
                self.assertEqual(summary['reason'],'history')
                self.assertEqual(summary['status'],'answered')
                service.model.complete.assert_not_called()
                self.assertEqual(response['reason'],'history')
                self.assertEqual(response['status'],'answered')
                self.assertEqual(response['citations'],[])
                self.assertEqual(service.model.answer.call_args.args[1][0]['content'],'你好')
                self.assertEqual(service.db.execute('SELECT COALESCE(SUM(used),0) FROM global_rag_daily_limits').fetchone()[0],0)
            finally:service.close()

if __name__=='__main__':unittest.main()
