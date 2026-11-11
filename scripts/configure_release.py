"""Initialize a new standalone installation without overwriting existing credentials."""
import json
import os
from pathlib import Path
import re
import secrets
import shlex
from urllib.parse import quote

ROOT = Path(__file__).resolve().parent.parent


def read(path):
    values = {}
    for line in path.read_text(encoding='utf-8').splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, value = line.split('=', 1)
        pieces = shlex.split(value, comments=True)
        if len(pieces) > 1 or key in values:
            raise ValueError('配置包含重复参数或未加引号的空格：' + key)
        values[key] = pieces[0] if pieces else ''
    return values


def initialize(root=ROOT):
    root = Path(root)
    env = root / '.env'
    text = env.read_text() if env.exists() else (root / '.env.example').read_text()
    # Parse the prospective file without creating half-configured installations.
    values = {}
    for line in text.splitlines():
        if not line.strip() or line.lstrip().startswith('#'):
            continue
        key, raw = line.split('=', 1)
        pieces = shlex.split(raw, comments=True)
        if key in values or len(pieces) > 1:
            raise ValueError('配置参数重复或值格式无效：' + key)
        values[key] = pieces[0] if pieces else ''
    required = ('POSTGRES_USER','POSTGRES_DB','POSTGRES_PORT','APP_DB_USER','MILVUS_PORT','MINIO_ROOT_USER')
    if any(not values.get(k) for k in required):
        raise ValueError('请使用本发布版本的.env.example准备配置，不直接复制旧服务.env')
    added = {}
    for key in ('AUTH_SECRET','OPERATIONS_TOKEN','POSTGRES_PASSWORD','APP_DB_PASSWORD',
                'MILVUS_ROOT_PASSWORD','MINIO_ROOT_PASSWORD'):
        if not values.get(key):
            added[key] = secrets.token_urlsafe(48 if key == 'AUTH_SECRET' else 32)
    values.update(added)
    url = ('postgresql://' + quote(values['APP_DB_USER'], safe='') + ':' +
           quote(values['APP_DB_PASSWORD'], safe='') + '@127.0.0.1:' +
           values['POSTGRES_PORT'] + '/' + quote(values['POSTGRES_DB'], safe=''))
    uri = 'http://127.0.0.1:' + values['MILVUS_PORT']
    token = 'root:' + values['MILVUS_ROOT_PASSWORD']
    for key, expected in (('DATABASE_URL', url), ('MILVUS_URI', uri), ('MILVUS_TOKEN', token)):
        if values.get(key) and values[key] != expected:
            raise ValueError(key + '与本地独立部署配置不一致，请核对；未覆盖任何配置')
        if not values.get(key):
            added[key] = expected
    for key, value in added.items():
        pattern = r'^' + re.escape(key) + r'=.*$'
        replacement = key + '=' + shlex.quote(value)
        text = re.sub(pattern, lambda _: replacement, text, flags=re.M) if re.search(pattern,text,re.M) else text+'\n'+replacement+'\n'
    # Allow all possible Milvus image UIDs to read its bind-mounted override;
    # parent directory is owner-only on the host. Files never enter source packages.
    generated = root / 'deploy/generated'
    generated.mkdir(parents=True, exist_ok=True, mode=0o700)
    target = generated / 'milvus-user.yaml'
    config = 'common:\n  security:\n    authorizationEnabled: true\n    defaultRootPassword: ' + json.dumps(values['MILVUS_ROOT_PASSWORD']) + '\n'
    if target.exists() and target.read_text() != config:
        raise ValueError('Milvus配置已存在且不同，请先核对现有数据卷凭证')
    if not target.exists():
        fd = os.open(target, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o644)
        with os.fdopen(fd, 'w') as handle:
            handle.write(config)
    temporary = env.with_name('.env.init-' + secrets.token_hex(6))
    try:
        fd = os.open(temporary, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
        with os.fdopen(fd, 'w') as handle:
            handle.write(text)
        temporary.replace(env)
    finally:
        temporary.unlink(missing_ok=True)
    for name in ('var', 'backups'):
        (root/name).mkdir(exist_ok=True, mode=0o700)
    print('本机配置已准备，已有密钥保持不变。请编辑.env中的模型服务与平台来源后继续。')


if __name__ == '__main__':
    initialize()
