# SmartTITU匿名智能客服

本分支`deploy-external-api-20261116`采用外部LLM、Embedding、Rerank API，以及已开通的PostgreSQL 16和Milvus 2.6服务。生产运行于Kubernetes，研发可用Docker独立验证。不部署模型、PG、Milvus、etcd或MinIO容器。

## 操作入口

完整配置、执行顺序和验收方式见[部署说明](docs/部署说明.md)。

```bash
sh scripts/production.sh init
# 填写.env：三个模型接口、PG、Milvus、公司镜像地址及Kubernetes参数。
sh scripts/production.sh build
sh scripts/cloud.sh init
# 如需自动准备业务库，填写私有.env.cloud。
sh scripts/cloud.sh prepare
sh scripts/production.sh deploy
```

已由平台准备业务库时，可跳过cloud步骤。研发服务器验证使用`scripts/dev.sh`，见部署说明。

## 交付目录

| 路径 | 用途 |
|---|---|
| `app/` | 原有问答、检索、匿名身份、日志及初始化代码 |
| `database/postgres/` | PostgreSQL 唯一 SQL 资产：Flyway 配置、版本迁移、回调、领域目录、模板与只读检查 |
| `scripts/db.sh`、`scripts/ci/check_sql.py` | 迁移脚手架、Flyway 命令封装及 SQL 命名/版本/格式门禁 |
| `deploy/docker/db-migrate/`、`deploy/k8s/dev` | 独立迁移镜像与 Kubernetes 迁移 Job，发布前先执行 |
| `deploy/k8s/dev`、`deploy/k8s/dev` | Milvus 集合初始化/核对 Job 与执行脚本，发布前先于 Deployment 执行 |
| `knowledge_sources/` | 正式Word、PDF知识源，随镜像交付 |
| `app/static/media/`、`data/media.json` | 图片及知识配图登记，随镜像交付 |
| `.env.example` | 唯一配置模板；生成的真实.env不提交Git |
| `scripts/cloud.sh`、`docs/cloud` | 云端业务库及专用账号准备 |
| `scripts/production.sh`、`docs/kubernetes` | Kubernetes初始化、部署、更新、日志及停止 |
| `scripts/dev.sh`、`deploy/compose/compose.dev.yaml` | 研发环境仅启动App的验证入口 |
| `docs/部署说明.md` | 部署及日常维护说明 |
| `var/` | 运行时生成；生产挂载PVC，保存原有日志和PDF图片 |
| `tests/` | 部署隔离及原有功能回归测试 |

## PostgreSQL 模块

生产使用平台已开通的 PostgreSQL 16，不部署数据库容器。`database/postgres/` 是 SQL 变更的唯一来源，执行入口是独立的 `db-migrate` 镜像/Job；应用启动仍保留幂等建表与检查点 `setup()`，其结构必须与基线一致。完整规范见[模块 README](database/postgres/README.md)、[SQL 规范与门禁](docs/SQL规范与门禁.md)和[K8s 发布顺序](deploy/k8s/dev/README.md)。

### SQL 资产（`database/postgres/`）

```text
database/postgres/
├── README.md                            # 版本、目录、变更流程与维护规范
├── flyway.conf                          # Flyway 配置；连接与归属占位符由环境变量注入
├── migrations/
│   ├── V1.0.0__baseline.sql             # 1.0.0 基线；已发布，不可修改
│   ├── callbacks/
│   │   ├── beforeMigrate__verify_identity.sql   # 迁移前校验部署归属凭证
│   │   └── afterMigrate__health.sql             # 迁移后只读结构体检
│   ├── repeatable/.gitkeep              # R__ 可重复脚本目录（当前为空）
│   ├── conversation/.gitkeep            # 会话与消息目录（当前为空）
│   ├── quota/.gitkeep                   # 配额目录（当前为空）
│   ├── knowledge/.gitkeep               # 知识库目录（当前为空）
│   ├── workflow/.gitkeep                # 工作流与检查点目录（当前为空）
│   └── platform/.gitkeep                # schema、扩展、授权、归属目录（当前为空）
├── templates/V__migration.sql.tmpl      # 新迁移脚本模板，不进入 Flyway 扫描
└── checks/
    ├── health.sql                       # 只读结构体检，psql/CI 调用
    └── schema_fingerprint.sql           # 结构指纹，比对 Flyway 库与应用自建库
```

### 执行链与配套文件

| 路径 | 作用 |
|---|---|
| `scripts/db.sh` | 本地入口：`new` / `check` / `info` / `migrate` / `validate` / `baseline` / `repair` |
| `scripts/ci/check_sql.py` | 校验文件命名、领域目录、版本顺序、文件头、基线 checksum、已执行脚本不可变及迁移镜像 COPY 一致性 |
| `.sqlfluff`、`.editorconfig`、`.pre-commit-config.yaml` | SQL 格式规则与提交前门禁 |
| `deploy/docker/db-migrate/Dockerfile` | 独立 Flyway 镜像，逐目录 COPY SQL 资产，不含应用代码，非 root 运行 |
| `deploy/docker/db-migrate/entrypoint.sh` | 将唯一的 `DATABASE_URL` 转换为 Flyway 的 JDBC URL/账号/密码 |
| `deploy/docker/db-migrate/build.sh` | 构建/推送镜像，并校验镜像内 SQL 资产 |
| `deploy/k8s/dev` | 发布前删除旧 Job、创建新 Job 并等待完成 |
| `deploy/k8s/dev` | 独立 `flyway migrate` Job，独立清单先执行，避免与 Deployment 并行 |
| `deploy/k8s/dev` | Init-1 `db-verify` 只跑 `flyway validate`，有 pending/未执行则 App 不启动 |
| `deploy/k8s/dev`、`deploy/k8s/dev` | Milvus 集合初始化/核对 Job 与执行脚本，先于 Deployment 执行 |
| `docs/部署说明.md` | 外部 PostgreSQL 业务库与日常部署说明 |

### 当前结构与流程

| 项 | 现状 |
|---|---|
| Schema / 表 | `assistant`、`knowledge`；17 张表（12 张业务表 + 4 张 LangGraph 检查点表 + `external_deployment`） |
| 版本 | `V1.0.0` 基线；检查点迁移 0–9；版本记录表 `assistant.flyway_schema_history` |
| 归属校验 | `deployment_id`、`milvus_uri`、`milvus_database`、`milvus_prefix` 四个占位符经环境变量注入，迁移前后回调校验 |
| 发布顺序 | 构建同 tag 镜像 → 运行迁移 Job → apply Deployment → `db-verify` validate → 知识入库 → App 启动 |

`deploy/k8s/dev/infra/postgres`、`docs/archive/PostgreSQL迁移解耦核对说明.md` 为归档材料，不属于当前执行链。

## 前端接入

```html
<script src="https://客服实际域名/smart-bot/iframe-anonymous.js"></script>
```

平台Ingress保留`/smart-bot`前缀并关闭SSE缓冲；配置`FRAME_ORIGINS`和需要的`CORS_ORIGINS`。JS自动获取匿名凭证和加载浮窗，不向前端暴露模型Key。演示页：`/smart-bot/widget/anonymous-demo`。

`.gitignore`用于保护密钥、日志、数据库导出及备份。代码、正式知识文件、图片和登记文件均在仓库中；原有问答和日志结构保持不变。
