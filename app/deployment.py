"""Existing-service deployment checks. No destructive database or collection operations."""
import argparse
import json
import os
from pathlib import Path
import sys


class DeploymentError(ValueError):
    pass


def output(stage, **fields):
    print(json.dumps({'step': stage, **fields}, ensure_ascii=False), flush=True)


def database_connection(create=False):
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import conninfo_to_dict
    options = conninfo_to_dict(os.environ['DATABASE_URL'])
    options.update(connect_timeout=10)
    name = options.get('dbname', '')
    if not name or name in ('postgres', 'template0', 'template1'):
        raise DeploymentError('请使用独立业务数据库，不能使用维护库')
    try:
        return psycopg.connect(**options, autocommit=True)
    except psycopg.Error as error:
        if not create or error.sqlstate != '3D000':
            raise
    # Explicit opt-in only: CREATE DATABASE needs CREATEDB privilege, no privilege escalation.
    with psycopg.connect(**{**options, 'dbname': 'postgres'}, autocommit=True) as admin:
        permitted = admin.execute('SELECT rolcreatedb OR rolsuper FROM pg_roles WHERE rolname=current_user').fetchone()[0]
        if not permitted:
            raise DeploymentError('账号没有建库权限，请管理员先创建独立数据库并授权')
        try:
            admin.execute(sql.SQL('CREATE DATABASE {}').format(sql.Identifier(name)))
        except psycopg.errors.DuplicateDatabase:
            pass
    output('独立测试数据库已创建')
    return psycopg.connect(**options, autocommit=True)


def namespace():
    return {
        'id': os.environ['DEPLOYMENT_ID'],
        'milvus_uri': os.environ['MILVUS_URI'].rstrip('/'),
        'milvus_database': os.getenv('MILVUS_DATABASE', 'default'),
        'milvus_prefix': os.environ['MILVUS_COLLECTION'],
    }


def check_database(conn):
    """Read-only validation; return whether knowledge has already been ingested."""
    from .schema import require_postgres_schema
    require_postgres_schema(conn)
    marker = conn.execute("SELECT to_regclass('assistant.external_deployment')").fetchone()[0]
    if not marker:
        raise DeploymentError('缺少部署归属表，请先执行独立PG迁移任务')
    row = conn.execute('SELECT metadata FROM assistant.external_deployment WHERE id=1').fetchone()
    if not row or row[0] != namespace():
        raise DeploymentError('数据库属于其他部署或Milvus配置已变更，拒绝继续')
    allowed = conn.execute("""
        SELECT has_schema_privilege('assistant','USAGE')
        AND has_schema_privilege('knowledge','USAGE')
        AND has_table_privilege('assistant.messages','SELECT')
        AND has_table_privilege('assistant.messages','INSERT')
        AND has_table_privilege('knowledge.rag_documents','SELECT')
    """).fetchone()[0]
    if not allowed:
        raise DeploymentError('业务账号缺少schema USAGE或业务表DML权限，请检查迁移任务授权')
    return bool(conn.execute('SELECT EXISTS(SELECT 1 FROM knowledge.rag_documents)').fetchone()[0])


def check_media_and_sources(config, rag):
    from .conversation import MediaCatalog
    from .core import BASE
    from .ingestion import SUPPORTED, parse_document
    catalog = MediaCatalog(config.media_path, BASE / 'app/static/media')
    catalog.include_generated(config.pdf_media_dir)
    sources = sorted(p for p in Path(rag.source_dir).rglob('*') if p.suffix.lower() in SUPPORTED and p.is_file() and not p.name.startswith('~$'))
    if not sources:
        raise DeploymentError('knowledge_sources中没有可入库文档')
    count = 0
    for path in sources:
        parsed = parse_document(path, rag.chunk_chars, rag.overlap_chars)
        count += len(parsed.chunks)
        required = {key for chunk in parsed.chunks for key in chunk.get('image_ids', [])}
        if required - catalog.rows.keys():
            raise DeploymentError('文档引用的图片编号没有登记，请核对media.json和图片文件')
    output('文档与图片检查通过', source_files=len(sources), text_chunks=count)


