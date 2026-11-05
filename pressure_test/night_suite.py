"""Scheduled load suite: pacing, quota boundary, then bounded concurrent waves."""
import argparse, concurrent.futures as cf, json, pathlib, threading, time
from load_test import sample, summarize


def run_phase(base, tokens, questions, timeout, count, concurrency, interval):
    gate=threading.Event(); lock=threading.Lock(); active=0; peak=0
    def work(i):
        nonlocal active,peak
        gate.wait()
        with lock: active+=1; peak=max(peak,active)
        try:return sample(base,tokens[i%len(tokens)],questions[i%len(questions)],timeout)
        finally:
            with lock:active-=1
    rows=[]; started=time.monotonic()
    with cf.ThreadPoolExecutor(max_workers=concurrency) as pool:
        pending=[]
        if interval:
            gate.set()
            for i in range(count):
                delay=started+i*interval-time.monotonic()
                if delay>0:time.sleep(delay)
                pending.append(pool.submit(work,i))
        else:
            pending=[pool.submit(work,i) for i in range(count)]
            gate.set()
        for f in cf.as_completed(pending): rows.append(f.result())
    report=summarize(rows,time.monotonic()-started)
    report['observed_peak_client_requests']=peak
    return rows,report


def main():
    p=argparse.ArgumentParser()
    p.add_argument('--output',required=True)
    p.add_argument('--tokens-file',required=True)
    p.add_argument('--base-url',default='http://127.0.0.1:18200')
    a=p.parse_args()
    tokens=pathlib.Path(a.tokens_file).read_text().splitlines()
    if len(tokens)<102:raise SystemExit('需要102枚不同测试企业的令牌')
    questions=pathlib.Path(__file__).with_name('questions.txt').read_text().splitlines()
    out=pathlib.Path(a.output);out.mkdir(exist_ok=False,parents=True)
    phases=[('每企业20条每分钟',20,20,3,tokens[:1]),
            ('同企业21次限流边界',21,21,1,tokens[1:2])]
    phases += [(f'{n}并发',n,n,0,tokens[2:2+n]) for n in (5,10,20,50,100)]
    reports=[]
    with (out/'requests.jsonl').open('w') as log:
        for index,(name,count,c,interval,identities) in enumerate(phases):
            if index:time.sleep(65)
            print('开始：'+name,flush=True)
            rows,r=run_phase(a.base_url,identities,questions,90,count,c,interval)
            for row in rows:
                row['phase']=name;log.write(json.dumps(row,ensure_ascii=False)+'\n')
            log.flush()
            r.update(phase=name,concurrency=c,stopped_early=False)
            limited=sum(x.get('error') in ('http_429','rate_limited') for x in rows)
            if index==1:
                r['quota_boundary_pass']=limited==1 and sum(x.get('status') in ('answered','suggestions','handoff') for x in rows)==20
                r['quota_note']='需结合服务日志确认配额检查时点；请求序号不等于服务端到达顺序。'
            unexpected=sum(bool(x.get('error')) and not(index==1 and x.get('error') in ('http_429','rate_limited'))
                           or x.get('reason') in ('retrieval_timeout','retrieval_unavailable','model_error','model_timeout') for x in rows)
            stop=(unexpected/count>=.2 or (index!=1 and limited>0) or r['answered'] < (count-1 if index==1 else count)*.8)
            if index==1 and not r['quota_boundary_pass']:stop=True
            r['stopped_early']=stop
            reports.append(r)
            (out/'summary.json').write_text(json.dumps(reports,ensure_ascii=False,indent=2))
            print(json.dumps(r,ensure_ascii=False),flush=True)
            if stop:
                print('停止后续升压：错误/非正常回答达到20%，或限流边界不符合预期。',flush=True);break
    print('计划最高100并发；未执行的阶段不能视为通过。',flush=True)

if __name__=='__main__':main()
