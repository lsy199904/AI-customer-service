# PostgreSQL SQL 覆盖核对与迁移解耦说明

> **状态**：核对完成，方案待评审；本文只描述改动，未修改 `../../app` 任何代码。
> **核对日期**：2026-11-19
> **核对对象**：`app/`（当前工作树）、`database/postgres/`、`deploy/`、`scripts/`
> **目标**：PostgreSQL 的初始化、版本升级与全部结构变更，由独立 migration 镜像/任务负责，并成为 app 部署升级的前置条件；app 只保留业务 DML，不再持有任何 PostgreSQL DDL。
> **关联文档**：[`工程化改造方案-运维域.md`](../工程化改造方案-运维域.md)、[`部署说明.md`](../部署说明.md)、[`../../database/postgres/README.md`](../../database/postgres/README.md)
> **路径说明**：本文为 2026-11-19 归档核对稿，历史路径保留原样；当前生效的 K8s 清单与脚本见 [`../../deploy/k8s/dev`](../../deploy/k8s/dev/README.md)。

---

## 0. 结论摘要

1. **新建库场景，SQL 资产是完备的**：17 张表全部覆盖；53 条去重后的可参数化 DML/查询（58 个调用点）逐条 `PREPARE` 通过，0 失败；Flyway 建库与应用自建库的结构指纹完全一致（`58965f7ba67e578c65c68901818154de`）。
2. **但不能直接解耦**：app 仍有 **5 处运行期 DDL**（`storage.py`、`core.py`、`rag.py`、`workflow.py`、`deployment.py`），其中 `PostgresSaver.setup()` 即使版本已是最新，仍会执行 `CREATE TABLE IF NOT EXISTS checkpoint_migrations`。
3. **最小权限下 app 起不来**：用只有 `USAGE + DML` 权限的角色启动，第一处失败是 `app/storage.py:64` 的 `CREATE SCHEMA IF NOT EXISTS`，报 `permission denied for database`。这说明“migration 独立”与“app 保留 DDL”不能并存。
4. **SQL 资产有 4 项缺口**：存量库收编前置检查、权限授予 SQL、`messages(session, seq)` 索引、`workflow_runs(session)` 索引。前两项影响解耦能否落地，后两项是性能差异，不阻断功能。
5. **有 9 处重复（D1–D9）**：5 处是 app 运行期 DDL，1 处是 `../../scripts/postgres` 遗留初始化脚本，1 处是归档副本，2 处是文档（归档 README、手动初始化说明）与 Flyway 入口冲突；`rag_state`、`external_deployment` 的种子数据各被写了两遍。
6. **目标形态**：migration 镜像是**唯一 schema DDL 执行者**，`migrations/` 是**唯一 schema 变更来源**；app 启动只校验版本，缺表/缺列/版本低一律 fail fast；K8s 上 migration 作为 Job/Init 前置闸门，失败则 app 不滚动。

---

## 1. 核对方法与证据

本次核对不只做文本比对，包含 5 类实证，全部在临时环境完成，未写入项目文件。

| # | 手段 | 对象 | 结果 |
|---|---|---|---|
| 1 | AST 抽取 `execute/executemany/executescript` 字面量 | `app/*.py` | 86 个调用点、75 条去重语句 |
| 2 | 临时 PostgreSQL 17.12 + `V1.0.0` 基线，逐条 `PREPARE` | 58 个调用点 / 53 条去重语句 | **53 通过 / 0 失败** |
| 3 | 应用代码在空库自建结构，比对 `schema_fingerprint.sql` | 17 张表、索引、约束 | 与 Flyway 库**完全一致** |
| 4 | 创建仅 `USAGE + DML` 的 `app_user`，启动 `Service` | 权限边界 | 在 `storage.py:64` 失败：`permission denied for database` |
| 5 | 反射 `langgraph-checkpoint-postgres==3.2.0` 的 `setup()` | 检查点初始化 | 每次启动都执行 `MIGRATIONS[0]`（`CREATE TABLE IF NOT EXISTS`） |

环境版本：PostgreSQL 17.12（目标生产 16，所用语法一致）、Flyway OSS 11.20.3、`langgraph-checkpoint-postgres==3.2.0`（`../../uv.lock` 与 `pyproject.toml` 均锁定该版本）。

> 说明：`PREPARE` 会做解析与语义分析，能发现表不存在、列不存在、列数不匹配、类型不兼容等问题；它不验证运行期数据，但足以证明“SQL 语句与 schema 匹配”。

---

## 2. 现状核对结论

### 2.1 表覆盖：17/17

| Schema | 表 | 创建来源 | app 使用位置 | 覆盖 |
|---|---|---|---|---|
| assistant | `sessions` | 基线 §二 | `core.py:455/471/481/531/538/551/569/659` | 是 |
| assistant | `messages` | 基线 §二 | `core.py:490/493/495/512/540/550/553/614/617/655/657` | 是 |
| assistant | `workflow_runs` | 基线 §二 | `core.py:531/542/548/564/660`、`workflow.py:360` | 是 |
| assistant | `global_rag_daily_limits` | 基线 §二 | `core.py:443/444` | 是 |
| assistant | `tenant_message_limits` | 基线 §二 | `core.py:426/428/432` | 是 |
| assistant | `rate_limits` | 基线 §二 | **无任何读写** | 是（冗余） |
| assistant | `external_deployment` | 基线 §二/§五 | `deployment.py:55/57/81/82` | 是 |
| assistant | `checkpoint_migrations` | 基线 §三 | LangGraph `setup()` | 是 |
| assistant | `checkpoints` | 基线 §三 | LangGraph checkpointer | 是 |
| assistant | `checkpoint_blobs` | 基线 §三 | LangGraph checkpointer | 是 |
| assistant | `checkpoint_writes` | 基线 §三 | LangGraph checkpointer | 是 |
| knowledge | `rag_state` | 基线 §四 | `rag.py:187/193/200/206/286/295`、`deployment.py:172` | 是 |
| knowledge | `rag_documents` | 基线 §四 | `rag.py:170/184/186/199/208/293` | 是 |
| knowledge | `rag_revisions` | 基线 §四 | `rag.py:173/180/191/290` | 是 |
| knowledge | `rag_chunks` | 基线 §四 | `rag.py:176/197/208/292` | 是 |
| knowledge | `rag_events` | 基线 §四 | `rag.py:188/201/294` | 是 |
| knowledge | `rag_embedding_cache` | 基线 §四 | `rag.py:258/267` | 是 |

### 2.2 语句覆盖：53/53（58 个调用点）