def check_models(config, rag):
    from .rag import EmbeddingClient, RerankerClient
    from .core import Model
    def invoke(name, call):
        output('模型接口检查', model_stage=name)
        try:
            return call()
        except Exception as error:
            raise DeploymentError(name + '检查失败（' + type(error).__name__ + '），请核对URL、Key、模型ID、协议和网络') from None
    vector = invoke('Embedding', lambda: EmbeddingClient(rag).embed(['连接检查']))[0]
    output('Embedding接口正常', dimensions=len(vector))
    invoke('Rerank', lambda: RerankerClient(rag).rank('如何注册企业账号', ['使用手机号注册企业账号。', '查询账单。']))
    output('Rerank接口正常')
    result = invoke('LLM', lambda: Model(config).answer('你好', [], [], {'_intent': 'greeting'}))
    if not result.get('answer'):
        raise DeploymentError('回答模型未返回有效正文')
    output('LLM接口正常')
    return len(vector)


def check_milvus(rag, owned, dimensions):
    from .vectors import MilvusVectors
    index = MilvusVectors(rag)
    try:
        names = index.client.list_collections(timeout=15)
        conflicts = [name for name in names if name.startswith(rag.milvus_collection + '_')]
        if conflicts and not owned:
            raise DeploymentError('Milvus集合前缀已被占用，请使用新的独立前缀')
        if index.collection in names:
            schema = index.client.describe_collection(index.collection, timeout=15)
            actual = next(int(f['params']['dim']) for f in schema['fields'] if f['name'] == 'vector')
            if actual != dimensions:
                raise DeploymentError('已有向量维度不一致，请使用新的Embedding版本和集合前缀')
        output('Milvus连接检查通过', database=rag.milvus_database, collection=index.collection,
               index_type=rag.milvus_index_type)
    finally:
        index.close()


def main():
    parser = argparse.ArgumentParser(description='连接已有服务，不启动数据库容器、不迁移旧数据')
    parser.add_argument('action', choices=['check', 'initialize'])
    parser.add_argument('--create-database', action='store_true')
    args = parser.parse_args()
    from .schema import SchemaNotReady
    stage = '配置检查'
    try:
        from .core import Settings
        from .rag import RAGSettings
        config = Settings(); config.validate()
        rag = RAGSettings(); rag.validate()
        if not config.database_url or rag.vector_backend != 'milvus' or not os.getenv('DEPLOYMENT_ID'):
            raise DeploymentError('请先通过production.sh init或dev.sh init准备配置')
        stage = 'PG连接与部署隔离检查'
        with database_connection(args.create_database) as conn:
            owned = check_database(conn)
            output('PG连接及隔离检查通过', knowledge_initialized=owned)
            if args.action == 'check' and owned:
                state = conn.execute('SELECT fingerprint FROM knowledge.rag_state WHERE id=1').fetchone()
                if not state or state[0] != rag.fingerprint:
                    raise DeploymentError('Embedding或切片配置已变化，请执行production.sh update-knowledge --rebuild后再启动')
            stage = '文档与图片检查'; check_media_and_sources(config, rag)
            stage = '模型接口检查'; dimensions = check_models(config, rag)
            stage = 'Milvus连接检查'; check_milvus(rag, owned, dimensions)
            if args.action == 'initialize':
                output('PG结构与版本校验通过', note='建表及升级由独立PG迁移任务完成')
        output('前置检查完成', note='未写入知识向量；下一步执行ingest')
    except Exception as error:
        # HTTP/DB exceptions can contain credentials or provider response bodies.
        message = str(error) if isinstance(error, (DeploymentError, SchemaNotReady)) else '请核对该阶段配置、权限、接口协议及网络；未输出可能含密钥的底层错误'
        output('失败', failed_stage=stage, error_type=type(error).__name__, message=message)
        raise SystemExit(1)


if __name__ == '__main__':
    main()
