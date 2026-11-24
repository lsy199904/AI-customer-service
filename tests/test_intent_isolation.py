import json
import unittest
from unittest.mock import Mock
from app.query_context import interpret

class IntentIsolationTests(unittest.TestCase):
    def model(self,**overrides):
        data=dict(intent='knowledge',kind='independent',question='旧问题',clarification='',evidence='')
        data.update(overrides)
        return Mock(complete=Mock(return_value=json.dumps(data,ensure_ascii=False)))

    def test_classifier_never_receives_old_complaint_or_action(self):
        for q in ('数据不出域是不是已经在所有版本默认支持？','API创建流程'):
            model=self.model()
            result=interpret(model,q,[{'role':'user','content':'我要投诉，帮我创建API Key并付账单'}])
            messages=model.complete.call_args.args[0]
            self.assertEqual(json.loads(messages[-1]['content']),{'current_question':q})
            self.assertEqual(result['intent'],'knowledge')
            self.assertEqual(result['question'],q)
            model.complete.assert_called_once()

    def test_wrong_complaint_cannot_use_previous_turn_as_evidence(self):
        with self.assertRaises(ValueError):
            interpret(self.model(intent='complaint',evidence='我要投诉'),'数据不出域是不是所有版本默认支持',
                      [{'role':'user','content':'我要投诉'}])

    def test_instruction_query_cannot_enter_fixed_action_response(self):
        result=interpret(self.model(intent='action',evidence='创建'),'API创建流程',[])
        self.assertEqual(result['intent'],'knowledge')
        self.assertEqual(result['question'],'API创建流程')

    def test_product_support_question_cannot_enter_complaint(self):
        q='数据不出域是不是已经在所有版本默认支持？'
        result=interpret(self.model(intent='complaint',evidence='数据不出域'),q,[])
        self.assertEqual(result['intent'],'knowledge')

    def test_referent_resolver_cannot_switch_speech_act(self):
        model=Mock(complete=Mock(side_effect=[json.dumps(dict(intent='knowledge',kind='followup',question='是否能多次申请',clarification='',evidence='')),
             json.dumps(dict(kind='followup',question='提前开票是否能多次申请',clarification=''))]))
        result=interpret(model,'是否能多次申请',[{'role':'user','content':'提前开票最高多少'},
                          {'role':'assistant','content':'最高2万元，预开一次'}])
        self.assertEqual(result['intent'],'knowledge')
        self.assertIn('提前开票',result['question'])
        self.assertEqual(model.complete.call_count,2)
        self.assertNotIn('recent_messages',json.loads(model.complete.call_args_list[0].args[0][-1]['content']))

    def test_resolution_timeout_asks_instead_of_inventing_old_topic(self):
        model=self.model(kind='followup')
        model.complete.side_effect=[model.complete.return_value,TimeoutError()]
        result=interpret(model,'第二种呢',[{'role':'user','content':'有哪些方式'}])
        self.assertEqual(result['kind'],'clarify')
        self.assertEqual(result['question'],'第二种呢')

if __name__=='__main__':unittest.main()
