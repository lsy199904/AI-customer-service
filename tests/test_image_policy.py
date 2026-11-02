"""Visual policy contracts with controlled semantic decisions; no model-quality claims."""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.core import Service,Settings
from app.image_policy import select_images,semantic_decision,resource_key

SECRET='image-policy-test-secret-abcdefghijklmnopqrstuvwxyz'
ACTOR={'tenant_id':'company','sub':'user'}

def row(key,flow,content):
 return {'id':key,'title':{'subscription':'服务订购流程','login':'登录流程','rating':'星级评定流程',
         'register':'注册流程','verification':'企业认证流程','invoice':'在线开票流程'}[flow],
         'content':content,'image_ids':['business-'+flow],'source_file':'manual.docx','source_pages':[],
         'source_references':[],'version':'test'}

class Evidence:
 def __init__(self,rows):self.rows={r['id']:r for r in rows};self.calls=[]
 def assess(self,q):
  self.calls.append(q)
  return {'matched':True,'hits':[(.9,r,.8) for r in self.rows.values()],
          'method':'hybrid_rrf_rerank','similarity':.8,'threshold':.6}
 def get(self,key):return self.rows.get(key)

class AnswerAndDecision:
 def __init__(self,answer,decision):self.text=answer;self.decision=decision;self.plans=[];self.generated=[]
 def answer(self,q,history,evidence,context):
  self.generated.append((q,list(evidence)))
  if context.get('_on_delta'):context['_on_delta'](self.text)
  # Deliberately cite and nominate all: the assembler must not blindly attach them.
  return {'answerable':True,'answer':self.text,'citation_ids':[r['id'] for r in evidence],
          'image_ids':[m['id'] for m in context['_media']]}
 def complete(self,messages,on_delta=None):
  self.plans.append(json.loads(messages[-1]['content']))
  return json.dumps(self.decision)

class VisualWorkflowTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.config=Settings(mode='llm',model='test-model',model_key='test-only-key',retrieval_backend='lexical',secret=SECRET,db=str(Path(self.temp.name)/'chat.db'))
  self.s=Service(self.config);self.sid=self.s.create(ACTOR,{})['session_id'];self.number=0
  self.rows=[row('subscription','subscription','打开服务订购，选择套餐，确认并提交。'),
             row('login','login','输入手机号和验证码登录。'),row('rating','rating','新注册客户默认一星。')]
 def tearDown(self):self.s.close();self.temp.cleanup()
 def ask(self,question,flows,need=True,reason='full_procedure',sources=('subscription',),answer='打开服务订购，选择套餐，确认并提交。',multiple=False,rows=None):
  self.number+=1;self.s.knowledge=Evidence(rows or self.rows)
  decision={'need_images':need,'reason':reason,'flow_ids':flows,'multiple_flows':multiple,'image_ids':[],'source_ids':list(sources)}
  model=AnswerAndDecision(answer,decision);self.s.model=model;events=[]
  with patch('app.workflow.event') as logged:
   result=self.s.chat(ACTOR,self.sid,{'message':question,'request_id':'visual-%04d'%self.number},observer=events.append)
  self.assertEqual(len(model.generated[0][1]),3)  # All three retrieval records still reach generation.
  self.assertEqual(len(self.s.knowledge.calls),1)
  self.assertTrue(any(e['type']=='delta' for e in events))
  self.assertEqual(result['answer'],answer)
  metadata=next(c.kwargs for c in logged.call_args_list if c.args[0]=='image_selection_completed')
  for key in ('need_images','reason','primary_flows','candidates','selected_images','excluded_images'):self.assertIn(key,metadata)
  self.assertEqual(set(r['id'] for r in result['citations']),set(sources))
  self.assertEqual(model.plans[0]['question'],question);self.assertEqual(model.plans[0]['answer'],answer)
  return result,model,metadata
 def test_subscription_paraphrases_and_registration_as_background(self):
  for question in ('如何订购服务','怎么买套餐','注册完成后怎么订购','想开一个套餐，应该从哪里操作？'):
   with self.subTest(question=question):
    result,model,meta=self.ask(question,['subscription'])
    self.assertEqual([r['id'] for r in result['images']],['business-subscription'])
    self.assertTrue(any(r['id']=='business-login' and r['reason']=='not_supported_by_answer_sources' for r in meta['excluded_images']))
  # A login source may support a prerequisite sentence without requiring its diagram.
  result,_,meta=self.ask('注册完成后怎么订购',['subscription'],sources=('subscription','login'),
      answer='输入手机号和验证码登录，然后打开服务订购，选择套餐并提交。')
  self.assertEqual([r['id'] for r in result['images']],['business-subscription'])
  self.assertTrue(any(r['id']=='business-login' and r['reason']=='different_business_flow' for r in meta['excluded_images']))
 def test_explicit_multiple_processes_can_show_multiple_diagrams(self):
  rows=[row('register','register','填写注册资料并提交。'),row('verification','verification','补充企业资料并提交认证。'),self.rows[1]]
  result,_,_=self.ask('注册和企业认证分别怎么做',['register','verification'],multiple=True,
                      sources=('register','verification'),answer='填写注册资料并提交，然后补充企业资料并提交认证。',rows=rows)
  self.assertEqual([r['id'] for r in result['images']],['business-register','business-verification'])
 def test_factual_limits_and_effective_dates_have_sources_without_images(self):
  for question in ('新注册客户默认是几星','预开票最高多少','28号后调整什么时候生效'):
   result,_,_=self.ask(question,['rating'],need=False,reason='fact_only',sources=('rating',),answer='新注册客户默认一星。')
   self.assertEqual(result['images'],[]);self.assertTrue(result['citations'])
 def test_explicit_rating_diagram_is_shown(self):
  result,_,_=self.ask('给我看看星级评定流程图',['rating'],reason='explicit_image',sources=('rating',),answer='可以查看星级评定流程。')
  self.assertEqual([r['id'] for r in result['images']],['business-rating'])
 def test_local_followup_uses_context_without_repeating_diagram(self):
  first,_,_=self.ask('如何订购服务',['subscription'])
  result,model,_=self.ask('这一步谁来处理',['subscription'],need=False,reason='local_followup')
  self.assertEqual(result['images'],[])
  self.assertIn('如何订购服务',model.plans[0]['recent_user_questions'])
  history=self.s.history(ACTOR,self.sid)['items']
  self.assertEqual(history[-3]['response']['images'],first['images']);self.assertEqual(history[-1]['response']['images'],[])
  self.s.close();self.s=Service(self.config)
  # Reloading persisted history must not invoke the selector or rebuild images.
  with patch('app.image_policy.semantic_decision',side_effect=AssertionError('must use saved images')):
   history=self.s.history(ACTOR,self.sid)['items']
  self.assertEqual(history[-3]['response']['images'],first['images']);self.assertEqual(history[-1]['response']['images'],[])
 def test_product_overview_does_not_force_illustration(self):
  result,_,_=self.ask('介绍一下平台有哪些服务',[],need=False,reason='no_visual_need')
  self.assertEqual(result['images'],[])
 def test_shared_picture_in_multiple_records_is_shown_once(self):
  rows=[self.rows[0],{**self.rows[0],'id':'subscription2'},self.rows[1]]
  result,_,meta=self.ask('怎么买套餐',['subscription'],sources=('subscription','subscription2'),rows=rows)
  self.assertEqual([r['id'] for r in result['images']],['business-subscription'])
  self.assertEqual(len([r for r in meta['candidates'] if r['id']=='business-subscription']),1)
 def test_planner_error_preserves_answer_sources_and_does_not_attach(self):
  self.s.knowledge=Evidence(self.rows)
  self.s.model=AnswerAndDecision('订购套餐。',{})
  result=self.s.chat(ACTOR,self.sid,{'message':'如何订购服务','request_id':'visual-bad-json'})
  self.assertEqual(result['answer'],'订购套餐。');self.assertEqual(result['images'],[]);self.assertTrue(result['citations'])

 def test_extractive_explicit_flow_image_uses_same_selector(self):
  self.s.config.mode='extractive';self.s.knowledge=Evidence(self.rows)
  result=self.s.chat(ACTOR,self.sid,{'message':'给我看看星级评定流程图','request_id':'visual-extractive'})
  self.assertEqual([r['id'] for r in result['images']],['business-rating'])
  self.assertEqual([r['id'] for r in result['citations']],['rating'])

 def test_http_stream_and_history_share_saved_selected_images(self):
  from fastapi.testclient import TestClient
  from app.server import create_app
  from app.core import issue_token
  self.s.knowledge=Evidence(self.rows)
  decision={'need_images':True,'reason':'full_procedure','flow_ids':['subscription'],'multiple_flows':False,'image_ids':[],'source_ids':['subscription']}
  self.s.model=AnswerAndDecision('打开服务订购，选择套餐，确认并提交。',decision)
  headers={'Authorization':'Bearer '+issue_token(SECRET,ACTOR['tenant_id'],ACTOR['sub'])}
  with TestClient(create_app(self.config,service=self.s)) as client:
   response=client.post('/v1/sessions/'+self.sid+'/messages/stream',headers=headers,json={'message':'怎么买套餐','request_id':'visual-http-stream'})
   self.assertEqual(response.status_code,200)
   frames=[]
   for block in response.text.split('\n\n'):
    if block.startswith('event: '):
     kind,data=block.split('\ndata: ',1);frames.append((kind[7:],json.loads(data)))
   result=next(data for kind,data in frames if kind=='complete')
   self.assertEqual(''.join(data['text'] for kind,data in frames if kind=='delta'),result['answer'])
   self.assertEqual([r['id'] for r in result['images']],['business-subscription'])
   history=client.get('/v1/sessions/'+self.sid+'/messages',headers=headers).json()
   self.assertEqual(history['items'][-1]['response']['images'],result['images'])

