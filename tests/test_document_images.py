"""Document-owned image IDs remain stable across semantic index revisions."""
from pathlib import Path
import tempfile
import unittest
import os
from app.ingestion import parse_document,split_sections
from app.rag import RAGSettings,SemanticKnowledge,ingest_documents,DocumentStore
from app.core import Settings,Service

BASE=Path(__file__).resolve().parent.parent
SECRET='test-secret-abcdefghijklmnopqrstuvwxyz-0123456789'
ACTOR={'tenant_id':'company','sub':'person'}

class Embeddings:
 def __init__(self):self.calls=[]
 def embed(self,texts):
  self.calls.extend(texts)
  return [[1,0] if '手机号' in t or 'get started' in t else [0,1] for t in texts]

class DocumentImageTests(unittest.TestCase):
 def setUp(self):
  self.temp=tempfile.TemporaryDirectory();self.root=Path(self.temp.name);self.source=self.root/'sources';self.source.mkdir()
  self.file=self.source/'企业.md';self.file.write_text('# 企业如何开户\n使用手机号和验证码登录，新客户按页面指引注册。\n配图：enterprise-register\n',encoding='utf-8')
  self.config=RAGSettings(index_path=str(self.root/'rag.sqlite3'),source_dir=str(self.source),rerank_enabled=False,http_origins=('http://127.0.0.1:11434',),min_similarity=.7)
  self.embed=Embeddings();ingest_documents(self.config,embedder=self.embed)
  self.service=Service(Settings(retrieval_backend='lexical',db=str(self.root/'chat.sqlite3'),secret=SECRET))
  self.service.knowledge=SemanticKnowledge(self.config,self.embed);self.service.config.retrieval_backend='semantic'
  self.sid=self.service.create(ACTOR,{})['session_id'];self.number=0
 def tearDown(self):self.service.db.close();self.temp.cleanup()
 def ask(self):
  self.number+=1
  return self.service.chat(ACTOR,self.sid,{'message':'How do we get started?','request_id':'register-%04d'%self.number})
 def model(self,answerable=True,select_bound=True):
  class Fake:
   def answer(me,q,h,e,c):return {'answerable':answerable,'answer':'请先使用手机号和验证码登录，按页面完成企业注册。','citation_ids':[e[0]['id']] if answerable else [],'image_ids':[]}
  self.service.config.mode='llm';self.service.model=Fake()
 def test_semantic_paraphrase_attaches_even_when_model_omits_image(self):
  self.model();r=self.ask();self.assertEqual(r['status'],'answered');self.assertEqual(r['retrieval']['method'],'hybrid_rrf')
  self.assertEqual(r['images'][0]['id'],'enterprise-register');self.assertTrue(r['citations']);self.assertIn('注册',r['answer'])
  self.assertEqual(self.service.history(ACTOR,self.sid)['items'][-1]['response']['images'],r['images'])
 def test_extractive_answer_also_attaches(self):
  r=self.ask();self.assertEqual(r['images'][0]['id'],'enterprise-register')
 def test_rejected_answer_does_not_attach(self):
  self.model(answerable=False);r=self.ask();self.assertTrue(r['handoff']);self.assertEqual(r['images'],[])
 def test_unavailable_model_does_not_attach(self):
  class Broken:
   def answer(self,*args):raise ValueError('unavailable')
  self.service.config.mode='llm';self.service.model=Broken();r=self.ask();self.assertTrue(r['handoff']);self.assertEqual(r['images'],[])
 def test_unrelated_retrieved_diagram_is_not_forced(self):
  # Both records are candidates, but the model cites only the record with no diagram.
  row=next(iter(self.service.knowledge.rows.values()));plain={**row,'id':'KB-aabbcc','title':'其他说明','image_ids':[]}
  self.service.knowledge.assess=lambda q:{'matched':True,'hits':[(1,plain,1),(.9,row,.9)],'method':'embedding','similarity':1}
  self.model();r=self.ask();self.assertFalse(r['handoff']);self.assertEqual(r['images'],[])
 def test_no_hit_does_not_attach(self):
  self.service.knowledge.assess=lambda q:{'matched':False,'hits':[],'method':'embedding','similarity':0}
  self.model();r=self.ask();self.assertTrue(r['handoff']);self.assertEqual(r['images'],[])
 def test_revision_changes_without_rebinding_image(self):
  before=next(iter(self.service.knowledge.rows));self.file.write_text(self.file.read_text()+'\n来源：修订后的注册流程。\n',encoding='utf-8')
  calls=len(self.embed.calls);ingest_documents(self.config,embedder=self.embed)
  after=next(iter(self.service.knowledge.rows));self.assertNotEqual(before,after);self.assertEqual(len(self.embed.calls),calls)
  self.model();self.assertEqual(self.ask()['images'][0]['id'],'enterprise-register')
 def test_unregistered_image_fails_before_publishing(self):
  before=DocumentStore(self.config.index_path).documents();self.file.write_text('# 流程\n修改的内容\n配图：unregistered-image\n',encoding='utf-8')
  with self.assertRaises(ValueError):ingest_documents(self.config,embedder=self.embed)
  self.assertEqual(DocumentStore(self.config.index_path).documents(),before)

