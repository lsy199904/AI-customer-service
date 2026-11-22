"""Anonymous iframe identity and real API ownership, without any external models."""
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient
from app.core import Settings, authenticate, issue_token
from app.anonymous import TENANT, issue_cookie, read_cookie
from app.server import create_app

SECRET='anonymous-tests-secret-abcdefghijklmnopqrstuvwxyz'

@pytest.fixture
def config(tmp_path):
    return Settings(secret=SECRET,db=str(tmp_path/'chat.db'),
        retrieval_backend='lexical',mode='extractive',anonymous_widget_enabled=True,
        frame_origins=('https://portal.example.com',))

@pytest.fixture
def app(config):
    return create_app(config)

@pytest.fixture
def client(app):
    with TestClient(app,base_url='https://assistant.example.com') as client:yield client

def headers(token):return {'Authorization':'Bearer '+token}
def get_token(client,**kwargs):
    return client.post('/widget/anonymous-auth',json={},**kwargs).json()['token']

def test_cookie_stable_secure_and_no_secret_exposure(client):
    r=client.post('/widget/anonymous-auth',json={});a=r.json()['token']
    b=get_token(client)
    assert authenticate(SECRET,a)['sub']==authenticate(SECRET,b)['sub']
    assert authenticate(SECRET,a)['tenant_id']==TENANT
    for flag in ('HttpOnly','Secure','SameSite=none','Partitioned','Path=/widget/anonymous-auth'):
        assert flag in r.headers['set-cookie']
    assert r.headers['cache-control']=='no-store'
    assert SECRET not in r.text

def test_two_browsers_cannot_list_read_write_stream_or_delete_each_others_history(client,app):
    a=get_token(client);ha=headers(a)
    sid=client.post('/v1/sessions',json={},headers=ha).json()['session_id']
    response=client.post(f'/v1/sessions/{sid}/messages/stream',headers=ha,
        json={'message':'你好','request_id':'anonymous-greet-123'})
    assert 'event: delta' in response.text and 'event: complete' in response.text
    assert '你好' in str(client.get(f'/v1/sessions/{sid}/messages',headers=ha).json())
    with TestClient(app,base_url='https://assistant.example.com') as other:
        b=get_token(other);hb=headers(b)
        assert authenticate(SECRET,a)['sub']!=authenticate(SECRET,b)['sub']
        assert other.get('/v1/sessions',headers=hb).json()['items']==[]
        for suffix in ('/messages','/messages/stream'):
            assert other.post(f'/v1/sessions/{sid}'+suffix,headers=hb,
                json={'message':'你好','request_id':'anonymous-denied-123'}).status_code==404
        assert other.get(f'/v1/sessions/{sid}/messages',headers=hb).status_code==404
        assert other.delete(f'/v1/sessions/{sid}',headers=hb).status_code==404
        formal=headers(issue_token(SECRET,'real-company','user'))
        assert other.get(f'/v1/sessions/{sid}/messages',headers=formal).status_code==404

def test_bearer_renews_when_cookie_blocked_and_spoofed_id_cannot_choose_identity(client):
    a=get_token(client);client.cookies.clear()
    b=get_token(client,headers=headers(a))
    assert authenticate(SECRET,a)['sub']==authenticate(SECRET,b)['sub']
    client.cookies.clear()
    r=client.post('/widget/anonymous-auth?visitor_id='+authenticate(SECRET,a)['sub'],
        json={'visitor_id':authenticate(SECRET,a)['sub']},headers=headers(a+'corrupt'))
    assert authenticate(SECRET,r.json()['token'])['sub']!=authenticate(SECRET,a)['sub']

def test_foreign_or_demo_token_cannot_select_anonymous_identity(client):
    foreign=issue_token(SECRET,'real-company','admin')
    a=get_token(client,headers=headers(foreign))
    assert authenticate(SECRET,a)['tenant_id']==TENANT
    assert authenticate(SECRET,a)['sub']!='admin'

def test_disabled_rejects_issuance_and_existing_anonymous_but_formal_api_still_works(client,config):
    a=get_token(client);config.anonymous_widget_enabled=False
    assert client.post('/widget/anonymous-auth',json={}).status_code==404
    assert client.get('/v1/bootstrap',headers=headers(a)).status_code==401
    formal=headers(issue_token(SECRET,'real-company','user'))
    assert client.get('/v1/bootstrap',headers=formal).status_code==200

def test_original_credential_entry_unchanged_and_new_frame_is_embeddable(client):
    old=client.get('/chatbot');new=client.get('/chatbot/anonymous')
    assert '/widget/frame.js' in old.text
    assert '/widget/anonymous-frame.js' in new.text
    assert 'id="login"' not in new.text
    for response in (old,new):
        assert "frame-ancestors 'self' https://portal.example.com" in response.headers['content-security-policy']
    preview=client.get('/widget/anonymous-demo')
    assert preview.status_code==200
    assert '/iframe-anonymous.js' in preview.text
    assert '/widget/demo-auth' not in preview.text
    for url in ('/iframe.js','/iframe-anonymous.js','/widget/anonymous-frame.js'):
        assert client.get(url).status_code==200
    assert client.get('/widget/demo-auth').status_code==404

def test_bad_origin_is_denied(client):
    assert client.post('/widget/anonymous-auth',json={},headers={'Origin':'https://evil.example'}).status_code==403

def test_tampering_expiry_and_http_cookie(app):
    identity='anon-'+'a'*32
    cookie=issue_cookie(SECRET,identity)
    assert read_cookie(SECRET,cookie)==identity
    assert read_cookie(SECRET,cookie+'x') is None
    with patch('app.anonymous.time.time',return_value=10**11):assert read_cookie(SECRET,cookie) is None
    with TestClient(app,base_url='http://assistant.example.com') as http:
        r=http.post('/widget/anonymous-auth',json={})
        assert 'SameSite=lax' in r.headers['set-cookie']
        assert 'Secure' not in r.headers['set-cookie']
