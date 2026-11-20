# assistant 应用镜像构建指南

本目录包含 `assistant` 应用镜像的 `Dockerfile` 与构建脚本 `build.sh`。

**镜像定位**：纯 Python 运行镜像 —— `python:3.12-slim` 基础镜像 + uv 管理的 `.venv` + 应用代码与运行期资产。
**不包含**：Flyway、Java 运行时、`migrations/`。数据库迁移由独立的 `deploy/docker/db-migrate/` 镜像执行，两者不要混用。

## 前置条件

- 已安装 Docker（脚本会检查 `docker` 命令）。
- 构建上下文恒为**仓库根目录**；脚本内部会自动定位，无需手动 `cd`。
- 能访问 `docker.io`（`python:3.12-slim-bookworm`）、`ghcr.io`（uv 工具镜像）与 Debian 软件源；内网环境见「内网构建」。
- Dockerfile **不声明** `# syntax=docker/dockerfile:1.7`，构建过程不会额外拉取 `docker/dockerfile` frontend 镜像（Docker 23+ 内置 frontend 已支持 `RUN --mount=type=cache`）。
- 仓库中存在 `pyproject.toml`、`uv.lock`、`app/`、`data/`、`knowledge_sources/`、`database/milvus/manage.py`。
- 建议存在 `.dockerignore`，否则构建上下文会明显变大（脚本会给出警告）。

## 快速开始

在 `deploy/docker/app/` 目录下：

```bash
./build.sh
```

或在仓库根目录：

```bash
deploy/docker/app/build.sh
```

默认产出：`harbor.rd.dsi/smarttitu/assistant:v<应用版本>-<YYYYMMDD>-<git短sha>`，
例如 `harbor.rd.dsi/smarttitu/assistant:v1.0.0-20261120-1b81457`。

## 常用用法

### 指定 tag 并推送

```bash
./build.sh -t v1.0.0-20261120 --push
# → harbor.rd.dsi/smarttitu/assistant:v1.0.0-20261120
```

### 指定完整镜像名

`-t` 只接受**纯 tag**；完整镜像名请用 `--image`。

```bash
./build.sh --image harbor.rd.dsi/smarttitu/smarttitu-assistant:v1.0.0-20261120 --push
```

> 把完整引用误传给 `-t` 也能工作（脚本检测到 `/` 或 `:` 会自动按 `--image` 处理），但推荐用 `--image` 明确表达意图。

### 拆分 registry / 镜像名 / tag

```bash
./build.sh -r harbor.rd.dsi/smarttitu -n smarttitu-assistant -t v1.0.0-20261120 --push
```

### 内网构建

三个外部依赖分别对应三个参数，可单独覆盖：

| 依赖 | 参数 | 内网示例 | 在受限网络实测 |
|---|---|---|---|
| `python:3.12-slim-bookworm`（docker.io） | `--python-image` | `docker.m.daocloud.io/library/python:3.12-slim-bookworm` | — |
| `ghcr.io/astral-sh/uv:0.9.5` | `--uv-image` | `ghcr.m.daocloud.io/astral-sh/uv:0.9.5` 或 `ghcr.nju.edu.cn/astral-sh/uv:0.9.5` | 两者均可解析 |
| Debian APT 源 | `--apt-mirror` | `mirrors.huaweicloud.com`（默认） | 7.8 MB/s（ustc 7.4 / tencent 6.2 / tuna 2.3 / 官方 1.9 / **aliyun 0.04**） |

```bash
./build.sh \
  --python-image docker.m.daocloud.io/library/python:3.12-slim-bookworm \
  --uv-image ghcr.m.daocloud.io/astral-sh/uv:0.9.5 \
  --apt-mirror mirrors.huaweicloud.com
```

> APT 源的速度差异是「构建卡在 `apt-get update` 一两分钟」的唯一原因：同一条 `Get:4 … Packages [9678 kB]`，换源前后从卡死变为约 2 秒。默认值已从 `mirrors.aliyun.com` 改为 `mirrors.huaweicloud.com`，如你们内网有自建 Debian 源，直接 `--apt-mirror <内网域名>`。

**完全离线时**（本地已有等价镜像）：直接补 tag 到默认引用，脚本就不会访问任何外部仓库：

```bash
docker tag <本地已有 python 镜像> python:3.12-slim-bookworm
docker tag <本地已有 uv 镜像>     ghcr.io/astral-sh/uv:0.9.5
./build.sh --image harbor.rd.dsi/smarttitu/smarttitu-assistant:v1.0.0-20261120
```

> `docker build` 在本地镜像库已有所需镜像时不会回源查询（除非显式 `--pull`）；若仍想强制刷新，需要先删掉本地同名 tag。
>
> 构建容器访问 PyPI/Debian 源走的是 **dockerd 所在主机的网络**，而不是你 shell 里的 `http_proxy`。宿主机没配代理时，`uv sync` 与 `apt-get` 会直连——内网请把源换成可达的镜像源。

### 多平台构建

```bash
./build.sh --platform linux/amd64,linux/arm64 --push
```

多平台必须配合 `--push`：多平台产物无法 `--load` 到本地。

### 只预览命令 / 禁用缓存

```bash
./build.sh -t v1.0.0 --dry-run      # 只打印 docker build 命令，不执行
./build.sh -t v1.0.0 --no-cache     # 禁用构建缓存（依赖层会重装）
```

## 参数一览

