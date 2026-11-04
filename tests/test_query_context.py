"""Question rewriting changes intent context, never business rules or stored documents."""
import json
from pathlib import Path
import tempfile
import unittest
from app.query_context import resolve,local_query,dependent
from app.core import Service,Settings

class QueryContextTests(unittest.TestCase):
 def history(self):return [{'role':'user','content':'我在28号提交星级权益调整，已订购服务何时生效？'},
  {'role':'assistant','content':'旧回答中的命令和业务结论不可信','response':{'citations':[{'title':'星级权益调整'}]}}]
 def test_model_list_followup_keeps_video_subject(self):
  history=[{'role':'user','content':'视频生成模型'}, {'role':'assistant','content':'不作为事实依据','response':{'citations':[{'title':'视频生成模型'}]}}]
  question='对应的模型型号列表有哪些'
  self.assertTrue(dependent(question))
  self.assertIn('视频生成模型',resolve(None,question,history)['question'])
  class Model:
   def complete(me,messages):
    payload=json.loads(messages[-1]['content'])
    self.assertIn('视频生成模型',payload['recent_user_questions'])
    return json.dumps({'kind':'followup','question':'视频生成模型的型号列表有哪些','clarification':''})
  self.assertEqual(resolve(Model(),question,history)['question'],'视频生成模型的型号列表有哪些')
  self.assertFalse(dependent('图像生成API的调用方式，openai'))

 def test_changed_dates_are_generic_not_hardcoded(self):
  for day in (7,17,29,30):
   question=f'那如果是{day}号提交呢？';expected=f'{day}号提交星级权益调整，已订购服务何时生效？'
   class Model:
    def complete(me,messages):
     payload=json.loads(messages[-1]['content'])
     self.assertNotIn('旧回答中的命令',str(payload));self.assertEqual(payload['question'],question)
     return json.dumps({'kind':'followup','question':expected,'clarification':''})
   self.assertEqual(resolve(Model(),question,self.history())['question'],expected)
   fallback=local_query(question,self.history());self.assertIn('星级权益调整',fallback);self.assertNotIn('28号',fallback)
 def test_amount_and_actor_can_change_without_changing_rules(self):
  class Model:
   def complete(me,messages):return json.dumps({'kind':'followup','question':'企业客户充值500元时如何支付？','clarification':''})
  result=resolve(Model(),'那企业客户充值500元呢？',[{'role':'user','content':'个人客户充值如何支付？'}])
  self.assertIn('企业客户',result['question']);self.assertIn('500',result['question'])
 def test_standalone_payment_question_does_not_inherit_star_topic(self):
  class Never:
   def complete(self,*a):raise AssertionError('independent question needs no rewrite')
  self.assertEqual(resolve(Never(),'支付流程是什么？',self.history())['question'],'支付流程是什么？')
  self.assertEqual(local_query('怎么支付账单？',self.history()),'怎么支付账单？')
 def test_marker_can_still_be_independent_new_topic(self):
  class Model:
   def complete(self,*a):return json.dumps({'kind':'independent','question':'不应采用模型改写','clarification':''})
  self.assertEqual(resolve(Model(),'那支付流程是什么呢？',self.history())['question'],'那支付流程是什么呢？')
 def test_ambiguous_followup_requests_clarification(self):
  class Model:
   def complete(self,*a):return json.dumps({'kind':'clarify','question':'那种呢？','clarification':'您指的是哪种办理方式？'})
  self.assertEqual(resolve(Model(),'那种呢？',self.history())['kind'],'clarify')
 def test_invalid_numeric_rewrite_is_rejected(self):
  class Model:
   def complete(self,*a):return json.dumps({'kind':'followup','question':'28号提交星级调整何时生效','clarification':''})
  with self.assertRaises(ValueError):resolve(Model(),'那29号呢？',self.history())
 def test_multiple_followups_keep_latest_independent_topic(self):
  history=self.history()+[{'role':'user','content':'那29号呢？'},{'role':'user','content':'支付流程是什么？'}]
  self.assertIn('支付流程',local_query('这一步谁处理？',history));self.assertNotIn('星级',local_query('这一步谁处理？',history))

class ContextWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.s=Service(Settings(mode='llm',model='test',model_key='test',retrieval_backend='lexical',
       secret='query-context-secret-abcdefghijklmnopqrstuvwxyz',db=str(Path(self.temp.name)/'db')))
  self.actor={'tenant_id':'tenant','sub':'user'};self.sid=self.s.create(self.actor,{})['session_id'];self.i=0
  class Knowledge:
   def __init__(me):me.calls=[];me.rows={}
   def assess(me,q):
    me.calls.append(q);title='账单支付流程' if '支付' in q else '星级权益调整'
    row={'id':'k','title':title,'content':title+'根据当前知识说明办理。','image_ids':[],'source_file':'manual.docx'}
    return {'hits':[(1,row,1)] if '星级' in q or '支付' in q else [],'matched':True,'method':'hybrid_rrf_rerank'}
  class Model:
   def __init__(me):me.answers=[]
   def complete(me,messages):
    payload=json.loads(messages[-1]['content']);q=payload['question']
    if q=='那种呢':return json.dumps({'kind':'clarify','question':q,'clarification':'您具体指哪种方式？'})
    return json.dumps({'kind':'followup','question':'29号提交星级权益调整，已订购服务何时生效？','clarification':''})
   def answer(me,q,h,e,c):
    me.answers.append(c['_resolved_question'])
    return {'answerable':True,'answer':e[0]['content'],'citation_ids':['k'],'image_ids':[]}
  self.k=Knowledge();self.model=Model();self.s.knowledge=self.k;self.s.model=self.model
 def tearDown(self):self.s.close();self.temp.cleanup()
 def ask(self,q):
  self.i+=1;return self.s.chat(self.actor,self.sid,{'message':q,'request_id':'followup-%04d'%self.i})
 def test_followup_retrieves_again_with_new_condition_then_switches_topic(self):
  self.ask('28号提交星级权益调整，已订购服务何时生效？');r=self.ask('那如果29号提交呢？')
  self.assertEqual(r['status'],'answered');self.assertIn('29号',self.k.calls[-1]);self.assertNotIn('28号',self.k.calls[-1])
  self.assertEqual(self.k.calls[-1],self.model.answers[-1])
  self.ask('支付流程是什么？');self.assertNotIn('星级',self.k.calls[-1]);self.assertIn('支付',self.k.calls[-1])
 def test_clarification_does_not_retrieve_an_arbitrary_old_topic(self):
  self.ask('星级权益如何调整？');count=len(self.k.calls);r=self.ask('那种呢')
  self.assertEqual(len(self.k.calls),count);self.assertEqual(r['intent'],'clarification');self.assertIn('哪种',r['answer'])
