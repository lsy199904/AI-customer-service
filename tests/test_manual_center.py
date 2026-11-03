"""Coverage of the explicitly requested public documentation snapshot."""
import json
import unittest
from pathlib import Path
from app.ingestion import parse_document
ROOT=Path(__file__).resolve().parent.parent
class ManualCenterTests(unittest.TestCase):
 def test_every_published_article_has_usable_chunks_and_original_url(self):
  manifest=json.loads((ROOT/'docs/manual-center-coverage.json').read_text())
  self.assertEqual(len(manifest),29);self.assertEqual(len({r['column'] for r in manifest}),9)
  chunks=parse_document(ROOT/'knowledge_sources/SmartTITU客户问答.docx').chunks
  for chunk in chunks[60:]:
   self.assertTrue(any(line.strip() and not line.startswith('原文链接:') for line in chunk['content'].splitlines()),chunk['title'])
  for article in manifest:
   with self.subTest(article=article['title']):
    matches=[c for c in chunks if article['url'] in c['content']]
    self.assertTrue(matches)
    self.assertTrue(all(c['content'].strip() and c['source_references'] for c in matches))
    self.assertTrue(any(article['title'] in c['title'] for c in matches))
 def test_error_types_keep_their_own_resolution_and_metallb_removes_only_broken_example(self):
  chunks=parse_document(ROOT/'knowledge_sources/SmartTITU客户问答.docx').chunks
  for title,term in [('authentication_error','API Key'),('rate_limit_error','TPM'),('permission_error','权限'),('invalid_request_error','参数')]:
   matches=[r for r in chunks if title in r['title']]
   self.assertTrue(matches);self.assertIn(term,'\n'.join(r['content'] for r in matches))
  metal=next(r for r in chunks if r['title'].startswith('问题57 '))
  self.assertNotIn('手册示例清单地址',metal['content'])
  self.assertIn('IPAddressPool',metal['content']);self.assertIn('v0.13.12',metal['content'])
  self.assertTrue(metal['source_references'])
