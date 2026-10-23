"""FastAPI HTTP application, served by Uvicorn; existing widget/API contracts remain stable."""
import argparse
from contextlib import asynccontextmanager
import json
import logging
import os
from pathlib import Path
import re
import socket
from urllib.parse import quote, urlsplit
from uuid import uuid4

import anyio
from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException
from starlette.datastructures import Headers, MutableHeaders
import uvicorn

from .core import APIError, BASE, Service, Settings, authenticate

LOG=logging.getLogger('assistant')
MAX_BODY=16384
STATIC={
    '/chatbot':('frame.html','text/html; charset=utf-8'),
    '/widget/frame.js':('frame.js','application/javascript; charset=utf-8'),
    '/widget/frame.css':('frame.css','text/css; charset=utf-8'),
    '/iframe.js':('iframe.js','application/javascript; charset=utf-8'),
    '/widget.js':('widget.js','application/javascript; charset=utf-8'),
    '/widget/demo':('demo.html','text/html; charset=utf-8'),
    '/widget/demo.js':('demo.js','application/javascript; charset=utf-8'),
    '/widget/demo.css':('demo.css','text/css; charset=utf-8'),
}

def failure(status,code,message):
    return JSONResponse({'error':{'code':code,'message':message}},status_code=status)

class RequestBoundary:
    """Bound bodies before FastAPI parsing; add safe correlation/CORS headers to every response."""
    def __init__(self,app,config):
        self.app,self.config=app,config
        self.active=0

    async def __call__(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        headers=Headers(scope=scope)
        supplied=headers.get('x-request-id','')
        request_id=supplied if re.fullmatch(r'[A-Za-z0-9_-]{8,80}',supplied) else str(uuid4())
        scope.setdefault('state',{})['request_id']=request_id
        origin=headers.get('origin')
        same_origin=bool(origin and urlsplit(origin).scheme in ('http','https') and urlsplit(origin).netloc==headers.get('host'))
        allowed=bool(origin and (origin in self.config.origins or same_origin))
        async def respond(message):
            if message['type']=='http.response.start':
                out=MutableHeaders(scope=message)
                out['X-Request-ID']=request_id
                out['X-Content-Type-Options']='nosniff'
                if 'cache-control' not in out:out['Cache-Control']='no-store'
                if allowed:
                    out['Access-Control-Allow-Origin']=origin
                    out.append('Vary','Origin')
                    out['Access-Control-Expose-Headers']='X-Request-ID'
            await send(message)
        async def error(status,code,message):
            await failure(status,code,message)(scope,receive,respond)
        if origin and not allowed:return await error(403,'origin_denied','该前端来源未授权')
        if scope['method']=='OPTIONS':
            return await Response(status_code=204,headers={
                'Access-Control-Allow-Methods':'GET, HEAD, POST, DELETE, OPTIONS',
                'Access-Control-Allow-Headers':'Authorization, Content-Type, X-Request-ID'})(scope,receive,respond)
        if self.active>=32:return await error(503,'service_busy','客服繁忙，请稍后重试')
        self.active+=1
        started=False
        async def tracked_send(message):
            nonlocal started
            if message['type']=='http.response.start':started=True
            await respond(message)
        try:
            if scope['method']=='POST':
                lengths=headers.getlist('content-length')
                if headers.get('transfer-encoding'):return await error(400,'invalid_encoding','不接受Transfer-Encoding')
                if len(lengths)!=1:return await error(400,'invalid_length','必须提供唯一Content-Length')
                try:size=int(lengths[0])
                except ValueError:return await error(400,'invalid_length','无效Content-Length')
                if not 0<size<=MAX_BODY:return await error(413,'body_too_large','请求体必须为1至16384字节')
                if headers.get('content-type','').split(';',1)[0].strip().lower()!='application/json':
                    return await error(415,'invalid_content_type','请使用application/json')
                body=bytearray()
                while True:
                    message=await receive()
                    if message['type']=='http.disconnect':return
                    body.extend(message.get('body',b''))
                    if len(body)>MAX_BODY:return await error(413,'body_too_large','请求体超过16384字节')
                    if not message.get('more_body',False):break
                if len(body)!=size:return await error(400,'invalid_length','请求长度不匹配')
                delivered=False
                original_receive=receive
                async def replay():
                    nonlocal delivered
                    if not delivered:
                        delivered=True
                        return {'type':'http.request','body':bytes(body),'more_body':False}
                    return await original_receive()
                receive=replay
            await self.app(scope,receive,tracked_send)
        except Exception:
            # Never log question bodies, query strings, auth headers or upstream error text.
            LOG.error('request failed request_id=%s',request_id)
            if not started:await error(500,'internal_error','服务暂时不可用')
        finally:self.active-=1

class SessionBody(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    context: dict=Field(default_factory=dict)

class ChatBody(BaseModel):
    model_config=ConfigDict(extra='forbid',strict=True)
    message: str=Field(min_length=1,max_length=2000)
    request_id: str=Field(min_length=8,max_length=80,pattern=r'^[a-zA-Z0-9_-]+$')

bearer=HTTPBearer(auto_error=False)

def current_service(request:Request):return request.app.state.service

def actor(credentials:HTTPAuthorizationCredentials=Depends(bearer),service=Depends(current_service)):
    if credentials is None or credentials.scheme.lower()!='bearer':
        raise APIError(401,'unauthorized','请提供登录凭证')
    return authenticate(service.config.secret,credentials.credentials)


def create_app(config=None,model=None,service=None):
    config=config or Settings()
    config.validate()
    @asynccontextmanager
    async def lifespan(app):
        anyio.to_thread.current_default_thread_limiter().total_tokens=32
        app.state.service=service or Service(config,model=model)
        app.state.ready=True
        try:yield
        finally:
            app.state.ready=False
            app.state.service.db.close()
    app=FastAPI(title='SmartTITU Customer Assistant',version='2.0.0',lifespan=lifespan,
                docs_url=None,redoc_url=None,openapi_url=None)
    app.state.ready=False
    app.add_middleware(RequestBoundary,config=config)

    @app.exception_handler(APIError)
    async def api_error(request,exc):return failure(exc.status,exc.code,exc.message)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request,exc):
        code='invalid_json' if any(e['type']=='json_invalid' for e in exc.errors()) else 'invalid_fields'
        return failure(400,code,'请求格式或字段无效，请检查输入')

    @app.exception_handler(HTTPException)
    async def missing_route(request,exc):
        return failure(exc.status_code,'not_found' if exc.status_code==404 else 'method_not_allowed',
                       '接口不存在' if exc.status_code==404 else '请求方法不支持')

    @app.head('/health',include_in_schema=False)
    @app.get('/health',tags=['health'])
    def health():return {'status':'ok'}

    @app.get('/ready',tags=['health'])
    def ready(request:Request,service=Depends(current_service)):
        with service.lock:service.db.execute('SELECT 1').fetchone()
        return {'status':'ready' if request.app.state.ready else 'starting'}

    @app.get('/widget/config',include_in_schema=False)
    def frame_config():return {'frame_origins':list(config.frame_origins)}

    def asset(path,service):
        registered={**STATIC,**service.media.assets}
        if path not in registered:raise APIError(404,'not_found','资源不存在')
        filename,content_type=registered[path]
        headers={'Referrer-Policy':'no-referrer','Cache-Control':'no-cache'}
        if content_type.startswith('text/html'):
            ancestors="'self'"+''.join(' '+x for x in config.frame_origins) if filename=='frame.html' else "'none'"
            headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' https:; connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors "+ancestors
        return FileResponse(BASE/'app/static'/filename,media_type=content_type,headers=headers)

    for path in STATIC:
        def static_endpoint(request:Request,service=Depends(current_service)):
            return asset(request.url.path,service)
        app.add_api_route(path,static_endpoint,methods=['GET','HEAD'],include_in_schema=False)

    @app.api_route('/media/{name}',methods=['GET','HEAD'],include_in_schema=False)
    def media(name:str,service=Depends(current_service)):return asset('/media/'+name,service)

    @app.get('/v1/bootstrap',tags=['assistant'])
    def bootstrap(user=Depends(actor),service=Depends(current_service)):return service.bootstrap()

    @app.get('/v1/sessions',tags=['sessions'])
    def sessions(user=Depends(actor),service=Depends(current_service)):return service.sessions(user)

    @app.post('/v1/sessions',status_code=201,tags=['sessions'])
    def create(body:SessionBody,user=Depends(actor),service=Depends(current_service)):
        service.rate(user)
        return service.create(user,body.model_dump())

    @app.get('/v1/sessions/{sid}/messages',tags=['sessions'])
    def history(sid:str,before:str|None=None,user=Depends(actor),service=Depends(current_service)):
        return service.history(user,sid,before)

    @app.post('/v1/sessions/{sid}/messages',tags=['sessions'])
    def chat(sid:str,body:ChatBody,user=Depends(actor),service=Depends(current_service)):
        return service.chat(user,sid,body.model_dump())

    @app.delete('/v1/sessions/{sid}',tags=['sessions'])
    def delete(sid:str,user=Depends(actor),service=Depends(current_service)):return service.delete(user,sid)

    @app.get('/v1/sources/{key}',tags=['knowledge'])
    def source(key:str,user=Depends(actor),service=Depends(current_service)):return service.source(key)

    @app.get('/v1/documents/{document_id}/revisions/{revision}/download',tags=['knowledge'])
    def document(document_id:str,revision:str,user=Depends(actor),service=Depends(current_service)):
        if not re.fullmatch(r'DOC-[a-f0-9]+',document_id) or not re.fullmatch(r'[a-f0-9]{64}',revision):
            raise APIError(404,'not_found','文档版本不存在')
        filename,raw=service.document(document_id,revision)
        types={'.docx':'application/vnd.openxmlformats-officedocument.wordprocessingml.document','.pdf':'application/pdf','.md':'text/markdown; charset=utf-8','.txt':'text/plain; charset=utf-8'}
        return Response(raw,media_type=types.get(Path(filename).suffix.lower(),'application/octet-stream'),
                        headers={'Content-Disposition':"attachment; filename*=UTF-8''"+quote(filename,safe='')})

    @app.get('/openapi.json',include_in_schema=False)
    def schema(user=Depends(actor)):return app.openapi()

    @app.api_route('/{path:path}',methods=['GET','HEAD','POST','DELETE'],include_in_schema=False)
    def unknown(path:str,user=Depends(actor)):raise APIError(404,'not_found','接口不存在')
    return app


class UvicornServer:
    """Socket-bound adapter for integration tests/embedded launchers, using the same ASGI app."""
    def __init__(self,config,host,port,model=None):
        self.service=Service(config,model=model)
        self.socket=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
        try:
            self.socket.setsockopt(socket.SOL_SOCKET,socket.SO_REUSEADDR,1)
            self.socket.bind((host,port));self.socket.listen(128)
            self.server_port=self.socket.getsockname()[1]
            self.app=create_app(config,service=self.service)
            self.server=uvicorn.Server(uvicorn.Config(self.app,host=host,port=self.server_port,
                access_log=False,log_level='warning',proxy_headers=False,timeout_graceful_shutdown=180))
        except Exception:
            self.socket.close();self.service.db.close();raise
    def serve_forever(self):self.server.run(sockets=[self.socket])
    def shutdown(self):self.server.should_exit=True
    def server_close(self):self.socket.close()


def create_server(config,host='127.0.0.1',port=8000,model=None):
    return UvicornServer(config,host,port,model)


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--host',default=os.getenv('HOST','127.0.0.1'))
    parser.add_argument('--port',type=int,default=int(os.getenv('PORT','8000')))
    args=parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    # Single worker retains the existing per-session in-process exclusion guarantees.
    uvicorn.run(create_app(),host=args.host,port=args.port,workers=1,access_log=False,
                proxy_headers=False,limit_concurrency=64,timeout_graceful_shutdown=180)

if __name__=='__main__':main()
