#!/usr/bin/env python3
"""Five serial customer questions with host/container GPU or CPU observations."""
import argparse
import csv
import importlib.util
import json
import os
from pathlib import Path
import statistics
import threading
import time
import urllib.request
import uuid

from resource_probe import Probe, publish

ROOT = Path(__file__).resolve().parents[1]
QUESTIONS = ['注册流程是什么', '我想知道api如何创建', '如何联系人工', '我当前的星级是多少？', '如何开发票']


def http_json(base, path, token=None, payload=None, timeout=120):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer '+token
    req = urllib.request.Request(base+path, data=json.dumps(payload or {}).encode(), headers=headers, method='POST')
    with urllib.request.urlopen(req, timeout=timeout) as response:
        return json.load(response)


def ask(base, token, question, request_id, timeout=120):
    session = http_json(base, '/v1/sessions', token, {'context': {'page_title': 'GPU/CPU资源对照测试'}})
    payload = {'message': question, 'request_id': request_id}
    req = urllib.request.Request(base+'/v1/sessions/'+session['session_id']+'/messages/stream',
        data=json.dumps(payload).encode(), headers={'Content-Type':'application/json',
        'Authorization':'Bearer '+token, 'X-Request-ID':request_id}, method='POST')
    started = time.monotonic(); first = None; events = 0; kind = ''; parts = []
    with urllib.request.urlopen(req, timeout=timeout) as response:
        if 'text/event-stream' not in response.headers.get('Content-Type', ''):
            raise RuntimeError('not_sse')
        for raw in response:
            if time.monotonic()-started > timeout:
                raise TimeoutError('total_stream_deadline')
            line = raw.decode().rstrip('\r\n')
            if line.startswith('event:'):
                kind = line[6:].strip()
            elif line.startswith('data:'):
                parts.append(line[5:].lstrip())
            elif not line and parts:
                data = json.loads('\n'.join(parts)); parts = []
                if kind == 'delta' and data.get('text'):
                    events += 1
                    if first is None:
                        first = time.monotonic()-started
                elif kind == 'error':
                    raise RuntimeError('sse_error_'+str(data.get('code','unknown')))
                elif kind == 'complete':
                    return {'session_id':session['session_id'], 'status':data.get('status'),
                        'reason':data.get('reason'), 'answer':data.get('answer',''),
                        'ttft_ms':None if first is None else round(first*1000,2),
                        'sse_ms':round((time.monotonic()-started)*1000,2), 'delta_events':events}
    raise RuntimeError('incomplete_stream')


def find_cost(directory, request_id):
    # Small test runs only: inspect newest worker files, never customer debug logs.
    result=None
    for path in sorted(Path(directory).glob('cost-*.jsonl'), reverse=True):
        with path.open() as handle:
            for line in handle:
                try:
                    item=json.loads(line)
                    if item.get('request_id') == request_id or item.get('http_request_id') == request_id:
                        if result is None or item.get('recorded_at',0)>=result.get('recorded_at',0):result=item
                except ValueError:
                    continue
    return result


class Sampler:
    def __init__(self, probe, path, interval, archive):
        self.probe, self.path, self.interval, self.archive = probe,path,interval,archive
        self.rows = {'embedding':[], 'rerank':[]}; self.stop = threading.Event()
        self.error = None; self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.run, daemon=True)
    def run(self):
        try:
            with self.archive.open('a') as archive:
                while not self.stop.is_set():
                    started = time.monotonic()
                    data = self.probe.sample()
                    with self.lock:
                        for stage, row in data.items():
                            self.rows[stage].append(row)
                            self.rows[stage] = self.rows[stage][-180:]
                        publish(self.path, self.rows)
                    archive.write(json.dumps(data)+'\n'); archive.flush()
                    self.stop.wait(max(.05,self.interval-(time.monotonic()-started)))
        except Exception as error:
            self.error = type(error).__name__
    def snapshot(self):
        with self.lock:
            return {k:list(v) for k,v in self.rows.items()}


def display(value):
    return '未测得' if value is None else str(value)


