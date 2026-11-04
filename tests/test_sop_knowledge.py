"""Customer SOP coverage and internal/public boundaries, without reading private originals."""
import json
from pathlib import Path
import re
import unittest
import xml.etree.ElementTree as ET
import zipfile
from app.ingestion import parse_document
ROOT=Path(__file__).resolve().parents[1]
PATH=ROOT/'knowledge_sources/SmartTITU客户问答.docx'
def word_question_blocks(path):
 ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
 with zipfile.ZipFile(path) as z:body=ET.fromstring(z.read('word/document.xml')).find('w:body',ns)
 result={};current=None
 for el in body:
  text=''.join(t.text or '' for t in el.findall('.//w:t',ns))
  m=re.match(r'^问题(\d+) ',text)
  if m:current=m[1];result[current]=[]
  elif el.tag.endswith('}p'):
   style=el.find('w:pPr/w:pStyle',ns)
   if style is not None and style.get('{'+ns['w']+'}val')=='Heading1':current=None
  if current:
   embeds=[v for t in el.iter() for k,v in t.attrib.items() if k.endswith('}embed')]
   result[current].append([text,embeds])
 return result

class SOPKnowledgeTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.rows=parse_document(PATH).chunks
  cls.by={}
  for row in cls.rows:
   match=re.match(r'问题(\d+)',row['title'])
   if match:cls.by.setdefault(int(match[1]),[]).append(row)
 def body(self,n):return '\n'.join(r['content'] for r in self.by[n])
 def test_unique_questions_and_every_new_topic_has_sources(self):
  self.assertEqual(set(self.by),set(range(1,354))-{348,349,350,351,352})
  ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
  with zipfile.ZipFile(PATH) as z:xml=ET.fromstring(z.read('word/document.xml'))
  headings=[''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in xml.findall('.//w:body/w:p',ns)]
  titles=[t for t in headings if re.match(r'^问题\d+ ',t)]
  self.assertEqual(len(titles),348)
  new=[re.sub(r'^问题\d+ ','',r['title']) for r in self.rows if (m:=re.match(r'问题(\d+)',r['title'])) and int(m[1])>=306]
  self.assertEqual(len(set(new)),43)
  for number in sorted(set(range(306,354))-{348,349,350,351,352}):
   for row in self.by[number]:self.assertTrue(row['source_references']);self.assertTrue(row['content'])
 def test_original_questions_are_preserved_except_authorized_editorial_changes(self):
  import hashlib
  coverage=json.loads((ROOT/'docs/sop-coverage-20261104.json').read_text())
  blocks=word_question_blocks(PATH)
  for n in range(1,306):
   if n in coverage['authorized_editorial_questions']:continue
   digest=hashlib.sha256(json.dumps(blocks[str(n)],ensure_ascii=False).encode()).hexdigest()
   self.assertEqual(digest,coverage['original_word_questions_sha256'][str(n)],f'original question {n} changed')
 def test_duplicate_login_and_authentication_topics_are_removed(self):
  self.assertNotIn(349,self.by);self.assertNotIn(350,self.by)
  self.assertIn(5,self.by);self.assertIn(6,self.by)
  self.assertNotIn(348,self.by);self.assertNotIn(351,self.by);self.assertNotIn(352,self.by)
 def test_new_portal_topics_have_enterprise_sources_only(self):
  for n in sorted(set(range(306,354))-{348,349,350,351,352}):
   self.assertNotIn('运营门户',self.body(n))
   for row in self.by[n]:
    self.assertIn('企业服务门户',str(row['source_references']))
    self.assertNotIn('运营门户',str(row['source_references']))
  self.assertIn('短信验证码',self.body(4))
  self.assertIn('创建 API Key',self.by[353][0]['title'])
 def test_payment_invoicing_and_errors_are_covered_with_payer_context(self):
  text='\n'.join(r['title']+'\n'+r['content'] for r in self.rows)
  for term in ['中信银行','对公汇款','代付协议','支付有效期','OFD、PDF、XML','专用发票仅支持企业单位抬头','已申请或已开票','信用额度相应恢复','模板、经办人手机号','重新签署','未完成用印审批']:
   self.assertIn(term,text)
  self.assertIn('未查明原支付结果前',text)
 def test_customer_word_does_not_contain_internal_control_procedures_or_uat(self):
  text='\n'.join(self.body(n) for n in sorted(set(range(306,354))-{348,349,350,351,352}))
  for term in ['101.96.235','CASH','Re-Rate','API重采','账期补采','3%','账期审核通过']:
   self.assertNotIn(term,text)
  self.assertNotIn('垃圾邮件箱',text)
 def test_original_flow_images_and_manual_center_remain_available(self):
  for n,key in [(4,'business-register'),(5,'business-login'),(6,'business-verification'),(7,'business-contract'),(8,'business-subscription'),(9,'business-rating'),(10,'business-delivery'),(11,'business-recharge'),(12,'business-payment'),(13,'business-invoice')]:
   self.assertTrue(any(key in r['image_ids'] for r in self.by[n]))
  coverage=json.loads((ROOT/'docs/manual-center-coverage.json').read_text())
  text='\n'.join(r['content'] for r in self.rows)
  for item in coverage:self.assertIn(item['url'],text)

 def test_ingestion_is_idempotent_and_word_is_downloadable(self):
  import tempfile,shutil
  from app.rag import RAGSettings,DocumentStore,ingest_documents
  class Embed:
   def __init__(self):self.count=0
   def embed(self,texts):self.count+=len(texts);return [[1.,2.,3.] for _ in texts]
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);source=root/'sources';source.mkdir();shutil.copyfile(PATH,source/PATH.name)
   cfg=RAGSettings(index_path=str(root/'index.db'),source_dir=str(source),database_url='',vector_backend='sqlite',pdf_media_enabled=False,rerank_enabled=False,http_origins=('http://127.0.0.1:11434',))
   model=Embed();first=ingest_documents(cfg,embedder=model)
   self.assertEqual(first['chunks'],len(self.rows));self.assertEqual(first['updated'],1)
   before=model.count;second=ingest_documents(cfg,embedder=model)
   self.assertEqual((second['updated'],second['unchanged']),(0,1));self.assertEqual(model.count,before)
   row=first['documents'][0];store=DocumentStore(cfg.index_path,'')
   self.assertEqual(store.download(row['id'],row['current_revision'])[1],PATH.read_bytes())
