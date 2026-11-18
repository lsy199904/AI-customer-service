# 服务手动初始化说明（含全部 SQL 与依赖关系）

本文不依赖仓库内任何 `scripts/` 脚本（`production.sh`、`dev.sh`、`cloud.sh`、`kubernetes.py` 均不使用）。所有 PostgreSQL 结构由文中给出的 SQL 以 `psql` 命令行手动执行；其余步骤给出逐条手动命令。整体部署背景见 [部署说明](部署说明.md)。

- 适用分支：`deploy-external-api-20261116`
- 数据库版本：PostgreSQL 16 系列
- SQL 提取来源：`app/core.py`（会话表）、`app/rag.py`（知识表）、`app/deployment.py`（归属标记）、`app/workflow.py` + `langgraph-checkpoint-postgres==3.2.0`（检查点表，`MIGRATIONS` 已展平为最终形态）。应用通过 SQLite 兼容层（`app/storage.py`）执行同类语句，手动执行的 SQL 与程序自动建表的最终结构一致。

## 一、服务初始化共分九个部分

| 序号 | 部分 | 内容 | 执行者 |
|---|---|---|---|
| 1 | 外部资源开通 | PG 实例、Milvus 实例、三个模型 API、网络白名单 | 平台 |
| 2 | PG 账号与业务库 | 专用登录角色 + 独立业务库 | DBA/管理员（psql） |
| 3 | 应用配置 `.env` | 密钥、`DATABASE_URL`、Milvus、三个模型 API 参数 | 部署人（手动编辑） |
| 4 | PG 表结构初始化 | 2 个 schema、全部业务表/知识表/检查点表/索引/归属标记 | 部署人（psql） |
| 5 | Milvus 业务库与集合 | 业务数据库 + 向量集合 | 平台控制台或 pymilvus 手动 |
| 6 | 运行环境与依赖 | Python 虚拟环境、安装锁定依赖 | 部署人（pip） |
| 7 | 知识入库 | 解析/切片/Embedding，写入 PG 与 Milvus | 部署人（应用命令） |
| 8 | 初始化验证 | psql 核对 + 应用 doctor | 部署人 |
| 9 | 启动服务 | 前台命令或 systemd | 部署人 |

## 二、依赖关系与执行顺序

```text
 P1 外部资源开通
 ├──→ P2 PG账号与业务库 ──→ P4 PG表结构 ──┐
 ├──→ P5 Milvus业务库/集合 ──────────────┤
 └──→ 模型API连通（无本地操作）           ├──→ P7 知识入库 ──→ P8 验证 ──→ P9 启动
            P3 .env配置 ──→ P6 依赖安装 ──┘
```

顺序规则：

1. P2 必须在 P4 之前（表建在业务库里）。
2. P4 中“归属标记”一行依赖 P3 的 `DEPLOYMENT_ID`/Milvus 三个参数取值，因此 P3 先于 P4 执行（或先建表、最后补标记行）。
3. P6 依赖 P3（安装时不需要，但运行任何应用命令都需要读取 `.env`）。
4. P7 依赖：P3 + P4（知识表）+ P5（Milvus 可达）+ 模型 API 连通；会真实调用 Embedding。
5. P5 的集合可以由 P7 自动创建；若手动创建，维度必须与 Embedding 输出一致。
6. P8、P9 依赖前面全部部分。
7. 可并行：P2 与 P5 与 P6 互不依赖；P3 与 P2 也可并行。

## 三、第一部分：外部资源开通（人工确认）

| 资源 | 要求 | 需要拿到的信息 |
|---|---|---|
| PostgreSQL | 16 系列，App 所在网络可达 | 地址、端口、TLS 要求、管理员连接（或由平台直接建库） |
| Milvus | 2.6 系列 | Endpoint、应用 Token、业务数据库名、支持的索引类型（HNSW/AUTOINDEX） |
| 模型 API | LLM / Embedding / Rerank | 各自 URL、Key、模型 ID；Embedding 兼容 OpenAI embeddings 协议 |

## 四、第二部分：PG 账号与业务库（psql 手动建）

以管理员身份连接实例维护库执行（`ON_ERROR_STOP` 保证出错即停）：

