"""FastAPI HTTP application, served by Uvicorn; existing widget/API contracts remain stable."""
import argparse
import asyncio
import functools
import hmac
import threading
import time
from contextvars import copy_context
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
from fastapi.responses import FileResponse, JSONResponse, Response, StreamingResponse
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
        from .observability import bind,event,error_fields,capture_request
        supplied=Headers(scope=scope).get('x-request-id','')
        request_id=supplied if re.fullmatch(r'[A-Za-z0-9_-]{8,80}',supplied) else str(uuid4())
        scope.setdefault('state',{})['request_id']=request_id
        started=time.monotonic();status=None;completed=False
        async def track(message):
            nonlocal status,completed
            if message['type']=='http.response.start':status=message['status']
            if message['type']=='http.response.body' and not message.get('more_body',False):completed=True
            await send(message)
        window_id=Headers(scope=scope).get('x-widget-id','')
        window_id=window_id if re.fullmatch(r'[A-Za-z0-9_-]{8,80}',window_id) else None
        is_chat=scope['method']=='POST' and bool(re.fullmatch(r'/v1/sessions/[^/]+/messages(?:/stream)?',scope['path']))
        with bind(http_request_id=request_id,window_id=window_id),capture_request(is_chat):
            try:
                await self._call(scope,receive,track)
            except Exception as error:
                event('http_failed',level='ERROR',**error_fields(error))
                raise
            finally:
                route=getattr(scope.get('route'),'path',None)
                # Never record unknown paths, query strings or headers.
                if not route:route=scope['path'] if scope['path'] in STATIC or scope['path'] in ('/health','/ready') else 'unmatched'
                if route not in ('/health','/ready') or (status is not None and status>=400):
                    event('http_completed',level='WARNING' if status is not None and status>=400 else 'INFO',
                          method=scope['method'],route=route,status=status,completed=completed,
                          elapsed_ms=round((time.monotonic()-started)*1000,2),
                          **scope.get('state',{}).get('actor_log_fields',{}))

    async def _call(self,scope,receive,send):
        if scope['type']!='http':return await self.app(scope,receive,send)
        headers=Headers(scope=scope)
        supplied=headers.get('x-request-id','')
        request_id=scope['state']['request_id']
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
                'Access-Control-Allow-Headers':'Authorization, Content-Type, X-Request-ID, X-Widget-ID'})(scope,receive,respond)
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
        except Exception as exc:
            from .observability import event,error_fields
            event('http_failed',level='ERROR',**error_fields(exc))
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

def actor(request:Request,credentials:HTTPAuthorizationCredentials=Depends(bearer),service=Depends(current_service)):
    if credentials is None or credentials.scheme.lower()!='bearer':
        raise APIError(401,'unauthorized','请提供登录凭证')
    claims=authenticate(service.config.secret,credentials.credentials)
    from .observability import reference
    fields={'tenant_ref':reference(service.config.secret,claims['tenant_id']),
            'user_ref':reference(service.config.secret,claims['tenant_id']+'\0'+claims['sub'])}
    sid=request.path_params.get('sid')
    if sid:fields['session_ref']=reference(service.config.secret,sid)
    request.scope.setdefault('state',{})['actor_log_fields']=fields
    return claims



