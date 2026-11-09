import importlib.util
import json
import os
from pathlib import Path
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch
from app import cost_metrics as metrics
from app import observability as ops

class CostMetricsTests(unittest.TestCase):
    def sample(self,t,cpu,**more):
        return dict(timestamp=t,cpu_total_ns=cpu,container_id='container-a',memory_bytes=10*1024**2,**more)
    def test_units_gpu_and_shared_scope(self):
        first=self.sample(10,1_000_000_000,gpu_process_memory_mib=200,gpus=[])
        last=self.sample(11,3_000_000_000,gpu_process_memory_mib=240,gpus=[{'uuid':'gpu-a','utilization_percent':40,'power_w':100}])
        result=metrics.resource_window([first],[first,last],10.1,11.1)
        self.assertEqual(result['cpu_seconds'],2)
        self.assertEqual(result['cpu_percent_one_core'],200)
        self.assertEqual(result['memory_peak_mib'],10)
        self.assertEqual(result['gpu_process_memory_peak_mib'],240)
        self.assertFalse(result['attributable_to_request'])
    def test_short_stale_restart_and_counter_reset_are_unknown(self):
        first=self.sample(10,100)
        for after,started,ended in (([first],10.1,10.2),([self.sample(11,200)],20,21),
                                   ([dict(self.sample(11,200),container_id='new')],10.1,11.1),
                                   ([self.sample(11,0)],10.1,11.1)):
            result=metrics.resource_window([first],after,started,ended)
            self.assertEqual(result['status'],'unavailable')
            self.assertIsNone(result['cpu_seconds'])
    def test_usage_metadata_and_legacy_fallback(self):
        expected={'input_tokens':14,'output_tokens':64,'total_tokens':78}
        self.assertEqual(metrics.usage_counts(SimpleNamespace(usage_metadata=expected)),expected)
        old=SimpleNamespace(response_metadata={'token_usage':{'prompt_tokens':14,'completion_tokens':64,'total_tokens':78}})
        self.assertEqual(metrics.usage_counts(old),expected)
        self.assertIsNone(metrics.usage_counts(SimpleNamespace()))
        self.assertIsNone(metrics.usage_counts(SimpleNamespace(usage_metadata={'input_tokens':True})))
    def test_no_invocation_and_missing_usage_not_conflated(self):
        self.assertEqual(metrics.summarize([])['embedding']['call_count'],0)
        report=metrics.summarize([{'stage':'llm','usage':None}])
        self.assertFalse(report['llm']['usage_complete'])
        self.assertEqual(report['llm']['usage_unknown_calls'],1)
        self.assertEqual(report['llm']['usage_known_calls'],0)
    def test_parallel_usage_survives_trace_limit_and_late_completion(self):
        with tempfile.TemporaryDirectory() as directory,patch.dict(os.environ,{'COST_REPORT_DIR':directory,'COST_REPORT_ENABLED':'true'}):
            trace=ops.RequestTrace()
            trace.record('chat_started',{'request_id':'cost-request'})
            for i in range(90):trace.record('routine',{})
            def add(i):
                trace.record('inference_cost',{'call_id':str(i),'stage':'llm','status':'completed','usage':{'input_tokens':10,'output_tokens':2,'total_tokens':12}})
            threads=[threading.Thread(target=add,args=(i,)) for i in range(4)]
            for t in threads:t.start()
            for t in threads:t.join()
            trace.record('inference_cost_started',{'call_id':'late','stage':'llm','status':'running','usage':None})
            trace.finish()
            trace.record('inference_cost',{'call_id':'late','stage':'llm','status':'completed','usage':{'input_tokens':1,'output_tokens':1,'total_tokens':2}})
            records=[json.loads(line) for line in next(Path(directory).glob('cost-*.jsonl')).read_text().splitlines()]
            self.assertEqual(records[0]['metrics']['llm']['usage_unknown_calls'],1)
            self.assertEqual(records[-1]['metrics']['llm']['known_token_totals']['total_tokens'],50)
            self.assertEqual(len(records[-1]['metrics']['calls']),5)
    def test_inference_exception_preserved_and_no_resource_probe_required(self):
        with patch.object(metrics,'samples',return_value=[]),patch.object(ops,'event') as event:
            with self.assertRaisesRegex(ValueError,'original'):
                with metrics.inference('embedding','bge'):
                    raise ValueError('original')
            self.assertEqual(event.call_args.kwargs['status'],'failed')
            self.assertEqual(event.call_args.kwargs['resources']['status'],'unavailable')

