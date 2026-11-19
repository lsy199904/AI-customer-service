# app 端迁移解耦改造说明

> **范围**：仅 `app/` 目录。本文不含 PostgreSQL 迁移方案、Dockerfile、K8s 清单与运维流程；这些见 [`archive/PostgreSQL迁移解耦核对说明.md`](archive/PostgreSQL迁移解耦核对说明.md)。
> **目标**：移除 app 的 PostgreSQL DDL，启动时只校验 schema 版本；SQLite 本地开发模式保持原样。
> **前置条件**：目标数据库已由独立 `db-migrate` 镜像迁移到 `1.0.0`，且 `assistant` / `knowledge` 两个 schema、17 张表、检查点表均已存在。
> **约束**：只改初始化与校验，不改请求处理、检索、生成、API 返回结构。
> **改动量**：新增约 80 行（`app/schema.py`），修改约 100 行；无业务逻辑变更。

---

## 1. 改造原则

1. **PG 分支零 DDL**：`DATABASE_URL` 有值时，启动与请求路径不再执行任何 `CREATE/ALTER/DROP`。`deployment.py --create-database` 的建库操作属于显式运维命令，不在启动路径内。
2. **SQLite 分支不动**：`DATABASE_URL` 为空时，仍由 app 自建 SQLite 表，本地开发与单测不受影响。
3. **失败即退出**：schema 缺失、版本低、迁移失败，一律抛 `SchemaNotReady`，进程非零退出；不降级、不自动修复。
4. **不改业务 SQL**：现有 `INSERT/SELECT/UPDATE/DELETE` 全部保留，包括位置式 `INSERT`。

---

## 2. 改动清单

| ID | 文件:行 | 现状 | 改动 | 优先级 |
|---|---|---|---|---|
| A1 | `app/storage.py:61-65` | 建连接池时 `CREATE SCHEMA IF NOT EXISTS` | 整块删除 | P0 |
| A2 | `app/core.py:376-397` | 启动时建 6 表 + 4 索引 + `messages.seq` | PG 分支改为 `require_postgres_schema()`；DDL 只留 SQLite 分支 | P0 |
| A3 | `app/rag.py:145-156`、`162-164` | 启动时建 6 表 + `rag_state` 种子 | `SCHEMA` 改名 `SQLITE_SCHEMA`；PG 分支改为版本校验 | P0 |
| A4 | `app/workflow.py:87-90` | `saver.setup()` 执行检查点迁移 | PG 分支删除 `setup()`，改为 `require_checkpoint_schema()` | P0 |
| A5 | `app/deployment.py:53-83` | `check_database()` + `claim()` 建表/写凭证行 | `check_database()` 只读；删除 `claim()` | P0 |
| A6 | `app/deployment.py:143-151`、`178-180` | `initialize_runtime()` 构造 Service 触发 DDL | 删除；`initialize` 改为校验 | P0 |
| A7 | `app/deployment.py:67` | 要求数据库 `CREATE` | 随 A5 改为 `USAGE` + 关键表 DML 校验 | P1 |
| A8 | `app/cloud.py:35-38` | 要求业务角色 `CREATE` | 改为 `CONNECT` 校验 | P1 |
| A9 | `app/migration.py:38-40` | 用 `Service`/`DocumentStore` 初始化目标库 | 改为 `PostgresDB` + `require_postgres_schema()` | P1 |
| A10 | 新增 `app/schema.py` | 无 | schema 版本契约与 fail-fast 校验 | P0 |
| A11 | `app/server.py:255-262` | `/ready` 只查 `SELECT 1` | **无需改动**；可选在 `/health` 暴露版本 | P2 |

---

## 3. 新增 `app/schema.py`

建议完整新增，约 80 行，不依赖任何业务模块，避免循环导入。

```python
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
    parts = [int(p) for p in re.findall(r'\d+', text or '')[:3]]
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
```

设计说明：

- `to_regclass` 先判断表是否存在，避免在未迁移库上抛出原始的 `UndefinedTable`。
- 先查 `success=false`，再取最新版本；否则失败迁移会被“版本号已够”掩盖。
- `WHERE version IS NOT NULL` 过滤 `R__` 可重复迁移，避免 `NULL` 版本干扰。
- `SCHEMA_VERSION` / `CHECKPOINT_VERSION` 是应用与迁移的显式契约；升级时必须同步修改。

---

## 4. 逐文件改动

### 4.1 `app/storage.py`

**现状（61–65）**：`PostgresDB.__init__` 建池后创建 schema。

