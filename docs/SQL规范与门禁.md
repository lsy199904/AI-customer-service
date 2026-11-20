# PostgreSQL SQL 规范与迁移门禁

适用范围：`database/postgres/` 下的全部 SQL（迁移、回调、巡检脚本）。

目标：**可读、可 diff、可自动检查、不改变语义**。风格没有唯一标准；本文件的价值在于团队只保留一套规则，并由 `scripts/ci/check_sql.py`、`.sqlfluff` 与 pre-commit 兜底。

分工：

| 内容 | 位置 |
|---|---|
| 数据资产（迁移/回调/巡检 SQL） | `database/postgres/` |
| 迁移操作与目录说明 | `database/postgres/README.md` |
| SQL 风格与门禁（本文件） | `docs/` |
| 检查脚本 | `scripts/ci/check_sql.py` |
| 编辑器与 lint 配置 | 仓库根 `.editorconfig`、`.sqlfluff` |

## 1. 通用风格

| 维度 | 约定 |
|---|---|
| 关键字 | 大写：`SELECT`、`FROM`、`WHERE`、`CREATE TABLE`、`INSERT INTO` |
| 标识符 | 小写 `snake_case`；表名用单数或复数由 schema 统一，不在迁移里混用 |
| 类型 | 小写：`text`、`bigint`、`timestamptz`、`jsonb`、`numeric` |
| 缩进 | 4 空格，禁用 Tab |
| 行宽 | 120 字符 |
| 逗号 | 行尾逗号 |
| 换行 | UTF-8、LF、文件末尾保留换行 |
| 引号 | 标识符非必要不加双引号；保留字（`user`、`window`）必须加 |
| 注释 | 文件头写目的；行内注释解释“为什么”，不复述 SQL |

## 2. DDL

- 每列一行；类型、`NOT NULL`、`DEFAULT` 尽量对齐。
- 主键、唯一、外键、检查约束显式命名，便于后续迁移引用：
  - `pk_<table>`、`uq_<table>_<cols>`、`fk_<table>_<ref>`、`ck_<table>_<rule>`、`ix_<table>_<cols>`
- 新表优先 `BIGINT GENERATED ALWAYS AS IDENTITY`，避免 `SERIAL` 的权限与序列归属问题。
- 时间列用 `timestamptz`，不要用无时区的 `timestamp`。
- 金额用 `numeric(p,s)`，不要用 `money` 或浮点。
- 半结构化数据用 `jsonb`，不要用 `json`。
- 版本化迁移中慎用 `IF NOT EXISTS`：它会掩盖 schema 漂移；幂等初始化/巡检脚本才适合。
- 大表加索引用普通 `CREATE INDEX`（维护窗口）或独立运维步骤；`CREATE INDEX CONCURRENTLY` 不能进 Flyway 事务。

```sql
CREATE TABLE app.account (
    id          BIGINT GENERATED ALWAYS AS IDENTITY,
    name        TEXT        NOT NULL,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT pk_account PRIMARY KEY (id),
    CONSTRAINT uq_account_name UNIQUE (name)
);
```

## 3. DML 与查询

### 3.1 DML

- **始终写列名**：

```sql
INSERT INTO app.account (name, created_at)
VALUES ('acme', now());
```

- 不要写 `INSERT INTO app.account VALUES (...)`：表加列后列数不匹配，是生产事故的常见来源。
- `UPDATE` / `DELETE` 必须有 `WHERE`；需要返回结果时用 `RETURNING`。
- 批量写入用一条多行 `VALUES` 或 `COPY`，避免循环单条插入。
- 可能为 `NULL` 的比较用 `IS NULL` / `IS DISTINCT FROM`，不要用 `= NULL`。
- `NOT IN` 遇到 `NULL` 可能返回空集，优先 `NOT EXISTS`。

### 3.2 查询

- 子句各占一行：

```sql
SELECT
    a.id,
    a.name,
    count(o.id) AS order_count
FROM app.account AS a
LEFT JOIN app.orders AS o
    ON o.account_id = a.id
WHERE a.deleted_at IS NULL
GROUP BY
    a.id,
    a.name
ORDER BY
    order_count DESC
LIMIT 50;
```

- 生产查询避免 `SELECT *`，显式列名。
- 显式 `JOIN`，不要用逗号连接；`ON` 缩进一层。
- 多表查询给表起有意义的别名，列名带别名前缀。
- `ORDER BY` 涉及可空列时显式 `NULLS FIRST/LAST`，避免不同环境排序不一致。
- CTE 一个 `WITH` 一个逻辑块，块间用逗号行尾；复杂查询优先 CTE 而不是深层嵌套。

## 4. PL/pgSQL

