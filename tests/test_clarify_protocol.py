import json
import unittest
from unittest.mock import Mock
from app.query_context import interpret,safe_provider_error

class ClarifyProtocolTests(unittest.TestCase):
    history=[{'role':'user','content':'提前开票最高多少'}, {'role':'assistant','content':'最高2万元，仅预开一次'}]
    def test_observed_vendor_output_gets_one_contextual_repair(self):
        raw='{"intent":"clarify","kind":"followup","question":"是否能多次申请","clarification":"您指哪项申请？","evidence":""}'
        repaired=json.dumps(dict(intent='knowledge',kind='followup',question='提前开票是否能多次申请'))
        model=Mock(complete=Mock(side_effect=[raw,repaired]))
        diagnostics=[]
        result=interpret(model,'是否能多次申请',self.history,diagnostics)
        self.assertEqual(result['intent'],'knowledge')
        self.assertEqual(result['kind'],'followup')
        self.assertIn('提前开票',result['question'])
        self.assertEqual(diagnostics[0]['normalization'],'clarify_intent_to_resolution')
        self.assertEqual(model.complete.call_count,2)

    def test_followup_uses_both_roles_in_one_call(self):
        model=Mock(complete=Mock(return_value=json.dumps(dict(
            intent='knowledge',kind='followup',question='提前开票是否能多次申请'))))
        self.assertEqual(interpret(model,'是否能多次申请',self.history)['kind'],'followup')
        recent=json.loads(model.complete.call_args.args[0][-1]['content'])['recent_messages']
        self.assertEqual([item['role'] for item in recent],['user','assistant'])
        model.complete.assert_called_once()

    def test_resolution_ambiguity_is_not_forced_into_an_answer(self):
        model=Mock(complete=Mock(return_value=json.dumps(dict(
            intent='knowledge',kind='clarify',clarification='您指开票还是退款？'))))
        result=interpret(model,'是否能多次申请',self.history)
        self.assertEqual(result['kind'],'clarify')

    def test_safe_status_through_wrapped_provider_error(self):
        cause=RuntimeError('secret body');cause.status_code=503
        error=RuntimeError('secret header');error.__cause__=cause
        result=safe_provider_error(error)
        self.assertEqual(result,{'http_status':503,'provider_category':'provider_server_error'})
        self.assertNotIn('secret',json.dumps(result))
        self.assertEqual(safe_provider_error(TimeoutError('secret')),{'provider_category':'timeout'})

if __name__=='__main__':unittest.main()