| 类别 | 代表性语句 | 结论 |
|---|---|---|
| 会话与消息 | `INSERT INTO sessions VALUES(?,?,?,?,?,?)`、`SELECT * FROM messages ... ORDER BY rowid`、`INSERT INTO messages(...)` | 通过；`rowid` 经 `storage.postgres_sql()` 正确翻译为 `seq` |
| 配额 | `INSERT INTO tenant_message_limits VALUES(?,?,?)`、`UPDATE global_rag_daily_limits ... RETURNING used` | 通过；位置式 INSERT 列数匹配 |
| 工作流登记 | `INSERT INTO workflow_runs VALUES(?,?,?,?)`、`DELETE FROM workflow_runs` | 通过 |
| 知识库 | `INSERT INTO rag_documents VALUES(?,?,?,?,?,?)`、`INSERT OR IGNORE INTO rag_chunks VALUES(...)`、`SELECT ... FOR UPDATE` | 通过；`INSERT OR IGNORE` 正确转为 `ON CONFLICT DO NOTHING` |
| 部署归属 | `SELECT metadata FROM assistant.external_deployment`、`INSERT INTO ... VALUES(1,%s)` | 通过 |
| SQLite→PG 迁移 | `setval(pg_get_serial_sequence(...))`、动态列 `INSERT/SELECT` | 列清单 9/9 与实际列一致；两个序列均存在 |

