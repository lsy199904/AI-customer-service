import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import model_benchmark as b

class Benchmark50Tests(unittest.TestCase):
    def row(self, purpose='answer', call_status='completed', status='answered', complete=True):
        return {'question':'测试问题','request_id':'r','status':status,'answer':'测试答案',
                'cost':{'metrics':{'llm':{'call_count':1,'usage_known_calls':1,'usage_unknown_calls':0 if complete else 1,
                  'usage_complete':complete,'known_token_totals':{'input_tokens':100,'output_tokens':20,'total_tokens':120}},
                  'calls':[{'stage':'llm','purpose':purpose,'status':call_status}]}}}
    def test_fifty_unique_standalone_questions(self):
        q=b.load_questions(ROOT/'scripts/benchmark_questions_50.txt')
        self.assertEqual(len(q),50)
        self.assertEqual(len(set(q)),50)
        self.assertEqual(sum('数据不出域' in x for x in q),1)
        self.assertTrue(any('29号提交星级权益调整' in x for x in q))
        self.assertFalse(any('那如果' in x or x=='如何联系人工' for x in q))
    def test_original_five_preserved(self):
        self.assertEqual(b.load_questions(),b.QUESTIONS)
        self.assertEqual(len(b.load_questions()),5)
    def test_reject_empty_duplicate(self):
        with tempfile.TemporaryDirectory() as td:
            p=Path(td)/'q.txt'
            for value in ('# 注释\n','问题\n问题\n'):
                p.write_text(value)
                with self.assertRaises(ValueError): b.load_questions(p)
    def test_only_completed_answer_llm_counts(self):
        self.assertTrue(b.llm_validation(self.row())['answer_llm_completed'])
        for r in [self.row(purpose='image_policy'),self.row(call_status='failed'),self.row(status='suggestions'),self.row(status='handoff'),{'status':'answered','answer':'固定回复'}]:
            self.assertFalse(b.llm_validation(r)['answer_llm_completed'])
    def test_recorded_and_complete_usage_separate(self):
        out=b.token_summary([self.row(),self.row(complete=False),self.row(purpose='image_policy')])
        self.assertEqual(out['answer_llm_questions'],2)
        self.assertEqual(out['excluded_questions'],1)
        self.assertEqual(out['complete_usage_questions'],1)
        self.assertEqual(out['recorded_tokens']['total_tokens'],240)
        self.assertEqual(out['complete_usage_tokens']['total_tokens'],120)
    def test_report_exports_tokens_and_validation(self):
        with tempfile.TemporaryDirectory() as td:
            r=self.row();r['llm_validation']=b.llm_validation(r)
            b.write_report(Path(td),'gpu',[r],{},{},{})
            data=json.loads((Path(td)/'results.json').read_text())
            self.assertEqual(data['token_summary']['answer_llm_questions'],1)
            self.assertIn('input_tokens',(Path(td)/'tokens.csv').read_text(encoding='utf-8-sig'))
            self.assertIn('GPU 1题',(Path(td)/'报告.md').read_text())
    def test_no_llm_samples_average_unknown(self):
        self.assertIsNone(b.token_summary([{'question':'固定回复'}])['recorded_average_per_answer']['total_tokens'])

if __name__=='__main__':unittest.main()
