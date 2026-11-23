#!/usr/bin/env bash
# dev 全量重建：最新代码打包镜像 → tag 写回 .env → down -v 彻底摧毁 → up -d --wait 全新起栈。
# 任意目录可执行；基底镜像换源走环境变量（PYTHON_IMAGE/UV_IMAGE/APT_MIRROR/FLYWAY_IMAGE，
# build.sh 原生识别），无需改脚本。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
COMPOSE_DIR="$ROOT/deploy/compose"

# .env 不存在时先从模板生成并退出，避免带着占位密钥把栈跑起来
if [[ ! -f "$COMPOSE_DIR/.env" ]]; then
    cp "$COMPOSE_DIR/.env.example" "$COMPOSE_DIR/.env"
    echo "已从模板生成 $COMPOSE_DIR/.env，请填好 MODEL_API_KEY 等密钥后重跑本脚本" >&2
    exit 1
fi

cd "$ROOT"

# 基底镜像国内默认走 daocloud 源（docker.io / ghcr.io 直连易超时），环境变量可覆盖回官方
export PYTHON_IMAGE="${PYTHON_IMAGE:-docker.m.daocloud.io/library/python:3.12-slim-bookworm}"
export UV_IMAGE="${UV_IMAGE:-ghcr.m.daocloud.io/astral-sh/uv:0.9.5}"
export FLYWAY_IMAGE="${FLYWAY_IMAGE:-docker.m.daocloud.io/flyway/flyway:11.20.3-alpine}"

uv lock    # 确保 uv.lock 与 pyproject.toml 一致（已同步时 no-op），否则镜像内 uv sync --locked 会失败

TAG="dev-$(date +%Y%m%d)-$(git rev-parse --short HEAD)"
echo "==> 打包镜像 $TAG"
deploy/docker/app/build.sh -n smarttitu-assistant -t "$TAG"
deploy/docker/db-migrate/build.sh -t "$TAG"

cd "$COMPOSE_DIR"
# 新 tag 写回 .env（幂等：正则整行替换两个镜像引用）；
# postgres 基底是国内易超时的 docker.io 镜像，仅当仍为官方原始值时换成 daocloud 源
sed -i.bak \
    -e "s|^ASSISTANT_IMAGE=.*|ASSISTANT_IMAGE=harbor.rd.dsi/smarttitu/smarttitu-assistant:$TAG|" \
    -e "s|^DB_MIGRATE_IMAGE=.*|DB_MIGRATE_IMAGE=harbor.rd.dsi/smarttitu/db-migrate:$TAG|" \
    -e 's|^POSTGRES_IMAGE=postgres:14-bookworm$|POSTGRES_IMAGE=docker.m.daocloud.io/library/postgres:14-bookworm|' \
    .env
rm -f .env.bak

echo "==> 彻底摧毁并全新起栈（数据卷清空，迁移与知识入库全量重跑）"
docker compose --env-file .env -f compose.yaml down -v --remove-orphans
docker compose --env-file .env -f compose.yaml up -d --wait

PORT="$(grep -E '^APP_NODE_PORT=' .env | head -n1 | cut -d= -f2 || true)"
echo "==> 完成：http://<宿主机IP>:${PORT:-30201}/smart-bot/   （镜像 tag：$TAG）"