- `DECLARE` / `BEGIN` / `END` 分层缩进，变量与类型对齐。
- 美元引号默认 `$$`；内部再嵌套时改用 `$body$` 等标签。
- `RAISE EXCEPTION` / `RAISE NOTICE` 用 `%` 占位，不拼接字符串。
- 动态 SQL 的标识符用 `format('%I', ...)`，字面量用 `%L`。
- `IF ... THEN ... ELSIF ... ELSE ... END IF;` 每层独立缩进。
- 注意 PL/pgSQL 会解析整个 `IF` 表达式：`to_regclass(...) IS NOT NULL AND EXISTS (SELECT ... FROM 表)` 在表不存在时仍会报错，必须嵌套 `IF`。

## 5. 迁移脚本

- 一个文件一个逻辑变更；按领域放入 `migrations/<domain>/`，文件名 `V<major>.<minor>.<patch>__<domain>_<verb>_<object>.sql`。
- 回调放 `migrations/callbacks/`；可重复迁移放 `migrations/repeatable/`；目录只影响可读性，执行顺序只由版本号决定。
- 文件头写：目的、领域、影响表、工单、应用版本、锁影响、回滚/正向修复方式。
- 不在迁移里写 `BEGIN` / `COMMIT`（Flyway 管理事务）。
- 新增迁移使用全限定名（`assistant.messages`），不依赖 `search_path`。
- 已应用的 `V__` 文件**永不修改**：包括改空白、改注释、重排。Flyway checksum 会失败。
- 破坏性变更拆两次发布：先加新列/新表 → 回填 → 下一个版本再删旧列。
- 纯移动（归档）必须保持文件字节一致；`scripts/ci/check_sql.py` 会校验。

## 6. PostgreSQL 特有

- 未加引号的标识符折叠为小写；`"User"` 与 `user` 是不同对象。
- 保留字作列名必须加引号；新 schema 尽量避开。
- `search_path` 不要依赖默认值；迁移中全限定名，应用连接显式设置。
- `CREATE INDEX CONCURRENTLY` 不能在事务块内执行。
- `SERIAL` 的序列权限/归属容易踩坑；新表用 `GENERATED ... AS IDENTITY`。
- 迁移账号与应用账号的属主/权限必须一致，否则应用启动时的 `CREATE TABLE IF NOT EXISTS`、`ALTER TABLE ... ADD COLUMN IF NOT EXISTS` 会因权限失败。

## 7. 工具与配置

| 工具/文件 | 位置 | 用途 |
|---|---|---|
| `.editorconfig` | 仓库根 | 编辑器缩进、换行、编码 |
| `.sqlfluff` | 仓库根 | PostgreSQL 方言、关键字大写、标识符/类型小写、4 空格、行尾逗号 |
| `.gitattributes` | 仓库根 | 统一 `*.sql` / `*.sh` / `*.conf` 为 LF |
| `.pre-commit-config.yaml` | 仓库根 | pre-commit 两个 hook：sqlfluff + 迁移检查 |
| `scripts/ci/check_sql.py` | `scripts/ci/` | 统一检查入口（见第 8 节） |
| `scripts/db.sh`（可选） | `scripts/` | SQL 脚手架与 Flyway 命令封装；本文流程不依赖它 |
| `pgFormatter` | 开发者本机（可选） | PL/pgSQL 排版辅助，人工 review |

说明：

- 当前没有 `.sqlfluffignore`。`check_sql.py` 只把**非基线 `V__`** 与 `checks/schema_fingerprint.sql` 交给 sqlfluff；PL/pgSQL 回调/巡检不参与。
- 如果直接运行 `sqlfluff lint .`，会扫到基线与 PL/pgSQL 文件，产生误报；请用 `python3 scripts/ci/check_sql.py`（需要时也可用 `scripts/db.sh check`）。
- `V1.0.0__baseline.sql` 是唯一允许“看起来没格式化”的 SQL：必须按字节保持不变，否则 Flyway checksum 会失败。

## 8. 门禁检查项

```bash
python3 scripts/ci/check_sql.py
# 如仓库提供 db.sh，也可用 scripts/db.sh check
```

退出码：`0` 通过（可能有警告），`1` 存在错误。

