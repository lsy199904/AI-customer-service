# db-migrate 镜像构建指南

本目录包含数据库 SQL 执行镜像 `db-migrate` 的 `Dockerfile`、入口脚本 `entrypoint.sh` 与构建脚本 `build.sh`。

**镜像定位**：Flyway 运行时 + `flyway.conf` + `migrations/` SQL 资产，只做一件事——对 PostgreSQL 执行 `migrate` / `validate` / `info`。
**不包含**：`app/` 代码、Python 运行时、应用依赖。应用镜像见 [`../app/README.md`](../app/README.md)，两者**必须用同一 tag 配套构建**，不要混用。

## 前置条件

- 已安装 Docker（脚本会检查 `docker` 命令）。
- 构建上下文恒为**仓库根目录**；脚本内部自动定位，无需手动 `cd`。
- 能拉取 Flyway 基底镜像 `flyway/flyway:11.20.3-alpine`。**国内网络无法直连 Docker Hub**，按「无法访问 Docker Hub」换用镜像源或自有仓库地址。
- 仓库中存在 `database/postgres/flyway.conf` 与 `database/postgres/migrations/`（脚本会前置校验）。
- 建议存在仓库根 `.dockerignore`，否则构建上下文会明显变大（脚本给出 WARN，不阻断）。

## 快速开始

仓库根目录执行：

```bash
deploy/docker/db-migrate/build.sh
```

或在本目录执行：

```bash
./build.sh
```

默认产出：`harbor.rd.dsi/smarttitu/db-migrate:v<应用版本>-<YYYYMMDD>-<git短sha>`，
例如 `harbor.rd.dsi/smarttitu/db-migrate:v1.0.0-20261120-5f98eca`。

tag 的三段分别取自 `pyproject.toml` 的 `version`、构建当天日期、`git rev-parse --short HEAD`；同一 commit 当天重复构建会得到相同 tag。

