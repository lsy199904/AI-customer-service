import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from app.public_links import PublicLinks
from app.core import Service,Settings

class LinkPolicyTests(unittest.TestCase):
 def setUp(self):self.policy=PublicLinks()
 def test_exact_official_hosts_only_and_technical_content(self):
  text='[官网](https://www.smarttitu.cn/path?a=1) [飞书](https://x.feishu.cn/doc) https://github.com/a/b https://www.smarttitu.cn.evil.com/ https://user@www.smarttitu.cn/ https://www.smarttitu.cn:8443/ API https://api.smarttitu.cn/v1。'
  result=self.policy.clean(text)
  self.assertIn('[官网](https://www.smarttitu.cn/path?a=1)',result);self.assertIn('飞书',result)
  self.assertNotIn('github.com',result);self.assertNotIn('feishu.cn',result);self.assertNotIn('evil.com',result);self.assertNotIn('user@',result);self.assertNotIn('8443',result)
  self.assertIn('https://api.smarttitu.cn/v1',result)
 def test_every_split_and_character_stream_matches_final_without_blocked_url(self):
  text='正文立即显示。请看[产品资料](https://x.feishu.cn/a_(b))，官网https://www.smarttitu.cn/help。\n```bash\ncurl https://github.com/a/b\n```\n继续回答。'
  expected=self.policy.clean(text)
  for index in range(len(text)+1):
   stream=self.policy.stream();parts=[stream.feed(text[:index]),stream.feed(text[index:]),stream.finish()]
   self.assertEqual(''.join(parts),expected,index)
   self.assertNotIn('feishu', ''.join(parts))
  stream=self.policy.stream();self.assertEqual(stream.feed('先给您说明，'),'先给您说明，')
  actual=''.join(stream.feed(c) for c in text)+stream.finish()
  self.assertEqual(actual,expected)
  self.assertIn('curl https://github.com/a/b',expected)
 def test_incomplete_targets_and_embedded_markdown_images_do_not_leak(self):
  self.assertEqual(self.policy.clean('看[资料](https://x.feishu.cn/private'), '看资料')
  self.assertEqual(self.policy.clean('正文![图](https://github.com/p.png)结束'),'正文结束')
 def test_local_media_and_replay_are_consistent(self):
  result={'answer':'[旧资料](https://x.feishu.cn/a)','images':[{'url':'/media/a.png'},{'url':'https://raw.githubusercontent.com/a.png'},{'url':'/media/../a.png'}],'citations':[{'url':'/v1/sources/id'}]}
  once=self.policy.response(result);self.assertEqual(once['answer'],'旧资料');self.assertEqual(len(once['images']),1)
  self.assertEqual(self.policy.response(once),once);self.assertTrue(once['citations'])
 def test_historical_content_and_source_are_filtered_without_rewriting_private_storage(self):
  with tempfile.TemporaryDirectory() as temp:
   s=Service(Settings(retrieval_backend='lexical',secret='links-test-abcdefghijklmnopqrstuvwxyz123456',db=str(Path(temp)/'chat.db')))
   try:
    a={'tenant_id':'t','sub':'u'};sid=s.create(a,{})['session_id']
    raw='正文[旧资料](https://x.feishu.cn/a)，`curl https://github.com/a`。'
    response={'answer':raw,'images':[],'citations':[]}
    import time
    with s.db:s.db.execute('INSERT INTO messages(id,session,request_id,role,content,payload,created) VALUES(?,?,?,?,?,?,?)',('old',sid,'old-links-test','assistant',raw,json.dumps(response),time.time()))
    item=s.history(a,sid)['items'][-1]
    self.assertEqual(item['content'],self.policy.clean(raw));self.assertEqual(item['response']['answer'],item['content'])
    self.assertEqual(s.db.execute('SELECT content FROM messages WHERE id=?',('old',)).fetchone()[0],raw)
   finally:s.close()
 def test_html_links_are_cleaned_and_website_allowlist_is_configurable(self):
  text='<a href="https://x.feishu.cn/a">资料</a> <img src="https://github.com/a.png">'
  self.assertEqual(self.policy.clean(text),'资料 ')
  for split in range(len(text)+1):
   stream=self.policy.stream();self.assertEqual(stream.feed(text[:split])+stream.feed(text[split:])+stream.finish(),'资料 ')
  policy=PublicLinks(('docs.company.example',))
  self.assertIn('https://docs.company.example',policy.clean('[正式文档](https://docs.company.example)'))
  self.assertNotIn('www.smarttitu.cn',policy.clean('https://www.smarttitu.cn'))
  for host in ('*.smarttitu.cn','https://www.smarttitu.cn','site:8443','site/path'):
   with self.assertRaises(ValueError):PublicLinks((host,))
 def test_unified_access_explanation_cannot_force_product_brochure(self):
  from app.image_policy import ImagePolicy
  decision={'need_images':True,'reason':'visual_explanation','flow_ids':[],'image_ids':['product-brochure'],'multiple_flows':False}
  self.assertFalse(ImagePolicy.guard('统一接入方式',decision)['need_images'])
  self.assertTrue(ImagePolicy.guard('给我看看产品介绍单页',decision)['need_images'])
  self.assertTrue(ImagePolicy.guard('解释一下服务体系架构',decision)['need_images'])