| 选项 | 等价环境变量 | 默认值 | 说明 |
|---|---|---|---|
| `-t, --tag` | `TAG` | `v<版本>-<YYYYMMDD>-<git短sha>` | 纯 tag；含 `/` 或 `:` 时自动识别为完整引用 |
| `-r, --registry` | `REGISTRY` | `harbor.rd.dsi/smarttitu` | 镜像仓库前缀 |
| `-n, --name` | `IMAGE_NAME` | `assistant` | 镜像名 |
| `--image` | `IMAGE_REF` | — | 完整镜像名，忽略 registry/name/tag |
| `--python-image` | `PYTHON_IMAGE` | `python:3.12-slim-bookworm` | 基础镜像 |
| `--uv-image` | `UV_IMAGE` | `ghcr.io/astral-sh/uv:0.9.5` | uv 工具镜像 |
| `--apt-mirror` | `APT_MIRROR` | `mirrors.huaweicloud.com` | Debian 源主机名；空串=沿用基础镜像官方源 |
| `--platform` | `PLATFORM` | — | 目标平台；多平台须 `--push` |
| `--push` | `PUSH=1` | 关 | 构建完成后推送 |
| `--no-cache` | `NO_CACHE=1` | 关 | 禁用构建缓存 |
| `--dry-run` | `DRY_RUN=1` | 关 | 只打印命令不执行 |
| `-h, --help` | — | — | 显示帮助 |

选项与同名环境变量等价，**选项优先**：

```bash
REGISTRY=harbor.rd.dsi/smarttitu TAG=v1.0.0-20261120 PUSH=1 ./build.sh
```

## 镜像内容

```text
/srv/assistant/
├── app/                 # 应用代码（含 static）
├── data/                # 运行期数据
├── knowledge_sources/   # 知识源
├── manage.py            # 运维/入库 CLI（python manage.py …）
├── var/                 # 唯一可写目录（挂载 PVC 的位置）
└── .venv/               # Python 依赖（uv sync --no-install-project）
```

| 项 | 值 |
|---|---|
| 运行用户 | `assistant`（UID/GID `10001`，非 root） |
| 工作目录 | `/srv/assistant` |
| 监听 | `0.0.0.0:8000`（`HOST` / `PORT` 可覆盖） |
| 启动命令 | `python -m app.server` |
| 健康检查 | `HEALTHCHECK` 请求 `/health` |

`app/` 以源码树方式运行（不安装进 site-packages），因为 `app/core.py` 以 `app` 包上级目录为 BASE 解析 `app/static`、`data/`、`knowledge_sources/`、`var/`。

## 验证构建结果

```bash
IMG=harbor.rd.dsi/smarttitu/assistant:v1.0.0-20261120

# 运行用户应为 assistant
docker image inspect "$IMG" --format '{{.Config.User}}'

# 目录结构
docker run --rm --entrypoint sh "$IMG" -c 'ls -la /srv/assistant'

# 确认镜像内不含 Flyway（预期输出 no flyway）
docker run --rm --entrypoint sh "$IMG" -c 'test -e /flyway && echo HAS_FLYWAY || echo "no flyway (expected)"'

# 冒烟：确认 Python 与入口文件就位（不触发应用初始化，无需 DATABASE_URL）
docker run --rm --entrypoint sh "$IMG" -c '/srv/assistant/.venv/bin/python --version && ls -l /srv/assistant/app/server.py'
```

## 与 db-migrate 镜像配合

本镜像只负责运行应用，不执行数据库迁移。发布时两个镜像**用同一 tag 配套构建**：

```bash
TAG=v1.0.0-20261120
deploy/docker/db-migrate/build.sh -t "$TAG" --push   # Flyway + SQL 资产
deploy/docker/app/build.sh        -t "$TAG" --push   # 本镜像
```

K8s 侧对应关系：`60-deployment.yml`（App）与 `50-job-milvus-init.yaml`（Milvus 初始化 Job）使用本镜像，`40-job-db-migrate.yaml` 使用 db-migrate 镜像。详见 [`deploy/k8s/dev/README.md`](../../k8s/dev/README.md)。

## 常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| `invalid reference format` | 把完整镜像名传给了 `-t` | 改用 `--image`，或直接重跑（新版脚本会自动识别） |
| 拉不到 `docker.io` 的 python | 网络不通 | `--python-image docker.m.daocloud.io/library/python:3.12-slim-bookworm`，或把本地镜像 tag 成 `python:3.12-slim-bookworm` |
| 拉不到 `ghcr.io` 的 uv 镜像 | 网络不通 | `--uv-image ghcr.m.daocloud.io/astral-sh/uv:0.9.5` |
| `apt-get update` 卡住一两分钟 | Debian 源带宽差（aliyun 部分网络仅 0.04MB/s） | 换 `--apt-mirror mirrors.huaweicloud.com` / `mirrors.ustc.edu.cn` / 内网源 |
| `uv sync` 很慢 | 99 个依赖（含 onnxruntime、opencv-python）走 daemon 直连 PyPI | 配内网 PyPI 索引，或复用 `/root/.cache/uv` 构建缓存；同机器二次构建只付一次 |
| `uv.lock 与 pyproject.toml 不同步` | 依赖变更后未更新锁文件 | 先在仓库根执行 `uv lock` |
| 构建上下文异常大 | 缺 `.dockerignore` | 在仓库根补 `.dockerignore`，排除 `var/`、`.venv/`、`knowledge_sources/` 等非必需项 |
| 推送失败 | 未登录仓库 | `docker login harbor.rd.dsi` 后重试 |
| 改了代码但镜像没变化 | 同名 tag 已存在且节点/本地有缓存 | 每次用不同 tag；或加 `--no-cache`；K8s 侧临时改 `imagePullPolicy: Always` |