完整 53 条见[附录 A](#附录-a53-条语句逐条核对)。

### 2.3 结构等价

- 12 张由 app DDL 管理的表（6 张 assistant + 6 张 knowledge）：列名、列序、类型、可空性、默认值 **零差异**。
- 4 张检查点表：与 `langgraph-checkpoint-postgres==3.2.0` 的 `MIGRATIONS` 0–9 一致，`checkpoint_migrations` 最大版本为 9。
- 序列：`assistant.messages_seq_seq`、`knowledge.rag_events_id_seq` 均存在，`pg_get_serial_sequence` 可解析。
- 结构指纹：Flyway 建库与应用自建库均为 `58965f7ba67e578c65c68901818154de`。

### 2.4 结论

> **SQL 资产对“全新空库 + Flyway 一次迁移”是完备的；对“存量库收编、最小权限、历史分页性能”不完备。**

因此本次要解决的不是“补表/补列”，而是三件事：

1. 把 app 里 5 处运行期 DDL 收敛掉（否则 migration 永远不是唯一执行者）；
2. 补上迁移资产缺失的 4 项（收编检查、授权、2 个索引）；
3. 建立“app 启动校验 schema 版本”的契约，让“未迁移就启动”变成显式失败，而不是靠 DDL 兜底。

---

## 3. 缺失清单

| ID | 缺失项 | 严重度 | 影响 | 处置 |
|---|---|---|---|---|
| M1 | 存量库收编前置检查 | 高 | 存量库缺 `external_deployment`/`seq` 时，`baseline` 只登记版本、不建对象；缺凭证行时 `beforeMigrate` 拒绝，均无标准修复路径 | 新增 `checks/pre_baseline.sql` + 收编 runbook |
| M2 | 权限授予 SQL | 高 | 基线无任何 `GRANT`；app 只能以对象属主运行，无法拆最小权限角色 | 新增 `R__grants.sql`（占位符注入角色名） |
| M3 | `messages(session, seq)` 索引 | 中 | 历史分页按 `seq` 倒序扫描，跨会话过滤，消息量增长后延迟上升 | `V1.1.0` 增加复合索引 |
| M4 | `workflow_runs(session)` 索引 | 中 | 删除会话时 FK 级联、`prune_sessions` 的 `EXISTS` 均全表扫描，批量清理近似 O(n²) | `V1.1.0` 增加索引 |

### M1 存量库收编前置检查

**现状证据**

- `../../deploy/k8s/base/job-db-baseline.yaml` 只执行 `flyway baseline`，注释明确“只写 history 基线行，不执行任何 SQL”。
- `beforeMigrate__verify_identity.sql` 有三种分支：表不存在 → 放行；表存在但凭证行缺失 → 拒绝；凭证行不一致 → 拒绝。
- 放行分支的前提是“V1.0.0 随后会建表”，但存量库执行 `baseline` 时 **V1.0.0 不会执行**，这个前提不成立。
- `checks/` 下只有 `health.sql` 与 `schema_fingerprint.sql`，没有“收编前体检”。

**受影响场景**

```text
场景 A：存量库缺 external_deployment 表
  → flyway baseline（登记 1.0.0，不建表）
  → flyway migrate
  → beforeMigrate 放行（表不存在）
  → 但没有待执行迁移，表仍不存在
  → app 启动/部署检查失败，且无标准修复路径

场景 B：表存在但凭证行缺失，或凭证行与当前环境不一致
  → beforeMigrate 直接拒绝
  → 迁移无法推进；基线里没有修复/补登凭证的迁移
```

**处置**

新增只读检查 `database/postgres/checks/pre_baseline.sql`，输出违规行（缺失表、缺失列、缺失序列、凭证行不一致），由 `scripts/ci/check_db.py` 包装为“有行即失败”。**不建议**用 `V1.0.1` 自动 `CREATE TABLE IF NOT EXISTS` 修复：版本化迁移里使用 `IF NOT EXISTS` 会掩盖漂移，违反本项目已确定的规则。若确实需要自动化，应作为一次性、人工审阅的运维脚本，而不是常规迁移。

### M2 权限授予 SQL

**现状证据**

- `V1.0.0__baseline.sql` 只有 `CREATE SCHEMA/TABLE/INDEX` 与 `INSERT`，没有任何 `GRANT`。
- `app/deployment.py:67`、`app/cloud.py:36` 都要求业务账号具备数据库级 `CREATE`，说明当前设计默认“app 与迁移同角色”。
- 实测：仅授予 `USAGE + SELECT/INSERT/UPDATE/DELETE + 序列 USAGE` 的 `app_user`，DML 正常；但 `CREATE TABLE IF NOT EXISTS` 即使表已存在，仍在解析阶段报 `permission denied for schema assistant`。

**处置**

新增可重复迁移 `database/postgres/migrations/repeatable/R__grants.sql`，用占位符注入角色名：

```sql
GRANT USAGE ON SCHEMA assistant, knowledge TO ${app_role};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA assistant TO ${app_role};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA knowledge TO ${app_role};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA assistant TO ${app_role};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA knowledge TO ${app_role};

ALTER DEFAULT PRIVILEGES IN SCHEMA assistant
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${app_role};
ALTER DEFAULT PRIVILEGES IN SCHEMA knowledge
    GRANT SELECT, INSERT, UPDATE, DELETE ON TABLES TO ${app_role};
```

`ingest_role` 只需要 `knowledge` 的 DML + 序列权限，单独授予，不与 app 角色合并。角色名属于环境配置，必须通过 `FLYWAY_PLACEHOLDERS_APP_ROLE` / `..._INGEST_ROLE` 注入，不写死在 SQL 里。

### M3 / M4 索引

**现状索引**（`pg_indexes` 实测）：

- `messages`：`messages_pkey(id)`、`message_request(session,request_id,role)`、`message_retention(created)`、`messages_seq_key(seq)`。
- `workflow_runs`：仅 `workflow_runs_pkey(id)`；外键 `session` **无索引**。

**受影响语句**

```sql
-- core.py:493/495/512
SELECT * FROM messages WHERE session=? AND seq<? AND created>=?
ORDER BY seq DESC LIMIT 101;

-- core.py:531/542/548/564/569，以及 sessions 删除时的 FK 级联
SELECT id FROM workflow_runs WHERE session=?;
DELETE FROM sessions WHERE id=?;   -- 级联到 workflow_runs
```

**建议 SQL**（放入 `V1.1.0__indexes.sql`）：

```sql
CREATE INDEX messages_session_seq ON assistant.messages(session, seq DESC);
CREATE INDEX workflow_runs_session ON assistant.workflow_runs(session);
```

`messages` 数据量大时，`CREATE INDEX` 会阻塞写入。Flyway 默认单迁移单事务，不能直接执行 `CREATE INDEX CONCURRENTLY`；应在维护窗口执行普通 `CREATE INDEX`，或用 `-- flyway:executeInTransaction=false` 的独立脚本并由人工在低峰执行。两条语句均为纯增量，可安全回滚（`DROP INDEX`）。

---

## 4. 重复清单

| ID | 重复内容 | 位置 | 重复对象 | 处置 |
|---|---|---|---|---|
| D1 | 客服 6 表 + 4 索引 + `messages.seq` 的 DDL | `app/core.py:378-397` | 基线 §二 | 仅保留 SQLite 分支；PG 分支删除 |
| D2 | 知识 6 表 + `rag_chunk_doc` + `rag_state` 种子的 DDL | `app/rag.py:145-156`、`162-164` | 基线 §四/§五 | 仅保留 SQLite 分支；PG 分支改为版本校验 |
| D3 | LangGraph 检查点 4 表 + 索引 + 版本登记 | `app/workflow.py:87-90` 的 `saver.setup()` | 基线 §三 | PG 分支删除 `setup()`，改为版本校验 |
| D4 | `external_deployment` 建表 + 凭证行写入 | `app/deployment.py:73-83` 的 `claim()` | 基线 §二/§五 | 删除 DDL 与 `INSERT`，改为只读校验 |
| D5 | `CREATE SCHEMA assistant/knowledge` | `app/storage.py:61-65` | 基线 §一 | 删除；schema 由迁移创建 |
| D6 | 全量初始化脚本 | `../../scripts/postgres/schema/1.0.0.sql`、`scripts/postgres/data/1.0.0.sql` | 基线全文 | 冻结/归档，禁止再被执行 |
| D7 | 基线副本 | `database/archive/postgres/migrations/V1.0.0__baseline.sql` | `../../database/postgres/migrations/V1.0.0__baseline.sql` | 保留为归档，标注只读；不得作为执行入口 |
| D8 | “唯一权威来源”的文档冲突 | `database/archive/postgres/README.md` | `../../database/postgres/README.md` | 修正归档 README 的表述与失效链接 |
| D9 | 手动 `psql` 建库/建表流程 | `docs/PostgreSQL数据库初始化.md` | 基线全文 | 标注“历史参考，已被 Flyway 取代”或重写；禁止用于生产初始化 |

### D6 的特别说明

`../../scripts/postgres/schema/1.0.0.sql` 与 `data/1.0.0.sql` 是 Flyway 之前的建库脚本，内容与基线**逐表对应**，且包含 `DO` 块（外来表检查、占位符校验）。它们当前没有被任何脚本引用，但仍在仓库中，存在被误执行的风险。建议：

1. 移入 `database/archive/postgres/legacy/`（需运维目录授权）；
2. 在文件头加 `-- FROZEN: 由 database/postgres/migrations 取代，禁止执行`；
3. 在 `../../database/postgres/README.md` 的“唯一入口”一节明确指向。

### D1–D5 的共性

这 5 处不是“重复代码”这么简单：它们让 app 在**每次启动**都重新执行 DDL。即使结构完全正确，也会带来三个后果：

- app 必须持有 schema 的 `CREATE` 权限，无法最小权限；
- 迁移失败时 app 仍可能把表建出来，掩盖迁移问题；
- `IF NOT EXISTS` 会把结构漂移静默吞掉，Flyway 的 `validate` 失去意义。

---

## 5. 差异清单

| ID | 差异 | 位置 | 是否影响功能 | 说明 |
|---|---|---|---|---|
| X1 | app 要求数据库级 `CREATE` | `deployment.py:67`、`cloud.py:36` | 是（解耦后） | 迁移独立后 app 不应有 `CREATE`；需改为 `USAGE + DML` 校验 |
| X2 | `rate_limits` 表无任何读写 | `core.py:390`、基线 §二 | 否 | 历史遗留；保留但标记 deprecated，暂不删除 |
| X3 | 遗留脚本有外来表 `DO` 防护，基线没有 | `scripts/postgres/schema/1.0.0.sql:11` | 否（当前） | 基线用“人工 baseline + 归属校验”替代；收编时需用 M1 的预检补齐 |
| X4 | 基线用会话级 `SET search_path`，app 用每连接 `SET search_path` | 基线 §二/§四、`storage.py:67` | 否 | 两者等价；Flyway 单连接执行已验证 |
| X5 | 检查点迁移 9：基线 `ADD COLUMN`，库内 `ADD COLUMN IF NOT EXISTS` | 基线 §三 | 否 | 结果结构一致；基线只执行一次，无需幂等 |
| X6 | 9 张表使用位置式 `INSERT` | 见下表 | 否（当前） | 未来给这些表加列会导致列数不匹配，必须禁止 |
| X7 | app 的 `postgres_sql()` 做方言转换，基线是手写 PG 方言 | `storage.py:32-45` | 否 | 转换规则已覆盖 `user/window/rowid/BLOB/REAL/INTEGER PRIMARY KEY` |
| X8 | 基线注释写“3.2.0”，当前依赖也是 3.2.0 | 基线 §三 | 否 | 一致，无需处理；升级依赖时必须新增迁移并同步 `../../database/postgres/README.md`，不得改已应用的基线 |

### X6：位置式 INSERT 的 9 张表

| 表 | 语句 | 列数 |
|---|---|---:|
| `sessions` | `INSERT INTO sessions VALUES(?,?,?,?,?,?)` | 6 |
| `workflow_runs` | `INSERT INTO workflow_runs VALUES(?,?,?,?,?,?)` | 6 |
| `tenant_message_limits` | `INSERT INTO tenant_message_limits VALUES(?,?,?)` | 3 |
| `rag_state` | `INSERT OR IGNORE INTO rag_state VALUES(1,'',0)` | 3 |
| `rag_documents` | `INSERT INTO rag_documents VALUES(?,?,?,?,?,?)` | 6 |
| `rag_revisions` | `INSERT OR IGNORE INTO rag_revisions VALUES(?,?,?,?,?,?)` | 6 |
| `rag_chunks` | `INSERT OR IGNORE INTO rag_chunks VALUES(?,?,?,?,?,?)` | 6 |
| `rag_embedding_cache` | `INSERT INTO rag_embedding_cache VALUES(?,?,?)` | 3 |
| `external_deployment` | `INSERT INTO assistant.external_deployment VALUES(1,%s)` | 2 |

**约束**：在 app 改为显式列名之前，迁移**不得**给这 9 张表加列、删列、调列序。新增列只能加在 `messages`（已显式列名）、`checkpoint_*`（库内管理）或新表上。

---

## 6. app 端调整点

> 本节是核对版摘要；面向 app 开发的独立实施文档见 [`../app端迁移解耦改造说明.md`](../app端迁移解耦改造说明.md)，含逐文件 diff、单测建议与提交顺序。

> 原则：**只改初始化与校验，不改请求处理、检索、生成逻辑**；API 行为、返回结构、会话语义保持不变。

### 6.1 改动总表

| ID | 文件:行 | 现状 | 改动 | 优先级 |
|---|---|---|---|---|
| A1 | `app/storage.py:61-65` | 每次建池执行 `CREATE SCHEMA IF NOT EXISTS` | 删除该块；schema 必须预先存在 | P0 |
| A2 | `app/core.py:376-397` | 每次启动执行 6 表 + 4 索引 + `ALTER messages` | PG 分支改为 `require_postgres_schema()`；DDL 只保留在 SQLite 分支 | P0 |
| A3 | `app/rag.py:145-156`、`162-164` | 每次启动执行 6 表 + 种子 | 同上；`SCHEMA` 改名 `SQLITE_SCHEMA` | P0 |
| A4 | `app/workflow.py:87-90` | `saver.setup()` 每次执行检查点迁移 | PG 分支删除 `setup()`，改为 `require_checkpoint_schema()` | P0 |
| A5 | `app/deployment.py:53-83` | `claim()` 建表 + 写凭证行 | 改为只读 `check_database()`；删除 `claim()` | P0 |
| A6 | `app/deployment.py:143-151`、`178-180` | `initialize_runtime()` 构造 Service 触发 DDL | 删除；`initialize` 改为校验模式 | P0 |
| A7 | `app/deployment.py:67` | 要求数据库 `CREATE` | 随 A5 一并改写为 `USAGE` + 关键表 DML 校验（见 6.7） | P1 |
| A8 | `app/cloud.py:35-38` | 要求业务角色 `CREATE` | 改为 `CONNECT` 校验；权限由迁移/部署检查 | P1 |
| A9 | `app/migration.py:38-40` | 用 `Service`/`DocumentStore` 初始化目标库 | 改为 `PostgresDB` + `require_postgres_schema()` | P1 |
| A10 | 新增 `app/schema.py` | 无 | schema 版本契约与 fail-fast 校验 | P0 |
| A11 | `app/server.py:255-262` | `/ready` 只查 `SELECT 1` | 可选：`/health` 返回 schema 版本；启动已由 A2 保证 | P2 |
| A12 | `Dockerfile`、`deployment.yaml`、`../../scripts/dev.sh` | 路径/产物与迁移未解耦 | 见 6.9（非 app 代码，但必须同步） | P0 |

### 6.2 新增 `app/schema.py`

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
        raise SchemaNotReady('数据库尚未迁移或业务账号缺少 assistant schema 的 USAGE 权限；请先运行 db-migrate 并检查授权')

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

设计要点：

- **只读**：全部为 `SELECT`，不建表、不写数据、不持有锁。
- **失败即退出**：`SchemaNotReady` 继承 `RuntimeError`，由现有启动流程抛出，进程非零退出，K8s 不会把未迁移的 Pod 标为 Ready。
- **版本过滤**：`WHERE version IS NOT NULL`，避免 `R__` 可重复迁移的 `NULL` 版本干扰“最新版本”判断。
- **失败迁移优先**：先检查 `success=false`，再取版本；否则失败迁移会被“版本号已够”掩盖。
- **检查点版本独立**：LangGraph 依赖升级时，应用与迁移必须同步；不同步则 fail fast。

### 6.3 `../../app/core.py`

现状（376–397）：

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

改为：

```python
        if config.database_url:
            from .schema import require_postgres_schema
            require_postgres_schema(self.db)
        else:
            self.db.executescript('''PRAGMA journal_mode=WAL;
            ...
            CREATE TABLE IF NOT EXISTS workflow_runs(...);
            ''')
```

注意：

- SQLite 分支**原样保留**（含 `PRAGMA`、`seq` 之外的全部 DDL），本地开发与测试不受影响。
- 删除 `nullcontext` 导入与 `schema_lock()` 调用；`PostgresDB.schema_lock()` 可保留但不再被调用。
- 错误信息应包含“请先执行 db-migrate/迁移 Job”，便于值班人员直接定位。

### 6.4 `../../app/rag.py`

现状（145–164）：

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

改为：

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

注意：

- `rag_state` 的种子行由基线 §五写入；PG 分支不再 `INSERT OR IGNORE`。
- 删除 `pg_advisory_xact_lock`：DDL 已移除，不再需要“建表串行化”；如果后续有并发写入需求，应使用行锁，而不是 DDL 锁。
- `DocumentStore` 在 `Service.__init__` 中先于 `self.db` 创建（`core.py:354-356`），因此**这里通常是应用启动的第一个 schema 校验点**，错误信息要写清楚。

### 6.5 `../../app/workflow.py`

现状（87–90）：

```python
            self.saver=PostgresSaver(self._resource)
            with self._resource.connection() as connection:
                connection.execute('SELECT pg_advisory_lock(729630041)')
                try:self.saver.setup()
                finally:connection.execute('SELECT pg_advisory_unlock(729630041)')
```

改为：

```python
            self.saver=PostgresSaver(self._resource)
            from .schema import require_checkpoint_schema
            with self._resource.connection() as connection:
                require_checkpoint_schema(connection)
```

注意：

- `PostgresSaver.setup()` **必须删除**，不能保留“版本已是最新就很快”的侥幸：它每次都会执行 `MIGRATIONS[0]` 的 `CREATE TABLE IF NOT EXISTS checkpoint_migrations`，需要 schema 的 `CREATE` 权限。
- SQLite 分支的 `SqliteSaver.setup()` 保留。
- 如果未来 LangGraph 升级引入新迁移，由 migration 镜像负责补齐，应用只校验 `CHECKPOINT_VERSION`。

### 6.6 `../../app/storage.py`

现状（61–65）：

```python
        with self.pool.connection() as c:
            key=int.from_bytes(hashlib.sha256(('schema:'+schema).encode()).digest()[:8],'big',signed=True)
            c.execute('SELECT pg_advisory_lock(%s)',(key,))
            try:c.execute('CREATE SCHEMA IF NOT EXISTS '+schema)
            finally:c.execute('SELECT pg_advisory_unlock(%s)',(key,))
```

改为：**整块删除**。连接池创建后不再执行任何 DDL；`configure()` 中的 `SET search_path`、`statement_timeout`、`lock_timeout` 保留。

注意：

- 删除后，`assistant`/`knowledge` 必须由迁移预先创建；否则第一条业务 SQL 会报 `schema does not exist`，错误比 `SchemaNotReady` 更难读。因此 A10 的校验必须在业务查询前执行（当前顺序满足：`Service` 先建 `DocumentStore`，再建 `self.db`）。
- `hashlib` 仍被 `session_lock` 使用，不要误删导入。

### 6.7 `../../app/deployment.py`

现状（53–83）：

```python
def check_database(conn):
    marker = conn.execute("SELECT to_regclass('assistant.external_deployment')").fetchone()[0]
    if marker:
        ...
        return True
    existing = conn.execute("SELECT count(*) FROM information_schema.tables WHERE table_schema IN ('assistant','knowledge')").fetchone()[0]
    if existing:
        raise DeploymentError('目标库已有客服数据但不属于本部署...')
    permitted = conn.execute("SELECT has_database_privilege(current_database(),'CREATE')").fetchone()[0]
    ...
    return False

def claim(conn):
    with conn.transaction():
        conn.execute('SELECT pg_advisory_xact_lock(729630042)')
        owned = check_database(conn)
        if not owned:
            conn.execute('CREATE SCHEMA IF NOT EXISTS assistant')
            conn.execute('CREATE TABLE assistant.external_deployment(...)')
            conn.execute('INSERT INTO assistant.external_deployment VALUES(1,%s)', ...)
```

改为：

```python
def check_database(conn):
    """只读校验：归属、权限、知识是否已初始化。"""
    marker = conn.execute("SELECT to_regclass('assistant.external_deployment')").fetchone()[0]
    if not marker:
        raise DeploymentError('数据库尚未由 Flyway 初始化：缺少 assistant.external_deployment，请先执行 db-migrate')
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
        raise DeploymentError('业务账号缺少 assistant/knowledge 的 USAGE 或业务表 DML 权限，请先执行迁移与授权')
    # 不能直接 return True：该值仍用于 check_milvus() 判断 Milvus 前缀是否可复用。
    return bool(conn.execute(
        'SELECT EXISTS(SELECT 1 FROM knowledge.rag_documents)'
    ).fetchone()[0])
```

并删除 `claim()` 整个函数；`main()` 中：

```python
            if args.action == 'initialize':
                stage = '校验数据库版本'
                from .schema import require_postgres_schema
                require_postgres_schema(conn)
```

注意：

- `initialize` 从“初始化”变成“校验”，保留命令名是为了不破坏现有运维脚本；文档与输出文案要同步改为“校验通过”，避免误解。
- 删除 `initialize_runtime()`（143–151）以及 `main` 中对它的调用（180）。
- `check` 分支里的 `rag_state.fingerprint` 校验保留：它判断的是“知识配置是否变化”，与 schema 版本是两件事。
- `--create-database` 仍保留：它只创建**空数据库**，不建 schema/表，属于基础设施准备，不违反解耦。

### 6.8 `../../app/cloud.py` 与 `app/migration.py`

**`../../app/cloud.py`（35–38）**

现状要求业务角色对目标库有 `CREATE`，用于“初始化两个 schema”。解耦后不应再由 app 建 schema：

```python
    with psycopg.connect(**target, connect_timeout=10) as conn:
        if not conn.execute(
            "SELECT has_database_privilege(current_database(),'CONNECT')"
        ).fetchone()[0]:
            raise ValueError('业务账号缺少目标库 CONNECT 权限')
```

schema/表权限由 `deployment check` 在迁移后校验（A7），`cloud prepare` 只负责“库和角色存在、能连上”。

**`../../app/migration.py`（38–40）**

现状：

```python
    from .core import Service
    from .rag import DocumentStore,RAGSettings
    # Initialize destination schemas without calling any external model.
    service=Service(config);service.close();rag=RAGSettings()
    DocumentStore(rag.index_path,config.database_url)
```

改为：

```python
    from .storage import PostgresDB
    from .schema import require_postgres_schema
    destination = PostgresDB(config.database_url, 'assistant', max_size=2)
    try:
        require_postgres_schema(destination)
    finally:
        destination.close()
```

并复用同一个 `destination` 连接池执行后续迁移（当前代码在后面又创建了一次 `PostgresDB`，可合并）。注意：

- `migrate-storage` 是**运维命令**，应使用迁移/运维角色执行（需要 `setval` 序列权限），不要用 app 角色。
- `export_sqlite` 仍走 SQLite 分支，`Service(database_url='')` 会创建 SQLite 表，保留不变。

### 6.9 非 app 代码但必须同步

| 位置 | 现状 | 问题 | 改动 |
|---|---|---|---|
| `deploy/docker/Dockerfile:5` | `COPY requirements.lock ./` | 仓库只有 `../../uv.lock`，构建直接失败 | CI 用 `uv export --frozen --no-dev -o requirements.lock`，或改为复制 `../../uv.lock` 并安装 `uv` |
| `deploy/docker/Dockerfile:8` | `COPY database ./database` | 应用镜像携带迁移 SQL，违反“app 不含 migration” | 删除；app 不需要 `../../database/postgres` |
| `deploy/docker/Dockerfile:11` | `COPY manage.py ./` | 根目录已无 `manage.py`（已移到 `../../database/milvus/manage.py`） | 恢复根目录入口 shim，或改为复制 `../../database/milvus/manage.py` |
| `deploy/k8s/base/deployment.yaml:55` | `python manage.py ingest` | 同上，路径失效 | 改为实际入口 |
| `scripts/dev.sh:43,52,53` | `python -m app.deployment initialize`、`python manage.py ingest` | 仍假设 app 负责初始化；路径失效 | 先跑 migration 镜像，再 `deployment check`；修正 `manage.py` 路径 |
| `deploy/docker/Dockerfile.dbmigrate:5` | `FROM flyway/flyway:11.x.x` | 非合法 tag，构建不可复现 | 固定 `11.20.3` 或 digest |

### 6.10 改动后的启动时序

```text
Pod 启动
  → Init: db-migrate（migrate，带归属占位符）
  → Init: knowledge-ingest（可选，独立任务）
  → app: Service.__init__
       → DocumentStore → require_postgres_schema(knowledge pool)
       → Service.db     → require_postgres_schema(assistant pool)
       → SupportWorkflow → require_checkpoint_schema()
  → app: lifespan 完成，state.ready=True
  → /ready 返回 200
```

说明：上图沿用当前 K8s 形态（Init 直接 `migrate`），适合单副本或开发环境；生产多副本推荐把 `migrate` 提升为独立 Job，Init 只做 `validate`，见 §7.3。

任何一步校验失败，进程非零退出；K8s 不会把 Pod 标为 Ready，也不会接流量。

---

## 7. migration 独立化的职责边界与前置流程

### 7.1 职责矩阵

| 角色 | 执行者 | 权限 | 负责 | 明确不负责 |
|---|---|---|---|---|
| Schema 变更 | `db-migrate` 镜像（Flyway） | 库/ schema 属主或 `CREATE`；表 DDL | `V__` 版本迁移、`R__` 可重复迁移、`callbacks`、`flyway_schema_history`、归属凭证行、检查点表 | 业务数据、Milvus、应用启动 |
| 业务读写 | `assistant` 镜像 | `USAGE` + 表 `SELECT/INSERT/UPDATE/DELETE` + 序列 `USAGE/SELECT` | 会话、消息、配额、知识读取、检查点读写 | 任何 DDL、schema 创建、种子写入 |
| 知识入库 | `knowledge-ingest` 任务 | `knowledge` DML + 序列；Milvus 凭证 | `manage.py ingest`、向量写入、`rag_*` 元数据 | schema DDL、应用启动 |
| 运维 | 人/流水线 | 备份、Job 执行、只读巡检 | 备份、迁移编排、验收、回滚决策 | 手工改表结构 |

**边界一句话**：`../../database/postgres/migrations` 是唯一的 schema 变更来源；`db-migrate` 是唯一的 schema DDL 执行者；`app` 只验证、只 DML。建库、建角色属于基础设施准备，由 DBA/平台执行，不在此列。

### 7.2 镜像与产物

| 产物 | 构建文件 | 内容 | 标签 |
|---|---|---|---|
| `db-migrate` | `../../deploy/docker/Dockerfile.dbmigrate` | Flyway + `flyway.conf` + `migrations/`（含 `callbacks/`、`repeatable/`、领域目录） | 与 app 同 commit/tag |
| `assistant` | `../../deploy/docker/Dockerfile` | 仅 `../../app`、`data/`、`knowledge_sources/`、启动入口 | 与 app 同 commit/tag |
| `knowledge-tools`（建议） | 新增 | `pymilvus` + `database/milvus/*`，不含模型 Key | 与 app 同 tag |

硬约束：

- `db-migrate` 镜像**不得**包含 `../../app`；
- `assistant` 镜像**不得**包含 `../../database/postgres`；
- 两个镜像必须同 commit/tag 构建，禁止“新 app + 旧 migration”。

### 7.3 发布前置流程

```text
[1] 构建双镜像（同 tag）
      ↓
[2] pg_dump -Fc 备份（失败即停）
      ↓
[3] db-migrate migrate（归属校验 → V__/R__ → afterMigrate 体检）
      ↓ 失败 → 停止发布；PG 事务回滚；修复后 flyway repair + 重跑
[4] db-migrate validate + checks/health.sql（只读）
      ↓
[5] knowledge-ingest（如知识有变更；失败不阻塞 app，但 /ready 可能 503）
      ↓
[6] 滚动 app（Init 只做 validate，不再 migrate）
      ↓
[7] 冒烟：/ready、一次问答、重启后历史
```

推荐职责划分：

- **生产**：`[3]` 用独立 `Job`（Helm pre-upgrade / Argo PreSync）执行一次；app Deployment 的 Init 容器只执行 `validate`，避免 N 个副本重复 `migrate` 与抢 Flyway 锁。
- **开发/单副本**：可以保留当前“Init 容器直接 migrate”，简单且够用；但必须接受“每个 Pod 都跑一次 migrate”的语义。
- **存量库**：先人工执行 `baseline`（`job-db-baseline.yaml`），再按 M1 的 `pre_baseline.sql` 体检；基线不修复结构，缺对象必须人工补齐。

### 7.4 配置与密钥边界

| 配置 | app | db-migrate | ingest |
|---|---|---|---|
| `DATABASE_URL` | 业务角色 | — | 业务/ingest 角色 |
| `FLYWAY_URL` / `FLYWAY_USER` / `FLYWAY_PASSWORD` | — | 迁移角色 | — |
| `DEPLOYMENT_ID` / `MILVUS_URI` / `MILVUS_DATABASE` / `MILVUS_COLLECTION` | 读取并校验归属 | `FLYWAY_PLACEHOLDERS_*` 同源注入 | 读取 |
| `MODEL_API_KEY` / `RERANK_API_KEY` | 需要 | **不注入** | 需要 |
| `AUTH_SECRET` | 需要 | **不注入** | 需要（签发/校验） |

关键点：迁移任务只拿数据库凭证与四个归属占位符，不拿模型 Key；app 不拿 `FLYWAY_*`。两边配置由 `deployment check` 比对，避免“迁移写了一套 Milvus 前缀、app 读了另一套”。

### 7.5 失败语义与回滚

| 场景 | 行为 | 处置 |
|---|---|---|
| `migrate` 中 SQL 失败 | PostgreSQL DDL 事务回滚；history 记录失败行 | 修复 SQL → `flyway repair` → 重跑；禁止手工改 history |
| `beforeMigrate` 归属不一致 | 迁移在第一条 SQL 前终止 | 核对 `DEPLOYMENT_ID`/`MILVUS_*`；确认是否连错库 |
| `afterMigrate` 体检失败 | 迁移已提交，回调失败 | 修复结构（正向迁移）→ 重跑；不要回滚已提交迁移 |
| app 启动无 schema | `SchemaNotReady`，进程退出 | 先跑 migration；不要临时给 app 开 `CREATE` |
| app 版本高于 schema | 同上 | 先升级 schema，再滚动 app |
| 迁移成功但 app 异常 | app 可回退到 N-1 | `ignoreMigrationPatterns=*:future` 保证旧镜像通过 `validate` |
| 迁移写错数据 | 优先 `V__fix` 正向修复 | 紧急时从 `pg_dump -Fc` 恢复；恢复前停止写入 |

原则：**schema 只前进，app 可回退**；已应用的 `V__` 文件永不修改；`clean` 永久禁用。

---

## 8. 交付与验收标准

### 8.1 交付物

| # | 交付物 | 责任方 | 说明 |
|---|---|---|---|
| 1 | `app/schema.py` + A1–A10 改动 | app 开发 | 只改初始化/校验，不改业务逻辑 |
| 2 | `V1.1.0__indexes.sql`（M3/M4） | 运维/DBA | 维护窗口执行；或 `CONCURRENTLY` 独立脚本 |
| 3 | `checks/pre_baseline.sql` + `scripts/ci/check_db.py`（M1） | 运维/DBA | 只读；runner 负责“有行即失败” |
| 4 | `R__grants.sql`（M2） | 运维/DBA | 角色名占位符注入 |
| 5 | Dockerfile / deployment / dev.sh 修正（6.9） | 运维 | 构建可复现、镜像不含 migration |
| 6 | CI 门禁扩展 | 运维 | 见 8.2 第 1、2 项 |
| 7 | 本文档 + 更新 `../../database/postgres/README.md` | 运维 | 运维入口唯一化 |

### 8.2 验收项

| # | 验收项 | 命令/方法 | 通过标准 |
|---|---|---|---|
| 1 | app 无 PG DDL | `grep -Rn "CREATE" app/; grep -Rn "ALTER TABLE" app/; grep -Rn "DROP" app/` | 仅命中 SQLite 分支；PG 分支 0 命中 |
| 2 | app 镜像不含迁移 | `docker run --rm <app> test ! -d database/postgres` | 退出码 0 |
| 3 | 空库迁移 | 空库执行 `db-migrate migrate` | 17 张表 + `flyway_schema_history`；`validate` 成功 |
| 4 | 重复迁移幂等 | 再次 `migrate` | `No migration necessary`；两个回调仍执行 |
| 5 | 最小权限启动 | app 角色仅 `USAGE + DML`，启动服务 | 启动成功；`/ready` 200 |
| 6 | 未迁移启动 | 空库直接启动 app | 非零退出；日志含 `SchemaNotReady`；库中 0 张业务表 |
| 7 | 版本低于要求 | 将 `flyway_schema_history` 版本改为 `0.9.0` 后启动 | 非零退出；提示“低于应用要求” |
| 8 | 检查点版本不足 | 将 `checkpoint_migrations` 最大版本改为 8 后启动 | 非零退出；提示检查点版本过低 |
| 9 | 语句回归 | 对迁移后库执行 53 条去重 `PREPARE`（58 个调用点） | 53 通过 / 0 失败 |
| 10 | 冒烟 | 创建会话 → 提问 → 重启 → 查历史 | 历史完整；`messages.seq` 连续；无重复 |
| 11 | 结构契约 | `schema_fingerprint.sql` 对比 golden | 指纹一致 |
| 12 | 回退 | app 回退到 N-1（schema 保持新版本） | 启动成功；`validate` 通过 |

### 8.3 红线

1. `../../app` 的 PostgreSQL 路径不得出现任何 `CREATE/ALTER/DROP`。
2. `assistant` 镜像不得包含 `../../database/postgres`。
3. 生产环境不得手工执行 DDL；所有变更必须走 migration 镜像。
4. 已应用的 `V__` 文件不得修改、重排、改注释；只能新增下一个版本。
5. 不得给 X6 列出的 9 张表加列/删列/调列序，直到 app 改为显式列名。
6. 不得用 `flyway clean`；不得手工改 `flyway_schema_history`。

---

## 9. 实施顺序

| 阶段 | 内容 | 退出条件 |
|---|---|---|
| P0 | 修 Dockerfile 构建阻断（`requirements.lock`、`manage.py` 路径）；新增 `app/schema.py`；A1–A6 | app 在最小权限库上启动成功；空库启动失败且提示明确 |
| P1 | A7–A9；`R__grants.sql`；migration Job + Init `validate`；`deployment initialize` 语义改为校验 | 双角色（migrator/app）跑通一轮发布 |
| P2 | M3/M4 索引；M1 `pre_baseline.sql`；CI 门禁（app 无 DDL、镜像无 migration） | 验收 12 项全过 |
| P3 | 清理 `../../scripts/postgres` 遗留脚本、修正归档 README、更新 `database/postgres/README.md` | 仓库只有一个 DDL 来源 |

---

## 附录 A：53 条语句逐条核对

| # | 语句（归一化） | 位置 | 结果 |
|---:|---|---|---|
| 1 | `INSERT INTO tenant_message_limits VALUES(?,?,?) ON CONFLICT(owner) DO NOTHING` | core.py:426 | PASS |
| 2 | `SELECT events FROM tenant_message_limits WHERE owner=? FOR UPDATE` | core.py:428 | PASS |
| 3 | `UPDATE tenant_message_limits SET events=?,updated=? WHERE owner=?` | core.py:432 | PASS |
| 4 | `SELECT to_char(CURRENT_TIMESTAMP AT TIME ZONE 'Asia/Shanghai','YYYY-MM-DD') AS day` | core.py:439 | PASS |
| 5 | `INSERT INTO global_rag_daily_limits(day,used,updated) VALUES(?,?,?) ON CONFLICT(day) DO NOTHING` | core.py:443 | PASS |
| 6 | `UPDATE global_rag_daily_limits SET used=used+1,updated=? WHERE day=? AND used<? RETURNING used` | core.py:444 | PASS |
| 7 | `SELECT * FROM sessions WHERE id=? AND tenant=? AND user=? AND updated>=?` | core.py:455 | PASS |
| 8 | `INSERT INTO sessions VALUES(?,?,?,?,?,?)` | core.py:471 | PASS |
| 9 | `SELECT id,created,updated,context FROM sessions WHERE tenant=? AND user=? AND updated>=? ORDER BY updated DESC LIMIT 100` | core.py:481 | PASS |
| 10 | `SELECT rowid FROM messages WHERE session=? AND id=? AND created>=?` | core.py:490 | PASS |
| 11 | `SELECT * FROM messages WHERE session=? AND rowid<? AND created>=? ORDER BY rowid DESC LIMIT 101` | core.py:493 | PASS |
| 12 | `SELECT * FROM messages WHERE session=? AND created>=? ORDER BY rowid DESC LIMIT 101` | core.py:495 | PASS |
| 13 | `SELECT * FROM messages WHERE session=? AND created>=? ORDER BY rowid DESC LIMIT ?` | core.py:512 | PASS |
| 14 | `SELECT updated FROM sessions WHERE id=?` | core.py:538 | PASS |
| 15 | `SELECT COUNT(*) FROM messages WHERE session=? AND created<?` | core.py:540 | PASS |
| 16 | `SELECT id FROM workflow_runs WHERE session=? AND updated<?` | core.py:542 | PASS |
| 17 | `DELETE FROM workflow_runs WHERE id=?` | core.py:548 | PASS |
| 18 | `SELECT COUNT(*) FROM messages WHERE session=?` | core.py:550 | PASS |
| 19 | `DELETE FROM messages WHERE session=? AND created<?` | core.py:553 | PASS |
| 20 | `SELECT id FROM workflow_runs WHERE session=?` | core.py:564 | PASS |
| 21 | `DELETE FROM sessions WHERE id=?` | core.py:569, core.py:551 | PASS |
| 22 | `SELECT payload,created FROM messages WHERE session=? AND request_id=? AND role='assistant'` | core.py:614 | PASS |
| 23 | `SELECT content FROM messages WHERE session=? AND request_id=? AND role='user'` | core.py:617 | PASS |
| 24 | `INSERT INTO messages(id,session,request_id,role,content,payload,created) VALUES(?,?,?,?,?,?,?)` | core.py:655, core.py:657 | PASS |
| 25 | `UPDATE sessions SET updated=? WHERE id=?` | core.py:659 | PASS |
| 26 | `INSERT INTO workflow_runs VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET status=excluded.status,updated=excluded.updated` | core.py:660 | PASS |
| 27 | `SELECT metadata FROM assistant.external_deployment WHERE id=1` | deployment.py:57 | PASS |
| 28 | `INSERT INTO assistant.external_deployment VALUES(1,%s)` | deployment.py:82 | PASS |
| 29 | `SELECT fingerprint FROM knowledge.rag_state WHERE id=1` | deployment.py:172 | PASS |
| 30 | `UPDATE knowledge.rag_state SET fingerprint=?,generation=? WHERE id=1` | migration.py:65 | PASS |
| 31 | `SELECT * FROM rag_documents ORDER BY path` | rag.py:170 | PASS |
| 32 | `SELECT document_id,revision,filename,metadata,created FROM rag_revisions WHERE document_id=? ORDER BY created DESC` | rag.py:173 | PASS |
| 33 | `SELECT record FROM rag_chunks WHERE id=?` | rag.py:176 | PASS |
| 34 | `SELECT filename,raw FROM rag_revisions WHERE document_id=? AND revision=?` | rag.py:180 | PASS |
| 35 | `SELECT * FROM rag_documents WHERE id=?` | rag.py:184 | PASS |
| 36 | `UPDATE rag_documents SET active=0,updated=? WHERE id=?` | rag.py:186 | PASS |
| 37 | `UPDATE rag_state SET generation=generation+1 WHERE id=1` | rag.py:187, rag.py:200 | PASS |
| 38 | `INSERT INTO rag_events(document_id,action,revision,created) VALUES(?,?,?,?)` | rag.py:188, rag.py:201, rag.py:294 | PASS |
| 39 | `SELECT metadata FROM rag_revisions WHERE document_id=? AND revision=?` | rag.py:191 | PASS |
| 40 | `SELECT fingerprint FROM rag_state WHERE id=1` | rag.py:193 | PASS |
| 41 | `SELECT record,vector FROM rag_chunks WHERE document_id=? AND revision=?` | rag.py:197 | PASS |
| 42 | `UPDATE rag_documents SET current_revision=?,active=1,updated=? WHERE id=?` | rag.py:199 | PASS |
| 43 | `SELECT * FROM rag_state WHERE id=1` | rag.py:206 | PASS |
| 44 | `SELECT c.record,c.vector FROM rag_chunks c JOIN rag_documents d ON d.id=c.document_id AND d.current_revision=c.revision WHERE d.active=1` | rag.py:208 | PASS |
| 45 | `SELECT vector FROM rag_embedding_cache WHERE fingerprint=? AND text_hash=?` | rag.py:258 | PASS |
| 46 | `INSERT INTO rag_embedding_cache VALUES(?,?,?) ON CONFLICT(fingerprint,text_hash) DO UPDATE SET vector=excluded.vector` | rag.py:267 | PASS |
| 47 | `SELECT generation FROM rag_state WHERE id=1 FOR UPDATE` | rag.py:286 | PASS |
| 48 | `INSERT OR IGNORE INTO rag_revisions VALUES(?,?,?,?,?,?)` | rag.py:290 | PASS |
| 49 | `INSERT OR IGNORE INTO rag_chunks VALUES(?,?,?,?,?,?)` | rag.py:292 | PASS |
| 50 | `INSERT INTO rag_documents VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET path=excluded.path,title=excluded.title,current_revision=excluded.current_revision,active=1,updated=excluded.updated` | rag.py:293 | PASS |
| 51 | `UPDATE rag_state SET fingerprint=?,generation=generation+1 WHERE id=1` | rag.py:295 | PASS |
| 52 | `SELECT pg_try_advisory_lock(%s)` | storage.py:122 | PASS |
| 53 | `INSERT INTO workflow_runs VALUES(?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET updated=excluded.updated` | workflow.py:360 | PASS |

---

## 附录 B：建议新增的 SQL

### B.1 `V1.1.0__indexes.sql`

```sql
-- 目的：补齐历史分页与会话级联删除的索引
-- 影响：messages 大表建索引会阻塞写入，须在维护窗口执行
-- 回滚：DROP INDEX assistant.messages_session_seq; DROP INDEX assistant.workflow_runs_session;

CREATE INDEX messages_session_seq
    ON assistant.messages (session, seq DESC);

CREATE INDEX workflow_runs_session
    ON assistant.workflow_runs (session);
```

### B.2 `R__grants.sql`（节选）

```sql
-- 可重复迁移：角色权限；角色名由 FLYWAY_PLACEHOLDERS_APP_ROLE 注入
GRANT USAGE ON SCHEMA assistant, knowledge TO ${app_role};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA assistant TO ${app_role};
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA knowledge TO ${app_role};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA assistant TO ${app_role};
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA knowledge TO ${app_role};
```

### B.3 `checks/pre_baseline.sql`（思路）

只读返回违规行，不抛异常；由外部 runner 判断“有行即失败”：

```sql
WITH required(table_name) AS (
    VALUES
        ('assistant.sessions'),
        ('assistant.messages'),
        ('assistant.workflow_runs'),
        ('assistant.external_deployment'),
        ('knowledge.rag_state')
)
SELECT 'missing_table' AS check_name, table_name AS detail
FROM required
WHERE to_regclass(table_name) IS NULL

UNION ALL

SELECT 'missing_column', 'assistant.messages.seq'
WHERE NOT EXISTS (
    SELECT 1 FROM information_schema.columns
    WHERE table_schema = 'assistant' AND table_name = 'messages' AND column_name = 'seq'
)

UNION ALL

SELECT 'missing_sequence', 'assistant.messages_seq_seq'
WHERE to_regclass('assistant.messages_seq_seq') IS NULL;
```

---

## 附录 C：核对脚本与临时环境

本次核对使用的脚本未写入项目，方法可复现：

1. 起临时 `postgres:17-alpine`，用替换占位符后的 `V1.0.0__baseline.sql` 建库；
2. Python AST 抽取 `app/*.py` 的 `execute/executemany` 字面量；
3. 用 `app.storage.postgres_sql()` 做方言转换，把 `%s` 顺序替换为 `$1..$n`；
4. `PREPARE audit_stmt AS <sql>`，成功即 `DEALLOCATE`；
5. 另起空库，用 `Service(Settings())` + `SupportWorkflow` 自建结构，跑 `schema_fingerprint.sql` 对比。

未在项目中留下容器、临时数据库或脚本。