```bash
psql "postgresql://管理员账号:管理员密码@PG地址:5432/postgres" -v ON_ERROR_STOP=1 <<'SQL'
-- 业务账号：普通 LOGIN 角色，不给 SUPERUSER/CREATEDB/CREATEROLE
CREATE ROLE titu_app LOGIN PASSWORD '替换为业务密码';

-- 独立业务库，owner 即业务账号；不能用 postgres/template0/template1
CREATE DATABASE titu_assistant OWNER titu_app;
SQL
```

用业务账号自检（应返回 `t`，应用建 schema 需要该权限）：

```bash
psql "postgresql://titu_app:业务密码@PG地址:5432/titu_assistant" -c \
  "SELECT has_database_privilege(current_database(),'CREATE');"
```

说明：

- 密码含特殊字符时，psql 连接串中需 URL 编码；`CREATE ROLE` 内的密码用单引号原样书写即可。
- 库名、账号名可自定，后续所有步骤与 `.env` 保持一致即可。
- 重复执行会因对象已存在报错，属预期；换名重跑即可。

## 五、第三部分：应用配置 .env（手动生成）

在项目根目录手工创建 `.env`（权限 600），可从 `.env.example` 复制为底稿再填写。随机值用标准库命令行生成，逐条粘贴：

```bash
python3 -c "import secrets; print('AUTH_SECRET='+secrets.token_urlsafe(48))"
python3 -c "import secrets; print('OPERATIONS_TOKEN='+secrets.token_urlsafe(24))"
python3 -c "import secrets; print('DEPLOYMENT_ID='+secrets.token_urlsafe(24))"
python3 -c "import secrets; print('MILVUS_COLLECTION=smarttitu_ext_'+secrets.token_hex(4))"
python3 -c "import secrets; print('ANONYMOUS_COOKIE_NAME=smarttitu_ext_'+secrets.token_hex(6))"
chmod 600 .env
```

必填项与取值（其余参数见 `.env.example` 注释）：

| 参数 | 取值 | 来源 |
|---|---|---|
| `DATABASE_URL` | `postgresql://titu_app:URL编码密码@PG地址:5432/titu_assistant?sslmode=require` | P2 建的库与账号；TLS 按平台要求 |
| `DEPLOYMENT_ID` | 上一步生成的值 | 用于 P4 归属标记，**生成后不要变更** |
| `MILVUS_URI` | `http(s)://milvus地址:端口`，结尾不带 `/` | 平台 |
| `MILVUS_TOKEN` | 应用 Token | 平台 |
| `MILVUS_DATABASE` | 业务数据库名；未分配时填 `default` | 平台 |
| `MILVUS_COLLECTION` | 生成的独立前缀（正则 `[A-Za-z][A-Za-z0-9_]{0,39}`） | 投入使用后不变 |
| `MILVUS_INDEX_TYPE` | 自建 `HNSW`；托管仅支持自动索引时 `AUTOINDEX` | 平台确认 |
| `MODEL_BASE_URL`/`MODEL_API_KEY`/`MODEL_NAME` | LLM `/v1` 基础地址、Key、模型 ID | 平台 |
| `EMBEDDING_URL`/`EMBEDDING_API_KEY`/`EMBEDDING_MODEL` | 完整 embeddings 地址、Key、模型 ID | 平台 |
| `RERANK_URL`/`RERANK_API_KEY`/`RERANK_MODEL` | 完整 rerank 地址、Key、模型 ID | 平台 |
| `AUTH_SECRET`/`OPERATIONS_TOKEN`/`ANONYMOUS_COOKIE_NAME` | 上一步生成的值 | — |

## 六、第四部分：PG 表结构初始化（全部 SQL）

### 6.0 执行方式

以下 SQL 按文件保存（如 `sql/01_schemas.sql` … `sql/05_marker.sql`），统一用业务账号执行：

```bash
export PGURL="postgresql://titu_app:URL编码密码@PG地址:5432/titu_assistant?sslmode=require"
psql "$PGURL" -v ON_ERROR_STOP=1 -f sql/01_schemas.sql
psql "$PGURL" -v ON_ERROR_STOP=1 -f sql/02_assistant.sql
psql "$PGURL" -v ON_ERROR_STOP=1 -f sql/03_knowledge.sql
psql "$PGURL" -v ON_ERROR_STOP=1 -f sql/04_checkpoints.sql
psql "$PGURL" -v ON_ERROR_STOP=1 -f sql/05_marker.sql
```

