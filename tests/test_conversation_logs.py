from datetime import datetime
import json
import logging
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from zoneinfo import ZoneInfo
from app import observability as ops
from app.conversation_logs import ConversationFiles,conversation_parts,conversation_paths,prune_conversations


def document(user='b'*20,session='c'*20,day='2026-10-28',content=False):
    row={'时间':day+'T12:00:00+08:00','输入':{'企业标识':'a'*20,'用户标识':user,'会话编号':session,'请求编号':'msg-12345678'},'处理流程':[],'输出':{'状态':'answered'}}
    if content:row['输入']['问题']='机密问题';row['输出']['最终响应']={'answer':'机密回复'}
    return row


def write(handler,row):
    record=logging.LogRecord('test',logging.INFO,'',0,'request_completed',(),None)
    record.operation_document=row;record.created=datetime.fromisoformat(row['时间']).timestamp()
    handler.handle(record)


class ConversationLogTests(unittest.TestCase):
 def handler(self,root):
    handler=ConversationFiles(root,ZoneInfo('Asia/Shanghai'),content=True)
    handler.setFormatter(ops.JSONFormatter(ZoneInfo('Asia/Shanghai')))
    return handler
 def test_same_month_groups_by_user_and_session_across_days(self):
    with tempfile.TemporaryDirectory() as root:
     handler=self.handler(root)
     for row in (document(),document(day='2026-10-29'),document(session='d'*20),document(user='e'*20),document(day='2026-11-01')):write(handler,row)
     paths=list(conversation_paths(root));self.assertEqual(len(paths),4)
     path=Path(root)/'conversations'/Path(*conversation_parts(document()))
     self.assertEqual(len(path.read_text().splitlines()),2)
     self.assertEqual(path.stat().st_mode&0o777,0o600)
     self.assertEqual(path.parent.stat().st_mode&0o777,0o700)
 def test_tenants_with_same_user_and_session_have_separate_files(self):
    with tempfile.TemporaryDirectory() as root:
     first=document();second=document();second['输入']['企业标识']='f'*20
     write(self.handler(root),first);write(self.handler(root),second)
     self.assertEqual(len(list(conversation_paths(root))),2)
 def test_content_disabled_still_stores_metadata_conversation(self):
    with tempfile.TemporaryDirectory() as root,patch.dict(os.environ,{'LOG_DEBUG_CONTENT':'false'}):
     handler=ConversationFiles(root,ZoneInfo('Asia/Shanghai'));handler.setFormatter(ops.JSONFormatter(ZoneInfo('Asia/Shanghai')))
     write(handler,document())
     self.assertEqual(len(list(conversation_paths(root))),1)
 def test_untrusted_paths_and_symlinks_do_not_escape(self):
    with tempfile.TemporaryDirectory() as root,tempfile.TemporaryDirectory() as outside:
     self.assertIsNone(conversation_parts(document(user='../outside')))
     (Path(root)/'conversations').symlink_to(outside,target_is_directory=True)
     write(self.handler(root),document())
     self.assertEqual(list(Path(outside).iterdir()),[])
 def test_retention_expires_old_records_in_active_session(self):
    with tempfile.TemporaryDirectory() as root:
     handler=self.handler(root)
     write(handler,document(day='2026-10-26',content=True));write(handler,document(day='2026-10-28',content=True))
     write(handler,document(day='2026-10-26',session='d'*20))
     prune_conversations(root,datetime(2026,10,29).date(),30,3)
     path=Path(root)/'conversations'/Path(*conversation_parts(document()))
     self.assertEqual(len(path.read_text().splitlines()),1)
     summary=Path(root)/'conversations'/Path(*conversation_parts(document(session='d'*20)))
     self.assertTrue(summary.exists())
 def test_query_month_user_and_content_opt_in(self):
    with tempfile.TemporaryDirectory() as root:
     write(self.handler(root),document(content=True));write(self.handler(root),document(user='e'*20,content=True))
     base=[sys.executable,'scripts/query_logs.py','--directory',root,'--month','2026-10','--user-ref','b'*20]
     plain=subprocess.check_output(base,text=True);self.assertNotIn('机密',plain);self.assertEqual(len(plain.splitlines()),1)
     full=subprocess.check_output(base+['--debug-content'],text=True)
     self.assertIn('机密问题',full);self.assertEqual(len(full.splitlines()),1)
     sessions=json.loads(subprocess.check_output(base+['--list-sessions'],text=True))
     self.assertEqual(sessions['问答数量'],1);self.assertIn('session-',sessions['文件'])
     empty=subprocess.check_output(base+['--date','2026-10-27'],text=True);self.assertEqual(empty,'')
 def test_multiple_processes_append_complete_records(self):
    with tempfile.TemporaryDirectory() as root:
     program='''
import json,logging,sys
from zoneinfo import ZoneInfo
from app.conversation_logs import ConversationFiles
from app.observability import JSONFormatter
h=ConversationFiles(sys.argv[1],ZoneInfo('Asia/Shanghai'),content=True);h.setFormatter(JSONFormatter(ZoneInfo('Asia/Shanghai')))
for i in range(15):
 r=logging.LogRecord('test',20,'',0,'request_completed',(),None);r.operation_document=json.loads(sys.argv[2]);r.operation_document['输入']['请求编号']=sys.argv[3]+'-'+str(i);h.handle(r)
'''
     processes=[subprocess.Popen([sys.executable,'-c',program,root,json.dumps(document()),str(i)]) for i in range(3)]
     self.assertTrue(all(p.wait()==0 for p in processes))
     rows=[json.loads(line) for p in conversation_paths(root) for line in p.read_text().splitlines()]
     self.assertEqual(len(rows),45);self.assertEqual(len({r['输入']['请求编号'] for r in rows}),45)
 def test_configured_logging_stores_one_full_record_not_duplicate(self):
    with tempfile.TemporaryDirectory() as root:
     program='''
import os,sys
os.environ['LOG_DEBUG_CONTENT']='true'
from app import observability as ops
ops.configure(sys.argv[1])
with ops.bind(request_id='msg-real-123',tenant_ref='a'*20,user_ref='b'*20,session_ref='c'*20),ops.capture_request():
 ops.event('chat_started');ops.debug_event('chat_input',question='完整问答');ops.debug_event('chat_output',response={'answer':'完整回复'});ops.event('chat_completed',outcome='answered')
'''
     result=subprocess.run([sys.executable,'-c',program,root],text=True,capture_output=True,check=True)
     rows=[json.loads(line) for p in conversation_paths(root) for line in p.read_text().splitlines()]
     self.assertEqual(len(rows),1);self.assertEqual(rows[0]['输入']['问题'],'完整问答')
     self.assertNotIn('完整问答',result.stderr)
     system=[json.loads(line) for p in Path(root).glob('app-*.jsonl') for line in p.read_text().splitlines()]
     self.assertFalse(any('处理流程' in row for row in system))