| # | 检查 | 失败条件 |
|---|---|---|
| 1 | 文件命名 | `migrations/**/*.sql` 不符合 `V<semver>__desc.sql`、`R__desc.sql`、`callbacks/(before/after)<Event>__desc.sql` |
| 2 | 领域目录 | 新增 `V__` 不在 `migrations/<domain>/` 下（domain 为 conversation、quota、knowledge、workflow、platform；基线除外） |
| 3 | 版本唯一 | 两个 `V` 文件使用相同 `major.minor.patch` |
| 4 | 版本顺序 | 新增 `V__` 的版本不大于 `BASE_REF` 分支的最大版本 |
| 5 | 文件头 | 新增 `V__` 缺少 `目的：`、`领域：`、`影响表：`、`回滚/修复：` |
| 6 | 基线不可变 | `V1.0.0__baseline.sql` 的 sha256 与 `database/postgres/README.md` 记录不一致 |
| 7 | 已发布迁移不可变 | 相对 `BASE_REF`，已存在的 `V*.sql` 被修改/删除；纯移动必须能在 `database/archive` 找到同内容副本 |
| 8 | 占位符 | `checks/*.sql` 中出现 `${...}`（易被 Flyway 误替换） |
| 9 | 并发索引 | `migrations/**/V*.sql` 中出现 `CREATE INDEX CONCURRENTLY`（不能进 Flyway 事务） |
| 10 | 格式 | sqlfluff 未通过（检查非基线 `V__` 与 `checks/schema_fingerprint.sql`） |

### 环境变量

| 变量 | 默认 | 说明 |
|---|---|---|
| `BASE_REF` | `origin/main` → `origin/master` → `HEAD` | 迁移不可变性与版本顺序的比较基线；CI 中建议显式设置为目标分支 |
| `SQLFLUFF_BIN` | 从 `PATH` 查找 | sqlfluff 可执行文件路径 |
| `REQUIRE_SQLFLUFF` | `0` | 设为 `1` 时，找不到 sqlfluff 直接失败（CI 推荐） |
| `CI` | — | 设为 `true` 时等价于 `REQUIRE_SQLFLUFF=1` |

## 9. PL/pgSQL 为什么不交给 sqlfluff

`migrations/callbacks/beforeMigrate__verify_identity.sql`、`migrations/callbacks/afterMigrate__health.sql`、`checks/health.sql` 使用 `DO $$ ... $$` 块。

sqlfluff 对 PL/pgSQL 的解析并不稳定，强行 lint 容易产生误报，甚至诱导为了过 lint 而改坏语义。

这三类文件采用：

- 人工评审 + 统一的 4 空格/关键字大写风格；
- 如团队已安装 [pgFormatter](https://github.com/darold/pgFormatter)，可用 `pg_format` 处理后再 review；
- CI 只做语法/结构验证时，可用临时 PostgreSQL 容器执行 `psql -f`（见 `database/postgres/README.md` 的“常见维护任务”）。

## 10. CI 接入

### GitLab CI

```yaml
sql-check:
  image: python:3.12-slim
  variables:
    REQUIRE_SQLFLUFF: "1"
    BASE_REF: "origin/$CI_DEFAULT_BRANCH"
  before_script:
    - pip install --no-cache-dir sqlfluff
  script:
    - python scripts/ci/check_sql.py
```

### GitHub Actions

```yaml
- uses: actions/checkout@v4
  with:
    fetch-depth: 0          # 需要 merge-base

- run: pip install sqlfluff
- run: python scripts/ci/check_sql.py
  env:
    REQUIRE_SQLFLUFF: "1"
    BASE_REF: origin/${{ github.base_ref }}
```

> 当前仓库没有 `.gitlab-ci.yml` 或 `.github/workflows/`。确定平台后再把上面的片段落到对应文件；不要在未知平台的情况下同时添加两套流水线。

### pre-commit

配置已放在仓库根，无需复制样例：

```bash
python3 -m pip install pre-commit sqlfluff
pre-commit install
```

两个 hook：

1. `sqlfluff-lint`：对本次变更的 `V*.sql` 与 `schema_fingerprint.sql` 执行 lint，排除 `V1.0.0__baseline.sql`；
2. `postgres-sql-checks`：运行 `scripts/ci/check_sql.py`，覆盖命名、领域目录、版本顺序、文件头、基线 checksum、迁移不可变性等。

`sqlfluff` 通过 `language: system` 调用，版本由开发者/CI 环境固定；建议在 CI 镜像里锁定 `sqlfluff==3.x.y`。

## 11. Review 清单

- [ ] 关键字/标识符大小写一致
- [ ] 每列一行；约束显式命名
- [ ] DML 写了列名；`UPDATE`/`DELETE` 有 `WHERE`
- [ ] 查询无 `SELECT *`；JOIN 显式
- [ ] 迁移放在正确领域目录；文件名/版本符合规则
- [ ] 迁移使用全限定名；无 `BEGIN`/`COMMIT`
- [ ] 未修改已应用的 `V__` 文件
- [ ] 未在迁移中使用 `CREATE INDEX CONCURRENTLY`
- [ ] 已运行 `python3 scripts/ci/check_sql.py`
- [ ] 需要时已运行数据库侧 `checks/health.sql`

## 12. 例外

`migrations/V1.0.0__baseline.sql` 是唯一不参与重排的 SQL：它是已版本化迁移，任何空白/注释变化都会改变 Flyway checksum。sha256 记录在 `database/postgres/README.md`，由 `scripts/ci/check_sql.py` 校验。
