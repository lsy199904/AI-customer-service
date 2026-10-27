import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
import io
import json
import logging
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
import httpx
from app import observability as ops

class OperationalLogs(unittest.TestCase):
 def setUp(self):
  self.output=io.StringIO();self.handler=logging.StreamHandler(self.output)
  self.handler.setFormatter(ops.JSONFormatter(ZoneInfo('Asia/Shanghai')))
  self.old=list(ops._log.handlers);self.level=ops._log.level;self.propagate=ops._log.propagate
  ops._log.handlers=[self.handler];ops._log.setLevel(logging.INFO);ops._log.propagate=False
 def tearDown(self):
  ops._log.handlers=self.old;ops._log.setLevel(self.level);ops._log.propagate=self.propagate
 def records(self):return [json.loads(line) for line in self.output.getvalue().splitlines()]
 def test_nested_context_does_not_leak(self):
  with ops.bind(http_request_id='http-1234'):
   with ops.bind(request_id='msg-1234',window_id='window-123'):
    ops.event('generation_failed',**ops.error_fields(ValueError('untrusted citations')))
   ops.event('http_completed')
  ops.event('outside')
  first,second,third=self.records()
  self.assertEqual(first['error_code'],'citation_validation');self.assertEqual(first['request_id'],'msg-1234')
  self.assertNotIn('request_id',second);self.assertNotIn('http_request_id',third)
  self.assertTrue(first['timestamp'].endswith('+08:00'))
 def test_concurrent_requests_keep_their_own_ids(self):
  def work(i):
   with ops.bind(request_id=f'msg-{i:08}'):
    ops.event('test',expected=f'msg-{i:08}')
  with ThreadPoolExecutor(max_workers=8) as pool:list(pool.map(work,range(32)))
  self.assertEqual(len(self.records()),32)
  self.assertTrue(all(r['request_id']==r['expected'] for r in self.records()))
 def test_only_error_categories_not_secrets(self):
  for error in [ValueError('SECRET-TOKEN https://example.com/?password=secret'),
                httpx.ConnectError('SECRET upstream'),json.JSONDecodeError('SECRET','sensitive raw answer',0),
                httpx.ReadTimeout('SECRET')]:
   ops.event('failed',**ops.error_fields(error))
  output=self.output.getvalue()
  self.assertNotIn('SECRET',output);self.assertNotIn('sensitive raw answer',output)
  self.assertEqual([r['error_code'] for r in self.records()],['unexpected','connection','invalid_json','timeout'])
 def test_upstream_status_only(self):
  e=httpx.HTTPStatusError('SECRET',request=httpx.Request('GET','https://secret.example'),response=httpx.Response(503))
  self.assertEqual(ops.error_fields(e)['upstream_status'],503)
 def test_classification_and_pseudonyms(self):
  self.assertEqual(ops.question_category('账单支付流程'),'billing_payment')
  self.assertEqual(ops.question_category('如何开票'),'invoice')
  self.assertEqual(ops.reference('secret','user1'),ops.reference('secret','user1'))
  self.assertNotEqual(ops.reference('secret','user1'),ops.reference('secret','user2'))
 def test_daily_rotation_retention_and_permissions(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);old=root/'app-2026-09-01-123.jsonl';old.write_text('old')
   unrelated=root/'keep-me.jsonl';unrelated.write_text('keep')
   handler=ops.DailyFiles(root,ZoneInfo('Asia/Shanghai'),days=2,max_bytes=300)
   handler.setFormatter(ops.JSONFormatter(ZoneInfo('Asia/Shanghai')))
   for day in ('2026-10-26','2026-10-27'):
    for _ in range(8):
     r=logging.LogRecord('test',logging.INFO,'',0,'event',(),None)
     r.created=datetime.fromisoformat(day+'T12:00:00+08:00').timestamp();handler.handle(r)
   handler.close()
   self.assertFalse(old.exists());self.assertTrue(unrelated.exists())
   for day in ('2026-10-26','2026-10-27'):
    files=list(root.glob('app-'+day+'-*'));self.assertGreater(len(files),1);self.assertLessEqual(len(files),5)
    self.assertTrue(all((f.stat().st_mode&0o777)==0o600 for f in files))
    for f in files:
     for line in f.read_text().splitlines():self.assertEqual(json.loads(line)['event'],'event')
 def test_http_logs_normalized_route_not_query_or_unmatched_path(self):
  from types import SimpleNamespace
  from app.server import RequestBoundary
  async def downstream(scope,receive,send):
   scope['route']=SimpleNamespace(path='/v1/sessions/{sid}/messages')
   await send({'type':'http.response.start','status':401,'headers':[]})
   await send({'type':'http.response.body','body':b''})
  config=SimpleNamespace(origins=())
  boundary=RequestBoundary(downstream,config)
  scope={'type':'http','method':'GET','path':'/v1/sessions/SECRET/messages',
         'query_string':b'token=SECRET','headers':[(b'x-request-id',b'http-check-123'),(b'x-widget-id',b'window-check-123')]}
  async def receive():return {'type':'http.request','body':b''}
  sent=[]
  async def send(message):sent.append(message)
  asyncio.run(boundary(scope,receive,send))
  record=self.records()[-1]
  self.assertEqual(record['route'],'/v1/sessions/{sid}/messages')
  self.assertEqual(record['window_id'],'window-check-123')
  self.assertEqual(record['http_request_id'],'http-check-123')
  self.assertNotIn('SECRET',self.output.getvalue())
  self.assertIn((b'x-request-id',b'http-check-123'),sent[0]['headers'])

 def test_retrieval_model_errors_are_logged_before_wrapping(self):
  from app.rag import post_json,RAGError
  with patch('app.transport.post_json',side_effect=httpx.ReadTimeout('SECRET upstream response')):
   with self.assertRaises(RAGError):post_json('https://secret.example',{},'SECRET',stage='rerank')
  record=self.records()[-1]
  self.assertEqual(record['model_stage'],'rerank');self.assertEqual(record['error_code'],'timeout')
  self.assertNotIn('SECRET',self.output.getvalue());self.assertNotIn('secret.example',self.output.getvalue())
 def test_query_filters_both_message_and_http_request_ids(self):
  import subprocess,sys
  with tempfile.TemporaryDirectory() as temp:
   p=Path(temp)/'app-2026-10-27-123.jsonl'
   p.write_text('\n'.join(json.dumps(r) for r in [
     {'event':'http_completed','http_request_id':'message-123','level':'ERROR'},
     {'event':'chat_completed','request_id':'message-123','level':'INFO'},
     {'event':'chat_completed','request_id':'different-id','level':'INFO'}])+'\n')
   result=subprocess.run([sys.executable,'scripts/query_logs.py','--directory',temp,
     '--date','2026-10-27','--request-id','message-123'],capture_output=True,text=True,check=True)
   self.assertEqual(len(result.stdout.splitlines()),2)
   result=subprocess.run([sys.executable,'scripts/query_logs.py','--directory',temp,
     '--request-id','message-123','--errors'],capture_output=True,text=True,check=True)
   self.assertEqual(len(result.stdout.splitlines()),1)

 def test_debug_snapshots_are_opt_in_separate_and_redacted(self):
  output=io.StringIO();handler=logging.StreamHandler(output)
  handler.setFormatter(ops.JSONFormatter(ZoneInfo('Asia/Shanghai')))
  previous=list(ops._debug_log.handlers);level=ops._debug_log.level;propagate=ops._debug_log.propagate
  ops._debug_log.handlers=[handler];ops._debug_log.setLevel(logging.INFO);ops._debug_log.propagate=False
  try:
   with patch.dict(os.environ,{'LOG_DEBUG_CONTENT':'false'}):ops.debug_event('chat_input',question='原始问题')
   self.assertEqual(output.getvalue(),'')
   with patch.dict(os.environ,{'LOG_DEBUG_CONTENT':'true','MODEL_API_KEY':'secret-model-key'}):
    with ops.bind(request_id='msg-debug-123'):
     ops.debug_event('model_output',text='业务回答 secret-model-key Bearer unrelated-token')
   row=json.loads(output.getvalue())
   self.assertEqual(row['request_id'],'msg-debug-123')
   self.assertIn('业务回答',row['snapshot']);self.assertNotIn('secret-model-key',row['snapshot'])
   self.assertNotIn('unrelated-token',row['snapshot']);self.assertNotIn('业务回答',self.output.getvalue())
   output.truncate(0);output.seek(0)
   with patch.dict(os.environ,{'LOG_DEBUG_CONTENT':'true'}):ops.debug_event('long',text='长'*20000)
   row=json.loads(output.getvalue());self.assertTrue(row['truncated']);self.assertEqual(len(row['snapshot']),16000)
  finally:
   ops._debug_log.handlers=previous;ops._debug_log.setLevel(level);ops._debug_log.propagate=propagate
 def test_debug_retention_does_not_delete_operational_files(self):
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);app=root/'app-2026-10-01-1.jsonl';app.write_text('keep')
   old=root/'debug-2026-10-01-1.jsonl';old.write_text('remove')
   handler=ops.DailyFiles(root,ZoneInfo('Asia/Shanghai'),days=3,prefix='debug')
   handler.setFormatter(ops.JSONFormatter(ZoneInfo('Asia/Shanghai')))
   record=logging.LogRecord('debug',logging.INFO,'',0,'debug_event',(),None)
   record.created=datetime.fromisoformat('2026-10-27T10:00:00+08:00').timestamp()
   handler.handle(record);handler.close()
   self.assertTrue(app.exists());self.assertFalse(old.exists())
 def test_report_pinpoints_validation_failure_and_includes_optional_contents(self):
  import subprocess,sys
  with tempfile.TemporaryDirectory() as temp:
   records=[{'timestamp':'2026-10-27T10:00:00+08:00','event':'retrieval_completed','matched':True,'evidence_count':1},
    {'timestamp':'2026-10-27T10:00:01+08:00','event':'answer_validation_failed','error_code':'citation_validation'},
    {'timestamp':'2026-10-27T10:00:02+08:00','event':'chat_completed','outcome':'suggestions','reason':'model_unavailable'}]
   for r in records:r['request_id']='msg-report-123'
   (Path(temp)/'app-2026-10-27-1.jsonl').write_text('\n'.join(json.dumps(r) for r in records)+'\n')
   snapshot={'timestamp':'2026-10-27T10:00:00+08:00','event':'chat_input','request_id':'msg-report-123',
       'snapshot':json.dumps({'question':'账单支付流程'},ensure_ascii=False),'truncated':False}
   (Path(temp)/'debug-2026-10-27-1.jsonl').write_text(json.dumps(snapshot)+'\n')
   base=[sys.executable,'scripts/query_logs.py','--directory',temp,'--request-id','msg-report-123','--report']
   r=subprocess.run(base,capture_output=True,text=True,check=True)
   self.assertIn('首个记录到的失败节点：回答格式或引用校验失败',r.stdout)
   self.assertNotIn('账单支付流程',r.stdout)
   r=subprocess.run(base+['--debug-content'],capture_output=True,text=True,check=True)
   self.assertIn('账单支付流程',r.stdout);self.assertIn('【用户输入】',r.stdout)

 def test_normal_logs_purge_old_debug_content_when_capture_disabled(self):
  with tempfile.TemporaryDirectory() as temp,patch.dict(os.environ,{'LOG_DEBUG_CONTENT':'false','LOG_DEBUG_RETENTION_DAYS':'3'}):
   root=Path(temp);old=root/'debug-2026-10-01-1.jsonl';old.write_text('expired')
   recent=root/'debug-2026-10-26-1.jsonl';recent.write_text('recent')
   handler=ops.DailyFiles(root,ZoneInfo('Asia/Shanghai'),days=30)
   handler.setFormatter(ops.JSONFormatter(ZoneInfo('Asia/Shanghai')))
   record=logging.LogRecord('app',logging.INFO,'',0,'event',(),None)
   record.created=datetime.fromisoformat('2026-10-27T10:00:00+08:00').timestamp()
   handler.handle(record);handler.close()
   self.assertFalse(old.exists());self.assertTrue(recent.exists())
 def test_debug_configuration_preserves_secret_and_requires_recreation(self):
  import subprocess,sys,shutil
  with tempfile.TemporaryDirectory() as temp:
   root=Path(temp);(root/'scripts').mkdir()
   shutil.copy2('scripts/configure_debug_logging.py',root/'scripts/configure_debug_logging.py')
   (root/'.env').write_text('AUTH_SECRET=do-not-print-this-secret\nLOG_DEBUG_CONTENT=false\n')
   r=subprocess.run([sys.executable,str(root/'scripts/configure_debug_logging.py'),'enable'],capture_output=True,text=True,check=True)
   self.assertIn('LOG_DEBUG_CONTENT=true',(root/'.env').read_text())
   self.assertIn('AUTH_SECRET=do-not-print-this-secret',(root/'.env').read_text())
   self.assertNotIn('do-not-print',r.stdout);self.assertIn('重建应用容器',r.stdout)
   backups=list((root/'backups').glob('*/env.before'));self.assertEqual(len(backups),1)
   self.assertEqual(backups[0].stat().st_mode&0o777,0o600)
   subprocess.run([sys.executable,str(root/'scripts/configure_debug_logging.py'),'disable'],capture_output=True,text=True,check=True)
   self.assertEqual((root/'.env').read_text().count('LOG_DEBUG_CONTENT='),1)
   self.assertIn('LOG_DEBUG_CONTENT=false',(root/'.env').read_text())

if __name__=='__main__':unittest.main()
