import http.server, importlib.util, json, threading, time, unittest
from pathlib import Path
spec = importlib.util.spec_from_file_location('load', Path(__file__).with_name('load_test.py'))
m = importlib.util.module_from_spec(spec); spec.loader.exec_module(m)
class Handler(http.server.BaseHTTPRequestHandler):
    mode = 'ok'
    def log_message(self, *args): pass
    def do_POST(self):
        self.rfile.read(int(self.headers['Content-Length']))
        if self.path == '/v1/sessions':
            self.send_response(201); self.end_headers(); self.wfile.write(b'{"session_id":"test"}'); return
        self.send_response(429 if self.mode == '429' else 200)
        self.send_header('Content-Type', 'text/event-stream'); self.end_headers()
        if self.mode == '429': return
        if self.mode == 'error':
            self.wfile.write(b'event: error\ndata: {"code":"retrieval_timeout"}\n\n'); return
        if self.mode == 'incomplete': return
        for text in ['hello', ' world']:
            self.wfile.write(('event: delta\ndata: ' + json.dumps({'text':text}) + '\n\n').encode()); self.wfile.flush(); time.sleep(.03)
        status = 'suggestions' if self.mode == 'nohit' else 'answered'
        self.wfile.write(('event: complete\ndata: ' + json.dumps({'status':status,'reason':'no_knowledge' if status == 'suggestions' else 'ok','answer':'hello world'}) + '\n\n').encode())
class Tests(unittest.TestCase):
    def test_paths(self):
        server = http.server.ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        try:
            for mode in ['ok','nohit','error','429','incomplete']:
                Handler.mode = mode
                r = m.sample('http://127.0.0.1:' + str(server.server_port), 'test', 'question', 2)
                if mode == 'ok':
                    self.assertEqual(r['status'], 'answered'); self.assertEqual(r['delta_events'],2)
                    self.assertLess(r['ttft_s'],r['chat_s']); self.assertGreater(r['stream_span_s'],.02)
                elif mode == 'nohit': self.assertEqual(m.summarize([r],1)['answered'],0)
                else: self.assertEqual(r['error'], {'error':'retrieval_timeout','429':'http_429','incomplete':'stream_incomplete'}[mode])
        finally: server.shutdown(); server.server_close()
    def test_percentile(self):
        self.assertEqual(m.percentile([1,2,3,4,5],.95),5)
        self.assertIsNone(m.percentile([], .95))
if __name__ == '__main__': unittest.main()
