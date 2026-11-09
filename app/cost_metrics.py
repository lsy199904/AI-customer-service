"""Per-call timing and explicitly non-attributable remote-container samples."""
from contextlib import contextmanager
from contextvars import ContextVar
from datetime import datetime
import json
import math
import os
import re
import threading
from pathlib import Path
import time
from zoneinfo import ZoneInfo

_prune_lock=threading.Lock()
_pruned_days=set()

_purpose = ContextVar('cost_model_purpose', default='planning')

@contextmanager
def purpose(value):
    token = _purpose.set(value)
    try:
        yield
    finally:
        _purpose.reset(token)


def model_purpose(streaming=False):
    from .evidence_selection import model_options
    return 'evidence_selection' if model_options() else 'answer' if streaming else _purpose.get()


def usage_counts(response):
    usage = getattr(response, 'usage_metadata', None)
    if not isinstance(usage, dict):
        usage = (getattr(response, 'response_metadata', {}) or {}).get('token_usage')
    if not isinstance(usage, dict):
        return None
    result = {}
    for target, aliases in {'input_tokens': ('input_tokens', 'prompt_tokens'),
                            'output_tokens': ('output_tokens', 'completion_tokens'),
                            'total_tokens': ('total_tokens',)}.items():
        value = next((usage[k] for k in aliases if k in usage), None)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            return None
        result[target] = value
    return result


def samples(stage):
    path = os.getenv('COST_RESOURCE_SAMPLES', 'var/cost-reports/resource-samples.json')
    try:
        with open(path, encoding='utf-8') as handle:
            data = json.loads(handle.read(2_000_001))
        rows = data.get(stage, [])
        return rows if isinstance(rows, list) else []
    except (OSError, ValueError, TypeError):
        return []


def resource_window(before, after, started, ended):
    """No division of shared process CPU/RAM between concurrent callers."""
    unavailable = {'scope': 'shared_container_sample_window', 'status': 'unavailable',
                   'reason': 'collector_missing_stale_or_call_shorter_than_sample_interval',
                   'cpu_seconds': None, 'cpu_percent_one_core': None,
                   'memory_peak_mib': None, 'sample_window_ms': None}
    # Boundaries can bracket the HTTP call by up to 3s; disclose actual window.
    valid = [r for r in before if isinstance(r, dict) and isinstance(r.get('timestamp'), (int, float))
             and started - 3 <= r['timestamp'] <= started]
    if not valid:
        return unavailable
    first = max(valid, key=lambda r: r['timestamp'])
    following = [r for r in after if isinstance(r, dict) and isinstance(r.get('timestamp'), (int, float))
                 and first['timestamp'] < r['timestamp'] <= ended and ended - r['timestamp'] <= 3]
    if not following:
        return unavailable
    last = max(following, key=lambda r: r['timestamp'])
    window = [r for r in after if first['timestamp'] <= r.get('timestamp', -1) <= last['timestamp']]
    if last['timestamp'] < started:
        return unavailable
    try:
        if any(r.get('container_id') != first['container_id'] for r in window + [last]):
            return {**unavailable, 'reason': 'container_restarted'}
        elapsed = last['timestamp'] - first['timestamp']
        cpu = (last['cpu_total_ns'] - first['cpu_total_ns']) / 1e9
        memory = max(r['memory_bytes'] for r in window + [first]) / 1024**2
        if cpu < 0 or elapsed <= 0 or not all(math.isfinite(v) for v in (cpu, memory)):
            return unavailable
        return {'scope': 'shared_container_sample_window', 'status': 'sampled',
                'attributable_to_request': False, 'container_id': first['container_id'],
                'cpu_seconds': round(cpu, 6), 'cpu_percent_one_core': round(cpu / elapsed * 100, 2),
                'memory_peak_mib': round(memory, 2), 'kernel_cpu_seconds': counter_delta(first,last,'kernel_cpu_ns'), 'user_cpu_seconds': counter_delta(first,last,'user_cpu_ns'), **gpu_window(window + [first]), 'sample_window_ms': round(elapsed * 1000, 2),
                'sample_start': first['timestamp'], 'sample_end': last['timestamp'],
                'reason': 'includes_model_residency_other_requests_and_background_work'}
    except (KeyError, TypeError, ValueError):
        return unavailable


@contextmanager
def inference(stage, model, workload=None):
    from uuid import uuid4
    from .observability import event
    call_id=uuid4().hex
    started = time.time(); clock = time.monotonic(); before = samples(stage)
    event('inference_cost_started',call_id=call_id,stage=stage,model=model,status='running',elapsed_ms=0)
    status = 'failed'
    try:
        yield
        status = 'completed'
    finally:
        # Instrumentation must never replace an inference result or exception.
        try:
            from .observability import event
            event('inference_cost', call_id=call_id, stage=stage, model=model, status=status, workload=workload or {},
                  elapsed_ms=round((time.monotonic()-clock)*1000, 2),
                  resources=resource_window(before, samples(stage), started, time.time()))
        except Exception:
            pass


