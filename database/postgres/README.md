# PostgreSQL 迁移（Flyway）

本目录是 PostgreSQL 结构与初始数据的唯一权威来源；原手工建表流程（`scripts/postgres/`，已冻结归档）由 Flyway 取代。完整规则与发布门禁见[工程化方案](../../docs/工程化方案.md) §6。

## 目录结构

| 路径 | 用途 |
|---|---|
| `flyway.conf` | 非敏感默认配置；连接信息只经环境变量注入 |
| `migrations/V1.0.0__baseline.sql` | 基线迁移：全新环境一次建库 + 初始数据 |
| `migrations/V<应用版本>__<描述>.sql` | 后续增量；版本号 = 引入该变更的应用版本 |

## 硬性纪律

1. 已应用的迁移文件**永不修改**（checksum 校验会 fail）；修 SQL = 新增迁移文件。
2. 新增迁移一律使用全限定表名（`assistant.messages`），不依赖 search_path。
3. `assistant.external_deployment`（部署归属登记表）不进迁移：由应用 claim 步骤创建并写入。
4. 禁止 `baselineOnMigrate=true`；存量环境接入先执行一次 `flyway baseline`（`baselineVersion=1.0.0` 已在 `flyway.conf` 预置），全新环境直接 `migrate`。

## 本地/研发执行

`scripts/db.sh` 建成前，可直接用官方镜像（连接信息经环境变量）：

```bash
docker run --rm --network host \
  -v "$PWD/database/postgres/flyway.conf:/flyway/conf/flyway.conf" \
  -v "$PWD/database/postgres/migrations:/flyway/migrations" \
  -e FLYWAY_URL -e FLYWAY_USER -e FLYWAY_PASSWORD \
  flyway/flyway:11.x migrate    # 或 validate / info / baseline
```

K8s 发布门禁 Job（claim → flyway migrate → ingest → doctor）见 `deploy/k8s`，由 CI 按序等待执行。
