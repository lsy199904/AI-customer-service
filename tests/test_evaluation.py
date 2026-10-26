"""Synthetic evaluation fixture: verifies metrics, review gate and private output."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from app.evaluation import evaluate
from app.core import Settings

class KB:
 vectors=None
 rows={'a':{'id':'a'},'b':{'id':'b'}}
 def assess(self,query,diagnostics=False):
  if query=='开户':return {'matched':True,'hits':[(.9,{'id':'a'},.8)],'_diagnostics':{'dense_top':[{'id':'a'}],'candidates':[{'id':'a'}]}}
  return {'matched':False,'hits':[],'_diagnostics':{}}
class EvaluationTests(unittest.TestCase):
 def test_recall_negative_rejection_coverage_and_review_gate(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);data=root/'dataset.jsonl';report=root/'report.jsonl'
   rows=[{'id':'1','query':'开户','expected_ids':['a'],'reviewed':True},{'id':'2','query':'天气','expected_ids':[],'reviewed':True}]
   data.write_text('\n'.join(json.dumps(row,ensure_ascii=False) for row in rows))
   with patch('app.evaluation.SemanticKnowledge',return_value=KB()):result=evaluate(Settings(),data,report)
   self.assertEqual(result['dense_recall_at_k'],1);self.assertEqual(result['selected_recall'],1)
   self.assertEqual(result['negative_rejection'],1);self.assertEqual(result['coverage'],.5)
   self.assertEqual(report.stat().st_mode&0o777,0o600)
   with patch('app.evaluation.SemanticKnowledge',return_value=KB()):
    with self.assertRaises(FileExistsError):evaluate(Settings(),data,report)
   rows[0]['reviewed']=False;data.write_text('\n'.join(json.dumps(row,ensure_ascii=False) for row in rows))
   with patch('app.evaluation.SemanticKnowledge',return_value=KB()):
    with self.assertRaisesRegex(ValueError,'审阅'):evaluate(Settings(),data,root/'new.jsonl')
 def test_stale_ground_truth_is_rejected(self):
  with tempfile.TemporaryDirectory() as temp:
   path=Path(temp)/'dataset';path.write_text(json.dumps({'id':'1','query':'开户','expected_ids':['stale'],'reviewed':True}))
   with patch('app.evaluation.SemanticKnowledge',return_value=KB()):
    with self.assertRaisesRegex(ValueError,'过期'):evaluate(Settings(),path,Path(temp)/'report')