class StreamAccountingTests(unittest.TestCase):
    def test_actual_langchain_usage_chunk_does_not_become_customer_text(self):
        import httpx
        from app.core import Model,Settings
        sent=[];seen=[]
        def handler(request):
            sent.append(json.loads(request.content))
            frames=[]
            for text in ('你好','，欢迎咨询。'):
                frames.append({'id':'test','object':'chat.completion.chunk','created':0,'model':'test-model',
                               'choices':[{'index':0,'delta':{'content':text},'finish_reason':None}]})
            frames.append({'id':'test','object':'chat.completion.chunk','created':0,'model':'test-model','choices':[],
                           'usage':{'prompt_tokens':14,'completion_tokens':64,'total_tokens':78}})
            body=''.join('data: '+json.dumps(f)+'\n\n' for f in frames)+'data: [DONE]\n\n'
            return httpx.Response(200,text=body,headers={'content-type':'text/event-stream'})
        model=Model(Settings(retrieval_backend='lexical',model='test-model',model_key='test-key'))
        with httpx.Client(transport=httpx.MockTransport(handler)) as client,patch('app.transport.client',return_value=client),patch.object(ops,'event') as event:
            text=model._complete_request([{'role':'user','content':'你好'}],seen.append)
        costs=[c.kwargs for c in event.call_args_list if c.args[0]=='inference_cost']
        self.assertTrue(sent[0]['stream_options']['include_usage'])
        self.assertEqual(text,'你好，欢迎咨询。')
        self.assertEqual(''.join(seen),text)
        self.assertEqual(costs[0]['usage']['total_tokens'],78)
        self.assertEqual(len(costs),1)


class BenchmarkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import sys
        sys.path.insert(0,str(Path(__file__).parents[1]/'scripts'))
        import model_benchmark
        cls.benchmark=model_benchmark
    def test_five_questions_and_latest_snapshot_selected(self):
        self.assertEqual(len(self.benchmark.QUESTIONS),5)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'cost-today-1.jsonl'
            path.write_text('\n'.join(json.dumps({'request_id':'request','recorded_at':i}) for i in (1,2)))
            self.assertEqual(self.benchmark.find_cost(directory,'request')['recorded_at'],2)
    def test_report_and_cpu_comparison(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory)
            old={'mode':'gpu','rows':[{'question':'注册流程是什么','cost':{'metrics':{'calls':[{'stage':'embedding','status':'completed','elapsed_ms':10}]}}}]}
            new={'mode':'cpu','rows':[{'question':'注册流程是什么','cost':{'metrics':{'calls':[{'stage':'embedding','status':'completed','elapsed_ms':40}]}}}]}
            (root/'gpu.json').write_text(json.dumps(old));(root/'cpu.json').write_text(json.dumps(new))
            self.benchmark.write_comparison(root/'gpu.json',root/'cpu.json',root/'compare.md')
            self.assertIn('4.0',(root/'compare.md').read_text())
            self.assertIn('未测得',(root/'compare.md').read_text())
    def test_report_marks_missing_not_zero(self):
        with tempfile.TemporaryDirectory() as directory:
            self.benchmark.write_report(Path(directory),'gpu',[{'question':'如何联系人工','request_id':'test','status':'answered','cost':None}],{}, {}, {})
            report=(Path(directory)/'报告.md').read_text()
            self.assertIn('未知',report)
            self.assertIn('没有匹配到请求统计',report)

if __name__=='__main__':unittest.main()
