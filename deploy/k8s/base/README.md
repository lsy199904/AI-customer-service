# 数据库 SQL 执行与 App 发布（K8s）

发布顺序固定为：

```text
构建同 tag 的 db-migrate / assistant 镜像
        │
        ▼
运行 db-migrate Job（Flyway migrate，幂等）
        │  失败 → 停止，不滚动 App
        ▼
apply Deployment
        │
        ▼
Init-1 db-verify（Flyway validate，只校验不执行）
        │  有 pending / 未执行 Job → App 不启动
        ▼
Init-2 knowledge-ingest（知识入库，增量幂等）
        │
        ▼
App 启动
```

SQL 侧的目录、命名、版本规范见 [`database/postgres/README.md`](../../../database/postgres/README.md)。

## 资源一览

| 资源 | 作用 | 执行时机 |
|---|---|---|
| `job-db-migrate.yaml` | 独立 Job，执行 `flyway migrate` | 每次发布前由 `run-db-migrate.sh` 创建；**不入 kustomization** |
| `deployment.yaml` | App Pod；Init-1 `db-verify` 只跑 `flyway validate`，Init-2 `knowledge-ingest` 入库 | 每次 apply / Pod 重启 |
| `job-db-baseline.yaml` | 存量手工库接入：只登记版本，不执行 SQL | 一次性，**不入 kustomization** |

`job-db-migrate.yaml` 不放进 `kustomization`，因为 Kustomize 不保证 Job 与 Deployment 的执行顺序；Job 必须由流水线/运维先单独执行并等待完成。

## 幂等如何成立

| 场景 | Job 行为 | App 行为 |
|---|---|---|
| 初次部署（空库） | `migrate` 执行 `V1.0.0` 全量建表 + 写入归属凭证行 | `db-verify` 通过；ingest 全量入库 |
| 版本升级 | 只执行新增版本；已执行版本为 no-op | `db-verify` 通过；ingest 增量入库 |
| 重复发布 / Pod 重启 | 再次 `migrate` 为 no-op（Flyway 按版本记录判断） | `db-verify` 通过；ingest 指纹无变化时秒级完成 |
| 未执行 Job 直接发 App | — | `validate` 检测到 pending 或缺少 history，Init 失败，App 不启动 |

Job 由脚本先 `delete` 再 `apply`，所以同名 Job 可以重复使用；Flyway 本身也通过 `flyway_schema_history` 保证幂等。并发保护由 Flyway 的 PostgreSQL advisory lock 提供。

## 前置条件

1. Secret `titu-assistant-secret` 含 `FLYWAY_URL`（JDBC URL，需带用户/密码或使用平台免密方式）。
2. ConfigMap `titu-assistant-config` 含 `DEPLOYMENT_ID`、`MILVUS_URI`、`MILVUS_DATABASE`、`MILVUS_COLLECTION`；它们会作为 `FLYWAY_PLACEHOLDERS_*` 注入 Job。
3. `db-migrate` 与 `assistant` 镜像使用**同一个 tag**构建并推送。
4. PVC `titu-assistant-var` 已存在（App 与 ingest 共用）。

## 构建镜像

两个镜像各占一个目录，Dockerfile 与构建脚本同放其中；构建上下文都是仓库根目录：

```text
deploy/docker/
├── app/
│   ├── Dockerfile            # 应用镜像（assistant）
│   └── build.sh
└── db-migrate/
    ├── Dockerfile            # SQL 执行镜像（Flyway + flyway.conf + migrations/）
    └── build.sh
```

```bash
# SQL 执行镜像
deploy/docker/db-migrate/build.sh -t v1.2.0

# 应用镜像：与 db-migrate 使用同一个 tag
deploy/docker/app/build.sh -t v1.2.0
```

如需推送到仓库，给两个脚本加 `--push`；`REGISTRY` / `FLYWAY_IMAGE` 可按环境覆盖。

## 发布步骤

```bash
NS=app-zone

# 1. 执行数据库 SQL Job，并等待完成
NAMESPACE=$NS deploy/k8s/run-db-migrate.sh

# 2. 再滚动 App；db-verify 会再次校验数据库版本
kubectl -n $NS apply -k deploy/k8s/base
kubectl -n $NS rollout status deployment/titu-assistant

# 3. 冒烟
curl -fsS https://实际域名/smart-bot/ready
```

`run-db-migrate.sh` 的行为：

1. `kubectl delete job titu-db-migrate --ignore-not-found`；
2. `kubectl apply -f job-db-migrate.yaml`；
3. 轮询 Job 状态，完成则打印日志并退出 0；失败或超时则打印 `describe` 与日志并退出 1。

## 失败排查

| 现象 | 查看位置 | 处理 |
|---|---|---|
| Job 失败 | `kubectl -n app-zone logs -l job-name=titu-db-migrate --all-containers=true --tail=200` | 修复 SQL/配置后重新执行；若 `flyway_schema_history` 留下 failed 行，先用同一镜像执行 `repair`，再重跑 Job |
| App 卡在 `Init:Error`，容器 `db-verify` | `kubectl -n app-zone logs deploy/titu-assistant -c db-verify` | 通常是没有先跑 Job，或镜像 tag 与 Job 不一致；先跑 Job 再重试 |
| 知识入库失败 | `kubectl -n app-zone logs deploy/titu-assistant -c knowledge-ingest` | 检查 Milvus/模型配置；不修改数据库版本 |
| `validate` 报 pending | `db-verify` 日志 | 说明 Job 未执行或镜像里的 SQL 比数据库新；先执行 Job |

**回滚**：`kubectl -n app-zone rollout undo deployment/titu-assistant`。数据库不回退；`flyway.ignoreMigrationPatterns=*:future` 允许旧 App 通过 `validate`。依赖“SQL 变更兼容 N-1”的纪律。

## 存量手工库接入（一次性）

仅用于已有结构、尚未登记 Flyway 的数据库；全新空库直接跑 `run-db-migrate.sh`，不要执行 baseline。

```bash
kubectl -n app-zone delete job titu-db-baseline --ignore-not-found
kubectl -n app-zone apply -f deploy/k8s/base/job-db-baseline.yaml
kubectl -n app-zone wait --for=condition=complete job/titu-db-baseline --timeout=600s

# 再执行正常 Job
NAMESPACE=app-zone deploy/k8s/run-db-migrate.sh
```

baseline 只写 `flyway_schema_history` 的基线行，不执行 SQL、不运行回调。执行前后各做一次 `pg_dump` 快照。

## 运维注意

- **停机窗口**：`strategy: Recreate` 下旧 Pod 先停止；Job 与 ingest 的耗时计入停机窗口。
- **多副本**：Job 在 Deployment 之外只执行一次；每个 Pod 的 `db-verify` 只读校验，可并行。`knowledge-ingest` 的多副本并发仍需单独加锁，当前按单副本设计。
- **大变更**：SQL 执行时间可能超过 10 分钟时，同步调大 `job-db-migrate.yaml` 的 `activeDeadlineSeconds` 与 `run-db-migrate.sh` 的 `TIMEOUT`。
- **不要**把 `job-db-migrate.yaml` 加进 `kustomization` 后直接 `apply -k`：Kustomize 不保证先 Job 后 Deployment；顺序由 `run-db-migrate.sh` 保证。