def create_app(config=None,model=None,service=None):
    config=config or Settings()
    from .observability import configure,event
    configure(os.getenv('LOG_DIR',str(BASE/'var/logs')))
    config.validate()
    @asynccontextmanager
    async def lifespan(app):
        anyio.to_thread.current_default_thread_limiter().total_tokens=32
        app.state.service=service or Service(config,model=model)
        async def cleanup():
            while True:
                try:
                    future=asyncio.get_running_loop().run_in_executor(None,app.state.service.prune_sessions)
                    try:report=await asyncio.shield(future)
                    except asyncio.CancelledError:
                        # Finish the current database cleanup before closing its connections.
                        try:await future
                        except Exception:event('retention_cleanup_failed',level='ERROR',during_shutdown=True)
                        raise
                    if report['batch_full'] and not report['skipped_busy']:
                        await asyncio.sleep(.05);continue
                except asyncio.CancelledError:raise
                except Exception:event('retention_cleanup_failed',level='ERROR',during_shutdown=False)
                await asyncio.sleep(config.cleanup_interval)
        cleanup_task=asyncio.create_task(cleanup())
        app.state.ready=True
        event('service_started',answer_mode=config.mode,retrieval_backend=config.retrieval_backend)
        try:yield
        finally:
            app.state.ready=False
            event('service_stopping')
            cleanup_task.cancel()
            try:await cleanup_task
            except asyncio.CancelledError:pass
            from .deadlines import close as close_retrieval
            close_retrieval()
            app.state.service.close()
            from .storage import close_knowledge_pools
            close_knowledge_pools()
            from .transport import close,close_async
            close()
            await close_async()
    app=FastAPI(title='SmartTITU Customer Assistant',version='3.0.0',lifespan=lifespan,
                docs_url=None,redoc_url=None,openapi_url=None)
    app.state.ready=False
    app.add_middleware(RequestBoundary,config=config)

    @app.exception_handler(APIError)
    async def api_error(request,exc):
        event('api_rejected',level='WARNING',http_status=exc.status,error_code=exc.code,
              **request.scope.get('state',{}).get('actor_log_fields',{}))
        return failure(exc.status,exc.code,exc.message)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request,exc):
        code='invalid_json' if any(e['type']=='json_invalid' for e in exc.errors()) else 'invalid_fields'
        event('request_validation_failed',level='WARNING',error_code=code,http_status=400)
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
        if not service.knowledge.rows:raise APIError(503,'index_empty','知识尚未入库')
        vector=getattr(service.knowledge,'vectors',None) if config.retrieval_backend=='semantic' else None
        if vector is not None and not vector.client.has_collection(vector.collection):raise APIError(503,'index_unavailable','知识索引尚未同步')
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
        return service.create(user,body.model_dump())

    @app.get('/v1/sessions/{sid}/messages',tags=['sessions'])
    def history(sid:str,before:str|None=None,user=Depends(actor),service=Depends(current_service)):
        return service.history(user,sid,before)

    @app.post('/v1/sessions/{sid}/messages',tags=['sessions'])
    def chat(sid:str,body:ChatBody,user=Depends(actor),service=Depends(current_service)):
        return service.chat(user,sid,body.model_dump())

    @app.post('/v1/sessions/{sid}/messages/stream',tags=['assistant'],response_class=StreamingResponse,
              responses={200:{'description':'Authenticated SSE: status, delta, complete, error',
                              'content':{'text/event-stream':{'schema':{'type':'string'}}}}})
    async def chat_stream(sid:str,body:ChatBody,request:Request,user=Depends(actor),service=Depends(current_service)):
        from .observability import event as log_event,error_fields
        # Ownership errors remain HTTP errors, before SSE headers have been sent.
        await anyio.to_thread.run_sync(functools.partial(service.owned,user,sid))
        async def events():
            loop=asyncio.get_running_loop();queue=asyncio.Queue(maxsize=32);cancel=threading.Event()
            def enqueue(item):
                if not queue.full():queue.put_nowait(item)
            def observe(item):loop.call_soon_threadsafe(enqueue,item)
            task=loop.run_in_executor(None,functools.partial(copy_context().run,service.chat,user,sid,body.model_dump(),observe,cancel))
            def event(kind,payload):return 'event: '+kind+'\ndata: '+json.dumps(payload,ensure_ascii=False)+'\n\n'
            try:
                yield event('status',{'stage':'connected'})
                while not task.done():
                    item=asyncio.create_task(queue.get())
                    done,_=await asyncio.wait([item,task],timeout=10,return_when=asyncio.FIRST_COMPLETED)
                    if item in done:yield event('status',item.result())
                    else:
                        item.cancel()
                        try:await item
                        except asyncio.CancelledError:pass
                        if not task.done():yield ': heartbeat\n\n'
                result=await task
                log_event('response_ready',request_id=body.request_id,outcome=result['status'],
                          answer_chars=len(result['answer']),**request.scope.get('state',{}).get('actor_log_fields',{}))
                # Only validated answers are streamed. Raw model JSON/thinking is never exposed.
                for i in range(0,len(result['answer']),128):yield event('delta',{'text':result['answer'][i:i+128]})
                yield event('complete',result)
                log_event('stream_completed',request_id=body.request_id,**request.scope.get('state',{}).get('actor_log_fields',{}))
            except APIError as error:
                log_event('stream_failed',level='ERROR',request_id=body.request_id,error_code=error.code)
                yield event('error',{'code':error.code,'message':error.message})
            except asyncio.CancelledError:
                log_event('stream_cancelled',level='WARNING',request_id=body.request_id)
                raise
            except Exception as error:
                log_event('stream_failed',level='ERROR',request_id=body.request_id,**error_fields(error))
                yield event('error',{'code':'service_unavailable','message':'服务暂时不可用，请重试。'})
            finally:
                cancel.set()
                # Consume exceptions even when the HTTP client disconnected during inference.
                def consume(future):
                    if not future.cancelled():future.exception()
                task.add_done_callback(consume)
        return StreamingResponse(events(),media_type='text/event-stream',headers={
            'Cache-Control':'no-store','X-Accel-Buffering':'no','Connection':'keep-alive'})

    @app.get('/metrics',include_in_schema=False)
    def metrics(request:Request,service=Depends(current_service)):
        secret=os.getenv('OPERATIONS_TOKEN','')
        supplied=request.headers.get('x-operations-token','')
        if len(secret)<32 or not hmac.compare_digest(secret,supplied):raise APIError(401,'unauthorized','运维认证失败')
        with service.lock:values=dict(service.metrics)
        text=''.join('smarttitu_'+key+' '+str(value)+'\n' for key,value in sorted(values.items()))
        return Response(text,media_type='text/plain; version=0.0.4')

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
    # Cross-process session locking requires PostgreSQL. Default remains one worker.
    workers=int(os.getenv('APP_WORKERS','1'))
    if workers<1 or workers>4:raise ValueError('APP_WORKERS范围为1至4，增加前须压测模型容量')
    if workers>1 and not os.getenv('DATABASE_URL'):raise ValueError('多worker必须使用PostgreSQL')
    uvicorn.run('app.server:create_app',factory=True,host=args.host,port=args.port,workers=workers,access_log=False,
                proxy_headers=False,limit_concurrency=64,timeout_graceful_shutdown=180)

if __name__=='__main__':main()
