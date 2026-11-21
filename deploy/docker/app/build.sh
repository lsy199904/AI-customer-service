#!/usr/bin/env bash
# 构建 assistant 应用镜像（deploy/docker/app/Dockerfile）。
# 构建上下文恒为仓库根目录：Dockerfile 需要 pyproject.toml / uv.lock / app / data / knowledge_sources。
# 该镜像同时用于知识入库/校验 Job，因此不区分“web 镜像”和“任务镜像”。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
DOCKERFILE="$SCRIPT_DIR/Dockerfile"

# Dockerfile 用了 RUN --mount=type=cache，必须 BuildKit：Docker 23+ 默认启用，
# 老版本（18.09-22）靠这里兜底；显式设了 DOCKER_BUILDKIT=0 则尊重用户选择
export DOCKER_BUILDKIT="${DOCKER_BUILDKIT:-1}"

REGISTRY="${REGISTRY:-harbor.rd.dsi/smarttitu}"
IMAGE_NAME="${IMAGE_NAME:-assistant}"
TAG="${TAG:-}"
IMAGE_REF="${IMAGE_REF:-}"
PYTHON_IMAGE="${PYTHON_IMAGE:-python:3.12-slim-bookworm}"
UV_IMAGE="${UV_IMAGE:-ghcr.io/astral-sh/uv:0.9.5}"
APT_MIRROR="${APT_MIRROR:-mirrors.huaweicloud.com}"
PLATFORM="${PLATFORM:-}"
PUSH="${PUSH:-0}"
NO_CACHE="${NO_CACHE:-0}"
DRY_RUN="${DRY_RUN:-0}"

usage() {
    cat <<'USAGE'
用法：deploy/docker/app/build.sh [选项]

只构建 assistant 应用镜像，Dockerfile 固定为本目录 Dockerfile，上下文固定为仓库根目录。
tag 默认取自 pyproject.toml 的 version 加当天日期。

选项：
  -t, --tag <tag>           镜像标签，默认 v<app 版本>-<YYYYMMDD>-<git短sha>；
                            若误传含 "/" 或 ":" 的完整镜像引用，会自动识别为 --image
  -r, --registry <addr>     镜像仓库前缀，默认 harbor.rd.dsi/smarttitu
  -n, --name <name>         镜像名，默认 assistant
      --image <ref>         直接指定完整镜像名，忽略 registry/name/tag
      --python-image <ref>  基础镜像，默认 python:3.12-slim-bookworm
      --uv-image <ref>      uv 工具镜像，默认 ghcr.io/astral-sh/uv:0.9.5
      --apt-mirror <host>   Debian 源主机名，默认 mirrors.huaweicloud.com
                            （实测 aliyun 在部分网络下只有 0.04MB/s，不要用默认值不动）
                            传空串则沿用基础镜像自带的官方源
      --platform <list>     目标平台，如 linux/amd64；多平台须配合 --push
      --push                构建完成后推送
      --no-cache            禁用构建缓存（依赖层也会重装）
      --dry-run             只打印命令不执行
  -h, --help                显示本帮助

环境变量与同名选项等价（选项优先）：
  REGISTRY IMAGE_NAME TAG IMAGE_REF PYTHON_IMAGE UV_IMAGE APT_MIRROR
  PLATFORM PUSH NO_CACHE DRY_RUN

示例：
  deploy/docker/app/build.sh                                  # 本地构建 v1.0.0-20261119-1b81457
  deploy/docker/app/build.sh -t v1.0.0-hotfix --push           # 指定 tag 并推送
  deploy/docker/app/build.sh --uv-image ghcr.m.daocloud.io/astral-sh/uv:0.9.5
  deploy/docker/app/build.sh --apt-mirror ""                   # 用官方 Debian 源
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
        --python-image) PYTHON_IMAGE="$2"; shift 2 ;;
        --uv-image) UV_IMAGE="$2"; shift 2 ;;
        --apt-mirror) APT_MIRROR="$2"; shift 2 ;;
        --platform) PLATFORM="$2"; shift 2 ;;
        --push) PUSH=1; shift ;;
        --no-cache) NO_CACHE=1; shift ;;
        --dry-run) DRY_RUN=1; shift ;;
        -h|--help) usage; exit 0 ;;
        *) usage; die "未知参数：$1" ;;
    esac
