"""Registry migration and provider-independent policy regression contracts."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from app.business_flows import FLOWS,GUIDED_FLOWS,NEXT,QUICK_QUESTIONS,IMAGE_BINDINGS,load_registry
from app.conversation import MediaCatalog
from app.image_policy import ImagePolicy
from app.retrieval import title_signals,retrieval_text,TEXT_VERSION

ROOT=Path(__file__).resolve().parent.parent

class RegistryTests(unittest.TestCase):
 def test_guidance_and_quick_question_order_unchanged(self):
  keys=['register','verification','subscription','recharge','payment','invoice']
  self.assertEqual(list(GUIDED_FLOWS),keys)
  self.assertEqual(QUICK_QUESTIONS,['注册流程','企业认证流程','服务订购流程','客户充值流程','账单支付流程','在线开票流程'])
  self.assertEqual(NEXT,{k:keys[i+1:i+2] for i,k in enumerate(keys)})
  self.assertEqual(GUIDED_FLOWS['subscription']['stages'],[['选择服务与模型',[1]],['办理签约',[2,3]],['查看生效与服务开通',[4]]])
  self.assertEqual(len(FLOWS),10)
 def test_image_bindings_resolve_without_duplicated_catalog_metadata(self):
  raw=json.loads((ROOT/'data/media.json').read_text())
  self.assertTrue(all('flow_ids' not in r and 'flow_priority' not in r for r in raw))
  media=MediaCatalog(ROOT/'data/media.json',ROOT/'app/static/media')
  self.assertTrue(IMAGE_BINDINGS.keys()<=media.rows.keys())
  for key in FLOWS:
   row=media.rows['business-'+key]
   self.assertEqual(row['flow_ids'],[key]);self.assertEqual(row['flow_priority'],100)
  self.assertEqual(media.rows['enterprise-register']['flow_ids'],['register','verification'])
  self.assertEqual(media.rows['recharge-balance-flow']['flow_ids'],['recharge','payment'])
 def test_bad_registry_references_fail_early(self):
  original=json.loads((ROOT/'data/business_flows.json').read_text())
  for change in ('image','next','stage','alias'):
   data=copy.deepcopy(original)
   if change=='image':data['images']['business-register']['flow_ids']=['foreign']
   elif change=='next':data['flows']['register']['next']=['foreign']
   elif change=='stage':data['flows']['register']['stages'][0][1]=[0]
   else:data['flows']['register']['aliases']=[None]
   with tempfile.TemporaryDirectory() as temp:
    path=Path(temp)/'flows.json';path.write_text(json.dumps(data))
    with self.assertRaises(ValueError):load_registry(path)
 def test_retrieval_document_representation_is_unchanged(self):
  self.assertEqual(TEXT_VERSION,'retrieval-text-v2')
  self.assertEqual(retrieval_text({'title':'问题57 安装MetalLB负载均衡器','content':'安装步骤\n图片URL：https://example.com/a.png\n来源：用户手册'}),'安装MetalLB负载均衡器\n安装步骤')

class UnifiedPolicyTests(unittest.TestCase):
 def setUp(self):
  self.policy=ImagePolicy()
  self.candidates=[{'id':'sub','title':'订购图','url':'/media/sub.png','flow_ids':['subscription']},
                   {'id':'login','title':'登录图','url':'/media/login.png','flow_ids':['login']}]
  self.evidence=[{'id':'s','title':'服务订购流程','content':'选择套餐并提交。','image_ids':['sub']},
                 {'id':'l','title':'登录流程','content':'手机号登录。','image_ids':['login']}]
 def test_provider_contract_and_final_selector_are_shared(self):
  class Model:
   def complete(self,messages):
    # Sources no longer have to be chosen by the visual model.
    return json.dumps({'need_images':True,'reason':'full_procedure','flow_ids':['subscription'],'multiple_flows':False,'image_ids':[]})
  for mode,model in [('llm',Model()),('extractive',None)]:
   decision=self.policy.propose(mode,model,'注册完成后怎么订购','',[],self.evidence,self.candidates)
   chosen,log=self.policy.assemble(decision,self.candidates,self.evidence,self.evidence)
   self.assertEqual([r['id'] for r in chosen],['sub']);self.assertEqual(log['primary_flows'],['subscription'])
 def test_failed_semantic_provider_does_not_silently_fall_back(self):
  class Broken:
   def complete(self,messages):raise TimeoutError('planner unavailable')
  with self.assertRaises(TimeoutError):self.policy.propose('llm',Broken(),'如何订购服务','',[],self.evidence,self.candidates)
  self.assertEqual(self.policy.assemble(self.policy.unavailable(),self.candidates,self.evidence,self.evidence)[0],[])
 def test_legacy_adapter_uses_same_offline_contract(self):
  direct=self.policy.propose('extractive',None,'如何订购服务','',[],self.evidence,self.candidates)
  legacy=self.policy.propose('llm',object(),'如何订购服务','',[],self.evidence,self.candidates)
  self.assertEqual(direct,legacy)
 def test_offline_facts_followups_and_product_intro_have_no_images(self):
  for question in ('新注册客户默认是几星','预开票最高多少','28号后调整什么时候生效','这一步谁来处理','介绍一下平台产品'):
   decision=self.policy.propose('extractive',None,question,'',[],self.evidence,self.candidates)
   self.assertEqual(self.policy.assemble(decision,self.candidates,self.evidence,self.evidence)[0],[],question)
 def test_forged_decisions_cannot_bypass_shared_contract(self):
  decision=self.policy.unavailable();decision.update(need_images=True,reason='explicit_image',flow_ids=['invented'])
  with self.assertRaises(ValueError):self.policy.assemble(decision,self.candidates,self.evidence,self.evidence)

class TitlePolicyTests(unittest.TestCase):
 def test_generic_abbreviations_do_not_depend_on_product_names(self):
  for name,role in [('MetalLB','负载均衡器'),('Redis','缓存'),('Postgres','数据库'),('Nginx','服务器')]:
   for op in ('安装','部署','配置','升级','卸载'):
    title='问题57 附录-'+op+name+role
    for question in ('如何'+op+name,name+'怎么'+op):
     signal=title_signals(question,[title])[0]
     self.assertEqual(signal['kind'],'operation_product_alias',(question,title));self.assertTrue(signal['strong'])
 def test_related_mentions_never_become_strong_title_equivalence(self):
  titles=['安装MetalLB负载均衡器','配置MetalLB负载均衡器','安装MetalLBPro负载均衡器','MetalLB故障排查','快速部署－验证与访问']
  signals=title_signals('如何安装MetalLB',titles)
  self.assertEqual([i for i,r in enumerate(signals) if r['matched']],[0])
  for question in ('MetalLB','如何安装','如何安装Me'):
   self.assertFalse(any(r['strong'] for r in title_signals(question,titles)))
 def test_normalized_procedure_prefix_and_ties_keep_existing_priorities(self):
  cases=[('TITUHub概况',['问题10 第6页 TITU Hub 概况'],'normalized_title',3),
         ('企业注册与认证流程是什么',['企业注册与认证'],'procedure_title',2),
         ('安装MetalLB流程',['安装MetalLB负载均衡器'],'operation_product_alias',2),
         ('快速使用流程',['快速使用检查清单'],'related_prefix',1)]
  for question,titles,kind,strength in cases:
   signal=title_signals(question,titles)[0];self.assertEqual((signal['kind'],signal['strength']),(kind,strength))
  ties=title_signals('如何安装MetalLB',['安装MetalLB负载均衡器','附录-安装MetalLB负载均衡器'])
  self.assertEqual([r['matched'] for r in ties],[True,True])
