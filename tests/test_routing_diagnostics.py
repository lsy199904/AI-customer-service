import io
import json
import unittest
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import Mock,patch
from scripts.check_conversation_routing import main,TracedModel
from app.query_context import interpret,resolution_error_code

class DiagnosticsTests(unittest.TestCase):
    def test_script_reports_validation_reason_and_redacts_output(self):
        key='private-test-key'
        model=SimpleNamespace(config=SimpleNamespace(model_key=key),complete=Mock(return_value=json.dumps(
            {'intent':'invalid','kind':'independent','detail':key+' sk-abcdef123456'})))
        output=io.StringIO()
        with patch('scripts.check_conversation_routing.Model',return_value=model),patch('sys.argv',['check','--case','开票追问','--rounds','1']),redirect_stdout(output):
            self.assertEqual(main(),1)
        rows=[json.loads(line) for line in output.getvalue().splitlines()]
        self.assertEqual(rows[0]['reason'],'invalid conversation interpretation')
        self.assertEqual(rows[0]['calls'][0]['stage'],'classification')
        self.assertNotIn(key,output.getvalue())
        self.assertNotIn('sk-abcdef123456',output.getvalue())
        self.assertEqual(rows[1],{'total':1,'failed':1})

    def test_malformed_response_after_history_lookup_is_reported(self):
        model=SimpleNamespace(config=SimpleNamespace(model_key=''),complete=Mock(side_effect=[
            json.dumps(dict(intent='knowledge',kind='lookup',history_query='提前开票')), 'bad json']))
        trace=TracedModel(model);diagnostics=[]
        history=[{'role':'user','content':'提前开票最高多少'}]
        with self.assertRaises(json.JSONDecodeError):
            interpret(trace,'之前那个能多次申请吗',[],diagnostics,lookup=lambda query:history)
        self.assertEqual(diagnostics,[{'stage':'history_lookup','messages':1}])
        self.assertEqual(trace.calls[1]['model_output'],'bad json')

    def test_unknown_provider_error_never_exposes_message(self):
        model=SimpleNamespace(config=SimpleNamespace(model_key='secret'),complete=Mock(side_effect=RuntimeError('Authorization: secret')))
        trace=TracedModel(model)
        with self.assertRaises(RuntimeError):trace.complete([])
        self.assertNotIn('secret',json.dumps(trace.calls))
        self.assertEqual(resolution_error_code(TimeoutError('sensitive')),'provider_timeout')

if __name__=='__main__':unittest.main()
