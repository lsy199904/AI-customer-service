# PostgreSQL SQL 脚本（Flyway）

本目录维护 PostgreSQL 的 schema 与受控数据，由 Flyway 按版本号执行 SQL。应用代码不在此目录。

## 一、当前现状

### 1.1 基本信息

| 项 | 值 |
|---|---|
| 当前版本 | `1.0.0`（`migrations/V1.0.0__baseline.sql`） |
| 数据库 | PostgreSQL 16（本地验证可用 17） |
| Flyway | 11.x |
| Schema | `assistant`（会话/配额/工作流/平台）、`knowledge`（知识库） |
| 表数量 | 17 张：12 张业务表 + 4 张 LangGraph 检查点表 + `external_deployment` |
| 版本记录表 | `assistant.flyway_schema_history` |
| 检查点依赖 | `langgraph-checkpoint-postgres==3.2.0`，`MIGRATIONS` 共 10 条（0–9） |

### 1.2 目录结构

```text
database/postgres/
├── flyway.conf                  # Flyway 配置；连接与占位符经环境变量注入
├── migrations/                  # Flyway 扫描根（递归）
│   ├── V1.0.0__baseline.sql     # 1.0.0 基线；内容与路径均不可变
│   ├── callbacks/               # 生命周期回调
│   │   ├── beforeMigrate__verify_identity.sql
│   │   └── afterMigrate__health.sql
│   ├── repeatable/              # R__ 可重复脚本（当前为空）
│   ├── conversation/            # 会话与消息
│   ├── quota/                   # 租户/全局配额
│   ├── knowledge/               # 知识文档、切片、向量元数据
│   ├── workflow/                # 工作流登记 + LangGraph 检查点
│   └── platform/                # schema、扩展、授权、共享函数、归属登记
├── templates/
│   └── V__migration.sql.tmpl    # 新脚本模板；不在 Flyway 扫描范围内
├── checks/
│   ├── health.sql               # 只读结构体检
│   └── schema_fingerprint.sql   # 结构指纹
└── README.md
```

说明：

- 5 个领域目录和 `repeatable/` 中的 `.gitkeep` 只用于保留空目录，首个脚本落地后可删除。
- 迁移镜像 `deploy/docker/db-migrate/Dockerfile` 按目录**显式 COPY**，新增领域目录时必须同步补一行：
  ```dockerfile
  COPY database/postgres/migrations/<新目录>/ /flyway/migrations/<新目录>/
  ```
  `scripts/ci/check_sql.py` 会校验两侧一一对应，漏改则门禁失败。
- `callbacks/`、`repeatable/` 是全局目录，不放入领域目录。
- `checks/` 不被 Flyway 执行，只由 `psql` 或 CI 调用。
- `templates/` 不进入 Flyway 扫描范围，也不会被打包进执行环境。

### 1.3 脚本组织

| 领域目录 | 包含的表 | 对应 App 模块 |
|---|---|---|
| `conversation/` | `assistant.sessions`、`assistant.messages` | `app/core.py` 会话/消息 |
| `quota/` | `assistant.tenant_message_limits`、`assistant.global_rag_daily_limits`、`assistant.rate_limits` | `app/core.py` 限流/配额 |
| `knowledge/` | `knowledge.rag_state`、`rag_documents`、`rag_revisions`、`rag_chunks`、`rag_events`、`rag_embedding_cache` | `app/rag.py`、`app/ingestion.py` |
| `workflow/` | `assistant.workflow_runs`、`assistant.checkpoint_*` | `app/workflow.py`、LangGraph |
| `platform/` | `assistant.external_deployment`、schema、扩展、授权、共享函数 | `app/deployment.py`、运维 |

- 一个 SQL 文件只做一个业务变更；同一领域的相关语句可以放在同一文件。
- 跨领域变更放主表所属领域，在文件头 `-- 影响表` 列出其他领域。
- 领域目录只影响阅读和 review，不影响执行顺序。

### 1.4 版本管理机制