@unittest.skipUnless(os.getenv('RUN_PRIVATE_KNOWLEDGE_TESTS')=='1', 'Private Word/attachments are supplied separately; set RUN_PRIVATE_KNOWLEDGE_TESTS=1 to verify them')
class DocumentImageParserTests(unittest.TestCase):
 def test_updated_word(self):
  result=parse_document(BASE/'knowledge_sources/SmartTITU客户问答.docx')
  self.assertEqual(len(result.chunks),71)
  self.assertFalse(any(c['title'].startswith('问题'+str(i)+' ') for c in result.chunks for i in [5,9,15,22,26,28]))
  self.assertEqual(result.version,'2026-10-23 v3')
  bound=[c for c in result.chunks if 'enterprise-register' in c['image_ids']];self.assertEqual(len(bound),1)
  self.assertIn('企业注册与认证流程',bound[0]['title'])
  self.assertEqual(len(set(k for c in result.chunks for k in c['image_ids'])),30)
  self.assertFalse(any('运营团队预创建' in c['content'] for c in result.chunks))
  self.assertFalse(any('配图:' in c['content'] for c in result.chunks))

 def test_external_source_order(self):
  rows=parse_document(BASE/'knowledge_sources/SmartTITU客户问答.docx').chunks
  for i,name in enumerate(['产品介绍网页','在线文件','模型清单','企业注册与认证流程']):self.assertIn(name,rows[i]['title'])
  for i,url in enumerate(['https://www.smarttitu.cn','https://doc.smarttitu.cn','https://www.smarttitu.cn/models']):self.assertIn(url,rows[i]['content'])
  positions={}
  for i,row in enumerate(rows):
   ref=row['source_references'][0];positions.setdefault(ref.split('，物理第')[0],[]).append(i)
  for indexes in positions.values():self.assertEqual(indexes,list(range(min(indexes),max(indexes)+1)))
  text='\n'.join(str(c['source_references']) for c in rows)
  for excluded in ['6.AICC','7.SmartTITU销售','8.AI_Token','12.TITU Edge']:self.assertNotIn(excluded,text)
 def test_online_ppt_preserves_user_deletions(self):
  import re
  rows=parse_document(BASE/'knowledge_sources/SmartTITU客户问答.docx').chunks
  ppt=[r for r in rows if '5.SmartTITU' in str(r['source_references'])]
  self.assertEqual([int(re.search(r'第(\d+)页',r['title']).group(1)) for r in ppt],[i for i in range(1,31) if i not in {1,5,11,18,22,24,26}])
 def test_word_media_and_source_resources_exist(self):
  import json,urllib.parse
  from app.conversation import MediaCatalog
  catalog=MediaCatalog(BASE/'data/media.json',BASE/'app/static/media')
  rows=parse_document(BASE/'knowledge_sources/SmartTITU客户问答.docx').chunks
  for row in rows:
   for image in row['image_ids']:self.assertIn(image,catalog.rows)
  for prefix in ['11.','13.','14.','15.']:self.assertEqual(len(list((BASE/'docs/sources').glob(prefix+'*.pdf'))),1)
  self.assertEqual(len(list((BASE/'knowledge_sources').rglob('*.docx'))),1)
 def test_long_section_keeps_bindings_in_each_chunk(self):
  blocks=[{'text':'流程','heading':True},{'text':'步骤。'*300,'heading':False,'locator':'段落1'},{'text':'配图：enterprise-register','heading':False}]
  chunks=split_sections(blocks,'标题',max_chars=200,overlap=20)
  self.assertGreater(len(chunks),1);self.assertTrue(all(c['image_ids']==['enterprise-register'] for c in chunks))
 def test_image_urls_in_document_are_rejected(self):
  blocks=[{'text':'流程','heading':True},{'text':'正文','heading':False,'locator':'段落1'},{'text':'配图：https://evil.example/image.png','heading':False}]
  with self.assertRaises(ValueError):split_sections(blocks,'标题')

if __name__=='__main__':unittest.main()
