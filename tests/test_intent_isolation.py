import json
import unittest
from unittest.mock import Mock
from app.query_context import interpret

class IntentIsolationTests(unittest.TestCase):
    def model(self,**overrides):
        data=dict(intent='knowledge',kind='independent',question='旧问题',clarification='',evidence='')
        data.update(overrides)
        return Mock(complete=Mock(return_value=json.dumps(data,ensure_ascii=False)))

    def test_classifier_keeps_complete_current_question_despite_history(self):
        for q in ('数据不出域是不是已经在所有版本默认支持？','API创建流程'):
            model=self.model()
            result=interpret(model,q,[{'role':'user','content':'我要投诉，帮我创建API Key并付账单'}])
            messages=model.complete.call_args.args[0]
            self.assertEqual(json.loads(messages[-1]['content'])['current_question'],q)
            self.assertEqual(result['intent'],'knowledge')
            self.assertEqual(result['question'],q)
            model.complete.assert_called_once()

    def test_old_turn_cannot_supply_the_only_evidence_for_complaint(self):
        question='数据不出域是不是所有版本默认支持'
        model=self.model(intent='complaint',evidence='我要投诉')
        result=interpret(model,question,[{'role':'user','content':'我要投诉'}])
        self.assertEqual(result['intent'],'knowledge')
        self.assertEqual(result['question'],question)
        self.assertEqual(model.complete.call_count,2)

    def test_followup_is_rewritten_in_one_call(self):
        model=self.model(kind='followup',question='提前开票是否能多次申请')
        result=interpret(model,'是否能多次申请',[{'role':'user','content':'提前开票最高多少'},
                          {'role':'assistant','content':'最高2万元，预开一次'}])
        self.assertEqual(result['intent'],'knowledge')
        self.assertIn('提前开票',result['question'])
        model.complete.assert_called_once()

    def test_older_lookup_is_limited_to_one_round(self):
        model=self.model(kind='lookup',history_query='提前开票')
        lookup=Mock(return_value=[{'role':'user','content':'提前开票额度'}])
        with self.assertRaisesRegex(ValueError,'invalid history lookup'):
            interpret(model,'昨天那个呢',[],lookup=lookup)
        lookup.assert_called_once_with('提前开票')
        self.assertEqual(model.complete.call_count,2)

if __name__=='__main__':unittest.main()