- 版本化脚本命名：`V<major>.<minor>.<patch>__<domain>_<verb>_<object>.sql`。
- 当前版本为 `1.0.0`；后续版本按 `V1.0.1`、`V1.0.2` 递增，新版本取当前最大值 + 1。
- `V1.0.0__baseline.sql` 是已执行基线，路径、内容、空白、注释均不可修改。
- `R__<domain>_<object>.sql` 为可重复脚本，只在内容 checksum 变化时重新执行；当前目录为空。
- `callbacks/` 中的回调在每次 Flyway 执行前后运行，不参与版本排序。
- Flyway 只按版本号排序，目录名不参与排序；`outOfOrder=false`，新增版本必须大于当前最大版本。
- 版本记录写入 `assistant.flyway_schema_history`；`validateOnMigrate=true` 会校验已执行脚本的 checksum。
- `flyway.conf` 的关键配置：`locations=filesystem:migrations`、`callbackLocations=filesystem:migrations/callbacks`、`schemas=assistant,knowledge`、`table=flyway_schema_history`、`cleanDisabled=true`、`baselineOnMigrate=false`。

## 二、SQL 变更操作与维护规范

### 2.1 先理解三件事

| 概念 | 事实 | 为什么 |
|---|---|---|
| 版本号 | Flyway 只按版本号排序，目录不参与排序 | 目录可以按领域随便分，但执行顺序必须由版本号唯一决定 |
| 领域目录 | 一个目录对应一组表和一个 App 模块 | 让 review、CODEOWNERS、问题定位有明确边界 |
| 单个文件 | 一个文件只做一个业务变更 | 失败时容易定位；review 时能看清“改了什么、为什么改” |

### 2.2 一张图看懂变更流程

```text
app 需要新增/修改表、字段、索引或受控数据
        │
        ▼
[1] 选领域 ── 主表在哪个目录？sessions/messages → conversation
        │
        ▼
[2] 定版本 ── 当前最大 V1.0.N，新文件用 N+1
        │
        ▼
[3] 建文件 ── 复制模板到 migrations/<domain>/
        │
        ▼
[4] 写 SQL ── 一个变更；文件头写清目的、影响表、回滚方式
        │
        ▼
[5] 静态检查 ─ python3 scripts/ci/check_sql.py
        │
        ▼
[6] 空库执行 ─ 用 Flyway 在空库跑一遍
        │
        ▼
[7] 验证 ── flyway info / validate + checks/health.sql
        │
        ▼
[8] 提交 PR
```

### 2.3 手动操作步骤

以下命令默认在仓库根目录执行。

#### 第 1 步：选领域目录

按**主表**选目录，不按 App 文件选：

| 要改的表 | 目录 |
|---|---|
| `sessions`、`messages` | `migrations/conversation/` |
| `tenant_message_limits`、`global_rag_daily_limits`、`rate_limits` | `migrations/quota/` |
| `rag_*` | `migrations/knowledge/` |
| `workflow_runs`、`checkpoint_*` | `migrations/workflow/` |
| `external_deployment`、schema、扩展、授权 | `migrations/platform/` |

跨领域变更放主表所属目录，并在文件头 `-- 影响表` 列出其他表。不要把 `platform/` 当成“不知道放哪”的默认目录。

#### 第 2 步：确定版本号

先看当前最大版本：

```bash
find database/postgres/migrations -name 'V*.sql' -exec basename {} \; | sort -V | tail -5
```

取最大版本的最后一位 + 1。例如当前是 `1.0.0`，新文件就是 `V1.0.1`；已有 `V1.0.9`，新文件是 `V1.0.10`。

**为什么不能按字符串排序**：字符串里 `1.0.10` 会排在 `1.0.9` 前面，但 Flyway 按数字比较，`1.0.10` 才是更大的版本。始终用 `sort -V` 或 `flyway info` 查看顺序。

#### 第 3 步：创建文件

```bash
cp database/postgres/templates/V__migration.sql.tmpl \
   database/postgres/migrations/conversation/V1.0.1__conversation_add_message_client_id.sql
```

然后编辑文件，把模板里的领域占位符改成实际领域，并补全文件头：

```sql
-- =====================================================================
-- 目的：为消息增加客户端幂等键，支持前端重试去重
-- 领域：conversation
-- 影响表：assistant.messages
-- 关联工单：TITU-1234
-- 应用版本：1.2.0
-- 锁/耗时：ADD COLUMN 仅改元数据；CREATE INDEX 需评估写入影响
-- 回滚/修复：DROP INDEX；DROP COLUMN 前确认无读写
-- =====================================================================

ALTER TABLE assistant.messages ADD COLUMN client_id TEXT;
```

**为什么要文件头**：半年后回看时，SQL 本身只能说明“做了什么”，文件头才能说明“为什么做、影响谁、怎么退”。