```python
        with self.pool.connection() as c:
            key=int.from_bytes(hashlib.sha256(('schema:'+schema).encode()).digest()[:8],'big',signed=True)
            c.execute('SELECT pg_advisory_lock(%s)',(key,))
            try:c.execute('CREATE SCHEMA IF NOT EXISTS '+schema)
            finally:c.execute('SELECT pg_advisory_unlock(%s)',(key,))
```

**改为**：整块删除。`configure()` 中的 `SET search_path`、`statement_timeout`、`lock_timeout` 保留。

**注意**：

- `hashlib` 仍被 `session_lock()` 使用，不要误删导入。
- `schema_lock()` 方法可以保留，但不再被调用；确认无其他引用后可一并删除。
- 删除后，schema 不存在会在 `require_postgres_schema()` 的 `to_regclass` 处报 `SchemaNotReady`，而不是连接池初始化时报 `permission denied`。

### 4.2 `app/core.py`

**现状（376–397）**：

```python
        from contextlib import nullcontext
        with (self.db.schema_lock() if config.database_url else nullcontext()):
            self.db.executescript('''PRAGMA journal_mode=WAL;
            ...
            CREATE TABLE IF NOT EXISTS workflow_runs(...);
            ''')
            if config.database_url:
                self.db.execute('ALTER TABLE messages ADD COLUMN IF NOT EXISTS seq BIGSERIAL UNIQUE')
```

**改为**：

```python
        if config.database_url:
            from .schema import require_postgres_schema
            try:
                require_postgres_schema(self.db)
            except Exception:
                self.db.close()
                raise
        else:
            self.db.executescript('''PRAGMA journal_mode=WAL;
            ...
            CREATE TABLE IF NOT EXISTS workflow_runs(...);
            ''')
```

**注意**：

- SQLite 分支原样保留，包括 `PRAGMA` 与全部 `CREATE TABLE/INDEX`。
- 删除 `nullcontext` 导入；`schema_lock()` 不再调用。
- `require_postgres_schema()` 失败时关闭连接池，避免启动失败后残留连接。
- 不要保留 `ALTER TABLE messages ADD COLUMN seq` 的 PG 分支；列已由 `V1.0.0` 创建。

### 4.3 `app/rag.py`

**现状（145–164）**：

```python
SCHEMA='''
PRAGMA journal_mode=WAL;
...
INSERT OR IGNORE INTO rag_state VALUES(1,'',0);
...
'''

class DocumentStore:
    def __init__(self,path,database_url=None):
        ...
        with self.connect() as db:
            if self.database_url:db.execute('SELECT pg_advisory_xact_lock(?)',(729630043,))
            db.executescript(SCHEMA)
```

**改为**：

```python
SQLITE_SCHEMA='''
PRAGMA journal_mode=WAL;
...
'''

class DocumentStore:
    def __init__(self,path,database_url=None):
        ...
        with self.connect() as db:
            if self.database_url:
                from .schema import require_postgres_schema
                require_postgres_schema(db)
            else:
                db.executescript(SQLITE_SCHEMA)
```

**注意**：

- `rag_state` 的种子行由迁移写入，PG 分支不再 `INSERT OR IGNORE`。
- 删除 `pg_advisory_xact_lock`：不再有 DDL 需要串行化。
- `DocumentStore` 在 `Service.__init__` 中先于 `self.db` 创建（`core.py:354-356`），所以它通常是**第一个** schema 校验点；错误信息要能直接指导值班人员。
- 如果校验失败，`storage.document_connection()` 会把连接池缓存在 `_knowledge_pools`；如需严格清理，可在异常时调用 `close_knowledge_pools()`，但非必需。

### 4.4 `app/workflow.py`

**现状（87–90）**：

```python
            self.saver=PostgresSaver(self._resource)
            with self._resource.connection() as connection:
                connection.execute('SELECT pg_advisory_lock(729630041)')
                try:self.saver.setup()
                finally:connection.execute('SELECT pg_advisory_unlock(729630041)')
```

**改为**：

```python
            self.saver=PostgresSaver(self._resource)
            from .schema import require_checkpoint_schema
            try:
                with self._resource.connection() as connection:
                    require_checkpoint_schema(connection)
            except Exception:
                self._resource.close()
                raise
```

**注意**：

