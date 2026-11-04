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
class SOPKnowledgeTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.rows=parse_document(PATH).chunks
  cls.by={}
  for row in cls.rows:
   match=re.match(r'问题(\d+)',row['title'])
   if match:cls.by.setdefault(int(match[1]),[]).append(row)
 def body(self,n):return '\n'.join(r['content'] for r in self.by[n])
 def test_contiguous_unique_questions_and_every_new_topic_has_sources(self):
  self.assertEqual(set(self.by),set(range(1,354)))
  ns={'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main'}
  with zipfile.ZipFile(PATH) as z:xml=ET.fromstring(z.read('word/document.xml'))
  headings=[''.join(t.text or '' for t in p.findall('.//w:t',ns)) for p in xml.findall('.//w:body/w:p',ns)]
  titles=[t for t in headings if re.match(r'^问题\d+ ',t)]
  self.assertEqual(len(titles),353)
  new=[re.sub(r'^问题\d+ ','',r['title']) for r in self.rows if (m:=re.match(r'问题(\d+)',r['title'])) and int(m[1])>=306]
  self.assertEqual(len(set(new)),48)
  for number in range(306,354):
   for row in self.by[number]:self.assertTrue(row['source_references']);self.assertTrue(row['content'])
 def test_original_questions_are_restored_without_sop_merges(self):
  import hashlib
  coverage=json.loads((ROOT/'docs/sop-coverage-20261104.json').read_text())
  self.assertEqual(coverage['updated_questions'],[])
  for n in range(1,306):
   data=[{k:r.get(k) for k in ['title','content','image_ids','source_references']} for r in self.by[n]]
   digest=hashlib.sha256(json.dumps(data,ensure_ascii=False,sort_keys=True).encode()).hexdigest()
   self.assertEqual(digest,coverage['original_questions_sha256'][str(n)],f'original question {n} changed')
 def test_new_portal_topics_have_enterprise_sources_only(self):
  for n in range(306,354):
   self.assertNotIn('运营门户',self.body(n))
   for row in self.by[n]:
    self.assertIn('企业服务门户',str(row['source_references']))
    self.assertNotIn('运营门户',str(row['source_references']))
  self.assertIn('注册账号',self.by[348][0]['title'])
  self.assertIn('创建 API Key',self.by[353][0]['title'])
 def test_payment_invoicing_and_errors_are_covered_with_payer_context(self):
  text='\n'.join(r['title']+'\n'+r['content'] for r in self.rows)
  for term in ['中信银行','对公汇款','代付协议','支付有效期','OFD、PDF、XML','专用发票仅支持企业单位抬头','已申请或已开票','信用额度相应恢复','模板、经办人手机号','重新签署','未完成用印审批']:
   self.assertIn(term,text)
  self.assertIn('未查明原支付结果前',text)
 def test_customer_word_does_not_contain_internal_control_procedures_or_uat(self):
  text='\n'.join(self.body(n) for n in range(306,354))
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
   self.assertEqual(first['chunks'],374);self.assertEqual(first['updated'],1)
   before=model.count;second=ingest_documents(cfg,embedder=model)
   self.assertEqual((second['updated'],second['unchanged']),(0,1));self.assertEqual(model.count,before)
   row=first['documents'][0];store=DocumentStore(cfg.index_path,'')
   self.assertEqual(store.download(row['id'],row['current_revision'])[1],PATH.read_bytes())
