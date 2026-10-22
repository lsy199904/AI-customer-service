"""HTTP adapter. Deploy behind a TLS reverse proxy; serves a self-contained floating widget."""
import argparse
import json
import logging
import os
import re
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlsplit, parse_qs
from .core import APIError, Service, Settings, authenticate, BASE

LOG=logging.getLogger('assistant')

class Handler(BaseHTTPRequestHandler):
    server_version='SmartTITU-MVP/1'

    def setup(self):
        super().setup()
        self.connection.settimeout(60)

    def log_message(self, fmt, *args):
        # No tokens, request bodies, questions or query parameters in access logs.
        pass

    def send_json(self, status, payload):
        raw=json.dumps(payload,ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header('Content-Type','application/json; charset=utf-8')
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('Cache-Control','no-store')
        self.send_header('X-Content-Type-Options','nosniff')
        origin=self.headers.get('Origin')
        if origin and origin in self.server.service.config.origins:
            self.send_header('Access-Control-Allow-Origin',origin)
            self.send_header('Vary','Origin')
        self.send_header('Connection','close')
        self.end_headers()
        self.wfile.write(raw)
        self.close_connection=True

    def send_asset(self, filename, content_type):
        raw=(BASE / 'app' / 'static' / filename).read_bytes()
        self.send_response(200)
        self.send_header('Content-Type',content_type)
        self.send_header('Content-Length',str(len(raw)))
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('Referrer-Policy','no-referrer')
        self.send_header('Cache-Control','no-cache')
        if content_type.startswith('text/html'):
            self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' https:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'")
        self.send_header('Connection','close')
        self.end_headers();self.wfile.write(raw);self.close_connection=True

    def body(self):
        if self.headers.get('Transfer-Encoding'):
            raise APIError(400,'invalid_encoding','不接受Transfer-Encoding')
        sizes=self.headers.get_all('Content-Length',[])
        if len(sizes)!=1:
            raise APIError(400,'invalid_length','必须提供唯一Content-Length')
        try:
            size=int(sizes[0])
        except ValueError:
            raise APIError(400,'invalid_length','无效Content-Length')
        if not 0<size<=16384:
            raise APIError(413,'body_too_large','请求体必须为1至16384字节')
        if self.headers.get_content_type()!='application/json':
            raise APIError(415,'invalid_content_type','请使用application/json')
        try:
            value=json.loads(self.rfile.read(size))
        except (ValueError,UnicodeError):
            raise APIError(400,'invalid_json','请求体不是有效JSON')
        if not isinstance(value,dict):
            raise APIError(400,'invalid_body','JSON请求体必须为对象')
        return value

    def dispatch(self):
        service=self.server.service
        split=urlsplit(self.path);path=split.path
        origin=self.headers.get('Origin')
        same_origin = bool(origin and urlsplit(origin).scheme in ('http','https') and urlsplit(origin).netloc == self.headers.get('Host'))
        if origin and origin not in service.config.origins and not same_origin:
            raise APIError(403,'origin_denied','该前端来源未授权')
        if self.command=='OPTIONS':
            self.send_response(204)
            if origin:
                self.send_header('Access-Control-Allow-Origin',origin)
                self.send_header('Vary','Origin')
            self.send_header('Access-Control-Allow-Methods','GET, POST, DELETE, OPTIONS')
            self.send_header('Access-Control-Allow-Headers','Authorization, Content-Type')
            self.send_header('Content-Length','0');self.end_headers();return
        if path=='/health' and self.command=='GET':
            return self.send_json(200,{'status':'ok'})
        assets={
            '/widget.js':('widget.js','application/javascript; charset=utf-8'),
            '/widget/demo':('demo.html','text/html; charset=utf-8'),
            '/widget/demo.js':('demo.js','application/javascript; charset=utf-8'),
            '/widget/demo.css':('demo.css','text/css; charset=utf-8')}
        assets.update(service.media.assets)
        if path in assets and self.command=='GET':
            return self.send_asset(*assets[path])
        header=self.headers.get('Authorization','')
        if not header.startswith('Bearer '):
            raise APIError(401,'unauthorized','请提供登录凭证')
        actor=authenticate(service.config.secret,header[7:])
        if path=='/v1/bootstrap' and self.command=='GET':
            return self.send_json(200,service.bootstrap())
        if path=='/v1/sessions':
            if self.command=='POST':
                service.rate(actor)
                return self.send_json(201,service.create(actor,self.body()))
            if self.command=='GET':
                return self.send_json(200,service.sessions(actor))
        m=re.fullmatch(r'/v1/sessions/([a-zA-Z0-9-]+)(/messages)?',path)
        if m:
            sid,sub=m.groups()
            if sub:
                if self.command=='GET':
                    before=parse_qs(split.query).get('before',[None])[0]
                    return self.send_json(200,service.history(actor,sid,before))
                if self.command=='POST':
                    return self.send_json(200,service.chat(actor,sid,self.body()))
            elif self.command=='DELETE':
                return self.send_json(200,service.delete(actor,sid))
        m=re.fullmatch(r'/v1/sources/(KB-[a-f0-9]+)',path)
        if m and self.command=='GET':
            return self.send_json(200,service.source(m.group(1)))
        raise APIError(404,'not_found','接口不存在')

    def handle_request(self):
        try:
            self.dispatch()
        except APIError as exc:
            self.send_json(exc.status,{'error':{'code':exc.code,'message':exc.message}})
        except (BrokenPipeError,ConnectionResetError,TimeoutError):
            pass
        except Exception:
            LOG.exception('request failed')
            self.send_json(500,{'error':{'code':'internal_error','message':'服务暂时不可用'}})

    do_GET=handle_request
    do_POST=handle_request
    do_DELETE=handle_request
    do_OPTIONS=handle_request


class BoundedServer(ThreadingHTTPServer):
    def __init__(self, *args, **kwargs):
        self.slots=threading.BoundedSemaphore(32)
        super().__init__(*args, **kwargs)

    def process_request(self, request, address):
        if not self.slots.acquire(blocking=False):
            self.shutdown_request(request)
            return
        try:
            super().process_request(request,address)
        except Exception:
            self.slots.release()
            raise

    def process_request_thread(self, request, address):
        try:
            super().process_request_thread(request,address)
        finally:
            self.slots.release()


def create_server(config, host='127.0.0.1', port=8000, model=None):
    service=Service(config,model=model)
    try:
        server=BoundedServer((host,port),Handler)
    except Exception:
        service.db.close()
        raise
    server.daemon_threads=True
    server.service=service
    return server


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default=os.getenv('HOST','127.0.0.1'))
    parser.add_argument('--port',type=int,default=int(os.getenv('PORT','8000')))
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    server=create_server(Settings(),args.host,args.port)
    LOG.info('backend ready on %s:%d; knowledge=%d; mode=%s',args.host,args.port,
             len(server.service.knowledge.rows),server.service.config.mode)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close();server.service.db.close()

if __name__=='__main__':
    main()