def summarize(calls):
    llm = [r for r in calls if r.get('stage') == 'llm']
    known = [r for r in llm if isinstance(r.get('usage'), dict)]
    totals = {k: sum(r['usage'][k] for r in known)
              for k in ('input_tokens', 'output_tokens', 'total_tokens')}
    return {'llm': {'call_count': len(llm), 'usage_known_calls': len(known),
                    'usage_unknown_calls': len(llm)-len(known),
                    'usage_complete': len(known) == len(llm), 'running_calls':sum(r.get('status')=='running' for r in llm), 'known_token_totals': totals},
            'embedding': stage_summary(calls, 'embedding'),
            'rerank': stage_summary(calls, 'rerank'), 'calls': calls,
            'resource_note': 'CPU/RAM are shared container window samples, not exclusive per-question cost; do not sum across overlapping questions.'}


def stage_summary(calls, stage):
    rows = [r for r in calls if r.get('stage') == stage]
    measured = [r['resources'] for r in rows if r.get('resources', {}).get('status') == 'sampled']
    return {'call_count': len(rows), 'failed_calls': sum(r.get('status') != 'completed' for r in rows),
            'http_elapsed_ms': round(sum(r['elapsed_ms'] for r in rows), 2),
            'sampled_calls': len(measured), 'unmeasured_calls': len(rows)-len(measured),
            'container_memory_peak_mib': max((r['memory_peak_mib'] for r in measured), default=None)}


def save_request(timestamp, metadata, output, summary):
    if os.getenv('COST_REPORT_ENABLED', 'true').lower() != 'true':
        return
    directory = Path(os.getenv('COST_REPORT_DIR', 'var/cost-reports'))
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    day = datetime.now(ZoneInfo(os.getenv('LOG_TIMEZONE', 'Asia/Shanghai'))).date().isoformat()
    prune(directory,day)
    record = {'schema_version': 1, 'timestamp': timestamp,
              'request_id': metadata.get('request_id') or metadata.get('http_request_id'),
              'http_request_id': metadata.get('http_request_id'),
              'session_ref': metadata.get('session_ref'), 'outcome': output.get('状态'),
              'request_elapsed_ms': output.get('耗时毫秒'), 'metrics': summary,
              'recorded_at':time.time()}
    encoded = (json.dumps(record, ensure_ascii=False, allow_nan=False)+'\n').encode()
    # Each worker owns its daily file; no credentials, prompts, or customer text.
    fd = os.open(directory / f'cost-{day}-{os.getpid()}.jsonl',
                 os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
    try:
        if os.write(fd, encoded) != len(encoded):
            raise OSError('incomplete cost record')
    finally:
        os.close(fd)


def gpu_window(rows):
    memory=[r['gpu_process_memory_mib'] for r in rows if isinstance(r.get('gpu_process_memory_mib'),(int,float))]
    cards={}
    for row in rows:
        for card in row.get('gpus',[]):
            cards.setdefault(card['uuid'],[]).append(card)
    summary=[]
    for uuid,values in cards.items():
        item={'uuid':uuid,'scope':'shared_physical_gpu'}
        for field in ('utilization_percent','memory_utilization_percent','memory_used_mib','power_w','temperature_c'):
            numbers=[c[field] for c in values if isinstance(c.get(field),(int,float))]
            item[field+'_peak']=max(numbers,default=None)
            item[field+'_mean']=round(sum(numbers)/len(numbers),2) if numbers else None
        summary.append(item)
    return {'gpu_process_memory_peak_mib':max(memory,default=None),'gpu_cards':summary}


def counter_delta(first,last,key):
    a,b=first.get(key),last.get(key)
    return round((b-a)/1e9,6) if isinstance(a,(int,float)) and isinstance(b,(int,float)) and b>=a else None


def prune(directory,day):
    from datetime import timedelta,date
    with _prune_lock:
        key=(str(directory),day)
        if key in _pruned_days:return
        days=max(1,min(365,int(os.getenv('COST_RETENTION_DAYS','30'))))
        cutoff=(date.fromisoformat(day)-timedelta(days=days-1)).isoformat()
        for path in directory.glob('cost-*.jsonl'):
            match=re.fullmatch(r'cost-(\d{4}-\d{2}-\d{2})-\d+\.jsonl',path.name)
            if match and match[1]<cutoff and path.is_file() and not path.is_symlink():path.unlink()
        _pruned_days.clear();_pruned_days.add(key)
