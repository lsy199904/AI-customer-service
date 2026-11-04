import ast,json,tempfile,unittest,re
from pathlib import Path
import zipfile
import xml.etree.ElementTree as ET
from app.ingestion import parse_document

class CodePreservationTests(unittest.TestCase):
 def test_word_code_preserves_indentation_unicode_and_is_not_split(self):
  code='import os\n\ndef answer():\n    text = "全角，标点：原样"\n    if text:\n        return text\n'+('# context\n'*150)
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/'code.docx'
   ns='http://schemas.openxmlformats.org/wordprocessingml/2006/main'
   doc=ET.Element('{'+ns+'}document');body=ET.SubElement(doc,'{'+ns+'}body')
   for text,heading in [('代码示例',True),('前置说明。',False),(code,False),('后续说明。',False)]:
    para=ET.SubElement(body,'{'+ns+'}p')
    if heading:
     pr=ET.SubElement(para,'{'+ns+'}pPr');ET.SubElement(pr,'{'+ns+'}pStyle',{'{'+ns+'}val':'Heading1'})
    ET.SubElement(ET.SubElement(para,'{'+ns+'}r'),'{'+ns+'}t').text=text
   with zipfile.ZipFile(p,'w') as z:z.writestr('word/document.xml',ET.tostring(doc))
   rows=parse_document(p,max_chars=200,overlap=30).chunks
   code_rows=[r for r in rows if '```' in r['content']]
   self.assertEqual(len(code_rows),1)
   body=re.search(r'```\n(.*?)\n```',code_rows[0]['content'],re.S)[1]
   self.assertEqual(body,code.rstrip('\n'));ast.parse(body)
 def test_markdown_code_and_yaml_keep_spaces_tabs_and_blank_lines(self):
  source='# Example\n```python\ndef f():\n\treturn "Ａ，"\n\n```\n\n~~~yaml\nservices:\n  app:\n    ports:\n      - "8080:8080"\n~~~\n'
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/'example.md';p.write_text(source)
   text='\n'.join(r['content'] for r in parse_document(p).chunks)
   self.assertIn('\treturn "Ａ，"',text);self.assertIn('\n  app:\n    ports:',text)
 def test_real_word_code_and_invoice_conditions(self):
  root=Path(__file__).resolve().parents[1];rows=parse_document(root/'knowledge_sources/SmartTITU客户问答.docx').chunks
  by={}
  for r in rows:by.setdefault(r['title'].split()[0],[]).append(r['content'])
  code='\n'.join(by['问题178']);self.assertIn('    get_result =',code);self.assertIn('        print(',code)
  text='\n'.join(r['content'] for r in rows)
  self.assertNotIn('smarttitu.cn%E7',text)
  self.assertNotIn('支持三种开票方式',text)
  for n in [13,306,329]:
   body='\n'.join(by['问题'+str(n)]);self.assertIn('2万',body);self.assertIn('一次',body)
