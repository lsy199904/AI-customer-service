"""V2 guidance uses the latest actual DOCX, existing ownership and ordinary retrieval gates."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.assistance import FLOWS,available,plan,stage_context
from app.core import BASE,Service,Settings,APIError
from app.ingestion import parse_document
from app.retrieval import title_text

A={'tenant_id':'company-a','sub':'one'}
B={'tenant_id':'company-a','sub':'two'}

class LatestKnowledge:
 def __init__(self):
  self.rows={}
  for i,row in enumerate(parse_document(BASE/'knowledge_sources/SmartTITU客户问答.docx').chunks):
   self.rows[f'KB-{i:024x}']={**row,'id':f'KB-{i:024x}','source_file':'SmartTITU客户问答.docx','revision':'v5','audience':'customer','status':'source_based'}
  self.fail=False
 def assess(self,query):
  rows=[row for row in self.rows.values() if title_text(row['title'])==query]
  hits=[] if self.fail else [(0.85,row,0.8) for row in rows]
  return {'matched':bool(hits),'hits':hits,'method':'fixture','threshold':.75,'similarity':.8 if hits else None}

class AssistanceTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.config=Settings(retrieval_backend='lexical',secret='v2-secret-abcdefghijklmnopqrstuvwxyz0123456789',db=str(Path(self.temp.name)/'chat.db'))
  self.s=Service(self.config);self.k=LatestKnowledge();self.s.knowledge=self.k
  self.sid=self.s.create(A,{})['session_id'];self.count=0
 def tearDown(self):self.s.close();self.temp.cleanup()
 def ask(self,text,sid=None,actor=A,rid=None):
  self.count+=1
  return self.s.chat(actor,sid or self.sid,{'message':text,'request_id':rid or f'v2-request-{self.count:06}'})
 def test_latest_doc_all_six_flows_and_source_excerpts(self):
  self.assertEqual(len(self.k.rows),57)
  self.assertEqual(len(available(list(self.k.rows.values()))),6)
  for key,flow in FLOWS.items():
   with self.subTest(flow=key):
    sid=self.s.create(A,{})['session_id'];result=self.ask('分步指导：'+flow['title'],sid)
    self.assertEqual(result['guidance']['flow_id'],key);self.assertEqual(result['guidance']['step'],0)
    self.assertEqual(result['status'],'answered');self.assertTrue(result['citations']);self.assertTrue(result['images'])
    row=next(row for row in self.k.rows.values() if title_text(row['title'])==flow['title'])
    self.assertEqual(result['answer'],stage_context(result['guidance'],[row])['stage_evidence'])
 def test_plain_chapter_question_stays_overview_with_opt_in(self):
  result=self.ask('账单支付流程')
  self.assertIsNone(result['guidance']);self.assertEqual(result['reason'],'extractive')
  self.assertEqual(result['actions'][0]['message'],'分步指导：账单支付流程')
 def test_ambiguous_payment_clarifies_and_ordinal_resolves(self):
  first=self.ask('支付不了')
  self.assertEqual(first['reason'],'clarification');self.assertEqual(first['citations'],[])
  self.assertEqual([a['message'] for a in first['actions']],['账单支付流程','客户充值流程'])
  second=self.ask('第一个')
  self.assertTrue(second['citations']);self.assertIn('待支付账单',second['answer'])
  self.assertEqual(second['actions'][0]['message'],'分步指导：账单支付流程')
 def test_steps_do_not_advance_without_explicit_completion(self):
  self.ask('带我办理账单支付流程')
  result=self.ask('这一步怎么做');self.assertEqual(result['guidance']['step'],0)
  result=self.ask('这一步已完成');self.assertEqual(result['guidance']['step'],1)
  result=self.ask('返回上一步');self.assertEqual(result['guidance']['step'],0)
  self.assertIn('未查询',result['guidance']['note'])
 def test_acknowledgement_preserves_stage_without_advancing(self):
  self.ask('分步指导：企业认证流程');self.ask('这一步已完成')
  result=self.ask('谢谢');self.assertEqual(result['guidance']['step'],1)
  result=self.ask('好的');self.assertEqual(result['guidance']['step'],1)
  result=self.ask('这一步怎么做');self.assertEqual(result['guidance']['step'],1)
 def test_completed_and_ended_are_not_business_success(self):
  self.ask('分步指导：注册流程')
  for _ in range(3):result=self.ask('这一步已完成')
  self.assertEqual(result['guidance']['status'],'completed');self.assertIn('没有查询后台',result['answer'])
  self.assertEqual(result['actions'][0]['message'],'企业认证流程')
  self.ask('分步指导：注册流程');result=self.ask('结束指导')
  self.assertEqual(result['guidance']['status'],'ended')
 def test_topic_switch_clears_guide_and_no_state_leaks_between_sessions(self):
  self.ask('分步指导：注册流程')
  result=self.ask('在线开票流程');self.assertIsNone(result['guidance'])
  result=self.ask('下一步');self.assertEqual(result['reason'],'clarification')
  self.ask('分步指导：注册流程')
  sid=self.s.create(A,{})['session_id'];self.assertEqual(self.ask('下一步',sid)['reason'],'clarification')
  with self.assertRaises(APIError):self.ask('下一步',actor=B)
 def test_restart_recovers_same_session_step_and_request_retry_is_idempotent(self):
  self.ask('分步指导：企业认证流程')
  first=self.ask('这一步已完成',rid='v2-same-request')
  duplicate=self.ask('这一步已完成',rid='v2-same-request')
  self.assertEqual(first,duplicate)
  self.s.close();self.s=Service(self.config);self.s.knowledge=self.k
  current=self.ask('这一步怎么做');self.assertEqual(current['guidance']['step'],1)
 def test_idle_does_not_resume_old_task(self):
  self.ask('分步指导：注册流程')
  with self.s.db:
   self.s.db.execute('UPDATE sessions SET updated=updated-4000 WHERE id=?',(self.sid,))
  self.assertEqual(self.ask('下一步')['reason'],'clarification')
 def test_real_business_requests_and_handoff_are_not_captured_by_guide(self):
  self.ask('分步指导：客户充值流程')
  result=self.ask('我的余额是多少');self.assertEqual(result['reason'],'business_tool_unavailable');self.assertIsNone(result['guidance'])
  self.ask('分步指导：客户充值流程')
  self.assertEqual(self.ask('转人工客服')['status'],'handoff')
 def test_retrieval_failure_never_uses_hardcoded_step_answers(self):
  self.k.fail=True;result=self.ask('分步指导：企业认证流程')
  self.assertNotEqual(result['status'],'answered');self.assertIsNone(result['guidance']);self.assertEqual(result['images'],[])
 def test_revision_change_resets_to_first_stage(self):
  self.ask('分步指导：企业认证流程');self.ask('这一步已完成')
  for row in self.k.rows.values():
   if title_text(row['title'])=='企业认证流程':row['revision']='v6';row['content']=row['content'].replace('企业名称','企业名称（新说明）')
  result=self.ask('这一步怎么做');self.assertEqual(result['guidance']['step'],0);self.assertIn('已更新',result['guidance']['notice'])
 def test_deactivated_chapter_does_not_resume_stale_guide(self):
  self.ask('分步指导：企业认证流程')
  self.k.rows={key:row for key,row in self.k.rows.items() if title_text(row['title'])!='企业认证流程'}
  result=self.ask('下一步');self.assertIsNone(result['guidance']);self.assertEqual(result['reason'],'clarification')
 def test_authentication_ambiguity_and_choice_stay_in_current_knowledge(self):
  result=self.ask('认证失败');self.assertEqual(result['reason'],'clarification')
  titles={title_text(row['title']) for row in self.k.rows.values()}
  self.assertTrue(all(action['message'] in titles for action in result['actions']))
 def test_direct_flow_overview_can_exit_current_guidance(self):
  self.ask('分步指导：企业认证流程')
  result=self.ask('企业认证流程');self.assertIsNone(result['guidance']);self.assertEqual(result['reason'],'extractive')
 def test_model_receives_current_stage_and_stream_callback_not_extra_generation(self):
  from app.core import Model
  self.s.config.mode='llm';self.s.model=Model(self.config)
  calls=[]
  def complete(model,messages,on_delta=None):
   data=json.loads(messages[-1]['content']);calls.append(data)
   text='请按当前页面填写企业资料。'
   if on_delta:on_delta(text)
   return text
  stages=[]
  with patch.object(Model,'_complete_request',complete):
   result=self.s.chat(A,self.sid,{'message':'分步指导：企业认证流程','request_id':'v2-real-model-stream'},observer=stages.append)
  self.assertEqual(len(calls),1);self.assertEqual(calls[0]['guidance']['stage'],'完善企业资料')
  self.assertEqual(result['reason'],'guidance');self.assertTrue(any(item['type']=='delta' for item in stages))
 def test_guidance_state_cannot_be_supplied_by_browser(self):
  with self.assertRaises(APIError):self.s.chat(A,self.sid,{'message':'下一步','request_id':'v2-inject-state','guidance':{'step':100}})