- `PostgresSaver.setup()` 必须删除。它每次都会执行 `MIGRATIONS[0]` 的 `CREATE TABLE IF NOT EXISTS checkpoint_migrations`，即使版本已是最新；这会要求 schema 的 `CREATE` 权限。
- SQLite 分支的 `SqliteSaver.setup()` 保留。
- 不再需要 `pg_advisory_lock(729630041)`，因为迁移已由 Flyway 的 advisory lock 串行化；应用只读校验。
- 检查点表的写入仍由 `PostgresSaver` 在请求中完成，属于 DML，不需要变更。

### 4.5 `app/deployment.py`

这是改动最集中的文件，分三处。

#### 4.5.1 `check_database()`：改为只读

**现状（53–70）**：表存在则校验凭证行；表不存在则允许空库，并要求数据库 `CREATE` 权限。

**改为**：

```python
def check_database(conn):
    """只读校验：归属、权限、知识是否已初始化。

    返回 knowledge_initialized，仅用于 Milvus 前缀冲突判断：
    - False：库刚迁移、尚未入库，Milvus 前缀不应被占用；
    - True：已有知识数据，允许复用同前缀集合。
    """
    marker = conn.execute("SELECT to_regclass('assistant.external_deployment')").fetchone()[0]
    if not marker:
        raise DeploymentError(
            '数据库尚未由 Flyway 初始化：缺少 assistant.external_deployment，请先执行 db-migrate'
        )
    row = conn.execute('SELECT metadata FROM assistant.external_deployment WHERE id=1').fetchone()
    if not row or row[0] != namespace():
        raise DeploymentError('数据库属于其他部署或 Milvus 配置已变更，拒绝继续；请使用独立空库')

    allowed = conn.execute(
        "SELECT has_schema_privilege('assistant','USAGE') "
        "AND has_schema_privilege('knowledge','USAGE') "
        "AND has_table_privilege('assistant.messages','SELECT') "
        "AND has_table_privilege('assistant.messages','INSERT') "
        "AND has_table_privilege('knowledge.rag_documents','SELECT')"
    ).fetchone()[0]
    if not allowed:
        raise DeploymentError(
            '业务账号缺少 assistant/knowledge 的 USAGE 或业务表 DML 权限，请先执行迁移与授权'
        )

    return bool(conn.execute(
        'SELECT EXISTS(SELECT 1 FROM knowledge.rag_documents)'
    ).fetchone()[0])
```

**关键点**：不要直接 `return True`。原来的返回值承担了“是否首次部署”的语义，用于 `check_milvus()` 判断 Milvus 前缀是否可复用。迁移会提前写入 `external_deployment`，如果这里恒为 `True`，首次部署时 Milvus 前缀冲突检查会被跳过。改为按 `knowledge.rag_documents` 是否有数据判断，保留原有行为。

#### 4.5.2 删除 `claim()`

**现状（73–83）**：`CREATE SCHEMA`、`CREATE TABLE assistant.external_deployment`、`INSERT` 凭证行。

**改为**：整个函数删除。凭证行由 `V1.0.0` 第五节经 Flyway 占位符写入；归属校验由 `check_database()` 完成。

#### 4.5.3 `main()`：`initialize` 改为校验

**现状（167–180）**：

```python
        with database_connection(args.create_database) as conn:
            owned = check_database(conn)
            output('PG连接及隔离检查通过', existing_deployment=owned)
            if args.action == 'check' and owned:
                state = conn.execute('SELECT fingerprint FROM knowledge.rag_state WHERE id=1').fetchone()
                ...
            ...
            if args.action == 'initialize':
                stage = '登记部署归属'; claim(conn)
                stage = '数据结构初始化'; initialize_runtime(config)
```

**改为**：

```python
        with database_connection(args.create_database) as conn:
            knowledge_initialized = check_database(conn)
            output('PG连接及隔离检查通过', knowledge_initialized=knowledge_initialized)
            if args.action == 'check' and knowledge_initialized:
                state = conn.execute('SELECT fingerprint FROM knowledge.rag_state WHERE id=1').fetchone()
                ...
            ...
            if args.action == 'initialize':
                stage = '校验数据库版本'
                from .schema import require_postgres_schema
                require_postgres_schema(conn)
```

并删除 `initialize_runtime()`（143–151）。

**注意**：

- `initialize` 保留命令名，避免破坏 `scripts/dev.sh`、文档与值班习惯；但输出文案要改成“校验通过”，不能再写“初始化完成”。
- `check_milvus(rag, owned, dimensions)` 的第二个参数改为传 `knowledge_initialized`；函数内部逻辑不变。
- `--create-database` 保留：它只创建空数据库，不建 schema/表，属于基础设施准备。
- `check` 分支的 `rag_state.fingerprint` 校验保留：它判断“知识配置是否变化”，与 schema 版本是两件事。

