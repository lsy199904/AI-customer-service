"""Metadata-only operational logs plus explicitly enabled local debug snapshots."""
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
import time
from zoneinfo import ZoneInfo

_context = ContextVar('operation_log_context', default={})
_log = logging.getLogger('assistant.operations')
_debug_log = logging.getLogger('assistant.debug_content')
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
        if name=='RequestCancelled':return {**result,'error_code':'cancelled'}
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
        if hasattr(record,'operation_document'):
            return json.dumps(record.operation_document,ensure_ascii=False,allow_nan=False)
        data = {'timestamp': datetime.fromtimestamp(record.created, self.timezone).isoformat(timespec='milliseconds'),
                'level': record.levelname, 'event': record.getMessage(), 'pid': os.getpid(),
                **getattr(record, 'operation_fields', {})}
        return json.dumps(data, ensure_ascii=False, allow_nan=False)


class DailyFiles(logging.Handler):
    """Each worker writes its own files; date + size rotation and finite retention."""
    def __init__(self, directory, timezone, days=30, max_bytes=20*1024*1024, prefix='app'):
        super().__init__()
        if prefix not in ('app','debug'):raise ValueError('invalid log prefix')
        self.prefix = prefix
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
                filename = self.directory / f'{self.prefix}-{day.isoformat()}-{os.getpid()}.jsonl'
                fd = os.open(filename, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
                os.close(fd)
                self.writer = RotatingFileHandler(filename, maxBytes=self.max_bytes, backupCount=4, encoding='utf-8')
                self.writer.setFormatter(self.formatter)
                self.day = day
                policies={self.prefix:self.days}
                if self.prefix=='app':
                    # Purge expired content even after content collection is disabled.
                    policies['debug']=max(1,min(30,int(os.getenv('LOG_DEBUG_RETENTION_DAYS','3'))))
                from .conversation_logs import prune_conversations
                prune_conversations(self.directory,day,int(os.getenv('LOG_RETENTION_DAYS','30')),max(1,min(30,int(os.getenv('LOG_DEBUG_RETENTION_DAYS','3')))))
                for path in self.directory.iterdir():
                    match = re.fullmatch(r'(app|debug)-(\d{4}-\d{2}-\d{2})-\d+\.jsonl(?:\.[1-4])?', path.name)
                    if not match or match[1] not in policies:continue
                    cutoff=(day-timedelta(days=policies[match[1]]-1)).isoformat()
                    if match[2]<cutoff and path.is_file() and not path.is_symlink():path.unlink()
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
    from .conversation_logs import ConversationFiles,conversation_parts
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
        stream.addFilter(BufferedSteps())
        _log.addHandler(stream)
        _log.setLevel(logging.INFO)
        _log.propagate = False
        for name in ('httpx','httpcore','openai'):
            logging.getLogger(name).setLevel(logging.WARNING)
        directory = directory or os.getenv('LOG_DIR')
        if directory:
            try:
                files = DailyFiles(directory, timezone, days)
                files.setFormatter(formatter);files.addFilter(BufferedSteps())
                from .conversation_logs import ConversationFiles,conversation_parts
                files.addFilter(lambda record:conversation_parts(getattr(record,'operation_document',None)) is None)
                conversations=ConversationFiles(directory,timezone)
                conversations.setFormatter(formatter);_log.addHandler(conversations)
                _log.addHandler(files)
            except OSError:
                event('log_storage_unavailable', level='ERROR')
        event('logging_configured', retention_days=days, timezone=str(timezone))
        if os.getenv('LOG_DEBUG_CONTENT','false').lower()=='true':
            debug_days=int(os.getenv('LOG_DEBUG_RETENTION_DAYS','3'))
            if not 1<=debug_days<=30:raise ValueError('LOG_DEBUG_RETENTION_DAYS must be 1..30')
            _debug_log.setLevel(logging.INFO);_debug_log.propagate=False
            if directory:
                try:
                    debug_files=ConversationFiles(directory,timezone,content=True)
                    debug_files.setFormatter(formatter);debug_files.addFilter(BufferedSteps());_debug_log.addHandler(debug_files)
                    unassigned=DailyFiles(directory,timezone,debug_days,prefix='debug')
                    unassigned.setFormatter(formatter);unassigned.addFilter(BufferedSteps())
                    unassigned.addFilter(lambda record:conversation_parts(getattr(record,'operation_document',None)) is None)
                    _debug_log.addHandler(unassigned)
                    event('debug_logging_enabled',retention_days=debug_days)
                except OSError:event('debug_log_storage_unavailable',level='ERROR')
            else:event('debug_log_storage_unavailable',level='ERROR')


def event(name, level='INFO', **fields):
    # Call sites supply metadata only. Never pass request bodies or exception strings.
    values={**_context.get(),**fields}
    trace=_trace.get()
    if trace is not None:trace.record(name,values,level)
    _log.log(getattr(logging,level),name,extra={'operation_fields':values,'request_buffered':trace is not None})


def debug_event(name, **fields):
    """Opt-in bounded content snapshots, only in local debug files; never stdout."""
    if os.getenv('LOG_DEBUG_CONTENT','false').lower()!='true' or not _debug_log.handlers:
        return
    trace=_trace.get()
    if trace is not None:
        trace.snapshot(name,fields)
        return
    try:
        snapshot=json.dumps(fields,ensure_ascii=False,default=lambda value:'<'+type(value).__name__+'>')
        for key,value in os.environ.items():
            if value and len(value)>=8 and re.search(r'SECRET|PASSWORD|TOKEN|API_KEY|PRIVATE_KEY|DATABASE_URL|AUTHORIZATION',key,re.I):
                snapshot=snapshot.replace(value,'[REDACTED]')
        snapshot=re.sub(r'(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+',r'\1[REDACTED]',snapshot)
        snapshot=re.sub(r'(?i)(https?://)[^\s/@]+:[^\s/@]+@',r'\1[REDACTED]@',snapshot)
        snapshot=re.sub(r'(?i)([?&](?:token|api_key|key|password|secret|authorization)=)[^&\s"\\]+',r'\1[REDACTED]',snapshot)
        limit=16000
        truncated=len(snapshot)>limit
        _debug_log.info(name,extra={'operation_fields':{**_context.get(),'snapshot':snapshot[:limit],'truncated':truncated},'request_buffered':trace is not None})
    except Exception:
        event('debug_snapshot_failed',level='WARNING')


# A shared mutable buffer is propagated to sync workers and SSE tasks through ContextVar.
_trace = ContextVar('request_trace', default=None)
_NODE_NAMES = {
    'chat_started':'接收问题','question_classified':'问题分类',
    'retrieval_model_started':'检索模型调用开始','retrieval_model_completed':'检索模型调用完成',
    'retrieval_model_failed':'检索模型调用失败','retrieval_completed':'知识检索完成',
    'retrieval_failed':'知识检索失败','model_request_started':'回答模型调用开始',
    'model_request_completed':'回答模型调用完成','model_request_failed':'回答模型调用失败',
    'answer_repair_started':'回答格式修复开始','answer_repair_completed':'回答格式修复成功',
    'answer_repair_failed':'回答格式修复失败','model_json_mode_unsupported':'模型接口不支持JSON模式',
    'model_first_token':'模型首段文字到达','response_assembled':'回复与配图组装完成',
    'model_finish':'模型结束原因','model_usage':'模型用量',
    'answer_validation_completed':'回答格式和引用校验通过','answer_validation_failed':'回答格式或引用校验失败',
    'generation_completed':'生成完成','generation_failed':'生成失败',
    'final_validation_completed':'最终内容校验','response_persist_started':'保存问答开始',
    'response_persist_completed':'保存问答完成','response_persist_failed':'保存问答失败',
    'chat_cache_hit':'复用已保存回答','chat_completed':'问答结束','chat_failed':'问答异常',
    'response_ready':'回复准备完成','stream_completed':'流式发送完成',
    'stream_cancelled':'流式发送中断','stream_failed':'流式发送失败','http_completed':'HTTP发送结果',
    'chat_input':'用户输入','retrieval_evidence':'命中知识内容','model_input':'模型输入',
    'model_output':'模型原始返回','answer_validation_context':'校验失败上下文',
    'answer_validated':'校验后回答','chat_output':'最终回答',
}

_DETAIL_NAMES={
    'intent':'问题意图','matched':'是否命中','similarity':'向量相似度','threshold':'相似度门槛',
    'title_matched':'标题匹配','evidence_count':'命中数量','evidence_ids':'知识编号',
    'rerank_scores':'重排分数','history_messages':'历史消息数','question_chars':'问题字数',
    'outcome':'处理结果','reason':'原因','model_stage':'模型阶段','answerable':'模型判断可回答',
    'max_tokens':'最大输出Token','history_and_prompt_messages':'模型输入消息数','finish_reason':'模型结束原因',
    'response_chars':'模型返回字数','answer_chars':'回复字数','elapsed_ms':'耗时毫秒',
    'error_code':'错误分类','error_type':'异常类型','upstream_status':'上游HTTP状态',
    'status':'HTTP状态','completed':'发送完成','success':'成功','citations':'引用数量',
    'selected_count':'选中知识数','image_count':'图片数量','suggestion_count':'推荐问题数',
}


class BufferedSteps(logging.Filter):
    def filter(self, record):
        return not getattr(record,'request_buffered',False)


def _safe_snapshot(fields):
    value=json.dumps(fields,ensure_ascii=False,default=lambda item:'<'+type(item).__name__+'>')
    for key,secret in os.environ.items():
        if secret and len(secret)>=8 and re.search(r'SECRET|PASSWORD|TOKEN|API_KEY|PRIVATE_KEY|DATABASE_URL|AUTHORIZATION',key,re.I):
            value=value.replace(secret,'[REDACTED]')
    value=re.sub(r'(?i)(Bearer\s+)[A-Za-z0-9._~+/-]+',r'\1[REDACTED]',value)
    value=re.sub(r'(?i)(https?://)[^\s/@]+:[^\s/@]+@',r'\1[REDACTED]@',value)
    value=re.sub(r'(?i)([?&](?:token|api_key|key|password|secret|authorization)=)[^&\s"\\]+',r'\1[REDACTED]',value)
    if len(value)>16000:return {'内容':value[:16000],'已截断':True}
    return json.loads(value)


class RequestTrace:
    def __init__(self):
        self.time=datetime.now(ZoneInfo(os.getenv('LOG_TIMEZONE','Asia/Shanghai'))).isoformat(timespec='milliseconds')
        self.started=time.monotonic()
        self.lock=threading.RLock();self.closed=False;self.steps=[];self.raw_steps=[];self.truncated=False
        self.input={};self.output={};self.metadata={};self.failures=[]
        self.content=os.getenv('LOG_DEBUG_CONTENT','false').lower()=='true'

    def record(self,name,fields,level='INFO'):
        with self.lock:
            if self.closed:return
            for key in ('http_request_id','request_id','session_ref','window_id','tenant_ref','user_ref','question_category'):
                if fields.get(key) is not None:self.metadata[key]=fields[key]
            details={_DETAIL_NAMES.get(key,key):value for key,value in fields.items() if key not in self.metadata}
            if len(self.steps)<80:
                self.steps.append({'节点':_NODE_NAMES.get(name,name),'事件':name,'级别':level,
                                   '开始后毫秒':round((time.monotonic()-self.started)*1000,2),'详情':details})
            else:self.truncated=True
            if name.endswith('_failed') or name in ('stream_cancelled','api_rejected') or (name=='http_completed' and isinstance(fields.get('status'),int) and fields['status']>=400):
                self.failures.append({'节点':_NODE_NAMES.get(name,name),'错误分类':fields.get('error_code',name),
                                      '异常类型':fields.get('error_type')})
            if name=='chat_completed':self.output.update({'状态':fields.get('outcome'),'原因':fields.get('reason'),'耗时毫秒':fields.get('elapsed_ms')})
            if name=='http_completed':self.output.update({'HTTP状态':fields.get('status'),'发送完成':fields.get('completed')})

    def snapshot(self,name,fields):
        if not self.content:return
        with self.lock:
            if self.closed:return
            value=_safe_snapshot(fields)
            if name=='chat_input':self.input={'问题':value.get('question',value)}
            elif name=='chat_output':self.output['最终响应']=value.get('response',value)
            elif len(self.raw_steps)<12:
                self.raw_steps.append({'节点':_NODE_NAMES.get(name,name),'事件':name,'数据':value,'序号':len(self.steps)})
            else:self.truncated=True

    def finish(self):
        with self.lock:
            if self.closed:return
            self.closed=True
            metadata_input={'请求编号':self.metadata.get('request_id') or self.metadata.get('http_request_id'),
                            '接口请求编号':self.metadata.get('http_request_id'),
                            '会话编号':self.metadata.get('session_ref'),'窗口编号':self.metadata.get('window_id'),
                            '企业标识':self.metadata.get('tenant_ref'),'用户标识':self.metadata.get('user_ref'),
                            '问题分类':self.metadata.get('question_category')}
            safe_output={key:value for key,value in self.output.items() if key!='最终响应'}
            if self.failures:
                recovered=self.output.get('状态')=='answered' and any(step.get('事件')=='answer_repair_completed' for step in self.steps)
                safe_output['已恢复异常' if recovered else '失败节点']=self.failures[0]
            if self.truncated:safe_output['流程已截断']=True
            if '状态' not in safe_output:safe_output['状态']='未完成'
            # Keep ordinary files and stdout content-free, but still one JSON per request.
            document={'时间':self.time,'输入':metadata_input,'处理流程':self.steps,'输出':safe_output}
            _log.info('request_completed',extra={'operation_document':document,'operation_fields':dict(self.metadata)})
            if self.content and _debug_log.handlers:
                steps=[];raw=list(self.raw_steps)
                for index,step in enumerate(self.steps):
                    while raw and raw[0]['序号']<=index:
                        item=raw.pop(0);item.pop('序号',None);steps.append(item)
                    steps.append(step)
                for item in raw:item.pop('序号',None);steps.append(item)
                full={'时间':self.time,'输入':{**metadata_input,**self.input},'处理流程':steps,
                      '输出':{**safe_output,**({'最终响应':self.output['最终响应']} if '最终响应' in self.output else {})}}
                _debug_log.info('request_completed',extra={'operation_document':full,'operation_fields':dict(self.metadata)})


@contextmanager
def capture_request(enabled=True):
    current=_trace.get()
    if current is not None or not enabled:
        yield current
        return
    trace=RequestTrace();token=_trace.set(trace)
    try:yield trace
    finally:
        try:trace.finish()
        finally:_trace.reset(token)
