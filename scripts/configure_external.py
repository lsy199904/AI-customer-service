"""Prepare external-service configuration without executing shell or copying DB identity."""
import argparse
import os
from pathlib import Path
import re
import secrets
import shlex
from urllib.parse import urlsplit, urlunsplit, quote

ROOT = Path(__file__).resolve().parent.parent


def read_env(path):
    values = {}
    for number, line in enumerate(Path(path).read_text(encoding='utf-8').splitlines(), 1):
        line = line.strip()
        if not line or line.startswith('#'):
            continue
        if line.startswith('export '):
            line = line[7:].strip()
        key, sep, raw = line.partition('=')
        key = key.strip()
        if not sep or not re.fullmatch(r'[A-Z][A-Z0-9_]*', key) or key in values:
            raise ValueError('配置行格式错误或重复，行号：' + str(number))
        tokens = shlex.split(raw, comments=True)
        if len(tokens) > 1:
            raise ValueError('配置值含空格，请加引号，行号：' + str(number))
        value = tokens[0] if tokens else ''
        if any(c in value for c in '\n\r\x00'):
            raise ValueError('配置不允许换行或空字符')
        values[key] = value
    return values


def initialize(root=ROOT, source=None, database='ai_customer_external_test'):
    root = Path(root)
    target = root / '.env'
    if source and target.exists():
        raise ValueError('已有.env，拒绝从旧环境覆盖；请直接编辑现有配置')
    text = (target if target.exists() else root / '.env.example').read_text()
    values = read_env(target if target.exists() else root / '.env.example')
    # Upgrade older generated configs by appending newly introduced keys, never replacing values.
    template_path = root / '.env.example'
    template_values = read_env(template_path)
    missing = set(template_values) - set(values)
    if target.exists() and missing:
        additions = []; comments = []
        for line in template_path.read_text().splitlines():
            if line.startswith('#'):
                comments.append(line); continue
            if not line.strip():
                comments = []; continue
            key = line.partition('=')[0]
            if key in missing:
                additions.extend(comments + [line])
                values[key] = template_values[key]
            comments = []
        text = text.rstrip() + '\n\n# 新版部署模板新增参数（原配置保留）\n' + '\n'.join(additions) + '\n'
    updates = {}
    if not target.exists() and values.get('COMPOSE_PROJECT_NAME') == 'smarttitu_external':
        updates['COMPOSE_PROJECT_NAME'] = 'smarttitu_ext_' + secrets.token_hex(4)
    if source:
        previous = read_env(source)
        # Copy only model/client policy settings; never reuse source DB, namespace or signing key.
        for key in values:
            if (key.startswith(('MODEL_', 'EMBEDDING_', 'RERANK_', 'RAG_')) or key in ('SEMANTIC_MIN_SIMILARITY','RETRIEVAL_TIMEOUT_SECONDS','SESSION_RETENTION_DAYS','SESSION_CONTEXT_ROUNDS','SESSION_IDLE_SECONDS','SESSION_CLEANUP_INTERVAL_SECONDS','TENANT_MESSAGES_PER_MINUTE')) and key in previous:
                updates[key] = previous[key]
        for key in ('MILVUS_URI', 'MILVUS_TOKEN', 'MILVUS_DATABASE'):
            if previous.get(key):
                updates[key] = previous[key]
        parsed = urlsplit(previous.get('DATABASE_URL', ''))
        if parsed.scheme not in ('postgres', 'postgresql') or not parsed.hostname:
            raise ValueError('来源环境没有有效DATABASE_URL')
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]{0,62}', database):
            raise ValueError('测试数据库名称仅允许字母、数字、下划线')
        if database == parsed.path.lstrip('/') or database in ('postgres', 'template0', 'template1'):
            raise ValueError('必须指定与旧环境不同的独立测试数据库')
        updates['DATABASE_URL'] = urlunsplit(parsed._replace(path='/' + quote(database, safe='')))
        updates.update(APP_HOST='0.0.0.0', ANONYMOUS_COOKIE_SECURE='false')
    values.update(updates)
    for key in ('AUTH_SECRET', 'OPERATIONS_TOKEN', 'DEPLOYMENT_ID'):
        if not values.get(key):
            updates[key] = secrets.token_urlsafe(48 if key == 'AUTH_SECRET' else 24)
    if not values.get('MILVUS_COLLECTION'):
        updates['MILVUS_COLLECTION'] = 'smarttitu_ext_' + secrets.token_hex(4)
    if not values.get('ANONYMOUS_COOKIE_NAME'):
        updates['ANONYMOUS_COOKIE_NAME'] = 'smarttitu_ext_' + secrets.token_hex(6)
    # No shell expansion in generated Compose .env, including literal dollar signs in credentials.
    for key, value in updates.items():
        escaped = "'" + value.replace('\\', '\\\\').replace("'", "\\'") + "'"
        pattern = r'^' + re.escape(key) + '=.*$'
        text = re.sub(pattern, lambda _: key + '=' + escaped, text, flags=re.M)
    # shlex and Compose single-quote escaping differ. Use a strict portable subset for generated values.
    for value in updates.values():
        if "'" in value or '\\' in value:
            raise ValueError('自动生成配置不接受单引号或反斜杠；请使用URL编码或手动配置')
    temporary = root / ('.env.init-' + secrets.token_hex(6))
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            handle.write(text)
        temporary.replace(target)
    finally:
        temporary.unlink(missing_ok=True)
    for name in ('var', 'backups'):
        (root / name).mkdir(exist_ok=True, mode=0o700)
    print('已准备.env；未连接或修改旧数据库。已有非空密钥保持不变。')
    if source:
        print('复制了旧环境模型接口，使用独立测试数据库及随机Milvus集合前缀。')
    else:
        print('请填写三个模型API、DATABASE_URL、MILVUS_URI、MILVUS_TOKEN后执行deploy。')


