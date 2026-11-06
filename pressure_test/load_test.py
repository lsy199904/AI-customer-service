#!/usr/bin/env python3
"""Bounded, dependency-free SmartTITU SSE load test. Python 3.9+."""
import argparse, concurrent.futures, collections, http.client, json, math
import pathlib, ssl, threading, time, uuid
from urllib.parse import urlsplit


def request(base, path, token, body, timeout, stream=False):
    u = urlsplit(base)
    cls = http.client.HTTPSConnection if u.scheme == 'https' else http.client.HTTPConnection
    conn = cls(u.hostname, u.port, timeout=timeout)
    started = time.monotonic()
    try:
        conn.request('POST', u.path.rstrip('/') + path, json.dumps(body).encode(),
                     {'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json',
                      'X-Request-ID': body.get('request_id', 'load-' + uuid.uuid4().hex)})
        response = conn.getresponse()
        if response.status != 200 and not (not stream and response.status == 201):
            return {'error': 'http_' + str(response.status), 'http': response.status}
        if not stream:
            return json.loads(response.read(1024 * 1024))
        if 'text/event-stream' not in response.getheader('Content-Type', ''):
            return {'error': 'not_sse', 'http': response.status}
        event, data, first, last, deltas = '', [], None, None, 0
        while True:
            remaining = timeout - (time.monotonic() - started)
            if remaining <= 0:
                raise TimeoutError('stream deadline')
            # HTTPResponse keeps the socket after Connection: close detaches conn.sock.
            sock = conn.sock or response.fp.raw._sock
            sock.settimeout(remaining)
            line = response.readline(1024 * 1024)
            if not line:
                return {'error': 'stream_incomplete', 'http': response.status}
            line = line.decode('utf-8').rstrip('\r\n')
            if line.startswith('event:'):
                event = line[6:].strip()
            elif line.startswith('data:'):
                data.append(line[5:].lstrip())
            elif not line and data:
                payload = json.loads('\n'.join(data)); data = []
                elapsed = time.monotonic() - started
                if event == 'delta' and payload.get('text'):
                    first = elapsed if first is None else first
                    last = elapsed; deltas += 1
                elif event == 'error':
                    return {'error': payload.get('code', 'sse_error'), 'http': response.status}
                elif event == 'complete':
                    return {'http': response.status, 'status': payload.get('status'),
                            'reason': payload.get('reason'), 'ttft_s': first,
                            'stream_span_s': None if first is None else last - first,
                            'delta_events': deltas, 'chat_s': elapsed,
                            'answer_chars': len(payload.get('answer', '')),
                            'citations': len(payload.get('citations', []))}
    finally:
        conn.close()


def sample(base, token, question, timeout):
    started = time.monotonic()
    row = {'request_id': 'load-' + uuid.uuid4().hex, 'question': question}
    try:
        session = request(base, '/v1/sessions', token, {'context': {'page_title': '压力测试'}}, timeout)
        if 'error' in session:
            row.update(session)
        else:
            row['session_id'] = session['session_id']
            row.update(request(base, '/v1/sessions/' + session['session_id'] + '/messages/stream',
                               token, {'message': question, 'request_id': row['request_id']}, timeout, True))
    except Exception as exc:
        # Do not log headers, tokens, response bodies or credentials.
        row['error'] = type(exc).__name__
    row['total_s'] = time.monotonic() - started
    return row


def percentile(values, p):
    values = sorted(v for v in values if v is not None)
    return round(values[max(0, math.ceil(len(values) * p) - 1)], 3) if values else None