#### 第 4 步：写 SQL

- 新增对象使用全限定名，如 `assistant.messages`、`knowledge.rag_state`，不依赖 `search_path`。
- 一个文件只做一个业务变更；同一领域的加列 + 索引可以放在一起，但不要跨领域拼盘。
- 不在文件里写 `BEGIN` / `COMMIT`；Flyway 会管理事务。
- 不在文件里写 `CREATE INDEX CONCURRENTLY`；Flyway 默认单脚本单事务，该语句会失败。
- 不用 `IF NOT EXISTS` 掩盖结构差异；只有存量库收编脚本可以例外。

#### 第 5 步：静态检查

```bash
python3 scripts/ci/check_sql.py
```

它会检查：文件命名、是否在领域目录、版本是否唯一/大于基线最大版本、文件头字段、`V1.0.0` 是否被改动、已执行脚本是否被修改、`checks/` 是否误用占位符、是否出现并发索引、sqlfluff 格式。

**为什么先静态检查**：这些问题在本地几秒就能发现，不必等到连数据库或 CI 才失败。

#### 第 6 步：在空库执行

先准备一个空的 PostgreSQL 库，并导出连接与占位符：

```bash
export FLYWAY_URL='jdbc:postgresql://127.0.0.1:5432/assistant'
export FLYWAY_USER=postgres
export FLYWAY_PASSWORD=postgres
export FLYWAY_PLACEHOLDERS_DEPLOYMENT_ID=local
export FLYWAY_PLACEHOLDERS_MILVUS_URI='http://127.0.0.1:19530'
export FLYWAY_PLACEHOLDERS_MILVUS_DATABASE=default
export FLYWAY_PLACEHOLDERS_MILVUS_PREFIX=local
```

直接用 Flyway 容器执行：

```bash
docker run --rm --network host \
  -v "$PWD/database/postgres/flyway.conf:/flyway/conf/flyway.conf:ro" \
  -v "$PWD/database/postgres/migrations:/flyway/migrations:ro" \
  -e FLYWAY_URL -e FLYWAY_USER -e FLYWAY_PASSWORD \
  -e FLYWAY_PLACEHOLDERS_DEPLOYMENT_ID \
  -e FLYWAY_PLACEHOLDERS_MILVUS_URI \
  -e FLYWAY_PLACEHOLDERS_MILVUS_DATABASE \
  -e FLYWAY_PLACEHOLDERS_MILVUS_PREFIX \
  flyway/flyway:11-alpine migrate
```

参数解释：

- `-v flyway.conf`：把本目录配置挂进容器；
- `-v migrations`：把全部版本化脚本挂进容器；
- `-e FLYWAY_*`：传入连接信息；
- `-e FLYWAY_PLACEHOLDERS_*`：传入归属登记所需的四个值，必须与 App 的 `DEPLOYMENT_ID`、`MILVUS_URI`、`MILVUS_DATABASE`、`MILVUS_COLLECTION` 一致；
- `--network host`：Linux 下让容器访问本机数据库；macOS 去掉该参数，把 URL 改成 `host.docker.internal`。

**为什么要在空库执行**：只测“在已有库上加一个字段”不够；空库能验证 `V1.0.0` 到最新版本整条链路都能从零跑通。

#### 第 7 步：验证

把上面命令最后的 `migrate` 换成 `info` 或 `validate`：

```bash
# 查看每个版本的执行状态；把 info 换成 validate 即可校验 checksum 与顺序
docker run --rm --network host \
  -v "$PWD/database/postgres/flyway.conf:/flyway/conf/flyway.conf:ro" \
  -v "$PWD/database/postgres/migrations:/flyway/migrations:ro" \
  -e FLYWAY_URL -e FLYWAY_USER -e FLYWAY_PASSWORD \
  flyway/flyway:11-alpine info
```

再跑一次结构体检：

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 \
  -f database/postgres/checks/health.sql
```

这里 `DATABASE_URL` 是 psql 使用的普通 URI（如 `postgresql://user:pass@host:5432/assistant`），不要与 JDBC 的 `FLYWAY_URL` 混用。

**看什么**：`info` 中所有版本应为 `Success`；`validate` 应输出 successfully validated；`health.sql` 应无报错。

#### 第 8 步：提交 PR