### 4.6 `app/cloud.py`

**现状（35–38）**：

```python
    with psycopg.connect(**target, connect_timeout=10) as conn:
        allowed = conn.execute("SELECT has_database_privilege(current_database(),'CREATE')").fetchone()[0]
        if not allowed:
            raise ValueError('业务账号需要目标库CREATE权限以初始化两个schema')
```

**改为**：

```python
    with psycopg.connect(**target, connect_timeout=10) as conn:
        allowed = conn.execute(
            "SELECT has_database_privilege(current_database(),'CONNECT')"
        ).fetchone()[0]
        if not allowed:
            raise ValueError('业务账号缺少目标库 CONNECT 权限')
```

**注意**：schema/表权限由迁移后的 `deployment check` 校验；`cloud prepare` 只负责“库和角色存在、能连上”，不再承担初始化职责。

### 4.7 `app/migration.py`

**现状（38–40）**：

```python
    from .core import Service
    from .rag import DocumentStore,RAGSettings
    # Initialize destination schemas without calling any external model.
    service=Service(config);service.close();rag=RAGSettings()
    DocumentStore(rag.index_path,config.database_url)
```

**改为**：

```python
    from .storage import PostgresDB
    from .schema import require_postgres_schema
    check=PostgresDB(config.database_url,'assistant',max_size=1)
    try:
        require_postgres_schema(check)
    finally:
        check.close()
```

**注意**：

- 保留后面原有的 `destination=PostgresDB(config.database_url,'assistant',max_size=2)`，用于真正的数据迁移；不要把它和 `check` 混用。
- `migrate-storage` 是运维命令，应使用迁移/运维角色执行（需要 `setval` 序列权限），不要用 app 角色。
- `export_sqlite` 走 SQLite 分支，`Service(database_url='')` 仍会创建 SQLite 表，保留不变。

### 4.8 `app/server.py`（不需要改）

`/ready` 当前只执行 `SELECT 1`，启动阶段已经由 `Service` / `DocumentStore` / `SupportWorkflow` 完成 schema 校验，因此**不需要为解耦改动**。

如果希望运维在 `/health` 直接看到版本，可选加一行：

```python
from .schema import SCHEMA_VERSION
...
def health():return {'status':'ok','schema_version':SCHEMA_VERSION}
```

这是可观测性增强，不是解耦必需项。

---

## 5. 启动时序（改造后）

```text
Service.__init__
  → SemanticKnowledge → DocumentStore
       → require_postgres_schema()       # 第一个校验点
  → Service.db → require_postgres_schema()
  → SupportWorkflow → require_checkpoint_schema()
  → 启动完成
```

失败行为：

| 场景 | 结果 |
|---|---|
| 数据库未迁移 | `SchemaNotReady`，进程非零退出；库中不会新建任何表 |
| 迁移记录有失败行 | `SchemaNotReady`，提示 `flyway repair` |
| schema 版本低于应用要求 | `SchemaNotReady`，提示先升级数据库 |
| 检查点表版本低 | `SchemaNotReady`，提示先执行迁移 |
| 业务账号缺 `USAGE`/DML | 启动时报权限错误或 `SchemaNotReady`；由 `deployment check` 提前发现 |

---

## 6. SQLite 本地开发兼容性

改造后，两条路径分离：

| 模式 | 条件 | 表结构来源 |
|---|---|---|
| PostgreSQL | `DATABASE_URL` 非空 | `db-migrate` 镜像 / Flyway |
| SQLite | `DATABASE_URL` 为空 | app 内 `SQLITE_SCHEMA` / `executescript` |

因此：

- 本地 `python manage.py serve`（无 `DATABASE_URL`）行为不变；
- 现有 SQLite 单测不需要改；
- `export_sqlite` 仍能创建 SQLite 目标库；
- 只有 PG 集成测试需要先跑 migration。

---

## 7. 测试与验收（app 范围）

### 7.1 静态检查

```bash
# PG 路径不应再出现 DDL；命中项应只位于 SQLite 分支
grep -RnE "CREATE (UNIQUE )?(TABLE|SCHEMA|INDEX)|ALTER TABLE|DROP (TABLE|SCHEMA|INDEX)" app/
```

人工确认 `core.py`、`rag.py` 的命中都在 `else:`（SQLite）分支内。

### 7.2 单元测试（建议新增 `tests/test_schema.py`）

