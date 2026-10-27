"""Structured operational logs without customer content or upstream payloads."""
from contextvars import ContextVar
from contextlib import contextmanager
from datetime import datetime, timedelta
import hashlib
import hmac
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import re
import threading
from zoneinfo import ZoneInfo

_context = ContextVar('operation_log_context', default={})
_log = logging.getLogger('assistant.operations')
_lock = threading.Lock()
_VALIDATION = {
    'invalid answer schema': 'answer_schema', 'invalid answer': 'answer_schema',
    'invalid citations': 'citation_schema', 'untrusted citations': 'citation_validation',
    'untrusted images': 'image_validation', 'empty customer answer': 'empty_answer',
    '模型响应无效或过大': 'response_size',
}

@contextmanager
def bind(**fields):
    token = _context.set({**_context.get(), **fields})
    try:
        yield
    finally:
        _context.reset(token)


def reference(secret, value):
    return hmac.new(secret.encode(), str(value).encode(), hashlib.sha256).hexdigest()[:20]


def question_category(question):
    for category, pattern in (
        ('billing_payment', r'账单|支付|结算'), ('recharge', r'充值|汇款|余额'),
        ('invoice', r'发票|开票'), ('authentication', r'认证|签约|合同'),
        ('account', r'注册|登录|账号|密码'), ('model_api', r'API|密钥|模型|调用|错误码|报错'),
        ('subscription', r'套餐|订购|星级|交付'), ('product', r'产品|平台|功能|架构'),
    ):
        if re.search(pattern, question, re.I):
            return category
    return 'other'


def error_fields(error):
    """Classify errors without serializing exception messages, URLs or response bodies."""
    kind = type(error).__name__
    result = {'error_type': kind if re.fullmatch(r'[A-Za-z0-9_]{1,80}', kind) else 'Exception'}
    current = error
    for _ in range(5):
        name = type(current).__name__
        status = getattr(current, 'status_code', None)
        if status is None:
            status = getattr(getattr(current, 'response', None), 'status_code', None)
        if isinstance(status, int) and 100 <= status <= 599:
            return {**result, 'error_code': 'upstream_http', 'upstream_status': status}
        if 'Timeout' in name:
            return {**result, 'error_code': 'timeout'}
        if name in ('ConnectError', 'APIConnectionError', 'NetworkError', 'RemoteProtocolError'):
            return {**result, 'error_code': 'connection'}
        if isinstance(current, json.JSONDecodeError):
            return {**result, 'error_code': 'invalid_json'}
        if isinstance(current, ValueError) and str(current) in _VALIDATION:
            return {**result, 'error_code': _VALIDATION[str(current)]}
        current = current.__cause__
        if current is None:
            break
    return {**result, 'error_code': 'unexpected'}


class JSONFormatter(logging.Formatter):
    def __init__(self, timezone):
        super().__init__()
        self.timezone = timezone

    def format(self, record):
        data = {'timestamp': datetime.fromtimestamp(record.created, self.timezone).isoformat(timespec='milliseconds'),
                'level': record.levelname, 'event': record.getMessage(), 'pid': os.getpid(),
                **getattr(record, 'operation_fields', {})}
        return json.dumps(data, ensure_ascii=False, allow_nan=False)


class DailyFiles(logging.Handler):
    """Each worker writes its own files; date + size rotation and finite retention."""
    def __init__(self, directory, timezone, days=30, max_bytes=20*1024*1024):
        super().__init__()
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.timezone, self.days, self.max_bytes = timezone, days, max_bytes
        self.day, self.writer = None, None

    def emit(self, record):
        try:
            day = datetime.fromtimestamp(record.created, self.timezone).date()
            if self.day != day:
                if self.writer:
                    self.writer.close()
                filename = self.directory / f'app-{day.isoformat()}-{os.getpid()}.jsonl'
                fd = os.open(filename, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
                os.close(fd)
                self.writer = RotatingFileHandler(filename, maxBytes=self.max_bytes, backupCount=4, encoding='utf-8')
                self.writer.setFormatter(self.formatter)
                self.day = day
                cutoff = (day - timedelta(days=self.days-1)).isoformat()
                for path in self.directory.iterdir():
                    match = re.fullmatch(r'app-(\d{4}-\d{2}-\d{2})-\d+\.jsonl(?:\.[1-4])?', path.name)
                    if match and match[1] < cutoff and path.is_file() and not path.is_symlink():
                        path.unlink()
            self.writer.emit(record)
            # RotatingFileHandler creates a new file after size rollover.
            os.chmod(self.writer.baseFilename, 0o600)
        except Exception:
            # The parallel stdout record remains available if file storage fails.
            if not getattr(self, '_failed', False):
                self._failed = True
                import sys
                print('Operational log file write failed; inspect stdout logs and disk permissions.', file=sys.stderr)

    def close(self):
        if self.writer:
            self.writer.close()
        super().close()


def configure(directory=None):
    with _lock:
        if _log.handlers:
            return
        timezone = ZoneInfo(os.getenv('LOG_TIMEZONE', 'Asia/Shanghai'))
        days = int(os.getenv('LOG_RETENTION_DAYS', '30'))
        if not 1 <= days <= 365:
            raise ValueError('LOG_RETENTION_DAYS must be 1..365')
        formatter = JSONFormatter(timezone)
        stream = logging.StreamHandler()
        stream.setFormatter(formatter)
        _log.addHandler(stream)
        _log.setLevel(logging.INFO)
        _log.propagate = False
        for name in ('httpx','httpcore','openai'):
            logging.getLogger(name).setLevel(logging.WARNING)
        directory = directory or os.getenv('LOG_DIR')
        if directory:
            try:
                files = DailyFiles(directory, timezone, days)
                files.setFormatter(formatter)
                _log.addHandler(files)
            except OSError:
                event('log_storage_unavailable', level='ERROR')
        event('logging_configured', retention_days=days, timezone=str(timezone))


def event(name, level='INFO', **fields):
    # Call sites supply metadata only. Never pass request bodies or exception strings.
    _log.log(getattr(logging, level), name, extra={'operation_fields': {**_context.get(), **fields}})
