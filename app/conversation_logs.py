"""Monthly conversation files, with cross-process append locking and per-record expiry."""
from contextlib import contextmanager
from datetime import datetime, timedelta
import fcntl
import json
import logging
import os
from pathlib import Path
import re
import tempfile

REF=re.compile(r'[a-f0-9]{20}')


def conversation_parts(document):
    if not isinstance(document,dict):return None
    meta=document.get('输入',{})
    values=[meta.get(key) for key in ('企业标识','用户标识','会话编号')]
    if not all(isinstance(value,str) and REF.fullmatch(value) for value in values):return None
    try:month=datetime.fromisoformat(document['时间']).strftime('%Y-%m')
    except (ValueError,KeyError,TypeError):return None
    return (month,'tenant-'+values[0],'user-'+values[1],'session-'+values[2]+'.jsonl')


def safe_directory(path):
    path.mkdir(mode=0o700,parents=True,exist_ok=True)
    if path.is_symlink() or not path.is_dir():raise OSError('unsafe log directory')


@contextmanager
def locked(path):
    fd=os.open(str(path)+'.lock',os.O_CREAT|os.O_RDWR|os.O_NOFOLLOW,0o600)
    try:
        fcntl.flock(fd,fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(fd,fcntl.LOCK_UN);os.close(fd)


def conversation_paths(root):
    root=Path(root)/'conversations'
    if not root.is_dir() or root.is_symlink():return
    for month in sorted(root.iterdir()):
        if month.is_symlink() or not month.is_dir() or not re.fullmatch(r'\d{4}-\d{2}',month.name):continue
        for tenant in sorted(month.iterdir()):
            if tenant.is_symlink() or not tenant.is_dir() or not re.fullmatch(r'tenant-[a-f0-9]{20}',tenant.name):continue
            for user in sorted(tenant.iterdir()):
                if user.is_symlink() or not user.is_dir() or not re.fullmatch(r'user-[a-f0-9]{20}',user.name):continue
                for path in sorted(user.glob('session-*.jsonl')):
                    if re.fullmatch(r'session-[a-f0-9]{20}\.jsonl',path.name) and not path.is_symlink() and path.is_file():yield path


def prune_conversations(directory,day,summary_days,content_days):
    """Expire individual requests, so active sessions do not retain old debug text."""
    for path in conversation_paths(directory):
        with locked(path):
            try:
                fd=os.open(path,os.O_RDONLY|os.O_NOFOLLOW)
            except FileNotFoundError:continue
            kept=[];changed=False
            with os.fdopen(fd,encoding='utf-8') as source:
                for line in source:
                    try:
                        row=json.loads(line);date=datetime.fromisoformat(row['时间']).date()
                        content='问题' in row.get('输入',{}) or '最终响应' in row.get('输出',{}) or any('数据' in step for step in row.get('处理流程',[]))
                        expired=date < day-timedelta(days=(content_days if content else summary_days)-1)
                    except (ValueError,KeyError,TypeError):expired=False
                    if expired:changed=True
                    else:kept.append(line)
            if not changed:continue
            if not kept:path.unlink();continue
            fd,name=tempfile.mkstemp(prefix='.retention-',dir=path.parent)
            try:
                with os.fdopen(fd,'w',encoding='utf-8') as target:target.writelines(kept)
                os.replace(name,path)
            finally:
                if os.path.exists(name):os.unlink(name)


class ConversationFiles(logging.Handler):
    def __init__(self,directory,timezone,content=False):
        super().__init__();self.directory=Path(directory);self.timezone=timezone;self.content=content;self.day=None

    def emit(self,record):
        document=getattr(record,'operation_document',None);parts=conversation_parts(document)
        if not parts:return
        # Exactly one stored record: full when enabled, otherwise metadata only.
        if not self.content and os.getenv('LOG_DEBUG_CONTENT','false').lower()=='true':
            from .observability import _debug_log
            if any(isinstance(h,ConversationFiles) for h in _debug_log.handlers):return
        try:
            day=datetime.fromtimestamp(record.created,self.timezone).date()
            if self.day!=day:
                prune_conversations(self.directory,day,int(os.getenv('LOG_RETENTION_DAYS','30')),max(1,min(30,int(os.getenv('LOG_DEBUG_RETENTION_DAYS','3')))))
                self.day=day
            parent=self.directory
            for part in ('conversations',*parts[:-1]):
                safe_directory(parent);parent=parent/part
            safe_directory(parent);path=parent/parts[-1]
            data=(self.format(record)+'\n').encode('utf-8')
            with locked(path):
                fd=os.open(path,os.O_CREAT|os.O_APPEND|os.O_WRONLY|os.O_NOFOLLOW,0o600)
                with os.fdopen(fd,'ab') as target:target.write(data)
        except Exception:
            if not getattr(self,'_failed',False):
                self._failed=True
                import sys
                print('Conversation log write failed; inspect stdout logs and disk permissions.',file=sys.stderr)