用假 db 对象覆盖 `require_postgres_schema()`：

| 用例 | 输入 | 期望 |
|---|---|---|
| 无 history 表 | `to_regclass` 返回 `None` | `SchemaNotReady`，含“尚未迁移” |
| 有失败迁移 | `success=false` 计数 > 0 | `SchemaNotReady`，含“flyway repair” |
| 版本过低 | 最新 `0.9.0`，要求 `1.0.0` | `SchemaNotReady`，含“低于应用要求” |
| 检查点过低 | `max(v)=8` | `SchemaNotReady`，含“检查点” |
| 全部满足 | `1.0.0` + `max(v)=9` | 不抛异常 |

### 7.3 集成测试

| # | 场景 | 步骤 | 通过标准 |
|---|---|---|---|
| 1 | 正常启动 | 迁移后的库 + app 角色（仅 `USAGE + DML`）启动 | 进程正常；`/ready` 200 |
| 2 | 未迁移启动 | 空库直接启动 | 非零退出；日志含 `SchemaNotReady`；`information_schema.tables` 中无业务表 |
| 3 | 版本过低 | 将 history 版本改为 `0.9.0` | 非零退出；提示版本低 |
| 4 | 检查点过低 | 将 `checkpoint_migrations` 最大版本改为 8 | 非零退出；提示检查点版本低 |
| 5 | 归属不一致 | 修改 `external_deployment.metadata.id` | `deployment check` 报“属于其他部署” |
| 6 | SQLite 回归 | 不设 `DATABASE_URL`，跑现有单测与本地启动 | 与改造前一致 |
| 7 | 迁移命令 | 迁移后的库执行 `migrate-storage`（有 SQLite 源） | 成功；`setval` 正常 |
| 8 | 导出回退 | 执行 `export-sqlite` | 生成 SQLite 文件；完整性检查通过 |

### 7.4 业务冒烟

1. 创建会话；
2. 提问一次，确认回答、引用、配图正常；
3. 重启服务；
4. 查历史，确认消息完整、`messages.seq` 连续；
5. 删除会话，确认 `workflow_runs` 级联清理。

---

## 8. 提交建议

- **一个 PR 只做解耦**：A1–A10 一起提交；不要把位置式 `INSERT` 改造、索引优化混进来。
- **提交顺序**：
  1. 新增 `app/schema.py` + 单测；
  2. 改 `storage.py`、`core.py`、`rag.py`、`workflow.py`；
  3. 改 `deployment.py`、`cloud.py`、`migration.py`；
  4. 更新本文档与运维说明。
- **PR 描述必须写明**：这是 breaking change——PG 模式不再自动建表，部署前必须先跑 `db-migrate`。
- **回滚**：应用可回退到上一版本，数据库 schema 保持新版本。注意旧版本仍带 DDL，在已迁移库上会执行 `CREATE ... IF NOT EXISTS`（需要 schema 的 `CREATE` 权限）。因此**首次上线不要同时切到 DML-only 角色**：先在原角色（或与迁移同角色）上验证新版本，确认无需回退后，再按运维计划拆角色、收回 `CREATE`。若已经切到 DML-only，回退前必须临时授予 `CREATE`，否则旧版本会在 `storage.py:64` 启动失败。

---

## 9. 明确不要做的事

1. 不要为了“兼容”保留 `saver.setup()` 或任何 `CREATE ... IF NOT EXISTS`。
2. 目标态不要给 app 角色授予数据库/schema 的 `CREATE`；回退窗口按 §8 临时保留或临时授予。
3. 不要把 `require_postgres_schema()` 包成 `try/except` 后只打 warning 继续启动。
4. 不要在本次改动中调整业务 SQL、位置式 `INSERT`、索引或检索逻辑。
5. 不要修改 `database/postgres/` 下的迁移文件；schema 变更走新的 `V__`。
6. 不要删除 SQLite 分支的 DDL；本地开发和 `export_sqlite` 仍依赖它。

---

## 10. 不在本文范围

以下内容属于运维/部署改造，见 [`archive/PostgreSQL迁移解耦核对说明.md`](archive/PostgreSQL迁移解耦核对说明.md) §6.9：

- `deploy/docker/Dockerfile` 的 `requirements.lock`、`COPY database`、`manage.py` 路径；
- `deploy/k8s/base/deployment.yaml` 的 `db-migrate` Init 与 `manage.py ingest` 路径；
- `scripts/dev.sh` 的初始化顺序；
- 迁移 Job/CronJob、GRANT、索引等数据库侧变更。
