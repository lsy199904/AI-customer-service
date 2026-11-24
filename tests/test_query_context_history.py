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

if __name__=='__main__':unittest.main()
