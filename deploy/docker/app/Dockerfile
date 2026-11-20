# 刻意不写 `# syntax=docker/dockerfile:1.7`：该指令会让 BuildKit 先去 docker.io
# 拉 dockerfile frontend 镜像，内网/离线环境直接超时构建失败。
# Docker 23+ 内置 frontend 已支持本文件用到的 RUN --mount=type=cache，无需外部 frontend。
# 应用镜像（assistant）：uv.lock 驱动的两阶段构建。
# 构建上下文必须是仓库根目录，例如：
#   deploy/docker/app/build.sh
# 本镜像同时被知识入库/校验 Job 复用（同源镜像），因此保留 knowledge_sources/ 与 manage.py。
# 数据库迁移（Flyway）不打包进本镜像：由独立的 db-migrate 镜像执行，见 deploy/docker/db-migrate/。

# ==========================================
# Stage 1: Builder
# ==========================================
# 基础镜像与 .python-version / pyproject.requires-python 对齐（3.12）；内网可换 Harbor 地址
ARG PYTHON_IMAGE=python:3.12-slim-bookworm
# UV 使用固定版本，生产环境不要使用 latest；
# 内网访问不了 ghcr.io 时覆盖为镜像或 Harbor，例如 ghcr.m.daocloud.io/astral-sh/uv:0.9.5
ARG UV_IMAGE=ghcr.io/astral-sh/uv:0.9.5

FROM ${UV_IMAGE} AS uv

FROM ${PYTHON_IMAGE} AS builder

COPY --from=uv /uv /uvx /bin/

WORKDIR /srv/assistant

# UV 配置
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/srv/assistant/.venv \
    UV_PYTHON_DOWNLOADS=never

# 先复制依赖定义文件，充分利用 Docker 缓存
COPY pyproject.toml uv.lock ./

# 只安装生产依赖，不安装项目本身：
# app 以源码树方式运行（app/core.py: BASE = app 包的上级目录），
# 一旦把 app 装进 site-packages，BASE 会指向 .venv/lib/python3.12/site-packages，
# app/static、data/、knowledge_sources/、var/ 全部解析失败。
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --locked --no-dev --no-install-project

# 再复制应用代码与运行期资产（越少变动的越靠前，最大化缓存命中）
COPY app ./app
COPY data ./data
COPY knowledge_sources ./knowledge_sources
# 运维/入库 CLI（python manage.py …）：必须与 app 同处 BASE 下才能 import app.core
COPY database/milvus/manage.py ./manage.py
# Milvus 建集合 SDK 脚本与 Job 封装同放 database/milvus/，镜像内路径与仓库一致
COPY database/milvus/02_milvus.py ./database/milvus/02_milvus.py
COPY database/milvus/knowledge-init.sh ./database/milvus/knowledge-init.sh


# ==========================================
# Stage 2: Runtime
# ==========================================
FROM ${PYTHON_IMAGE} AS runtime

WORKDIR /srv/assistant

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONPATH=/srv/assistant \
    PATH="/srv/assistant/.venv/bin:$PATH" \
    HOST=0.0.0.0 \
    PORT=8000

# 运行期系统库：opencv-python 需要 libgl1 + libglib2.0-0，onnxruntime 需要 libgomp1。
# APT_MIRROR 只填主机名（如 mirrors.huaweicloud.com）；留空沿用基础镜像自带的官方源。
# 同时兼容 deb822（Debian 12+ 的 debian.sources）与旧式 sources.list 两种格式：
# 只替换仓库主机名，/debian 与 /debian-security 路径保持不变。
ARG APT_MIRROR=
RUN set -eux; \
    if [ -n "$APT_MIRROR" ]; then \
        for f in /etc/apt/sources.list.d/debian.sources /etc/apt/sources.list; do \
            [ -f "$f" ] || continue; \
            sed -i -E "s#https?://deb\.debian\.org#http://${APT_MIRROR}#g" "$f"; \
        done; \
    fi; \
    apt-get -o Acquire::Retries=3 -o Acquire::Languages=none update; \
    apt-get install -y --no-install-recommends \
        libgl1 libglib2.0-0 libgomp1; \
    rm -rf /var/lib/apt/lists/*

# 创建非 Root 用户；UID/GID 固定，便于与 PVC、securityContext 对齐
RUN groupadd --system --gid 10001 assistant && \
    useradd --system --uid 10001 --gid assistant --create-home assistant

# 仅复制虚拟环境和运行期文件
COPY --from=builder --chown=assistant:assistant /srv/assistant/.venv /srv/assistant/.venv
COPY --from=builder --chown=assistant:assistant /srv/assistant/app /srv/assistant/app
COPY --from=builder --chown=assistant:assistant /srv/assistant/data /srv/assistant/data
COPY --from=builder --chown=assistant:assistant /srv/assistant/knowledge_sources /srv/assistant/knowledge_sources
COPY --from=builder --chown=assistant:assistant /srv/assistant/manage.py /srv/assistant/manage.py
COPY --from=builder --chown=assistant:assistant /srv/assistant/database/milvus/02_milvus.py /srv/assistant/database/milvus/02_milvus.py
COPY --from=builder --chmod=0755 --chown=assistant:assistant /srv/assistant/database/milvus/knowledge-init.sh /srv/assistant/database/milvus/knowledge-init.sh

# 唯一可写目录：SQLite(DATABASE_PATH)、RAG 索引、日志、PDF 媒体都落在 /srv/assistant/var 下
RUN install -d -o assistant -g assistant -m 0750 /srv/assistant/var

USER assistant

EXPOSE 8000

# 存活探针用 /health（带不带 /smart-bot 前缀都通）；
# 「知识是否入库」的 /ready 判定交给 compose/k8s 的就绪探针
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:'+os.environ.get('PORT','8000')+'/health',timeout=4).read()"

# 入口沿用现有行为：app.server 自带 HOST/PORT/APP_WORKERS 解析与 worker 上限校验，
# 以及与线上一致的 limit_concurrency / graceful shutdown 参数。
# 等价裸 uvicorn 写法：uvicorn app.server:create_app --factory --host 0.0.0.0 --port 8000
CMD ["python", "-m", "app.server"]
