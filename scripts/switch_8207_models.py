#!/usr/bin/env python3
"""Rebuild and cut over only the SmartTITU 8207 model trial."""
import argparse
import fcntl
import getpass
import json
from pathlib import Path
import subprocess
import tempfile
import time
from urllib.parse import parse_qsl, urlsplit, urlunsplit

SERVICE = 'smarttitu_rag_8207-assistant-1'
BACKUP = 'smarttitu-rag-8207-before-model-trial'
PENDING = 'smarttitu-rag-8207-model-trial-pending'
DATABASE = 'smarttitu_rag_8207_pro'
FLYWAY = 'flyway/flyway:11.20.3-alpine'
REPO = Path(__file__).resolve().parents[1]


def docker(*args, capture=False):
    result = subprocess.run(['docker', *args], check=True, text=True, capture_output=capture)
    return result.stdout.strip() if capture else None


def exists(name):
    return subprocess.run(['docker', 'container', 'inspect', name],
                          stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0


def isolated_database(url):
    parts = urlsplit(url)
    if (parts.scheme not in ('postgresql', 'postgres') or not parts.hostname
            or any(key.lower() == 'dbname' for key, _ in parse_qsl(parts.query))):
        raise SystemExit('当前 DATABASE_URL 不是可安全替换库名的 PostgreSQL URI。')
    if parts.path.rstrip('/') == '/' + DATABASE:
        raise SystemExit('8207 已经指向新库，请先核对当前容器状态。')
    return urlunsplit(parts._replace(path='/' + DATABASE, fragment=''))


def write_env(path, values):
    for key, value in values.items():
        if '\r' in value or '\n' in value:
            raise SystemExit(f'环境变量 {key} 有换行，请先核对配置。')
    with path.open('x', encoding='utf-8') as handle:
        path.chmod(0o600)
        handle.write(''.join(f'{key}={value}\n' for key, value in values.items()))


def cutover(candidate):
    renamed = False
    stopped = False
    try:
        docker('stop', '--timeout', '30', SERVICE)
        stopped = True
        docker('rename', SERVICE, BACKUP)
        renamed = True
        docker('rename', candidate, SERVICE)
        docker('start', candidate)
        deadline = time.monotonic() + 90
        probe = ("import urllib.request; "
                 "urllib.request.urlopen('http://127.0.0.1:8207/smart-bot/ready',timeout=4).close()")
        while time.monotonic() < deadline:
            result = subprocess.run(['docker', 'exec', candidate, 'python', '-c', probe],
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            if result.returncode == 0:
                print(f'8207 已就绪。旧 8207 容器保留为 {BACKUP}。', flush=True)
                return
            time.sleep(2)
        raise RuntimeError('8207 在等待时限内未就绪。')
    except BaseException:
        print('切换失败，尝试恢复旧 8207。', flush=True)
        if exists(candidate):
            docker('rm', '-f', candidate)
        if renamed:
            docker('rename', BACKUP, SERVICE)
        if stopped:
            docker('start', SERVICE)
        raise


def switch(flyway_image):
    for name in (PENDING, BACKUP):
        if exists(name):
            raise SystemExit(f'{name} 已存在，请先检查上次切换结果。')
    source = json.loads(docker('inspect', SERVICE, capture=True))[0]
    if not source['State']['Running']:
        raise SystemExit('请先确认现有 8207 正在运行。')
    for path in (REPO / 'app/query_context.py', REPO / 'database/postgres/flyway.conf',
                 REPO / 'database/milvus/manage.py', REPO / 'deploy/docker/db-migrate/entrypoint.sh'):
        if not path.is_file():
            raise SystemExit(f'缺少所需文件：{path}')
    if subprocess.run(['docker', 'image', 'inspect', flyway_image],
                      stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode:
        raise SystemExit('本机没有指定 Flyway 镜像。可用 --flyway-image 选择本机已有镜像。')
    source_id = source['Id']
    config, host = source['Config'], source['HostConfig']
    network = 'host' if host['NetworkMode']=='host' else next(iter(source['NetworkSettings']['Networks']), '')
    if not network:
        raise SystemExit('无法识别 8207 的 Docker 网络。')
    python, app_root = docker('exec', SERVICE, 'python', '-c',
        'import sys; from pathlib import Path; import app.core as m;'
        'print(sys.executable); print(Path(m.__file__).resolve().parents[1])', capture=True).splitlines()
    env = dict(item.split('=', 1) for item in config['Env'])
    db_url = isolated_database(env.get('DATABASE_URL', ''))
    test_var = REPO / 'var/embedding-pro-8207'
    test_var.mkdir(parents=True, exist_ok=True)
    config_path = REPO / 'deploy/compose/8207-model-trial.env.example'
    trial = dict(line.split('=', 1) for line in config_path.read_text().splitlines()
                 if line and not line.startswith('#'))
    key = getpass.getpass('请输入上述网关的 API Key（两种模型都须有权限，输入不可见）：').strip()
    if not key:
        raise SystemExit('需要提供试用网关 API Key。')
    env.update(trial)
    env.update(DATABASE_URL=db_url, DEPLOYMENT_ID='smarttitu-rag-8207-pro',
               VECTOR_BACKEND='milvus', MILVUS_COLLECTION='smarttitu_rag_8207_pro',
               QUERY_CONTEXT_API_KEY=key, EMBEDDING_API_KEY=key,
               ANONYMOUS_COOKIE_NAME='smarttitu_8207_pro_visitor',
               PORT='8207', APP_PORT='8207', HOST='0.0.0.0',
               KNOWLEDGE_SOURCE_DIR=f'{app_root}/knowledge_sources',
               PDF_MEDIA_DIR=f'{app_root}/var/pdf_media', LOG_DIR='')
    migration_env = {
        'DATABASE_URL': db_url,
        'FLYWAY_PLACEHOLDERS_DEPLOYMENT_ID': env['DEPLOYMENT_ID'],
        'FLYWAY_PLACEHOLDERS_MILVUS_URI': env['MILVUS_URI'].rstrip('/'),
        'FLYWAY_PLACEHOLDERS_MILVUS_DATABASE': env.get('MILVUS_DATABASE') or 'default',
        'FLYWAY_PLACEHOLDERS_MILVUS_PREFIX': env['MILVUS_COLLECTION'],
    }
    base = ['--pull=never', '--network', network, '--volumes-from', source_id,
            '-v', f'{test_var}:{app_root}/var',
            '-v', f'{REPO}/app:{app_root}/app:ro',
            '-v', f'{REPO}/data:{app_root}/data:ro',
            '-v', f'{REPO}/knowledge_sources:{app_root}/knowledge_sources:ro',
            '-w', app_root, '--entrypoint', python]
    if config.get('User'):
        base += ['--user', config['User']]
    if host.get('ReadonlyRootfs'):
        base += ['--read-only']
    for target, options in (host.get('Tmpfs') or {}).items():
        base += ['--tmpfs', f'{target}:{options}' if options else target]
    image = source['Image']
    with tempfile.TemporaryDirectory(prefix='smarttitu-8207-') as private:
        app_env, flyway_env = Path(private) / 'app.env', Path(private) / 'flyway.env'
        write_env(app_env, env)
        write_env(flyway_env, migration_env)
        base += ['--env-file', str(app_env)]
        print(f"检查模型接口。理解模型 {trial['QUERY_CONTEXT_MODEL_NAME']}，"
              f"Embedding {trial['EMBEDDING_MODEL']}。", flush=True)
        docker('run', '--rm', *base, image, '-c',
               "from app.core import Model, Settings;"
               "from app.query_context import interpret;"
               "s=Settings(); s.validate();"
               "result=interpret(Model(s), '如何创建 API 密钥？', []);"
               "assert result['intent']=='knowledge', '理解模型未识别产品问题';"
               "print('理解模型检查通过')")
        docker('run', '--rm', *base, image, '-c',
               "from pathlib import Path; from app.rag import RAGSettings, EmbeddingClient;"
               "s=RAGSettings(); v=EmbeddingClient(s).embed(['连接检查'])[0];"
               "p=Path(s.pdf_media_dir); p.mkdir(parents=True,exist_ok=True);"
               "print('Embedding 返回维度:',len(v))")
        print(f'准备独立 PostgreSQL 库 {DATABASE}。', flush=True)
        docker('run', '--rm', *base, image, '-c',
               'from app.deployment import database_connection; database_connection(create=True).close()')
        docker('run', '--rm', '--pull=never', '--network', network,
               '--env-file', str(flyway_env), '-w', '/flyway',
               '-v', f'{REPO}/database/postgres/flyway.conf:/flyway/conf/smarttitu.conf:ro',
               '-v', f'{REPO}/database/postgres/migrations:/flyway/migrations:ro',
               '-v', f'{REPO}/deploy/docker/db-migrate/entrypoint.sh:/tmp/smarttitu-migrate.sh:ro',
               '--entrypoint', 'sh', flyway_image, '/tmp/smarttitu-migrate.sh',
               '-configFiles=/flyway/conf/smarttitu.conf', 'migrate')
        docker('run', '--rm', *base, image, '-m', 'app.deployment', 'initialize')
        print('全量生成新知识向量。8207 仍在运行旧版本。', flush=True)
        job = ['--rm', *base, '-v', f'{REPO}/database/milvus/manage.py:{app_root}/manage.py:ro', image]
        docker('run', *job, 'manage.py', 'ingest', '--rebuild')
        docker('run', '--rm', *base, image, '-c',
               "from app.rag import RAGSettings, SemanticKnowledge;"
               "r=SemanticKnowledge(RAGSettings()).assess('客户充值流程');"
               "assert r['matched'], '新索引没有命中客户充值流程'; print('新索引检索通过')")
        publish = [] if network=='host' else ['-p', '0.0.0.0:8207:8207']
        candidate = docker('create', '--name', PENDING, '--restart', 'unless-stopped',
                           *base, *publish, image, '-m', 'app.server',
                           '--host', '0.0.0.0', '--port', '8207', capture=True)
        cutover(candidate)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--flyway-image', default=FLYWAY, help='宿主机已有的 Flyway 镜像')
    args = parser.parse_args()
    lock = Path.home() / '.smarttitu-8207-model-trial.lock'
    with lock.open('a') as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise SystemExit('已有一个 8207 切换在运行。') from None
        switch(args.flyway_image)


if __name__ == '__main__':
    main()
