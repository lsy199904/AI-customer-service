"""Public prefix covers identity, SSE, history and static resources without models."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from app.core import Settings, authenticate
from app.server import create_app
from app.url_prefix import public_payload, external_prefix

SECRET='prefix-tests-secret-abcdefghijklmnopqrstuvwxyz'

@pytest.fixture
def app(tmp_path):
    return create_app(Settings(secret=SECRET,db=str(tmp_path/'chat.db'),
        retrieval_backend='lexical',mode='extractive',anonymous_widget_enabled=True,
        origins=('https://portal.example.com',),frame_origins=('https://portal.example.com',)))

@pytest.fixture
def client(app):
    with TestClient(app,base_url='https://assistant.example.com') as client:yield client

def auth(client):
    return client.post('/smart-bot/widget/anonymous-auth',json={})

def test_prefixed_cookie_preserves_identity(client):
    first=auth(client);second=auth(client)
    assert first.status_code==200
    assert 'Path=/smart-bot/widget/anonymous-auth' in first.headers['set-cookie']
    a=authenticate(SECRET,first.json()['token']);b=authenticate(SECRET,second.json()['token'])
    assert a['sub']==b['sub']

def test_prefixed_sse_history_and_ownership(client,app):
    headers={'Authorization':'Bearer '+auth(client).json()['token']}
    assert client.get('/smart-bot/v1/bootstrap',headers=headers).status_code==200
    sid=client.post('/smart-bot/v1/sessions',json={},headers=headers).json()['session_id']
    r=client.post(f'/smart-bot/v1/sessions/{sid}/messages/stream',headers=headers,
        json={'message':'你好','request_id':'prefix-greet-1234'})
    assert r.status_code==200 and 'event: delta' in r.text and 'event: complete' in r.text
    assert '你好' in str(client.get(f'/smart-bot/v1/sessions/{sid}/messages',headers=headers).json())
    with TestClient(app,base_url='https://assistant.example.com') as other:
        headers={'Authorization':'Bearer '+auth(other).json()['token']}
        assert other.get(f'/smart-bot/v1/sessions/{sid}/messages',headers=headers).status_code==404

def test_prefixed_assets_and_legacy_health(client):
    for path in ('/iframe-anonymous.js','/widget.js','/chatbot/anonymous','/widget/anonymous-frame.js','/widget/frame.css','/media/support-robot-b.png','/health','/ready'):
        assert client.get('/smart-bot'+path).status_code==200,path
    assert client.get('/ready').status_code==200
    html=client.get('/smart-bot/chatbot/anonymous').text
    assert 'src="/smart-bot/widget.js"' in html
    assert 'href="/smart-bot/widget/frame.css"' in html

def test_json_and_sse_return_prefixed_links(client,app):
    headers={'Authorization':'Bearer '+auth(client).json()['token']}
    sid=client.post('/smart-bot/v1/sessions',json={},headers=headers).json()['session_id']
    result={'status':'answered','answer':'示例 /v1/responses',
        'images':[{'url':'/media/test.png'}],'citations':[{'url':'/v1/sources/test'}]}
    with patch.object(app.state.service,'chat',return_value=result):
        path=f'/smart-bot/v1/sessions/{sid}/messages'
        body={'message':'你好','request_id':'prefix-links-1234'}
        r=client.post(path,json=body,headers=headers)
        assert r.json()['images'][0]['url']=='/smart-bot/media/test.png'
        r=client.post(path+'/stream',json=body,headers=headers)
        assert '/smart-bot/media/test.png' in r.text
        assert '/smart-bot/v1/sources/test' in r.text
        assert '示例 /v1/responses' in r.text

def test_prefix_preflight_and_errors(client):
    r=client.options('/smart-bot/v1/sessions',headers={'Origin':'https://portal.example.com'})
    assert r.status_code==204
    assert client.get('/smart-bot/v1/sessions').status_code==401
    assert client.get('/smart-bot/health',headers={'Origin':'https://evil.example'}).status_code==403

def test_link_rewriting_leaves_answers_and_external_urls_untouched():
    token=external_prefix.set('/smart-bot')
    try:
        source={'answer':'接口示例 /v1/responses','images':[{'url':'/media/test.png'}],
            'citations':[{'url':'/v1/sources/abc'}],'url':'https://example.com/v1/a'}
        out=public_payload(source)
        assert out['images'][0]['url']=='/smart-bot/media/test.png'
        assert out['citations'][0]['url']=='/smart-bot/v1/sources/abc'
        assert out['answer']==source['answer'] and out['url']==source['url']
        assert source['images'][0]['url']=='/media/test.png'
    finally:external_prefix.reset(token)
