"""Customer portal SOP supersedes old registration/order flow descriptions."""
import unittest,re
from pathlib import Path
from app.ingestion import parse_document
from app.assistance import available,guide_state,stage_context,actions_for
ROOT=Path(__file__).resolve().parents[1]
class CustomerSOPAlignmentTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.rows=parse_document(ROOT/'knowledge_sources/SmartTITU客户问答.docx').chunks
  cls.by={int(re.match(r'问题(\d+)',r['title'])[1]):r for r in cls.rows if re.match(r'问题(\d+)',r['title'])}
 def test_register_and_login_use_phone_not_old_email_or_esp_login(self):
  self.assertIn('邮箱(选填)',self.by[4]['content'])
  self.assertIn('短信验证码',self.by[4]['content'])
  self.assertNotIn('旧ESP',self.by[5]['content'])
  self.assertIn('密码登录填写手机号和密码',self.by[5]['content'])
  self.assertIn('【总览】',self.by[5]['content'])
 def test_verification_is_customer_esign_authorization_not_internal_crm_review(self):
  text=self.by[6]['content']
  for term in ['统一社会信用代码','公司地址','【去认证】','【登录并授权】','管理员审批','认证中','已认证']:self.assertIn(term,text)
  for term in ['CRM','风险名单','实际控制人','推荐客户经理','线下认证']:self.assertNotIn(term,text)
 def test_contract_precedes_subscription_and_failure_is_not_offline_fallback(self):
  self.assertIn('企业认证与签约均已完成',self.by[8]['content'])
  self.assertIn('甲方、乙方、模板、经办人手机号',self.by[7]['content'])
  self.assertIn('仍须办理服务订购',self.by[7]['content'])
  self.assertNotIn('失败时,转客户经理',self.by[7]['content'])
  self.assertIn('仅能订购1个服务',self.by[8]['content'])
  self.assertIn('【全选含后续新增】',self.by[40]['content'])
  self.assertNotIn('预付款金额生成协议',self.by[40]['content'])
 def test_duplicate_topics_removed_without_losing_password_recovery_or_api_key(self):
  for n in [348,349,350,351,352]:self.assertNotIn(n,self.by)
  self.assertIn('6位短信验证码',self.by[308]['content'])
  self.assertNotIn('垃圾邮件箱',self.by[308]['content'])
  self.assertIn('订购服务',self.by[353]['content'])
  self.assertNotIn('完成标志:合同状态显示',self.by[310]['content'])
 def test_guide_stages_follow_sop_and_verification_links_to_contract(self):
  options=available(self.rows)
  guide=guide_state('verification',1,options['verification'])
  self.assertIn('e签宝',stage_context(guide,self.rows)['stage_evidence'])
  completed=guide_state('verification',3,options['verification'],status='completed')
  self.assertEqual(actions_for(completed,self.rows)[0]['message'],'在线签约流程')
  stage=guide_state('subscription',1,options['subscription'])
  context=stage_context(stage,self.rows)
  self.assertIn('供应商',context['stage_evidence'])
  self.assertNotIn('跳转e签宝',context['stage_evidence'])
 def test_flow_sources_and_star_dates_remain_available(self):
  for n in [4,5,6,7,8,40]:self.assertTrue(self.by[n]['source_references'])
  for term in ['28号(含)前','次月1日','隔月1日']:self.assertIn(term,self.by[9]['content'])
  for key in ['register','login','verification','contract','subscription','rating']:
   self.assertTrue((ROOT/f'docs/diagrams/business-{key}.svg').is_file())
 def test_word_embedded_diagrams_equal_deployed_assets(self):
  import zipfile,xml.etree.ElementTree as ET,posixpath
  ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main','a':'http://schemas.openxmlformats.org/drawingml/2006/main'}
  mapping={4:'register',5:'login',6:'verification',7:'contract',8:'subscription',9:'rating'}
  with zipfile.ZipFile(ROOT/'knowledge_sources/SmartTITU客户问答.docx') as z:
   rels={r.attrib['Id']:r.attrib['Target'] for r in ET.fromstring(z.read('word/_rels/document.xml.rels'))}
   current=None;checked=set()
   for el in ET.fromstring(z.read('word/document.xml')).find('w:body',ns):
    text=''.join(t.text or '' for t in el.findall('.//w:t',ns));m=re.match(r'^问题(\d+) ',text)
    if m:current=int(m[1])
    if current not in mapping:continue
    for blip in el.findall('.//a:blip',ns):
     key=blip.attrib['{http://schemas.openxmlformats.org/officeDocument/2006/relationships}embed']
     member=posixpath.normpath('word/'+rels[key])
     self.assertEqual(z.read(member),(ROOT/f'app/static/media/business-{mapping[current]}.png').read_bytes())
     checked.add(current)
   self.assertEqual(checked,set(mapping))
