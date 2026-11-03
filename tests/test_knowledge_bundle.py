import io
import json
from pathlib import Path
import tarfile
import tempfile
import unittest
from scripts.knowledge_bundle import pack,restore

class BundleTests(unittest.TestCase):
 def test_roundtrip_persistent_images_sources_and_database_without_secrets_models_or_logs(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp)/'old';target=Path(temp)/'new';root.mkdir();target.mkdir()
   values={'data/media.json':b'[]','knowledge_sources/test.md':'# 测试\n正文'.encode(),'app/static/media/a.png':b'PNG','var/pdf_media/assets/pdf-a.png':b'QR','var/pdf_media/reports/one.json':b'{}','.env':b'AUTH_SECRET=secret','models/weights':b'model','var/logs/private.log':b'private'}
   for name,value in values.items():p=root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_bytes(value)
   identifier='pdf-'+'a'*32
   values['var/pdf_media/assets/'+identifier+'.png']=b'QR retained'
   report={'assets':[{'id':identifier,'status':'retained','title':'试用申请二维码','kind':'qr','purpose':'trial'}]}
   (root/'var/pdf_media/assets'/ (identifier+'.png')).write_bytes(b'QR retained')
   (root/'var/pdf_media/reports/one.json').write_text(json.dumps(report))
   storage=Path(temp)/'storage';storage.mkdir()
   for name in ('assistant.db','rag.sqlite3','export.json'):(storage/name).write_bytes(b'database snapshot')
   archive=Path(temp)/'bundle.tar.gz';pack(root,archive,storage);result=restore(target,archive)
   self.assertTrue(result['database_export']);self.assertEqual((target/'app/static/media/a.png').read_bytes(),b'PNG')
   self.assertEqual((target/'var/pdf_media/assets/pdf-a.png').read_bytes(),b'QR')
   from app.pdf_media import catalog
   restored=catalog(target/'var/pdf_media');self.assertEqual(len(restored),1)
   self.assertEqual(restored[0]['url'],'/media/'+identifier+'.png');self.assertIn(str(target),restored[0]['asset_path'])
   self.assertEqual(Path(restored[0]['asset_path']).read_bytes(),b'QR retained')
   self.assertFalse((target/'.env').exists());self.assertFalse((target/'models').exists());self.assertFalse((target/'var/logs').exists())
   self.assertEqual(restore(target,archive)['restored_files'],0)
   with self.assertRaises(ValueError):pack(root,archive)
 def test_modified_resource_and_unsafe_paths_are_rejected_before_any_write(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);archive=root/'bad.tar.gz';target=root/'new';target.mkdir()
   with tarfile.open(archive,'w:gz') as output:
    row=tarfile.TarInfo('../outside');row.size=1;output.addfile(row,io.BytesIO(b'x'))
   with self.assertRaises(ValueError):restore(target,archive)
   self.assertEqual(list(target.iterdir()),[])
   source=root/'source';(source/'data').mkdir(parents=True);(source/'data/media.json').write_text('[]')
   archive=root/'good.tar.gz';pack(source,archive);(target/'data').mkdir();(target/'data/media.json').write_text('[1]')
   with self.assertRaises(ValueError):restore(target,archive)
   self.assertEqual((target/'data/media.json').read_text(),'[1]')