def validate_local(root=ROOT):
    values = read_env(Path(root) / '.env')
    required = ('ANONYMOUS_COOKIE_NAME', 'AUTH_SECRET', 'DEPLOYMENT_ID', 'DATABASE_URL', 'MILVUS_URI', 'MILVUS_TOKEN',
                'MILVUS_COLLECTION', 'MODEL_BASE_URL', 'MODEL_API_KEY', 'MODEL_NAME',
                'EMBEDDING_URL', 'EMBEDDING_MODEL', 'EMBEDDING_API_KEY',
                'RERANK_URL', 'RERANK_MODEL', 'RERANK_API_KEY')
    missing = [key for key in required if not values.get(key)]
    if missing:
        raise ValueError('请填写.env参数：' + ', '.join(missing))
    if values.get('ANSWER_MODE') != 'llm' or values.get('RETRIEVAL_BACKEND') != 'semantic' or values.get('VECTOR_BACKEND') != 'milvus':
        raise ValueError('本入口固定采用llm + semantic + milvus')
    if values.get('RERANK_ENABLED') != 'true' or values.get('EMBEDDING_PROVIDER') != 'openai':
        raise ValueError('本入口要求三个模型API：openai兼容Embedding与启用Rerank')
    if len(values['AUTH_SECRET'].encode()) < 32:
        raise ValueError('AUTH_SECRET须至少32字节')
    database = urlsplit(values['DATABASE_URL'])
    if database.scheme not in ('postgres', 'postgresql') or not database.hostname or database.path in ('', '/', '/postgres', '/template0', '/template1'):
        raise ValueError('DATABASE_URL必须指向独立业务数据库，不能使用维护库')
    if not re.fullmatch(r'[a-z0-9][a-z0-9_-]{0,49}', values.get('COMPOSE_PROJECT_NAME', '')):
        raise ValueError('COMPOSE_PROJECT_NAME格式无效')
    if not 1 <= int(values.get('APP_PORT', '8201')) <= 65535:
        raise ValueError('APP_PORT无效')
    if values.get('MILVUS_COLLECTION') == 'smarttitu_knowledge':
        raise ValueError('拒绝复用旧服务默认集合前缀；请为新部署选择独立前缀')
    print('本地配置完整；密钥未输出。')
    return values


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='已有服务部署配置')
    parser.add_argument('--from', dest='source')
    parser.add_argument('--database', default='ai_customer_external_test')
    parser.add_argument('--check', action='store_true')
    parser.add_argument('--image')
    parser.add_argument('--show-url', action='store_true')
    parser.add_argument('--check-port', action='store_true')
    args = parser.parse_args()
    try:
        if args.check:
            validate_local()
        elif args.image:
            if not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_./:@-]*', args.image):
                raise ValueError('镜像名称格式无效')
            env = ROOT / '.env'
            text = re.sub(r'^ASSISTANT_IMAGE=.*$', lambda _: 'ASSISTANT_IMAGE=' + args.image, env.read_text(), flags=re.M)
            env.write_text(text); os.chmod(env, 0o600)
            print('已保存本次使用的本地应用镜像，后续start沿用该镜像。')
        elif args.check_port:
            import socket
            values = read_env(ROOT / '.env')
            host = values.get('APP_HOST', '127.0.0.1'); port = int(values.get('APP_PORT', '8201'))
            with socket.socket(socket.AF_INET6 if ':' in host else socket.AF_INET, socket.SOCK_STREAM) as listener:
                try:
                    listener.bind((host, port))
                except OSError:
                    raise ValueError('APP_HOST或APP_PORT不可绑定，请检查地址或选择未占用端口') from None
            print('应用监听地址及端口可用。')
        elif args.show_url:
            values = read_env(ROOT / '.env'); port = values.get('APP_PORT', '8201')
            print('部署完成。本机检查页：http://127.0.0.1:' + port + '/smart-bot/widget/anonymous-demo')
            print('其他电脑访问请使用服务器真实地址；APP_HOST需监听该地址，且防火墙允许访问。')
        else:
            initialize(source=args.source, database=args.database)
    except (ValueError, OSError):
        # The parser can encounter secret values in malformed lines; never show raw exception text.
        import sys
        error = sys.exc_info()[1]
        print(str(error) if isinstance(error, ValueError) else '配置读取失败，请检查文件路径、权限、引号与格式', file=sys.stderr)
        raise SystemExit(2)