def summarize(rows, elapsed):
    answered = [r for r in rows if r.get('status') == 'answered' and not r.get('error')]
    return {'requests': len(rows), 'answered': len(answered),
            'outcomes': dict(collections.Counter(r.get('error') or (str(r.get('status')) + ':' + str(r.get('reason'))) for r in rows)),
            'completed_rps': round(len(rows) / max(elapsed, .001), 3),
            'answered_rps': round(len(answered) / max(elapsed, .001), 3),
            'answered_ttft_p50_s': percentile([r.get('ttft_s') for r in answered], .5),
            'answered_ttft_p95_s': percentile([r.get('ttft_s') for r in answered], .95),
            'answered_total_p95_s': percentile([r['total_s'] for r in answered], .95),
            'all_total_p95_s': percentile([r['total_s'] for r in rows], .95),
            'answered_with_multiple_deltas': sum(r.get('delta_events', 0) > 1 for r in answered)}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--base-url', required=True)
    p.add_argument('--tokens-file', required=True, help='one valid test identity token per line')
    p.add_argument('--questions', default=str(pathlib.Path(__file__).with_name('questions.txt')))
    p.add_argument('--concurrency', default='1,2,5')
    p.add_argument('--requests', type=int, default=5, help='requests PER stage')
    p.add_argument('--timeout', type=float, default=90)
    p.add_argument('--cooldown', type=float, default=65)
    p.add_argument('--stop-failure-rate', type=float, default=.2)
    p.add_argument('--output', default='load-results-' + time.strftime('%Y%m%d-%H%M%S'))
    a = p.parse_args()
    levels = [int(x) for x in a.concurrency.split(',')]
    u = urlsplit(a.base_url)
    if u.scheme not in ('http', 'https') or not u.hostname or u.username or u.query or u.fragment:
        p.error('base URL must be an http(s) service URL without credentials/query/fragment')
    if not levels or min(levels) < 1 or max(levels) > 1000 or a.requests < max(levels) or a.timeout <= 0 or a.cooldown < 0 or not 0 < a.stop_failure_rate <= 1:
        p.error('invalid bounds; requests must be >= largest concurrency')
    tokens = [x.strip() for x in pathlib.Path(a.tokens_file).read_text().splitlines() if x.strip()]
    questions = [x.strip() for x in pathlib.Path(a.questions).read_text().splitlines() if x.strip()]
    if not tokens or not questions:
        p.error('tokens and questions must not be empty')
    out = pathlib.Path(a.output); out.mkdir(parents=True, exist_ok=False)
    reports = []
    print('测试将产生真实模型调用、日志和会话；Ctrl+C 停止提交新请求，已提交请求仍可能继续执行。', flush=True)
    with (out / 'requests.jsonl').open('w') as log:
        for stage, concurrency in enumerate(levels):
            if stage:
                time.sleep(a.cooldown)
            rows = []; started = time.monotonic(); pending = {}; submitted = 0; stopped = False
            executor = concurrent.futures.ThreadPoolExecutor(max_workers=concurrency)
            try:
                while pending or (submitted < a.requests and not stopped):
                    while len(pending) < concurrency and submitted < a.requests and not stopped:
                        n = submitted; submitted += 1
                        future = executor.submit(sample, a.base_url, tokens[n % len(tokens)], questions[n % len(questions)], a.timeout)
                        pending[future] = n
                    done, _ = concurrent.futures.wait(pending, return_when=concurrent.futures.FIRST_COMPLETED)
                    for future in done:
                        pending.pop(future); row = future.result(); row['concurrency'] = concurrency
                        rows.append(row); log.write(json.dumps(row, ensure_ascii=False) + '\n'); log.flush()
                    failures = sum(r.get('status') != 'answered' or bool(r.get('error')) for r in rows)
                    if any(r.get('error') in ('http_401', 'http_403', 'http_429', 'rate_limited') for r in rows) or (len(rows) >= min(5, a.requests) and failures / len(rows) >= a.stop_failure_rate):
                        stopped = True
            except KeyboardInterrupt:
                for future in pending:
                    future.cancel()
                print('已停止提交；等待已运行请求退出（受请求超时限制）。', flush=True)
                raise
            finally:
                executor.shutdown(wait=True)
            report = {'concurrency': concurrency, 'stopped_early': stopped, **summarize(rows, time.monotonic() - started)}
            reports.append(report)
            (out / 'summary.json').write_text(json.dumps(reports, ensure_ascii=False, indent=2))
            print(json.dumps(report, ensure_ascii=False, indent=2), flush=True)
            if stopped:
                print('已停止升压：请先排查失败/限流。'); break
    print('结果目录：' + str(out.resolve()))

if __name__ == '__main__':
    main()
