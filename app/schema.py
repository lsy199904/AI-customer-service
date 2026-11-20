"""数据库 schema 契约：迁移由独立 migration 镜像/任务完成，应用只校验、不建表。"""
import re

# 应用要求的最低 schema 版本；只有 app 依赖的新结构才需要上调，不跟随 Flyway 最新版本。
SCHEMA_VERSION = '1.0.0'
# 与 langgraph-checkpoint-postgres==3.2.0 的 MIGRATIONS 数量 - 1 保持一致。
CHECKPOINT_VERSION = 9


class SchemaNotReady(RuntimeError):
    """数据库未迁移、迁移失败或版本低于应用要求。"""


def _value(row, key, index=0):
    if row is None:
        return None
    if isinstance(row, dict):
        return row.get(key)
    return row[index]


def _version(text):
    if not isinstance(text, str) or not re.fullmatch(r'\d+(?:\.\d+){0,2}', text):
        raise SchemaNotReady('数据库迁移版本格式无效，请检查 Flyway 迁移记录')
    parts = [int(p) for p in text.split('.')]
    return tuple(parts + [0] * (3 - len(parts)))


def require_postgres_schema(db):
    """在应用启动最早期调用；任何不满足都直接失败，不尝试修复。"""
    marker = db.execute(
        "SELECT to_regclass('assistant.flyway_schema_history') AS t"
    ).fetchone()
    if _value(marker, 't') is None:
        raise SchemaNotReady(
            '数据库尚未迁移或业务账号缺少 assistant schema 的 USAGE 权限；'
            '请先运行 db-migrate 并检查授权'
        )

    failed = db.execute(
        'SELECT count(*) AS n FROM assistant.flyway_schema_history WHERE success=false'
    ).fetchone()
    if _value(failed, 'n'):
        raise SchemaNotReady('Flyway 存在失败迁移，请先修复并执行 flyway repair')

    row = db.execute(
        'SELECT version FROM assistant.flyway_schema_history '
        'WHERE version IS NOT NULL ORDER BY installed_rank DESC LIMIT 1'
    ).fetchone()
    if row is None:
        raise SchemaNotReady('数据库尚未执行 Flyway 迁移，请先运行 db-migrate 或迁移 Job')

    current = _value(row, 'version')
    if _version(current) < _version(SCHEMA_VERSION):
        raise SchemaNotReady(
            '数据库版本 %s 低于应用要求 %s，请先升级数据库' % (current, SCHEMA_VERSION)
        )

    checkpoints = db.execute(
        'SELECT max(v) AS v FROM assistant.checkpoint_migrations'
    ).fetchone()
    version = _value(checkpoints, 'v')
    if version is None or version < CHECKPOINT_VERSION:
        raise SchemaNotReady('LangGraph 检查点表版本过低，请先执行数据库迁移')


def require_checkpoint_schema(connection):
    """供 workflow 在持有 psycopg 连接时调用（返回 tuple，不是 dict）。"""
    marker = connection.execute(
        "SELECT to_regclass('assistant.checkpoint_migrations')"
    ).fetchone()
    if not marker or marker[0] is None:
        raise SchemaNotReady('LangGraph 检查点表不存在或不可见，请先执行数据库迁移并检查授权')

    row = connection.execute(
        'SELECT max(v) FROM assistant.checkpoint_migrations'
    ).fetchone()
    version = row[0] if row else None
    if version is None or version < CHECKPOINT_VERSION:
        raise SchemaNotReady('LangGraph 检查点表版本过低，请先执行数据库迁移')