def write_report(output, mode, rows, metadata, baseline, errors):
    valid = [r for r in rows if r.get('cost')]
    unknown = sum(r['cost']['metrics']['llm']['usage_unknown_calls'] for r in valid)
    totals = {k:sum(r['cost']['metrics']['llm']['known_token_totals'][k] for r in valid)
              for k in ('input_tokens','output_tokens','total_tokens')}
    report = f'# {mode.upper()} 五题资源对照报告\n\n'
    report += f'测试题数：{len(rows)}；匹配到请求统计文件：{len(valid)}；LLM用量未知调用：{unknown}。\n\n'
    report += f'已知Token：输入{totals["input_tokens"]}，输出{totals["output_tokens"]}，合计{totals["total_tokens"]}。缺失统计不按0计入完整总成本。\n\n'
    report += '此报告为5题串行观测，不代表并发上限。CPU100%表示占用1个逻辑核，平均占用核数=CPU核秒÷采样秒数；并不是Linux内核占用。内存包含常驻模型，不能按问题累加。GPU利用率、显存带宽利用率、功耗与温度为关联整卡共享采样，不是模型独占；模型进程显存可按容器进程映射。短调用可能没有足够采样，显示未测得。\n\n'
    report += '| 问题 | 结果 | 总耗时ms | 首字ms | LLM已知输入/输出 | 未知调用数 |\n|---|---|---:|---:|---|---:|\n'
    for row in rows:
        cost = row.get('cost'); llm = cost['metrics']['llm'] if cost else None
        tokens = f'{llm["known_token_totals"]["input_tokens"]}/{llm["known_token_totals"]["output_tokens"]}' if llm else '未知'
        report += f'| {row["question"]} | {row.get("status") or row.get("error")} | {display(row.get("total_ms"))} | {display(row.get("ttft_ms"))} | {tokens} | {llm["usage_unknown_calls"] if llm else "未知"} |\n'
    csvrows=[]
    for row in rows:
        report += f'\n## {row["question"]}\n\n'
        if not row.get('cost'):
            report += '没有匹配到请求统计：先确认统计代码已部署、目录映射一致及请求日志已落盘。资源值不替代缺失的调用记录。\n'
            continue
        calls = row['cost']['metrics']['calls']
        report += '| 阶段 | 模型 | 输入/候选数 | HTTP耗时ms | CPU核秒 | 平均核数 | CPU%（1核=100%） | 内存峰值MiB | 模型显存峰值MiB |\n|---|---|---:|---:|---:|---:|---:|---:|---:|\n'
        for call in calls:
            if call.get('stage') == 'llm':
                continue
            resource = call.get('resources',{})
            cpu = resource.get('cpu_percent_one_core')
            cores = round(cpu/100,3) if cpu is not None else None
            workload_count=call.get('workload',{}).get('document_count' if call['stage']=='rerank' else 'input_count','未知')
            report += f'| {call["stage"]} | {call.get("model", "")} | {workload_count} | {call["elapsed_ms"]} | {display(resource.get("cpu_seconds"))} | {display(cores)} | {display(cpu)} | {display(resource.get("memory_peak_mib"))} | {display(resource.get("gpu_process_memory_peak_mib"))} |\n'
            csvrows.append({'question':row['question'], 'request_id':row['request_id'], 'mode_label':mode,
                'stage':call['stage'], 'model':call.get('model'), 'input_count':call.get('workload',{}).get('input_count'), 'candidate_count':call.get('workload',{}).get('document_count'), 'http_ms':call['elapsed_ms'],
                'resource_status':resource.get('status'), 'cpu_seconds':resource.get('cpu_seconds'),
                'average_cpu_cores':cores, 'cpu_percent_one_core':cpu,
                'memory_peak_mib':resource.get('memory_peak_mib'),
                'model_gpu_memory_peak_mib':resource.get('gpu_process_memory_peak_mib'),
                'sampling_window_ms':resource.get('sample_window_ms')})
            report += '\n资源范围：'+resource.get('reason','unknown')+'；采样窗口ms：'+display(resource.get('sample_window_ms'))+'。\n\n'
            for card in resource.get('gpu_cards',[]):
                report += f'- GPU {card["uuid"]}：整卡GPU利用率平均/峰值 {card.get("utilization_percent_mean")}/{card.get("utilization_percent_peak")}%；显存带宽利用率峰值 {card.get("memory_utilization_percent_peak")}%；整卡显存峰值 {card.get("memory_used_mib_peak")} MiB；功耗平均/峰值 {card.get("power_w_mean")}/{card.get("power_w_peak")} W；温度峰值 {card.get("temperature_c_peak")}℃。\n'
        for stage in ('embedding','rerank'):
            if not any(c.get('stage')==stage for c in calls):
                report += f'\n{stage}：本轮未调用（规则、人工或其他路径），不是模型性能为0。\n'
        report += '\n回答（供人工核对）：\n\n'+row.get('answer','').replace('\n','\n\n')+'\n'
    report += '\n## 空闲基线与部署信息\n\n'
    report += 'GPU/CPU是运行时人工指定的测试标签，不自动证明推理后端；切换后核对模型服务配置、DeviceRequests和实际GPU进程。共享Ollama容器可能包含其他模型，记录的是整个容器资源。\n\n'
    report += '```json\n'+json.dumps({'deployment':metadata,'idle_baseline':baseline,'sampling_errors':errors},ensure_ascii=False,indent=2)+'\n```\n'
    report += '\n本地脚本报告完成不代表业务答案正确；CPU/GPU对比应保持模型权重、参数、知识库、候选数与LLM配置一致。5题样本不适合用P95推断容量；扩展样本后再计算稳定分位数。\n'
    (output/'报告.md').write_text(report)
    (output/'results.json').write_text(json.dumps({'mode':mode,'rows':rows,'deployment':metadata,'idle_baseline':baseline,'sampling_errors':errors},ensure_ascii=False,indent=2))
    if csvrows:
        with (output/'resources.csv').open('w',encoding='utf-8-sig',newline='') as handle:
            writer=csv.DictWriter(handle, fieldnames=list(csvrows[0]));writer.writeheader();writer.writerows(csvrows)


