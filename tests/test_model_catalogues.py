"""Complete source model inventories and subject-preserving followups."""
import json,re,unittest
from pathlib import Path
from app.ingestion import parse_document
from app.query_context import resolve
from app.retrieval import title_signals
ROOT=Path(__file__).resolve().parents[1]

class ModelCatalogueTests(unittest.TestCase):
 @classmethod
 def setUpClass(cls):
  cls.catalogues=json.loads((ROOT/'docs/model-catalogue-coverage-20261104.json').read_text())
  cls.rows=parse_document(ROOT/'knowledge_sources/SmartTITU客户问答.docx').chunks
 def test_every_source_id_and_name_is_in_one_complete_catalogue(self):
  for item in self.catalogues:
   with self.subTest(title=item['title']):
    chunks=[r for r in self.rows if r['title'].startswith('问题'+str(item['question'])+' ')]
    self.assertEqual(len(chunks),1)
    self.assertEqual(sum(len(s['rows']) for s in item['sections']),item['count'])
    for section in item['sections']:
     if section['channel']:self.assertIn(section['channel'],chunks[0]['content'])
     for row in section['rows']:
      self.assertIn(row[0],chunks[0]['content']);self.assertIn(row[1],chunks[0]['content'])
 def test_no_old_video_spec_or_missing_new_ids(self):
  by={r['title'].split()[0]:r['content'] for r in self.rows}
  self.assertIn('doubao-seedance-2-0-mini-260615',by['问题103'])
  self.assertIn('doubao-seedance-2.0',by['问题103'])
  self.assertIn('doubao-seedream-5-0-pro-260628',by['问题111'])
  self.assertNotIn('能力 | 时长',by['问题103'])
  self.assertIn('待定',by['问题103']);self.assertIn('待定',by['问题111'])
 def test_anaphoric_model_lists_do_not_depend_on_another_model_call(self):
  class Never:
   def complete(self,*args):raise AssertionError('explicit source already identifies catalogue')
  for item in self.catalogues:
   history=[{'role':'user','content':item['title']},{'role':'assistant','content':'untrusted prose','response':{'citations':[{'title':item['title']}]}}]
   for q in ['对应的模型型号列表有哪些','有哪些型号','型号有哪些','这些模型型号呢']:
    result=resolve(Never(),q,history)
    self.assertEqual(result['question'],item['title']+'-模型列表')
    signals=title_signals(result['question'],[r['title'] for r in self.rows])
    titles=[r['title'] for r,s in zip(self.rows,signals) if s['matched'] and s['strong']]
    self.assertEqual(titles,['问题'+str(item['question'])+' '+item['title']+'-模型列表'])
   switched=resolve(Never(),'图像生成API怎么调用',history)
   self.assertEqual(switched['question'],'图像生成API怎么调用')
 def test_reasonable_catalogue_wording_normalizes_to_same_title(self):
  for text in ['视频生成模型型号列表有哪些','视频生成模型的型号清单有哪些','视频生成模型的模型列表有哪些']:
   signal=title_signals(text,['问题103 视频生成模型-模型列表'])[0]
   self.assertTrue(signal['strong'] and signal['matched'],text)

class CatalogueConversationTests(unittest.TestCase):
 def test_real_word_followup_retrieves_catalogue_and_persists_it(self):
  import tempfile
  from app.core import Service,Settings
  from app.retrieval import title_text
  class Knowledge:
   def __init__(self):
    self.rows={str(i):{**r,'id':str(i),'source_file':'SmartTITU客户问答.docx'} for i,r in enumerate(parse_document(ROOT/'knowledge_sources/SmartTITU客户问答.docx').chunks)}
   def assess(self,q):
    rows=[r for r in self.rows.values() if title_text(r['title'])==q]
    return {'matched':bool(rows),'hits':[(.9,r,.9) for r in rows],'method':'fixture'}
  with tempfile.TemporaryDirectory() as temp:
   service=Service(Settings(retrieval_backend='lexical',secret='catalogue-secret-abcdefghijklmnopqrstuvwxyz012345',db=str(Path(temp)/'chat.db')))
   try:
    service.knowledge=Knowledge();actor={'tenant_id':'catalogue-test','sub':'user'}
    for title,expected in [('视频生成模型','doubao-seedance-2-5-260628'),('图像生成模型','doubao-seedream-5-0-pro-260628'),('多模态模型','moonshotai/Kimi-K2.7-Code'),('文本模型','qwen3.8-max')]:
     sid=service.create(actor,{})['session_id']
     service.chat(actor,sid,{'message':title,'request_id':'catalogue-first-'+sid})
     result=service.chat(actor,sid,{'message':'对应的模型型号列表有哪些','request_id':'catalogue-follow-'+sid})
     self.assertEqual(result['status'],'answered')
     self.assertEqual(result['citations'][0]['section_title'],title+'-模型列表')
     self.assertIn(expected,result['answer'])
     self.assertEqual(service.history(actor,sid)['items'][-1]['response']['answer'],result['answer'])
   finally:service.close()