> 国内网络执行上面两条命令前，先看「[无法访问 Docker Hub](#无法访问-docker-hub国内网络)」——默认的基底镜像地址在 `docker.io`，会直接超时。

## 常用用法

### 指定 tag 并推送

```bash
./build.sh -t v1.0.0-20261119 --push
# → harbor.rd.dsi/smarttitu/db-migrate:v1.0.0-20261119
```

### 指定完整镜像名

`-t` 只接受纯 tag；完整镜像名请用 `--image`。

```bash
./build.sh --image harbor.rd.dsi/smarttitu/db-migrate:v1.0.0-20261120 --push
```

> 把完整引用误传给 `-t` 也能工作（脚本检测到 `/` 或 `:` 会自动按 `--image` 处理），但推荐用 `--image` 明确表达意图。

### 构建当前部署环境的镜像

K8s 清单 [`40-job-db-migrate.yaml`](../../k8s/dev/40-job-db-migrate.yaml) 使用火山引擎仓库与 `smarttitu-db-migrate` 名称，与脚本默认值不同，需要显式覆盖：

```bash
REGISTRY=ctt-repository-cn-guangzhou.cr.volces.com/smarttitu-assistant \
IMAGE_NAME=smarttitu-db-migrate \
./build.sh -t v1.0.0-20261119 --push
# → ctt-repository-cn-guangzhou.cr.volces.com/smarttitu-assistant/smarttitu-db-migrate:v1.0.0-20261119
```

清单里的 tag 变了，镜像地址也要同步改，否则 Pod 会拉不到镜像。

### 无法访问 Docker Hub（国内网络）

`registry-1.docker.io` 在国内一般直连超时（实测 8 秒无响应）。本镜像只有一个外部依赖——Flyway 基底镜像，三种绕法按长期成本从低到高排列。

#### A. 用国内公共镜像源（最快）

`11.20.3-alpine` 已实测可拉取（manifest 与层均可用）：

```bash
./build.sh \
  --flyway-image docker.m.daocloud.io/flyway/flyway:11.20.3-alpine \
  -t v1.0.0-20261119 --push
```

备选源：`docker.1ms.run/flyway/flyway:11.20.3-alpine`（同样能解析该 tag）。

> 公共源是第三方代理，可能限流、改址或下线，适合临时构建；不要把它写进流水线的硬编码默认值。

#### B. 中转进自有仓库（推荐长期）

先取一次，再推进自己的镜像仓库，之后构建只认自有地址：

```bash
docker pull docker.m.daocloud.io/flyway/flyway:11.20.3-alpine

docker tag docker.m.daocloud.io/flyway/flyway:11.20.3-alpine \
           ctt-repository-cn-guangzhou.cr.volces.com/smarttitu-assistant/flyway:11.20.3-alpine
docker push ctt-repository-cn-guangzhou.cr.volces.com/smarttitu-assistant/flyway:11.20.3-alpine

./build.sh \
  --flyway-image ctt-repository-cn-guangzhou.cr.volces.com/smarttitu-assistant/flyway:11.20.3-alpine \
  -t v1.0.0-20261119 --push
```

这种写法把「能不能拉到基础镜像」变成与业务镜像同一套仓库权限，CI 与本地行为一致。

#### C. 完全离线（导入 tar）

有外网的机器上导出：

```bash
docker pull flyway/flyway:11.20.3-alpine
docker save flyway/flyway:11.20.3-alpine -o flyway-11.20.3-alpine.tar
```

构建机导入后直接构建（tar 内保留了 `flyway/flyway:11.20.3-alpine` 这个名称，正好是默认值，无需 retag）：

```bash
docker load -i flyway-11.20.3-alpine.tar
./build.sh -t v1.0.0-20261119
```

#### 注意事项

- 拉取动作发生在 **dockerd 所在主机**，不是你 shell 里的 `http_proxy`。远程 Docker、CI runner、K8s 节点要各自能访问该镜像源。
- 也可以在主机 `daemon.json` 配 `registry-mirrors`，让 `flyway/flyway:...` 这类 docker.io 引用自动走代理；但这是主机级改动，影响该机所有项目，需运维确认。
- 基底镜像固定到版本或 digest，不要用 `latest`：Flyway 版本变化会改变校验与日志行为，发布应当可复现。当前 `11.20.3-alpine` 经 DaoCloud 拉取的 digest 为 `sha256:07f65a04ac518f3bf1c00a52dab46aa9649d931510860c6ac5363d6fb75e4c1b`。

### 多平台构建

```bash
./build.sh --platform linux/amd64,linux/arm64 --push
```

多平台必须配合 `--push`：多平台产物无法 `--load` 到本地，脚本会直接拒绝这种组合。

### 只预览命令 / 禁用缓存 / 跳过自检

```bash
./build.sh -t v1.0.0 --dry-run      # 只打印 docker build 命令，不执行
./build.sh -t v1.0.0 --no-cache     # 禁用构建缓存
./build.sh -t v1.0.0 --no-verify    # 跳过构建后的镜像内资产自检
```

## 参数一览

| 选项 | 等价环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `-t, --tag` | `TAG` | `v<版本>-<YYYYMMDD>-<git短sha>` | 纯 tag；含 `/` 或 `:` 时自动识别为完整引用 |
| `-r, --registry` | `REGISTRY` | `harbor.rd.dsi/smarttitu` | 镜像仓库前缀 |
| `-n, --name` | `IMAGE_NAME` | `db-migrate` | 镜像名 |
| `--image` | `IMAGE_REF` | — | 完整镜像名，忽略 registry/name/tag |
| `--flyway-image` | `FLYWAY_IMAGE` | `flyway/flyway:11.20.3-alpine` | Flyway 基底镜像；国内须换镜像源（见上文） |
| `--platform` | `PLATFORM` | — | 目标平台；多平台须 `--push` |
| `--push` | `PUSH=1` | 关 | 构建完成后推送 |
| `--no-cache` | `NO_CACHE=1` | 关 | 禁用构建缓存 |
| `--verify` / `--no-verify` | `VERIFY=1` / `0` | 开 | 构建后列出镜像内 SQL 资产 |
| `--dry-run` | `DRY_RUN=1` | 关 | 只打印命令不执行 |
| `-h, --help` | — | — | 显示帮助 |

选项与同名环境变量等价，**选项优先**：

```bash
REGISTRY=harbor.rd.dsi/smarttitu TAG=v1.0.0-20261119 PUSH=1 ./build.sh
```

## 镜像内容

构建时 `Dockerfile` 按目录**逐项 COPY**，不用整树复制，便于一眼确认镜像里有什么：

```text
/flyway/
├── conf/flyway.conf        # database/postgres/flyway.conf
├── migrations/
│   ├── V*.sql              # 根目录版本化脚本（当前为 V1.0.0__baseline.sql）
│   ├── callbacks/          # beforeMigrate / afterMigrate
│   ├── conversation/       # 领域目录
│   ├── quota/
│   ├── knowledge/
│   ├── workflow/
│   ├── platform/
│   └── repeatable/         # R__ 可重复迁移
└── entrypoint.sh           # DATABASE_URL → FLYWAY_URL / USER / PASSWORD
```

| 项 | 值 |
|---|---|
| 基底镜像 | `flyway/flyway:11.20.3-alpine`（`--flyway-image` 可覆盖） |
| 运行用户 | UID `10001`（非 root；K8s 侧另配 `runAsGroup` / `fsGroup: 10001`） |
| 工作目录 | `/flyway` |
| 入口 | `/flyway/entrypoint.sh` |
| 默认命令 | `migrate`（Job 可通过 `args` 覆盖） |

**新增领域目录时必须同步改 `Dockerfile` 补一行 `COPY`**，否则文件不会进镜像，而 Flyway 仍会「成功」跑完——这是最容易漏的一步。`scripts/ci/check_sql.py` 会校验 `migrations/` 下的领域目录与本文件的 `COPY` 是否一一对应。

## 运行时行为

入口脚本负责把应用唯一的连接配置翻译成 Flyway 需要的三要素，迁移侧不需要再维护 `FLYWAY_URL` / `FLYWAY_USER` / `FLYWAY_PASSWORD`：

| 输入 `DATABASE_URL` | 处理 |
|---|---|
| `postgresql://user:pass@host:5432/db?sslmode=require` | 拆成 `FLYWAY_URL=jdbc:postgresql://host:5432/db?sslmode=require` + `FLYWAY_USER` / `FLYWAY_PASSWORD` |
| `postgres://...` | 同上 |
| `jdbc:postgresql://...` | 原样透传 |
| 其它前缀 / 缺少 host 或库名 | 报错退出，不会静默连错库 |

细节：

- 端口缺省 `5432`；密码按**最后一个 `@`** 切分，因此密码里含 `@` 也能正确还原。
- 只保留 query 中的 `sslmode`，其余 libpq 专有参数丢弃，避免 JDBC 不识别导致连接失败。
- 密码中的 `%XX` 会做等价解码（`#` `@` `:` `/` `?` `&` `=` `%`），因为 libpq 会解码而 Flyway 不会。
- 已显式设置 `FLYWAY_URL` 时跳过转换，便于本地调试或特殊场景覆盖。

容器默认执行 `migrate`；K8s 侧通过 `args` 覆盖为其它命令：

| 场景 | `args` | 说明 |
|---|---|---|
| 发布前迁移 | `["-connectRetries=10", "migrate"]` | `40-job-db-migrate.yaml` 使用 |
| 排查状态 | `["info"]` | 只读，不影响 schema |
| 人工校验 | `["-connectRetries=10", "validate"]` | 有 pending 版本即失败，可作为发布后复核 |

## 配置与占位符

`flyway.conf` 只放非敏感默认值，连接信息一律走环境变量。关键项：

| 配置 | 值 | 作用 |
|---|---|---|
| `flyway.locations` | `filesystem:migrations` | 递归扫描，目录只做业务分组，顺序由版本号决定 |
| `flyway.callbackLocations` | `filesystem:migrations/callbacks` | 回调与版本化脚本分开放 |
| `flyway.schemas` / `defaultSchema` | `assistant,knowledge` / `assistant` | 结构域与知识元数据域；history 表在 `assistant` |
| `flyway.validateOnMigrate` | `true` | 每次 migrate 前校验 checksum 与顺序 |
| `flyway.outOfOrder` | `false` | 禁止乱序应用，保证各环境顺序一致 |
| `flyway.ignoreMigrationPatterns` | `*:future` | 回滚到旧镜像时忽略库中的「未来」版本 |
| `flyway.cleanDisabled` | `true` | 永久禁用 `clean`，避免误删两个 schema |
| `flyway.baselineOnMigrate` | `false` | 存量库只允许人工 `baseline` |
| `flyway.lockRetryCount` | `120` | 多 Pod 竞争 advisory lock 时重试 |

迁移前还会执行 `beforeMigrate__verify_identity.sql`，比对 `external_deployment` 凭证行与四个归属占位符，不一致直接拒绝迁移（全新空库自动放行）。四个占位符由环境变量注入，缺失时 Flyway 内建防呆直接报错：

| 环境变量 | 对应占位符 | K8s 来源 |
|---|---|---|
| `FLYWAY_PLACEHOLDERS_DEPLOYMENT_ID` | `${deployment_id}` | ConfigMap `DEPLOYMENT_ID` |
| `FLYWAY_PLACEHOLDERS_MILVUS_URI` | `${milvus_uri}` | ConfigMap `MILVUS_URI` |
| `FLYWAY_PLACEHOLDERS_MILVUS_DATABASE` | `${milvus_database}` | ConfigMap `MILVUS_DATABASE` |
| `FLYWAY_PLACEHOLDERS_MILVUS_PREFIX` | `${milvus_prefix}` | ConfigMap `MILVUS_COLLECTION` |

`baseline` / `validate` / `info` 不执行迁移语句，无需提供占位符。四个值的取值约束见 [`database/postgres/README.md`](../../../database/postgres/README.md)。

## 验证构建结果

`--verify`（默认开启）会在构建后自动列出镜像内 `/flyway/migrations` 与 `callbacks/`，确认 SQL 资产确实打进去了。也可以手工核对：

```bash
IMG=harbor.rd.dsi/smarttitu/db-migrate:v1.0.0-20261120-5f98eca

# 运行用户应为 10001
docker image inspect "$IMG" --format '{{.Config.User}}'

# Flyway 版本与入口文件
docker run --rm --entrypoint flyway "$IMG" -v
docker run --rm --entrypoint sh "$IMG" -c 'ls -l /flyway/entrypoint.sh /flyway/conf/flyway.conf'

# SQL 资产清单
docker run --rm --entrypoint sh "$IMG" -c 'ls -1 /flyway/migrations && echo --- && ls -1 /flyway/migrations/callbacks'

# 确认镜像内不含应用代码（预期 no app）
docker run --rm --entrypoint sh "$IMG" -c 'test -e /srv/assistant && echo HAS_APP || echo "no app (expected)"'
```

对真实库做只读连通性检查（需要可达的数据库）：

```bash
docker run --rm -e DATABASE_URL='postgresql://user:pass@host:5432/assistant' "$IMG" info
```

## 与 app 镜像 / K8s 的配合

两个镜像职责严格分开，**用同一 tag 配套构建**，保证 SQL 与代码版本一致：

```bash
TAG=v1.0.0-20261119
deploy/docker/db-migrate/build.sh -t "$TAG" --push      # Flyway + SQL 资产
deploy/docker/app/build.sh        -t "$TAG" --push      # 纯 Python 应用镜像
```

K8s 侧对应关系：

| 清单 | 使用的镜像 | 命令 |
|---|---|---|
| [`40-job-db-migrate.yaml`](../../k8s/dev/40-job-db-migrate.yaml) | 本镜像 | `migrate` |
| [`50-job-milvus-init.yaml`](../../k8s/dev/50-job-milvus-init.yaml)、[`60-deployment.yml`](../../k8s/dev/60-deployment.yml) | assistant 镜像 | `knowledge-init.sh`（集合核对 + 入库 + 自检）/ `python -m app.server` |

本镜像是仓库里**唯一**执行 `flyway migrate` 的地方，且只以 Job 形式运行。`60-deployment.yml` 当前没有 Flyway Init 容器，Deployment 不会替你补迁移：Job 没跑成功就发版，App 会直接跑在旧 schema 上。完整发布顺序（scale 0 → 迁移 Job → 知识 Job → apply Deployment）见 [`deploy/k8s/dev/README.md`](../../k8s/dev/README.md)。

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 拉不到 `flyway/flyway:11.20.3-alpine`（`context deadline exceeded` / `i/o timeout`） | 国内无法直连 Docker Hub | `--flyway-image docker.m.daocloud.io/flyway/flyway:11.20.3-alpine`，或按「无法访问 Docker Hub」把镜像中转进自有仓库 |
| 提示缺少 `flyway.conf` / `migrations` | 构建上下文不是仓库根 | 用 `build.sh`；手工 `docker build` 时上下文写 `.` 且 `-f` 指向本目录 |
| 镜像里没有新加的领域目录 | `Dockerfile` 缺对应 `COPY` 行 | 补一行 `COPY database/postgres/migrations/<domain>/ /flyway/migrations/<domain>/` |
| `Validate failed: Detected pending migrations` | 库版本落后于镜像里的脚本 | 先跑 `40-job-db-migrate.yaml` 的 Job，成功后再滚动 Deployment |
| `Detected resolved migration not applied`（future） | 回滚到旧版本镜像 | 已由 `ignoreMigrationPatterns=*:future` 忽略；仍报错说明校验和/版本顺序另有问题 |
| `Validate failed: checksum mismatch` | 改了已发布的迁移脚本 | 已发布的 `V*.sql` 不可改；新增版本脚本，必要时人工 `repair` |
| `Unable to obtain lock` | 多个迁移同时启动 | `lockRetryCount=120` 已提供重试；仍失败则确认没有残留 Job 在跑 |
| `DATABASE_URL 必须以 ... 开头` | 连接串写成了 `host=... dbname=...` 形式 | 改用 libpq URI 或 JDBC URL |
| 推送失败 | 未登录仓库 | `docker login <registry>` 后重试 |
| 改了 SQL 但 Pod 行为没变 | 同名 tag 已存在，节点有缓存 | 每次用不同 tag；K8s 侧确认 `imagePullPolicy` 与 tag 已更新 |




./build.sh --image harbor.rd.dsi/smarttitu/db-migrate:v1.0.0-20261120 \
--flyway-image docker.m.daocloud.io/flyway/flyway:11.20.3-alpine
