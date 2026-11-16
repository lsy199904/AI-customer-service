"""Prepare business databases inside already provisioned cloud instances."""
import json
import os


def prepare_postgres():
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    target = conninfo_to_dict(os.environ['DATABASE_URL'])
    name, user = target.get('dbname', ''), target.get('user', '')
    password = target.get('password', '')
    if not name or name in ('postgres', 'template0', 'template1') or not user or not password:
        raise ValueError('DATABASE_URL需填写独立业务库、专用账号及密码')
    if os.getenv('CLOUD_PREPARE_PG', 'true') == 'true':
        admin_options = conninfo_to_dict(os.environ['PG_ADMIN_URL'])
        # Never create on an accidentally different instance.
        for key, default in [('host', ''), ('port', '5432')]:
            if str(admin_options.get(key, default)) != str(target.get(key, default)):
                raise ValueError('PG管理员与业务连接必须指向同一实例和端口')
        with psycopg.connect(**admin_options, connect_timeout=10, autocommit=True) as admin:
            if user == admin.execute('SELECT current_user').fetchone()[0]:
                raise ValueError('业务账号不能复用管理员账号')
            role = admin.execute('SELECT rolsuper,rolcreatedb,rolcreaterole FROM pg_roles WHERE rolname=%s', (user,)).fetchone()
            if role and any(role):
                raise ValueError('已有业务角色权限过高，请使用专用普通角色')
            if not role:
                admin.execute(sql.SQL('CREATE ROLE {} LOGIN PASSWORD {}').format(sql.Identifier(user), sql.Literal(password)))
            existing = admin.execute('SELECT pg_get_userbyid(datdba) FROM pg_database WHERE datname=%s', (name,)).fetchone()
            if existing and existing[0] != user:
                raise ValueError('同名数据库由其他角色拥有，拒绝修改；请使用新库名')
            if not existing:
                admin.execute(sql.SQL('CREATE DATABASE {} OWNER {}').format(sql.Identifier(name), sql.Identifier(user)))
        # No ALTER ROLE, DROP or password reset on repeated runs.
    with psycopg.connect(**target, connect_timeout=10) as conn:
        allowed = conn.execute("SELECT has_database_privilege(current_database(),'CREATE')").fetchone()[0]
        if not allowed:
            raise ValueError('业务账号需要目标库CREATE权限以初始化两个schema')
    print('PG业务库及业务账号连接检查通过', flush=True)


def prepare_milvus():
    from pymilvus import MilvusClient
    uri = os.environ['MILVUS_URI']; database = os.getenv('MILVUS_DATABASE', 'default')
    if os.getenv('CLOUD_PREPARE_MILVUS', 'false') == 'true':
        admin = MilvusClient(uri=uri, token=os.environ['MILVUS_ADMIN_TOKEN'], timeout=15)
        try:
            if database not in admin.list_databases(timeout=15):
                admin.create_database(db_name=database, timeout=30)
        finally:
            admin.close()
    # Cloud IAM/token issuance is provider-specific; use the platform-issued app token.
    client = MilvusClient(uri=uri, token=os.environ['MILVUS_TOKEN'], db_name=database, timeout=15)
    try:
        client.list_collections(timeout=15)
    finally:
        client.close()
    print('Milvus业务数据库及应用凭证连接检查通过', flush=True)


def main():
    stage = 'PG'
    try:
        prepare_postgres()
        stage = 'Milvus'; prepare_milvus()
        print('云端业务数据库准备完成；表结构与向量集合由部署初始化创建', flush=True)
    except Exception as error:
        # Provider/DB exceptions may echo passwords or tokens.
        print(json.dumps({'stage': stage, 'error_type': type(error).__name__,
                          'message': str(error) if isinstance(error, ValueError) else '请核对连接、权限及网络；底层错误未输出以保护凭证'}, ensure_ascii=False), flush=True)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