class VisualSelectorTests(unittest.TestCase):
 def image(self,key,flow,url=None,priority=100):return {'id':key,'url':url or '/media/'+key+'.png','flow_ids':[flow],'flow_priority':priority,'title':key}
 def decision(self,flows=('subscription',),**kw):return {'need_images':True,'reason':'full_procedure','flow_ids':list(flows),'multiple_flows':False,'image_ids':[],**kw}
 def test_resource_url_deduplicated_across_distinct_ids_and_flows(self):
  images=[self.image('one','register','https://example.com/shared.png#first'),self.image('two','verification','https://example.com/shared.png#second')]
  e=[{'id':'r','image_ids':['one','two']}]
  chosen,log=select_images(self.decision(('register','verification'),multiple_flows=True),images,e,e)
  self.assertEqual(len(chosen),1);self.assertEqual(log['excluded_images'][0]['reason'],'duplicate_resource')
 def test_metadata_prefers_dedicated_diagram_without_rerank_order(self):
  images=[self.image('legacy','subscription',priority=10),self.image('modern','subscription')]
  e=[{'id':'r','image_ids':['legacy','modern']}]
  chosen,_=select_images(self.decision(),images,e,e)
  self.assertEqual([r['id'] for r in chosen],['modern'])
 def test_ambiguous_multiple_flow_request_is_not_guessed(self):
  image=self.image('x','subscription');e=[{'id':'r','image_ids':['x']}]
  chosen,log=select_images(self.decision(('subscription','login')),[image],e,e)
  self.assertEqual(chosen,[]);self.assertEqual(log['reason'],'ambiguous')
 def test_fact_and_local_decisions_cannot_accidentally_enable_images(self):
  for reason in ('fact_only','local_followup','no_visual_need','planning_unavailable'):
   image=self.image('x','rating');e=[{'id':'r','image_ids':['x']}]
   self.assertEqual(select_images(self.decision(('rating',),reason=reason),[image],e,e)[0],[])
 def test_untrusted_ids_and_flow_names_are_rejected(self):
  class Model:
   def complete(self,*args):return json.dumps({'need_images':True,'reason':'explicit_image','multiple_flows':False,'flow_ids':['unknown'],'image_ids':['invented'],'source_ids':['foreign']})
  with self.assertRaises(ValueError):semantic_decision(Model(),'看图','答案',[],[],[])
 def test_no_keyword_only_model_prompt_contains_answer_context_and_candidates(self):
  class Model:
   def complete(me,messages):
    payload=json.loads(messages[-1]['content'])
    self.assertEqual(payload['recent_user_questions'],['怎么买套餐'])
    self.assertEqual(payload['answer'],'先选择套餐。')
    self.assertTrue(payload['candidate_images']);self.assertIn('注册完成后怎么订购',messages[0]['content'])
    return json.dumps({'need_images':False,'reason':'local_followup','flow_ids':['subscription'],'multiple_flows':False,'image_ids':[],'source_ids':['r']})
  result=semantic_decision(Model(),'这一步谁处理','先选择套餐。',[{'role':'user','content':'怎么买套餐'}],
       [{'id':'r','title':'服务订购流程','content':'先选择套餐。'}],[self.image('x','subscription')])
  self.assertEqual(result['reason'],'local_followup')
