"""Map the private App .env into the existing independent Flyway runner.

Does not create a PostgreSQL instance/database, run ingest or start the App.
Existing migration SQL remains owned by database/postgres.
"""
import os
from pathlib import Path
import subprocess
import sys
from urllib.parse import unquote, urlsplit, urlunsplit

from configure_external import read_env

ROOT = Path(__file__).resolve().parent.parent


def migration_environment(values):
    uri = urlsplit(values.get('DATABASE_URL', ''))
    if uri.scheme not in ('postgres', 'postgresql') or not uri.hostname:
        raise ValueError('请填写指向独立测试库的DATABASE_URL')
    database = unquote(uri.path.lstrip('/'))
    if not database or database in ('postgres', 'template0', 'template1'):
        raise ValueError('拒绝在维护库运行业务迁移，请管理员先创建独立业务库')
    username = unquote(uri.username or '')
    if not username:
        raise ValueError('DATABASE_URL需要明确指定迁移账号')
    names = {'DEPLOYMENT_ID': 'DEPLOYMENT_ID', 'MILVUS_URI': 'MILVUS_URI',
             'MILVUS_DATABASE': 'MILVUS_DATABASE', 'MILVUS_COLLECTION': 'MILVUS_PREFIX'}
    env = {}
    for source, target in names.items():
        value = values.get(source, 'default' if source == 'MILVUS_DATABASE' else '')
        if not value or any(c in value for c in "'\\\r\n\x00"):
            raise ValueError('迁移归属配置缺失或含不支持字符：' + source)
        env['FLYWAY_PLACEHOLDERS_' + target] = value
    host = '[' + uri.hostname + ']' if ':' in uri.hostname else uri.hostname
    authority = host + (':' + str(uri.port) if uri.port else '')
    env.update(FLYWAY_URL='jdbc:' + urlunsplit(('postgresql', authority, uri.path, uri.query, '')),
               FLYWAY_USER=username, FLYWAY_PASSWORD=unquote(uri.password or ''))
    env['FLYWAY_IMAGE'] = os.getenv('FLYWAY_IMAGE', 'flyway/flyway:11.20.3-alpine')
    return env


def main():
    if len(sys.argv) > 1:
        raise ValueError('本入口只执行migrate；info/baseline等运维动作请使用scripts/db.sh')
    values = read_env(ROOT / '.env')
    env = {**os.environ, **migration_environment(values)}
    print('使用.env对应业务库执行独立Flyway迁移；不输出凭证，不入库、不启动App。', flush=True)
    return subprocess.call(['bash', str(ROOT / 'scripts/db.sh'), 'migrate'], cwd=ROOT, env=env)


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except (ValueError, OSError):
        print('迁移配置无效或执行器不可用；请核对独立数据库、归属参数、Docker与Bash。未输出凭证。', file=sys.stderr)
        raise SystemExit(2)