done

command -v docker >/dev/null 2>&1 || die "未找到 docker 命令"
[[ -f "$DOCKERFILE" ]] || die "缺少 Dockerfile：$DOCKERFILE"
[[ -f "$ROOT/pyproject.toml" && -f "$ROOT/uv.lock" ]] || die "缺少 pyproject.toml 或 uv.lock，构建上下文必须是仓库根"
[[ -f "$ROOT/.dockerignore" ]] || echo "WARN: 缺少 .dockerignore，构建上下文会明显变大" >&2
[[ "$PLATFORM" == *,* && "$PUSH" != "1" ]] && die "多平台构建无法 --load 到本地，请加 --push"

# 兼容把完整镜像引用误传给 -t 的情况：合法 Docker tag 不允许 "/" 与 ":"，
# 一旦出现即视为完整引用（等价 --image），并从引用中拆出 tag 供 label 使用。
if [[ -z "$IMAGE_REF" && "$TAG" == *[:/]* ]]; then
    IMAGE_REF="$TAG"
    TAG="${TAG##*:}"
fi

if [[ -z "$IMAGE_REF" ]]; then
    [[ -n "$TAG" ]] || TAG="v$(app_version)-$(date +%Y%m%d)-$(git_rev)"
    if [[ -n "$REGISTRY" ]]; then
        IMAGE_REF="$REGISTRY/$IMAGE_NAME:$TAG"
    else
        IMAGE_REF="$IMAGE_NAME:$TAG"
    fi
fi

# uv.lock 与 pyproject 不同步时，--locked 会在构建中途才失败，本机有 uv 就先拦下
if command -v uv >/dev/null 2>&1; then
    (cd "$ROOT" && uv lock --check) >/dev/null 2>&1 || die "uv.lock 与 pyproject.toml 不同步，请先执行 uv lock"
fi

args=(
    build
    -f "$DOCKERFILE"
    -t "$IMAGE_REF"
    --build-arg "PYTHON_IMAGE=$PYTHON_IMAGE"
    --build-arg "UV_IMAGE=$UV_IMAGE"
    --build-arg "APT_MIRROR=$APT_MIRROR"
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
  1) 拉不到 docker.io 的 python    → --python-image docker.m.daocloud.io/library/python:3.12-slim-bookworm
  2) 拉不到 ghcr.io 的 uv 镜像     → --uv-image ghcr.m.daocloud.io/astral-sh/uv:0.9.5
  3) Debian 源太慢/卡住            → --apt-mirror mirrors.ustc.edu.cn（或 mirrors.huaweicloud.com /
                                     mirrors.cloud.tencent.com）；aliyun 在部分网络仅 0.04MB/s
  4) uv.lock 与 pyproject 不同步   → 先执行 uv lock
  5) 完全离线（基础镜像本地已有）  → 直接给本地 tag，例如
       docker tag <本地已有镜像> python:3.12-slim-bookworm
     之后重跑本脚本即可，不会访问 docker.io
  注意：Dockerfile 已不再声明 # syntax frontend，构建不会再拉 docker/dockerfile 镜像。
HINT
    exit 1
fi

if [[ "$PUSH" == "1" ]]; then
    echo "==> 推送 $IMAGE_REF"
    docker push "$IMAGE_REF"
fi

size="$(docker image inspect "$IMAGE_REF" --format '{{.Size}}' 2>/dev/null || echo 0)"
echo "完成：$IMAGE_REF（$(awk -v s="$size" 'BEGIN{printf "%.0f MB", s/1048576}')）"
