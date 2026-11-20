#!/usr/bin/env bash
# 构建数据库 SQL 执行镜像（db-migrate）：只包含 Flyway + flyway.conf + migrations/。
# 构建上下文恒为仓库根目录：Dockerfile 需要 database/postgres/{flyway.conf,migrations}。
# 与应用镜像使用同一个 TAG，保证 SQL 与 App 版本一致。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
DOCKERFILE="$SCRIPT_DIR/Dockerfile"

REGISTRY="${REGISTRY:-harbor.rd.dsi/smarttitu}"
IMAGE_NAME="${IMAGE_NAME:-db-migrate}"
TAG="${TAG:-}"
IMAGE_REF="${IMAGE_REF:-}"
FLYWAY_IMAGE="${FLYWAY_IMAGE:-flyway/flyway:11.20.3-alpine}"
PLATFORM="${PLATFORM:-}"
PUSH="${PUSH:-0}"
NO_CACHE="${NO_CACHE:-0}"
DRY_RUN="${DRY_RUN:-0}"
VERIFY="${VERIFY:-1}"

usage() {
    cat <<'USAGE'
用法：deploy/docker/db-migrate/build.sh [选项]

只构建 db-migrate 镜像，Dockerfile 固定为本目录 Dockerfile，上下文固定为仓库根目录。
tag 默认取自 pyproject.toml 的 version、当天日期与 git 短 sha，保证每次构建唯一，且与应用镜像保持一致。

选项：
  -t, --tag <tag>           镜像标签，默认 v<app 版本>-<YYYYMMDD>-<git短sha>
  -r, --registry <addr>     镜像仓库前缀，默认 harbor.rd.dsi/smarttitu
  -n, --name <name>         镜像名，默认 db-migrate
      --image <ref>         直接指定完整镜像名，忽略 registry/name/tag
      --flyway-image <ref>  Flyway 基底镜像，默认 flyway/flyway:11.20.3-alpine
      --platform <list>     目标平台，如 linux/amd64；多平台须配合 --push
      --push                构建完成后推送
      --no-cache            禁用构建缓存
      --verify              构建后列出镜像内 SQL 资产（默认开启）
      --no-verify           跳过构建后自检
      --dry-run             只打印命令不执行
  -h, --help                显示本帮助

环境变量与同名选项等价（选项优先）：
  REGISTRY IMAGE_NAME TAG IMAGE_REF FLYWAY_IMAGE PLATFORM PUSH NO_CACHE DRY_RUN VERIFY

示例：
  deploy/docker/db-migrate/build.sh                            # 本地构建 v1.2.0-20261119-1b81457
  deploy/docker/db-migrate/build.sh -t v1.2.0 --push           # 指定 tag 并推送
  deploy/docker/db-migrate/build.sh \
    --flyway-image registry.example.com/flyway/flyway:11.20.3-alpine
USAGE
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

app_version() {
    local ver
    ver="$(sed -n 's/^version = "\([^"]*\)".*/\1/p' "$ROOT/pyproject.toml" 2>/dev/null | head -n 1)"
    echo "${ver:-0.0.0}"
}

git_rev() {
    git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo nogit
}

while [[ $# -gt 0 ]]; do
    case "$1" in
        -t|--tag) TAG="$2"; shift 2 ;;
        -r|--registry) REGISTRY="$2"; shift 2 ;;
        -n|--name) IMAGE_NAME="$2"; shift 2 ;;
        --image) IMAGE_REF="$2"; shift 2 ;;
        --flyway-image) FLYWAY_IMAGE="$2"; shift 2 ;;
        --platform) PLATFORM="$2"; shift 2 ;;
        --push) PUSH=1; shift ;;
        --no-cache) NO_CACHE=1; shift ;;
        --verify) VERIFY=1; shift ;;
        --no-verify) VERIFY=0; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage; die "未知参数：$1" ;;
    esac
done