- 一个 PR 原则上只新增一个 `V__` 文件；跨领域拆分最多 2 个，版本必须连续。
- 合并前先 rebase 主分支；如果主分支已有同号或更大号，把自己的文件改成当前最大值 + 1。
- CI 会再次检查版本顺序、领域目录、文件头、基线 checksum 与格式。
- 不在 PR 中修改已执行的 `V__` 文件；修正通过下一个版本完成。

### 2.4 命名与存放

| 类型 | 规则 | 示例 |
|---|---|---|
| 版本化脚本 | `V<major>.<minor>.<patch>__<domain>_<verb>_<object>.sql` | `V1.0.1__conversation_add_message_client_id.sql` |
| 可重复脚本 | `R__<domain>_<object>.sql`，放 `repeatable/` | `R__platform_grants.sql` |
| 回调 | `(before/after)<Event>__<desc>.sql`，放 `callbacks/` | `beforeMigrate__verify_identity.sql` |

- 动词使用 `add`、`alter`、`drop`、`create`、`rename`、`index`、`backfill`、`grant`、`align`。
- 文件名保留领域前缀，便于 `flyway info` 的扁平列表阅读。
- 不在文件名中使用 `final`、`new`、`fix2` 等无意义后缀。
- 已执行的 `V__` 文件不能改名、移动或修改；修正通过下一个版本完成。

### 2.5 执行顺序

```text
beforeMigrate 回调
        │
        ▼
V1.0.0 → V1.0.1 → V1.0.2 → ...   按版本号升序
        │
        ▼
R__ 可重复脚本（按描述排序；checksum 变化才执行）
        │
        ▼
afterMigrate 回调
```

规则：

- 版本化脚本按版本号升序执行；`V1.0.9` 之后是 `V1.0.10`，不要按字符串排序。
- `R__` 脚本在版本化脚本之后执行，按描述排序；只有内容变化时才重新执行。
- `beforeMigrate` 回调先于版本化脚本，`afterMigrate` 回调最后执行。
- 合并前先 rebase 主分支；若主分支已有同号或更大号，将自己的文件改为当前最大值 + 1。
- 不使用 `flyway repair` 绕过顺序问题；`repair` 只用于修复失败的版本记录。

### 2.6 长期维护规范

#### 修改已有结构

**修改 = 新增下一个版本，不是编辑旧文件。**

例如给 `messages` 加字段：

```sql
-- V1.0.N__conversation_add_message_client_id.sql
ALTER TABLE assistant.messages ADD COLUMN client_id TEXT;
```

即使只是改一个注释、改一个空格，也不能动已执行的 `V1.0.0`；Flyway 的 checksum 会变化，`validate` 会失败。

#### 新增表、索引、回填

- 新表：放对应领域目录，建表语句只写一次；后续变更用新版本。
- 索引：小表可直接 `CREATE INDEX`；大表走维护窗口或独立运维步骤。
- 数据回填：放新版本；大批量分批执行，避免长事务。
- 业务数据：由 App/ingest 写入，不要放进版本化脚本。

#### 不能直接加列的 9 张表

以下表使用位置式 `INSERT ... VALUES`，列数变化会导致现有 App 写入失败：

`sessions`、`workflow_runs`、`tenant_message_limits`、`external_deployment`、`rag_state`、`rag_documents`、`rag_revisions`、`rag_chunks`、`rag_embedding_cache`。

加列前必须先把 App 改为显式列名。可以安全加列的表：`messages`、`global_rag_daily_limits`、`rag_events`。

#### 特殊目录

- `workflow/` 中的 `checkpoint_*` 由 `langgraph-checkpoint-postgres` 管理，不手工修改列、索引或约束；升级依赖时按 2.3 新增脚本对齐版本。
- `platform/` 只放 schema、扩展、授权、共享函数、归属登记。
- `callbacks/` 只做归属校验和结构体检，不写业务变更。
- `repeatable/` 只放幂等对象（授权、视图等），不放业务数据。

#### 禁止事项

- 不修改已执行的 `V__` 文件（包括空白、注释、路径）。
- 不在版本化脚本中写 `BEGIN` / `COMMIT`。
- 不在版本化脚本中写 `CREATE INDEX CONCURRENTLY`。
- 不用 `IF NOT EXISTS` 掩盖结构差异。
- 不引入 SQL 宏或自定义预处理器。
- 不在 `checks/` 中写 `${...}` 占位符。
