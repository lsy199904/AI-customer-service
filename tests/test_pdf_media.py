"""Real local OCR/QR tests plus isolated publication and streaming contracts.

No remote chat model, embedding service, production DB or QR destination is used.
"""
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.ingestion import parse_document
from app.pdf_media import (extract,catalog,classify,analyze_image,asset_id,purpose_of,
                          safe_qr_url,generation_evidence,reserved_qr,atomic_json)
from app.conversation import MediaCatalog
from app.core import Service,Settings
from tests.test_image_policy import Evidence,ACTOR,SECRET

ROOT=Path(__file__).resolve().parent.parent

class MediaPolicyTests(unittest.TestCase):
 def test_unknown_never_auto_retained_and_small_decoration_is_excluded(self):
  self.assertEqual(classify('',600,400)[1],'review')
  self.assertEqual(classify('',40,40)[1:],('excluded','small_resource'))
  self.assertEqual(classify('Certificate 评估证书',600,400)[0:2],('certificate','retained'))
  self.assertEqual(classify('Token运营管理 多模型统一接入 计量计费 '+'框架说明'*10,600,400,rectangles=8)[0:2],('diagram','retained'))
  self.assertEqual(classify('视频封面',1600,900,'观看视频')[0:2],('video_cover','excluded'))
 def test_qr_purpose_comes_from_label_and_payload_is_not_executed(self):
  self.assertEqual(purpose_of('扫码申请免费 POC'),'trial');self.assertEqual(purpose_of('欢迎访问官方网站'),'website')
  self.assertIsNone(purpose_of('未知图案'))
  for url in ['javascript:alert(1)','file:///etc/passwd','https://user:pass@example.com/']:self.assertFalse(safe_qr_url(url))
  self.assertTrue(safe_qr_url('https://example.com/form'))
 def test_qr_crop_deduplication_and_unknown_purpose(self):
  import cv2,numpy as np
  qr=cv2.QRCodeEncoder_create().encode('https://example.com/request')
  qr=cv2.copyMakeBorder(qr,4,4,4,4,cv2.BORDER_CONSTANT,value=255)
  qr=cv2.cvtColor(cv2.resize(qr,None,fx=8,fy=8,interpolation=cv2.INTER_NEAREST),cv2.COLOR_GRAY2BGR)
  with patch('app.pdf_media.ocr_image',return_value=[]):
   results=analyze_image(qr,'扫码申请免费POC')
   code=next(r for r in results if r['kind']=='qr')
   self.assertEqual((code['status'],code['purpose']),('retained','trial'))
   pending=next(r for r in analyze_image(qr,'') if r['kind']=='qr')
   self.assertEqual(pending['status'],'review')
 def test_unavailable_scan_instructions_are_not_fed_into_generation(self):
  rows=[{'id':'x','content':'已知安全方案。\n扫描二维码申请。\n联系电话：123','image_evidence':'扫码申请免费POC\n私有化部署'}]
  safe=generation_evidence(rows,False)
  self.assertNotIn('扫码',safe[0]['image_evidence']);self.assertNotIn('扫描',safe[0]['content'])
  self.assertIn('联系电话',safe[0]['content']);self.assertIn('扫码',rows[0]['image_evidence'])
  self.assertEqual(generation_evidence(rows,True),rows)

class RealPDFMediaTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.temp=tempfile.TemporaryDirectory();cls.root=Path(cls.temp.name);cls.parsed={};cls.reports={}
  for path in sorted((ROOT/'knowledge_sources').glob('*.pdf')):
   value,report=extract(path,parse_document(path),cls.root)
   cls.parsed[path.name]=value;cls.reports[path.name]=report
 @classmethod
 def tearDownClass(cls):cls.temp.cleanup()
 def test_three_actual_pdfs_retain_qr_certificate_diagram_and_reject_related(self):
  for report in self.reports.values():self.assertEqual(len({r['id'] for r in report['assets']}),len(report['assets']))
  assets=[r for report in self.reports.values() for r in report['assets']]
  retained=[r for r in assets if r['status']=='retained']
  self.assertTrue(any(r['kind']=='qr' and r['purpose']=='trial' for r in retained))
  self.assertTrue(any(r['kind']=='qr' and r['purpose']=='website' for r in retained))
  self.assertTrue(any(r['kind']=='certificate' for r in retained))
  self.assertTrue(any(r['kind']=='diagram' for r in retained))
  self.assertTrue(any(r['status']=='excluded' and r['reason']=='after_article_recommendations' for r in assets))
  self.assertTrue(any(r['status']=='review' for r in assets))
 def test_cache_reuses_analysis_and_original_bytes_remain_unchanged(self):
  path=next((ROOT/'knowledge_sources').glob('企业*.pdf'));before=path.read_bytes()
  with patch('app.pdf_media.ocr_image',side_effect=AssertionError('should reuse report')) as mocked:
   parsed,report=extract(path,parse_document(path),self.root)
  mocked.assert_not_called()
  self.assertEqual(path.read_bytes(),before);self.assertEqual(parsed.raw,before)
  self.assertTrue(all((self.root/'assets'/(r['id']+'.png')).is_file() for r in report['assets']))
 def test_only_retained_assets_are_served_and_ambiguous_assets_are_not(self):
  rows=catalog(self.root);ids={r['id'] for r in rows}
  for report in self.reports.values():
   for asset in report['assets']:
    if asset['status']=='review':self.assertNotIn(asset['id'],ids)
  self.assertTrue(all(r['url']=='/media/'+r['id']+'.png' for r in rows))
 def test_qr_is_its_own_action_topic_not_attached_to_all_business_topics(self):
  parsed=next(v for k,v in self.parsed.items() if '五大' in k)
  trial=next(c for c in parsed.chunks if c.get('media_action')=='trial')
  private=next(c for c in parsed.chunks if c['title']=='私有化部署')
  qr=next(r for r in catalog(self.root) if r.get('purpose')=='trial')
  self.assertIn(qr['id'],trial['image_ids']);self.assertNotIn(qr['id'],private['image_ids'])
  self.assertIn('POC',trial['content']);self.assertEqual(trial['source_kind'],'wechat')
 def test_task_qr_streams_and_history_matches_without_a_second_model_call(self):
  with tempfile.TemporaryDirectory() as temp:
   config=Settings(mode='llm',model='test-model',model_key='test-key',secret=SECRET,retrieval_backend='lexical',db=str(Path(temp)/'chat.db'),pdf_media_dir=str(self.root))
   service=Service(config)
   try:
    parsed=next(v for k,v in self.parsed.items() if '五大' in k)
    trial=next(c for c in parsed.chunks if c.get('media_action')=='trial')
    evidence={**trial,'id':'trial-record','revision':'r','source_file':parsed.filename}
    service.knowledge=Evidence([evidence]);sid=service.create(ACTOR,{})['session_id'];events=[]
    class Model:
     def complete(self,*a,**kw):raise AssertionError('no late or parallel classifier needed for reserved QR')
     def answer(self,q,h,e,c):
      assert c['_reserved_qr'];text='可以使用下方试用申请二维码查看原文提供的入口。'
      for piece in ['可以使用下方','试用申请二维码','查看原文提供的入口。']:c['_on_delta'](piece)
      return {'answerable':True,'answer':text,'citation_ids':['trial-record'],'image_ids':[]}
    service.model=Model();result=service.chat(ACTOR,sid,{'message':'如何申请免费POC试用？','request_id':'pdf-qr-stream-test'},observer=events.append)
    self.assertEqual(result['status'],'answered');self.assertEqual(len(result['images']),1)
    self.assertEqual(''.join(e['text'] for e in events if e['type']=='delta'),result['answer'])
    self.assertEqual(service.history(ACTOR,sid)['items'][-1]['response']['images'],result['images'])
    from fastapi.testclient import TestClient
    from app.server import create_app
    with TestClient(create_app(config,service=service)) as client:
     response=client.get(result['images'][0]['url']);self.assertEqual(response.status_code,200)
     self.assertTrue(response.content.startswith(b'\x89PNG'))
     self.assertEqual(client.get('/media/pdf-unknown.png').status_code,404)
    service.close();service=Service(config)
    self.assertEqual(service.history(ACTOR,sid)['items'][-1]['response']['images'],result['images'])
   finally:service.close()
 def test_catalog_never_resurrects_old_generated_qr_without_active_evidence(self):
  media=MediaCatalog(ROOT/'data/media.json',ROOT/'app/static/media');media.include_generated(self.root)
  self.assertEqual(media.candidates('给我试用二维码图片',[]),[])
 def test_plain_business_question_does_not_reserve_trial_qr(self):
  rows=catalog(self.root)
  self.assertIsNone(reserved_qr('对数据安全要求特别高，有什么方案？',rows))
  self.assertIsNone(reserved_qr('是否支持免费试用？',rows))
  self.assertIsNotNone(reserved_qr('免费POC怎么申请？',rows))