全部语句幂等（`IF NOT EXISTS` / `ON CONFLICT DO NOTHING`），可安全重跑。说明两处与库内代码的差异：库内对检查点索引用 `CREATE INDEX CONCURRENTLY`（不能在事务内执行），此处新库无数据，用普通 `CREATE INDEX` 等价；`PRAGMA` 类 SQLite 语句不适用于 PG，已剔除。

### 6.1 01_schemas.sql — 创建 schema

```sql
CREATE SCHEMA IF NOT EXISTS assistant;
CREATE SCHEMA IF NOT EXISTS knowledge;
```

### 6.2 02_assistant.sql — 会话、消息、限流与工作流表

```sql
-- 会话（app/core.py Service）
CREATE TABLE IF NOT EXISTS assistant.sessions(
    id       TEXT PRIMARY KEY,
    tenant   TEXT NOT NULL,
    "user"   TEXT NOT NULL,          -- user 为保留字，必须带引号
    context  TEXT NOT NULL,
    created  DOUBLE PRECISION NOT NULL,
    updated  DOUBLE PRECISION NOT NULL
);
CREATE INDEX IF NOT EXISTS assistant.session_owner    ON assistant.sessions(tenant, "user", updated);
CREATE INDEX IF NOT EXISTS assistant.session_retention ON assistant.sessions(updated);

-- 聊天消息
CREATE TABLE IF NOT EXISTS assistant.messages(
    id         TEXT PRIMARY KEY,
    session    TEXT NOT NULL REFERENCES assistant.sessions(id) ON DELETE CASCADE,
    request_id TEXT NOT NULL,
    role       TEXT NOT NULL,
    content    TEXT NOT NULL,
    payload    TEXT NOT NULL,
    created    DOUBLE PRECISION NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS assistant.message_request  ON assistant.messages(session, request_id, role);
CREATE INDEX IF NOT EXISTS        assistant.message_retention ON assistant.messages(created);
-- 仅 PostgreSQL：稳定排序用的自增列（程序启动时同样执行该语句，幂等）
ALTER TABLE assistant.messages ADD COLUMN IF NOT EXISTS seq BIGSERIAL UNIQUE;

-- 每租户 60 秒滑动窗口限流（window 为保留字，必须带引号）
CREATE TABLE IF NOT EXISTS assistant.tenant_message_limits(
    owner   TEXT PRIMARY KEY,
    events  TEXT NOT NULL,
    updated DOUBLE PRECISION NOT NULL
);

-- 全库共享的每日 RAG 额度（北京时间零点切换，程序按需写入行）
CREATE TABLE IF NOT EXISTS assistant.global_rag_daily_limits(
    day     TEXT PRIMARY KEY,
    used    INTEGER NOT NULL CHECK(used >= 0),
    updated DOUBLE PRECISION NOT NULL
);

-- 旧版固定窗口计数表（程序创建并保留，当前限流主要由 tenant_message_limits 承担）
CREATE TABLE IF NOT EXISTS assistant.rate_limits(
    owner  TEXT PRIMARY KEY,
    "window" INTEGER,
    count  INTEGER
);

-- 问答工作流运行记录
CREATE TABLE IF NOT EXISTS assistant.workflow_runs(
    id         TEXT PRIMARY KEY,
    session    TEXT NOT NULL REFERENCES assistant.sessions(id) ON DELETE CASCADE,
    request_id TEXT NOT NULL,
    status     TEXT NOT NULL,
    created    DOUBLE PRECISION NOT NULL,
    updated    DOUBLE PRECISION NOT NULL
);
```

### 6.3 03_knowledge.sql — 知识库表（app/rag.py SCHEMA）

