import json
import unittest
from unittest.mock import Mock
from app.query_context import interpret,safe_provider_error

class ClarifyProtocolTests(unittest.TestCase):
    history=[{'role':'user','content':'提前开票最高多少'}, {'role':'assistant','content':'最高2万元，仅预开一次'}]
    def test_observed_vendor_output_is_resolved_against_history(self):
        raw='{"intent":"clarify","kind":"followup","question":"是否能多次申请","clarification":"需要明确用户指的是哪种申请或具体业务内容","evidence":""}'
        model=Mock(complete=Mock(side_effect=[raw,json.dumps({'kind':'followup','question':'提前开票是否能多次申请','clarification':''})]))
        diagnostics=[]
        result=interpret(model,'是否能多次申请',self.history,diagnostics)
        self.assertEqual(result['intent'],'knowledge')
        self.assertEqual(result['kind'],'followup')
        self.assertIn('提前开票',result['question'])
        self.assertEqual(model.complete.call_count,2)
        self.assertEqual(diagnostics[0]['normalization'],'clarify_intent_to_resolution')

    def test_early_clarification_uses_history_before_asking_user(self):
        model=Mock(complete=Mock(side_effect=[json.dumps(dict(intent='knowledge',kind='clarify',clarification='哪项业务')),
              json.dumps(dict(kind='followup',question='提前开票是否能多次申请',clarification=''))]))
        self.assertEqual(interpret(model,'是否能多次申请',self.history)['kind'],'followup')

    def test_no_history_keeps_clarification(self):
        model=Mock(complete=Mock(return_value=json.dumps(dict(intent='clarify',kind='followup',clarification='您指哪种申请？'))))
        result=interpret(model,'是否能多次申请',[])
        self.assertEqual(result['kind'],'clarify')
        self.assertEqual(result['clarification'],'您指哪种申请？')
        model.complete.assert_called_once()

    def test_resolution_ambiguity_is_not_forced_into_an_answer(self):
        model=Mock(complete=Mock(side_effect=[json.dumps(dict(intent='clarify',kind='followup',clarification='哪项业务')),
            json.dumps(dict(kind='clarify',question='是否能多次申请',clarification='您指开票还是退款？'))]))
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
