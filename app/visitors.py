"""Signed browser identity, separate from one-hour API access credentials."""
import hashlib
import hmac
import re
import time

VISITOR_LIFETIME=30*86400
VISITOR_COOKIE='smarttitu_visitor_identity'

def issue_visitor_cookie(secret,identity):
    if not re.fullmatch(r'demo-[a-f0-9]{32}',identity):raise ValueError('invalid visitor')
    payload=f'v1.{identity}.{int(time.time())+VISITOR_LIFETIME}'
    signature=hmac.new(secret.encode(),('smarttitu-visitor:'+payload).encode(),hashlib.sha256).hexdigest()
    return payload+'.'+signature

def read_visitor_cookie(secret,value):
    try:
        if not isinstance(value,str) or len(value)>256:return None
        version,identity,expiry,signature=value.split('.')
        if version!='v1' or not re.fullmatch(r'demo-[a-f0-9]{32}',identity):return None
        payload=f'{version}.{identity}.{expiry}'
        expected=hmac.new(secret.encode(),('smarttitu-visitor:'+payload).encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature,expected):return None
        if not time.time()<int(expiry)<=time.time()+VISITOR_LIFETIME:return None
        return identity
    except (ValueError,TypeError):return None