```sql
-- 单行状态：Embedding/切片配置指纹与知识代数；必须写入初始行
CREATE TABLE IF NOT EXISTS knowledge.rag_state(
    id          INTEGER PRIMARY KEY CHECK(id = 1),
    fingerprint TEXT,
    generation  INTEGER NOT NULL
);
INSERT INTO knowledge.rag_state (id, fingerprint, generation)
VALUES (1, '', 0)
ON CONFLICT (id) DO NOTHING;

-- 文档登记与当前激活修订
CREATE TABLE IF NOT EXISTS knowledge.rag_documents(
    id               TEXT PRIMARY KEY,
    path             TEXT UNIQUE,
    title            TEXT,
    current_revision TEXT,
    active           INTEGER,
    updated          DOUBLE PRECISION
);

-- 全文修订历史（原始文件字节）
CREATE TABLE IF NOT EXISTS knowledge.rag_revisions(
    document_id TEXT,
    revision    TEXT,
    filename    TEXT,
    raw         BYTEA,
    metadata    TEXT,
    created     DOUBLE PRECISION,
    PRIMARY KEY (document_id, revision)
);

-- 切片正文与向量 JSON（向量本体在 Milvus，PG 为准）
CREATE TABLE IF NOT EXISTS knowledge.rag_chunks(
    id          TEXT PRIMARY KEY,
    document_id TEXT,
    revision    TEXT,
    ordinal     INTEGER,
    record      TEXT,
    vector      TEXT
);
CREATE INDEX IF NOT EXISTS knowledge.rag_chunk_doc ON knowledge.rag_chunks(document_id, revision);

-- 入库/启停事件审计（PG 下为 BIGSERIAL）
CREATE TABLE IF NOT EXISTS knowledge.rag_events(
    id          BIGSERIAL PRIMARY KEY,
    document_id TEXT,
    action      TEXT,
    revision    TEXT,
    created     DOUBLE PRECISION
);

-- Embedding 缓存：重复入库复用，不重复调用接口
CREATE TABLE IF NOT EXISTS knowledge.rag_embedding_cache(
    fingerprint TEXT,
    text_hash   TEXT,
    vector      TEXT,
    PRIMARY KEY (fingerprint, text_hash)
);
```

### 6.4 04_checkpoints.sql — LangGraph 检查点表

来源：`langgraph-checkpoint-postgres==3.2.0` 的 `MIGRATIONS` 列表（10 项）展平后的最终结构，全部建在 `assistant` schema（程序通过 `search_path=assistant,public` 访问）。版本登记表 `checkpoint_migrations` 必须写入 0–9，使程序下次 `setup()` 直接跳过迁移。

```sql
CREATE TABLE IF NOT EXISTS assistant.checkpoint_migrations(
    v INTEGER PRIMARY KEY
);

CREATE TABLE IF NOT EXISTS assistant.checkpoints(
    thread_id            TEXT NOT NULL,
    checkpoint_ns        TEXT NOT NULL DEFAULT '',
    checkpoint_id        TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type                 TEXT,
    checkpoint           JSONB NOT NULL,
    metadata             JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

CREATE TABLE IF NOT EXISTS assistant.checkpoint_blobs(
    thread_id     TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel       TEXT NOT NULL,
    version       TEXT NOT NULL,
    type          TEXT NOT NULL,
    blob          BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);

CREATE TABLE IF NOT EXISTS assistant.checkpoint_writes(
    thread_id     TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id       TEXT NOT NULL,
    idx           INTEGER NOT NULL,
    channel       TEXT NOT NULL,
    type          TEXT,
    blob          BYTEA NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

CREATE INDEX IF NOT EXISTS assistant.checkpoints_thread_id_idx      ON assistant.checkpoints(thread_id);
CREATE INDEX IF NOT EXISTS assistant.checkpoint_blobs_thread_id_idx ON assistant.checkpoint_blobs(thread_id);
CREATE INDEX IF NOT EXISTS assistant.checkpoint_writes_thread_id_idx ON assistant.checkpoint_writes(thread_id);

ALTER TABLE assistant.checkpoint_writes
    ADD COLUMN IF NOT EXISTS task_path TEXT NOT NULL DEFAULT '';

-- 迁移版本登记 0..9：程序 setup() 读取最大版本号，等于 9 时跳过全部迁移
INSERT INTO assistant.checkpoint_migrations (v)
SELECT g FROM generate_series(0, 9) AS g
ON CONFLICT (v) DO NOTHING;
```

### 6.5 05_marker.sql — 部署归属标记

应用启动时会校验该行与 `.env` **完全一致**，不一致直接拒绝启动，因此必须在 P3 完成后、且按实际取值填写。元数据共 4 个字段：

