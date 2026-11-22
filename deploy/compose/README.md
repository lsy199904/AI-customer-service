# deploy/compose —— deploy/k8s/dev 的 Docker Compose 等价部署

单机自包含的 `docker compose` 栈：一次 `up` 完成「起依赖 → 跑迁移 → 知识入库 →
起应用」的完整发布链路，执行顺序与 `deploy/k8s/dev` 严格一致。用于本地/单机
环境的部署验证与联调；集群部署仍以 `deploy/k8s/` 为准。

## 文件清单

| 文件 | 作用 |
| --- | --- |
| `compose.yaml` | 全栈编排：postgres、etcd、minio、milvus、db-migrate、milvus-init、assistant |
| `.env.example` | 配置模板 = K8s ConfigMap + Secret + 编排参数的合并等价物（入库） |
| `.env` | 实际配置（`cp .env.example .env` 生成；已被 .gitignore 忽略） |
| `scripts/run-compose-check.sh` | 自动化部署检查：起栈 → 验证 Job 与健康接口 → 清理 |

## 与 k8s/dev 的资源映射

| k8s/dev | compose | 说明 |
| --- | --- | --- |
| `00-namespace.yml` | 顶层 `name: titu-assistant` | 项目名等价命名空间，容器/卷/网络自动隔离 |
| `10-configmap.yml` + `20-secret.yml` | `.env`（`env_file` 注入） | 键名一一对应；`MILVUS_URI` 改指栈内服务 |
| `30-pvc.yml`（titu-assistant-var） | 卷 `var` → `/srv/assistant/var` | 容量随宿主机磁盘 |
| `infra/postgres/02-postgres-14.yaml` | `postgres`（14-bookworm 单实例） | CNPG 3 副本 → 单实例 |
| `infra/milvus/milvus-test-minimal.yaml` | `milvus`(standalone) + `etcd` + `minio` | operator cluster → standalone；消息流 rocksmq，对应用透明 |
| `40-job-db-migrate.yaml` | `db-migrate`（`restart: "no"`） | 同一 db-migrate 镜像与 args；等 postgres healthy 后执行 |
| `50-job-milvus-init.yaml` | `milvus-init`（`restart: "no"`） | 同一 app 镜像与 knowledge-init.sh；等 milvus healthy 后执行 |
| `60-deployment.yml` | `assistant` | `depends_on` 两个 Job `service_completed_successfully`；`stop_grace_period: 190s` |
| `70-service.yml`（NodePort 30201） | 端口映射 `${APP_NODE_PORT:-30201}:8201` | `http://<宿主机IP>:30201/smart-bot/` |

发布顺序的还原方式：

- K8s「Job 成功退出后才滚动 Deployment」→ `depends_on.condition: service_completed_successfully`；
- K8s「依赖服务就绪后 Job 才跑」→ `depends_on.condition: service_healthy`；
- K8s 就绪门禁 `/smart-bot/ready` → `assistant` 的 healthcheck（`up --wait` 以
  healthy 为放行条件）。

## 快速开始

```bash
# 一键验证（默认用 .env 里的仓库镜像；.env 缺失时自动从模板生成）
deploy/compose/scripts/run-compose-check.sh

# 验证通过后保留现场手动体验，之后清理
deploy/compose/scripts/run-compose-check.sh --keep
docker compose --env-file .env -f compose.yaml down -v
```

本地构建镜像走 `deploy/docker/{app,db-migrate}/build.sh`，完成后把产物 tag 更新到
`.env` 的 `ASSISTANT_IMAGE` / `DB_MIGRATE_IMAGE`。

手动操作：

```bash
cd deploy/compose
cp .env.example .env          # 首次；修改 MODEL_API_KEY 等密钥后生效
docker compose --env-file .env -f compose.yaml up -d --wait

# 只重启应用（不重跑迁移/入库）
docker compose --env-file .env -f compose.yaml restart assistant

# 改配置后重建应用
docker compose --env-file .env -f compose.yaml up -d assistant

# 主动重跑初始化 Job（两者均幂等：迁移 no-op、ingest 指纹未变时 no-op）
docker compose --env-file .env -f compose.yaml up -d --force-recreate db-migrate
docker compose --env-file .env -f compose.yaml up -d --force-recreate milvus-init

# 日志与排障
docker compose --env-file .env -f compose.yaml logs -f assistant
```

访问入口：`http://<宿主机IP>:30201/smart-bot/`（与 K8s NodePort 端口一致）。
镜像版本切换：改 `.env` 的 `ASSISTANT_IMAGE` / `DB_MIGRATE_IMAGE`（同一 tag 配套）
后 `up -d`。

## 与 K8s 的已知差异

1. **PostgreSQL**：CNPG 3 副本高可用 → 单实例；`.env` 的 `POSTGRES_USER` 即容器
   超级用户（CNPG 由 managed roles 精细授权），dev 等价、权限更宽。
2. **Milvus**：operator cluster（woodpecker 消息流）→ standalone（etcd + minio +
   内置 rocksmq）。应用走 gRPC API，无感知；性能与容量不与集群对等。
3. **Job 语义**：无 `backoffLimit` / `activeDeadlineSeconds`，失败不自动重试
   （`restart: "no"`），重跑用 `--force-recreate`；首次全量 ingest 的 ~30 分钟
   预算体现在 `run-compose-check.sh` 的 `--wait-timeout 2400`。
4. **RWO 卷约束消失**：本地卷可并行挂载，发布无需「先停 App 再跑 Job」；
   compose 的 `depends_on` 已保证 Job 先完成。
5. **滚动更新/回退**：无 Recreate/rollout undo 语义，重建即换版；回退 =
   `.env` 改回旧镜像 tag 后 `up -d`。
6. **探针**：startupProbe/readinessProbe/livenessProbe → 单个 healthcheck
   （选 `/smart-bot/ready`，与就绪门禁同语义）；K8s 首启 10 分钟容忍对应
   `start_period: 60s` + `retries: 20`（知识已由 milvus-init 先入库，通常够用）。
7. **资源限制**：未设置 CPU/内存限额（K8s 有 requests/limits），需要时在服务上
   加 `deploy.resources.limits`。
8. **密钥明文**：Secret 值明文存于 `.env`（不入库）；K8s 是 Secret 对象。
   `.env.example` 里的 dev 密钥与 `k8s/dev/20-secret.yml` 同源，生产必须轮换。
9. **Cookie**：`ANONYMOUS_COOKIE_SECURE` 模板默认 `false`（compose 走 HTTP）；
   K8s dev 因走 HTTPS Ingress 为 `true`。

## 前置条件

- Docker 20.10+ 与 Docker Compose v2（`--wait` 需支持
  `service_completed_successfully`，建议 v2.22+）。
- 宿主机可拉取 `.env` 中引用的镜像（内网 Harbor 或已 `docker load` 的本地镜像）。
- 外部 API 可达：SiliconFlow 的 LLM / Embedding / Rerank（首次入库必用 Embedding）。
- 端口未被占用：`30201`（应用）；postgres/milvus 默认不发布端口，调试时再放开。
