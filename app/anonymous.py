"""Independent signed anonymous browser identities; never trust client-selected IDs."""
import hashlib
import hmac
import re
import time

TENANT='__smarttitu_anonymous__'
COOKIE='smarttitu_anonymous_visitor'
LIFETIME=30*86400
PATTERN=r'anon-[a-f0-9]{32}'


def issue_cookie(secret,identity):
    if not re.fullmatch(PATTERN,identity):raise ValueError('invalid anonymous identity')
    payload=f'v1.{identity}.{int(time.time())+LIFETIME}'
    signature=hmac.new(secret.encode(),('anonymous-visitor:'+payload).encode(),hashlib.sha256).hexdigest()
    return payload+'.'+signature


def read_cookie(secret,value):
    try:
        if not isinstance(value,str) or len(value)>256:return None
        version,identity,expiry,signature=value.split('.')
        if version!='v1' or not re.fullmatch(PATTERN,identity):return None
        payload=f'{version}.{identity}.{expiry}'
        expected=hmac.new(secret.encode(),('anonymous-visitor:'+payload).encode(),hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected,signature):return None
        if not time.time()<int(expiry)<=time.time()+LIFETIME:return None
        return identity
    except (ValueError,TypeError):return None