| 字段 | 取值 | 注意 |
|---|---|---|
| `id` | `.env` 的 `DEPLOYMENT_ID` | 原样粘贴 |
| `milvus_uri` | `MILVUS_URI` 去掉结尾 `/` | 程序存储前会 `rstrip('/')` |
| `milvus_database` | `MILVUS_DATABASE`，未配置时为 `default` | 与 .env 一致 |
| `milvus_prefix` | `MILVUS_COLLECTION` | 与 .env 一致 |

```bash
python3 - <<'PY'
import json
env = {}
for line in open('.env'):
    line = line.strip()
    if line and not line.startswith('#') and '=' in line:
        k, v = line.split('=', 1); env[k] = v.strip().strip("'\"")
meta = {
    'id': env['DEPLOYMENT_ID'],
    'milvus_uri': env['MILVUS_URI'].rstrip('/'),
    'milvus_database': env.get('MILVUS_DATABASE') or 'default',
    'milvus_prefix': env['MILVUS_COLLECTION'],
}
open('sql/05_marker.sql', 'w').write(
    'CREATE TABLE IF NOT EXISTS assistant.external_deployment(\n'
    '    id       INTEGER PRIMARY KEY CHECK(id = 1),\n'
    '    metadata JSONB NOT NULL\n'
    ');\n'
    'INSERT INTO assistant.external_deployment (id, metadata)\n'
    "VALUES (1, '%s'::jsonb)\n" % json.dumps(meta, ensure_ascii=False) +
    'ON CONFLICT (id) DO UPDATE SET metadata = EXCLUDED.metadata;\n')
print(open('sql/05_marker.sql').read())
PY
psql "$PGURL" -v ON_ERROR_STOP=1 -f sql/05_marker.sql
```

生成的建表语句与程序一致：

```sql
CREATE TABLE IF NOT EXISTS assistant.external_deployment(
    id       INTEGER PRIMARY KEY CHECK(id = 1),
    metadata JSONB NOT NULL
);
```

## 七、第五部分：Milvus 业务库与集合

### 7.1 业务数据库（无自动建库能力时必须手动）

优先由平台控制台分配；供应商支持建库 API 时也可手动：

```bash
pip3 install "pymilvus>=2.6,<3"   # 与 requirements.lock 版本一致
python3 - <<'PY'
from pymilvus import MilvusClient
admin = MilvusClient(uri='MILVUS地址', token='管理员Token', timeout=30)
print(admin.list_databases())
if '业务数据库名' not in admin.list_databases():
    admin.create_database(db_name='业务数据库名')
admin.close()
PY
```

### 7.2 向量集合

**推荐不手动建集合**：第七部分知识入库会自动创建，维度取自 Embedding 实际输出，不会错。确需手动创建时（例如平台要求预审）：

```bash
# 1) 计算集合名：前缀 + 配置指纹前16位；指纹与 .env 的 Embedding 参数绑定
python3 - <<'PY'
import hashlib, json
fingerprint = hashlib.sha256(json.dumps([
    'documents-v2', 'retrieval-text-v2',        # 固定流水线版本，不要改
    'openai', '<EMBEDDING_URL>', '<EMBEDDING_MODEL>', '<EMBEDDING_REVISION>',
    1000, 100]).encode()).hexdigest()           # 切片参数为代码固定值
print('<MILVUS_COLLECTION>' + '_' + fingerprint[:16])
PY
# 2) 先调用一次 Embedding 接口确认输出维度 dim（如 1024），再执行建集合
python3 - <<'PY'
from pymilvus import MilvusClient, DataType
c = MilvusClient(uri='MILVUS地址', token='应用Token', db_name='业务数据库名')
schema = c.create_schema(auto_id=False, enable_dynamic_field=False)
schema.add_field('id',          DataType.VARCHAR, is_primary=True, max_length=80)
schema.add_field('document_id', DataType.VARCHAR, max_length=80)
schema.add_field('revision',    DataType.VARCHAR, max_length=64)
schema.add_field('vector',      DataType.FLOAT_VECTOR, dim=1024)   # 必须等于Embedding维度
index = c.prepare_index_params()
index.add_index(field_name='vector', index_type='HNSW', metric_type='COSINE',
                params={'M': 16, 'efConstruction': 128})            # AUTOINDEX 时去掉 params
c.create_collection(collection_name='上一步输出的集合名', schema=schema,
                    index_params=index, consistency_level='Strong')
c.close()
PY
```

