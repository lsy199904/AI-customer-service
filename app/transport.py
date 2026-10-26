"""Pooled, bounded model HTTP calls. No redirects, environment proxy, or credential logging."""
import threading
import httpx

_lock=threading.Lock()
_client=None

def client():
    global _client
    with _lock:
        if _client is None:
            _client=httpx.Client(follow_redirects=False,trust_env=False,
                limits=httpx.Limits(max_connections=40,max_keepalive_connections=20),
                timeout=httpx.Timeout(60,connect=5,pool=5))
        return _client


def post_json(url,payload,key='',timeout=60,max_bytes=8*1024*1024):
    from .deadlines import remaining,check
    timeout=remaining(timeout)
    headers={'Content-Type':'application/json'}
    if key:headers['Authorization']='Bearer '+key
    with client().stream('POST',url,json=payload,headers=headers,
                         timeout=httpx.Timeout(timeout,connect=min(5,timeout),pool=min(5,timeout))) as response:
        response.raise_for_status();raw=bytearray()
        for chunk in response.iter_bytes():
            check();raw.extend(chunk)
            if len(raw)>max_bytes:raise ValueError('模型响应超过大小限制')
        import json
        check();return json.loads(raw)


def close():
    global _client
    with _lock:
        if _client is not None:_client.close();_client=None


_async_client=None

def async_client():
    # LangChain initializes both SDK variants even for synchronous invoke().
    # Explicit client prevents accidental use of machine-wide proxy credentials.
    global _async_client
    with _lock:
        if _async_client is None:
            _async_client=httpx.AsyncClient(follow_redirects=False,trust_env=False,
                limits=httpx.Limits(max_connections=40,max_keepalive_connections=20),
                timeout=httpx.Timeout(45,connect=5,pool=5))
        return _async_client

async def close_async():
    global _async_client
    with _lock:
        previous=_async_client;_async_client=None
    if previous is not None:await previous.aclose()