command -v docker >/dev/null 2>&1 || die "未找到 docker 命令"
[[ -f "$DOCKERFILE" ]] || die "缺少 Dockerfile：$DOCKERFILE"
[[ -f "$ROOT/database/postgres/flyway.conf" ]] || die "缺少 database/postgres/flyway.conf，构建上下文必须是仓库根"
[[ -d "$ROOT/database/postgres/migrations" ]] || die "缺少 database/postgres/migrations，构建上下文必须是仓库根"
[[ -f "$ROOT/.dockerignore" ]] || echo "WARN: 缺少 .dockerignore，构建上下文会明显变大" >&2
[[ "$PLATFORM" == *,* && "$PUSH" != "1" ]] && die "多平台构建无法 --load 到本地，请加 --push"

if [[ -z "$IMAGE_REF" ]]; then
    [[ -n "$TAG" ]] || TAG="v$(app_version)-$(date +%Y%m%d)-$(git_rev)"
    if [[ -n "$REGISTRY" ]]; then
        IMAGE_REF="$REGISTRY/$IMAGE_NAME:$TAG"
    else
        IMAGE_REF="$IMAGE_NAME:$TAG"
    fi
fi

args=(
    build
    -f "$DOCKERFILE"
    -t "$IMAGE_REF"
    --build-arg "FLYWAY_IMAGE=$FLYWAY_IMAGE"
    --label "org.opencontainers.image.title=$IMAGE_NAME"
    --label "org.opencontainers.image.version=${TAG:-latest}"
    --label "org.opencontainers.image.revision=$(git -C "$ROOT" rev-parse --short HEAD 2>/dev/null || echo unknown)"
    --label "org.opencontainers.image.created=$(date -u +%Y-%m-%dT%H:%M:%SZ)"
)
[[ -n "$PLATFORM" ]] && args+=(--platform "$PLATFORM")
[[ "$NO_CACHE" == "1" ]] && args+=(--no-cache)
args+=("$ROOT")

if [[ "$DRY_RUN" == "1" ]]; then
    printf 'docker'; printf ' %q' "${args[@]}"; printf '\n'
    [[ "$PUSH" == "1" ]] && echo "docker push $IMAGE_REF"
    exit 0
fi

echo "==> 上下文 $ROOT"
echo "==> 目标   $IMAGE_REF"
if ! docker "${args[@]}"; then
    cat >&2 <<'HINT'

构建失败。常见原因与处理：
  1) 拉不到 flyway 镜像 → --flyway-image <内网镜像地址>，需固定 tag 或 digest
  2) 上下文缺 SQL 资产   → 确认 database/postgres/{flyway.conf,migrations} 存在
  3) 内网无法访问 docker.io → 先 docker pull 到本地，再用 --flyway-image 指定本地 tag
HINT
    exit 1
fi

if [[ "$PUSH" == "1" ]]; then
    echo "==> 推送 $IMAGE_REF"
    docker push "$IMAGE_REF"
fi

if [[ "$VERIFY" == "1" ]]; then
    echo "==> 校验镜像内 SQL 资产"
    if ! docker run --rm --entrypoint sh "$IMAGE_REF" -c '
        set -e
        test -f /flyway/conf/flyway.conf
        ls /flyway/migrations/V*.sql >/dev/null 2>&1
        echo "  配置: /flyway/conf/flyway.conf"
        echo "  迁移根目录:"
        ls -1 /flyway/migrations | sed "s/^/    /"
        echo "  回调:"
        ls -1 /flyway/migrations/callbacks 2>/dev/null | sed "s/^/    /" || echo "    （无）"
    '; then
        die "镜像内 SQL 资产校验失败：确认构建上下文是仓库根，且 database/postgres 未被 .dockerignore 排除"
    fi
fi

size="$(docker image inspect "$IMAGE_REF" --format '{{.Size}}' 2>/dev/null || echo 0)"
echo "完成：$IMAGE_REF（$(awk -v s="$size" 'BEGIN{printf "%.0f MB", s/1048576}')）"