## 八、第六部分：运行环境与依赖

```bash
python3 --version          # 需 3.12（requirements.lock 按此解析）
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.lock
```

## 九、第七部分：知识入库

切片、Embedding 调用与 PG/Milvus 双写逻辑在应用代码内，无法用纯 SQL 完成；此步骤用应用自带命令（`manage.py`，非 `scripts/` 脚本），它直接使用 `.env` 与上一步手动建好的表：

```bash
. .venv/bin/activate
python3 manage.py ingest               # 增量入库；首次调用 Embedding，产生少量用量
# python3 manage.py ingest --rebuild   # 仅当 Embedding 地址/模型/版本或切片配置变化时使用
```

执行完成后 PG 的 `rag_*` 表写入文档、切片与缓存；Milvus 集合（若未手动建）自动创建并写入向量。

## 十、第八部分：初始化验证

数据库侧（psql）：

```bash
psql "$PGURL" -c "\dn"                                  # assistant、knowledge 两个 schema
psql "$PGURL" -c "\dt assistant.*"                      # 业务表 + checkpoints 三表 + 归属标记
psql "$PGURL" -c "\dt knowledge.*"                      # rag_* 六表
psql "$PGURL" -c "SELECT id, metadata FROM assistant.external_deployment;"   # 与.env核对
psql "$PGURL" -c "SELECT max(v) FROM assistant.checkpoint_migrations;"       # 应为9
psql "$PGURL" -c "SELECT id, fingerprint, generation FROM knowledge.rag_state;"  # 单行存在
```

应用侧：

```bash
python3 manage.py doctor --models      # 检查 PG 连接、知识数、Milvus 集合与三个模型接口
curl -fsS "http://127.0.0.1:8201/smart-bot/ready"    # 启动后执行
```

## 十一、第九部分：启动服务

前台手动启动：

```bash
python3 manage.py serve --host 0.0.0.0 --port 8201
```

生产建议用 systemd 托管（示例，按平台规范调整）：

```ini
# /etc/systemd/system/titu-assistant.service
[Unit]
Description=SmartTITU assistant
After=network-online.target

[Service]
User=deploy
WorkingDirectory=/opt/titu-assistant
Environment=HOST=0.0.0.0
Environment=PORT=8201
ExecStart=/opt/titu-assistant/.venv/bin/python manage.py serve
Restart=always
RestartSec=3

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl daemon-reload && sudo systemctl enable --now titu-assistant
```

验收：浏览器访问 `http://服务器地址:8201/smart-bot/widget/anonymous-demo`，验证提问、引用与刷新历史。

## 十二、与脚本流程的关系

- 本文档建出的库结构与程序自动建表**完全一致**；之后若改用 `scripts/production.sh deploy`，其归属检查会识别归属标记、视为本部署的库直接复用，不会重复建表。
- 反之，脚本建过的库也可用本文 SQL 核对结构，全部语句幂等。
- 唯一强约束：`assistant.external_deployment` 的 4 个字段必须与 `.env` 当前值一致；更换 `DEPLOYMENT_ID` 或 Milvus 参数属于新部署，需换独立空库。

## 十三、常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `has_database_privilege` 返回 `f` | 业务账号缺目标库 CREATE 权限 | 管理员执行 `GRANT CREATE ON DATABASE 业务库 TO 业务账号;` |
| 应用启动报“数据库属于其他部署或Milvus配置已变更” | 归属标记与 `.env` 不一致 | 核对 4 个字段（尤其 `milvus_uri` 尾部斜杠），重跑 05_marker.sql |
| `syntax error at or near "user"/"window"` | 保留字未加引号 | 使用本文带引号的原句 |
| `checkpoint_migrations` 版本不为 9 后程序仍执行迁移 | 版本行被手工删改 | 重跑 04_checkpoints.sql（幂等补齐 0–9） |
| 连接报认证/超时 | 密码未 URL 编码或网络未放通 | 按 P2/P3 说明编码；核对白名单 |
| Milvus 建集合维度不符 | 手动建的 dim 与 Embedding 输出不一致 | 删除手动集合，改由 `ingest` 自动创建 |
