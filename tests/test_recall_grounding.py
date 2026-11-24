import json
import unittest
from unittest.mock import Mock
from types import SimpleNamespace
from app.history_recall import recall

class RecallGroundingTests(unittest.TestCase):
    history=[{'role':'user','content':'我要投诉，客服没解决我的问题'},
             {'role':'assistant','content':'请联系人工客服'},
             {'role':'user','content':'转人工客服'}]
    def test_current_echo_falls_back_before_streaming(self):
        model=Mock(complete=Mock(return_value=json.dumps({'answer':'您刚才问了：我刚才问了哪些问题','source_indexes':[0]})))
        chunks=[]
        result=recall(model,'我刚才问了哪些问题',self.history,chunks.append)
        self.assertIn('我要投诉',result['answer'])
        self.assertIn('转人工客服',result['answer'])
        self.assertNotIn('我刚才问了哪些问题',result['answer'])
        self.assertEqual(chunks,[result['answer']])

    def test_valid_recall_uses_indexed_previous_records(self):
        model=Mock(complete=Mock(return_value=json.dumps({'answer':'您之前提出投诉，并要求转人工。','source_indexes':[0,2]})))
        self.assertEqual(recall(model,'回顾一下',self.history)['answer'],'您之前提出投诉，并要求转人工。')

    def test_invalid_indexes_and_provider_failure_use_real_history(self):
        for value in ('bad json',json.dumps({'answer':'编造记录','source_indexes':[99]})):
            result=recall(Mock(complete=Mock(return_value=value)),'之前问了啥',self.history)
            self.assertIn('我要投诉',result['answer'])
        self.assertIn('没有之前',recall(Mock(complete=Mock(side_effect=TimeoutError())),'之前问了啥',[])['answer'])

    def test_complaint_routes_to_contact_not_action(self):
        from app.workflow import SupportWorkflow,Context
        workflow=object.__new__(SupportWorkflow)
        answer={'intent':'complaint','kind':'independent','question':'我要投诉','clarification':''}
        workflow.service=SimpleNamespace(config=SimpleNamespace(mode='llm',min_similarity=.6),model=Mock(complete=Mock(return_value=json.dumps(answer))))
        result=workflow.route({'question':'我要投诉，客服没有解决问题','history':[]},SimpleNamespace(context=Context()))
        self.assertEqual(result['intent'],'handoff')
        self.assertEqual(result['reason'],'complaint_handoff')
        self.assertNotIn('自行办理',result['answer'])
        self.assertIn('无法直接登记',result['answer'])

if __name__=='__main__':unittest.main()