def write_comparison(previous,current,target):
    before=json.loads(Path(previous).read_text());after=json.loads(Path(current).read_text())
    if before.get('mode')!='gpu' or after.get('mode')!='cpu':
        raise ValueError('comparison requires GPU baseline then CPU test')
    lookup={r['question']:r for r in before['rows']}
    text='# GPU / CPU 五题对照\n\n同题不保证检索候选相同，请检查调用数量、候选数及答案。只有5题，不推断并发容量。\n\n'
    text+='| 问题 | 阶段 | GPU耗时ms | CPU耗时ms | CPU/GPU耗时倍数 |\n|---|---|---:|---:|---:|\n'
    for row in after['rows']:
        old=lookup.get(row['question'],{})
        for stage in ('embedding','rerank'):
            def duration(r):
                calls=(r.get('cost') or {}).get('metrics',{}).get('calls',[])
                data=[c['elapsed_ms'] for c in calls if c.get('stage')==stage and c.get('status')=='completed']
                return sum(data) if data else None
            a,b=duration(old),duration(row)
            ratio=round(b/a,2) if a and b is not None else None
            text+=f'| {row["question"]} | {stage} | {display(a)} | {display(b)} | {display(ratio)} |\n'
    text+='\n未调用或缺失不是0。资源详情分别见两次报告及CSV；不得将共享容器CPU窗口求和后当作独占成本。\n'
    Path(target).write_text(text)


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mode',choices=('gpu','cpu'),required=True)
    parser.add_argument('--base-url',default='http://127.0.0.1:8200')
    parser.add_argument('--assistant-container',default='ai_customer_v2-assistant-1')
    parser.add_argument('--embedding-container',default='ollama')
    parser.add_argument('--rerank-container',default='qwen3-reranker-4b')
    parser.add_argument('--docker-socket',default='/var/run/docker.sock')
    parser.add_argument('--cost-dir',default=str(ROOT/'var/cost-reports'))
    parser.add_argument('--samples-file',default=str(ROOT/'var/cost-reports/resource-samples.json'))
    parser.add_argument('--interval',type=float,default=.1)
    parser.add_argument('--baseline-seconds',type=float,default=10)
    parser.add_argument('--cooldown',type=float,default=3)
    parser.add_argument('--output')
    parser.add_argument('--compare-with',help='GPU报告目录或results.json，生成逐题CPU/GPU对比')
    args=parser.parse_args()
    from urllib.parse import urlsplit
    parsed=urlsplit(args.base_url)
    if parsed.scheme not in ('http','https') or not parsed.hostname or parsed.username or parsed.query or parsed.fragment:
        parser.error('invalid base URL')
    if args.interval<.05 or args.baseline_seconds<2 or args.cooldown<0:
        parser.error('interval>=0.05, baseline>=2, cooldown>=0 required')
    # Existing anonymous identity API; no AUTH_SECRET, synthetic tenant or new auth endpoint.
    token=http_json(args.base_url.rstrip('/'),'/widget/anonymous-auth')['token']
    probe=Probe({'embedding':args.embedding_container,'rerank':args.rerank_container}, args.docker_socket)
    metadata=probe.describe()  # fail before testing if containers cannot be observed
    assistant=probe.get('/containers/'+args.assistant_container+'/json')
    allowed={'EMBEDDING_MODEL','EMBEDDING_REVISION','RERANK_MODEL','RERANK_ENABLED','RERANK_MIN_SCORE','SEMANTIC_MIN_SIMILARITY','MODEL_NAME','RETRIEVAL_BACKEND','COST_REPORT_ENABLED','COST_REPORT_DIR','COST_RESOURCE_SAMPLES'}
    metadata['assistant']={'container_id':assistant.get('Id'), 'image':assistant.get('Config',{}).get('Image'),
       'configuration':dict(value.split('=',1) for value in assistant.get('Config',{}).get('Env',[]) if value.split('=',1)[0] in allowed)}
    output=Path(args.output or ROOT/'var/model-benchmarks'/f'{args.mode}-{time.strftime("%Y%m%d-%H%M%S")}-{uuid.uuid4().hex[:6]}')
    output.mkdir(parents=True,exist_ok=False,mode=0o700)
    # A single sampler owns this shared file. Never silently overwrite another run.
    lock=Path(args.samples_file+'.lock');lock.parent.mkdir(parents=True,exist_ok=True)
    fd=os.open(lock,os.O_CREAT|os.O_EXCL|os.O_WRONLY,0o600);os.close(fd)
    sampler=Sampler(probe,args.samples_file,args.interval,output/'samples.jsonl')
    rows=[]; baseline={}
    try:
        print('采集空闲基线；会产生5次真实提问和独立会话。请避免其他测试并发。',flush=True)
        sampler.thread.start();time.sleep(args.baseline_seconds)
        idle=sampler.snapshot()
        for stage,samples in idle.items():
            baseline[stage]={'samples':len(samples),'cpu_percent_one_core':(round((samples[-1]['cpu_total_ns']-samples[0]['cpu_total_ns'])/1e9/(samples[-1]['timestamp']-samples[0]['timestamp'])*100,2) if len(samples)>1 else None),'memory_peak_mib':max((s['memory_bytes']/1024**2 for s in samples),default=None),
                             'gpu_process_memory_peak_mib':max((s['gpu_process_memory_mib'] for s in samples if s.get('gpu_process_memory_mib') is not None),default=None)}
        for index,question in enumerate(QUESTIONS,1):
            if sampler.error or any(not v for v in sampler.snapshot().values()):
                raise RuntimeError('sampler_unavailable')
            request_id='resource-'+args.mode+'-'+uuid.uuid4().hex
            row={'request_id':request_id,'question':question};started=time.monotonic()
            try:
                row.update(ask(args.base_url.rstrip('/'),token,question,request_id))
            except Exception as error:
                row['error']=type(error).__name__
            row['total_ms']=round((time.monotonic()-started)*1000,2)
            # Wait only for logging completion; never delays chatbot streaming.
            for attempt in range(50):
                row['cost']=find_cost(args.cost_dir,request_id)
                if row['cost'] and not any(c.get('status')=='running' for c in row['cost']['metrics']['calls']):
                    break
                time.sleep(.2)
            rows.append(row)
            write_report(output,args.mode,rows,metadata,baseline,probe.errors)
            print(f'{index}/5 {question}：{row.get("status") or row.get("error")}；统计'+('已匹配' if row['cost'] else '缺失'),flush=True)
            time.sleep(args.cooldown)
    finally:
        sampler.stop.set();sampler.thread.join(timeout=15)
        write_report(output,args.mode,rows,metadata,baseline,{**probe.errors,**({'sampler':sampler.error} if sampler.error else {})})
        if not sampler.thread.is_alive():
            Path(args.samples_file).unlink(missing_ok=True);lock.unlink(missing_ok=True)
    if args.compare_with:
        if args.compare_with=='latest':
            candidates=list((ROOT/'var/model-benchmarks').glob('gpu-*/results.json'))
            if not candidates:raise SystemExit('未找到GPU报告，请指定 --compare-with GPU报告目录')
            previous=max(candidates,key=lambda p:p.stat().st_mtime)
        else:previous=Path(args.compare_with)
        if previous.is_dir():previous=previous/'results.json'
        write_comparison(previous,output/'results.json',output/'GPU_CPU对比.md')
    print('报告：'+str(output/'报告.md'),flush=True)
    if len(rows)!=5 or any(not r.get('cost') or r.get('error') for r in rows):
        raise SystemExit('测试不完整，报告已保存；请检查缺失统计，不要用于完整成本结论。')

if __name__=='__main__':
    main()
