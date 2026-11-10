"""Public gateway prefix; internal routes and ownership/logging stay unchanged."""
from contextvars import ContextVar

PREFIX = '/smart-bot'
external_prefix = ContextVar('external_prefix', default='')

def public_payload(value):
    """Rewrite only link fields, never user/model text or external URLs."""
    if not external_prefix.get():
        return value
    if isinstance(value, list):
        return [public_payload(item) for item in value]
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            if key in ('url', 'download_url', 'qr_url') and isinstance(item, str) and item.startswith(('/v1/', '/media/', '/widget/', '/common/')):
                result[key] = PREFIX + item
            else:
                result[key] = public_payload(item)
        return result
    return value

class PublicPrefix:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        path = scope['path']
        prefixed = path == PREFIX or path.startswith(PREFIX + '/')
        token = external_prefix.set(PREFIX if prefixed else '')
        if prefixed:
            scope = dict(scope)
            scope['path'] = path[len(PREFIX):] or '/'
            raw = scope.get('raw_path', path.encode())
            scope['raw_path'] = raw[len(PREFIX):] or b'/'
        async def respond(message):
            if prefixed and message['type'] == 'http.response.start':
                message = dict(message)
                headers = []
                for key, value in message['headers']:
                    if key.lower() == b'set-cookie':
                        value = value.replace(b'Path=/widget/', b'Path=/smart-bot/widget/')
                    elif key.lower() == b'location' and value.startswith(b'/') and not value.startswith((b'//', b'/smart-bot/')):
                        value = PREFIX.encode() + value
                    headers.append((key, value))
                message['headers'] = headers
            await send(message)
        try:
            await self.app(scope, receive, respond)
        finally:
            external_prefix.reset(token)
