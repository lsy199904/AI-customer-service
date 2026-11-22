#!/usr/bin/env bash
# deploy/compose 全栈自动化部署检查：起栈（含迁移/入库 Job）-> 验证 Job 退出码与
# 健康接口 -> 清理。等价 K8s dev 的「apply 全套清单 -> 等 Job 完成 -> 滚 Deployment
# -> curl NodePort 就绪口」发布链路。
#
# 用法（在任意目录执行均可）：
#   deploy/compose/scripts/run-compose-check.sh           # 用 .env 中的仓库镜像
#   deploy/compose/scripts/run-compose-check.sh --build   # 源码构建镜像（compose.test.yaml）
#   deploy/compose/scripts/run-compose-check.sh --keep    # 验证后保留现场供调试
#
# 前置：docker compose v2（--wait 需支持 service_completed_successfully 语义）；
#       .env 不存在时自动从 .env.example 生成（默认 dev 值）。
# 首次全量知识入库依赖外部 Embedding API，预留约 30 分钟（与 K8s Job 超时一致）。
set -euo pipefail

cd "$(dirname "$0")/.."

KEEP=0
BUILD=0
for arg in "$@"; do
    case "$arg" in
        --keep) KEEP=1 ;;
        --build) BUILD=1 ;;
        *) echo "未知参数：$arg（支持 --keep / --build）" >&2; exit 2 ;;
    esac
done

if [ ! -f .env ]; then
    cp .env.example .env
    echo "==> 已从 .env.example 生成 .env（默认 dev 值，按需修改后重跑）"
fi

COMPOSE=(docker compose --env-file .env -f compose.yaml)
if [ "$BUILD" = 1 ]; then
    COMPOSE+=(-f compose.test.yaml)
fi

cleanup() {
    local code=$?
    if [ "$code" -ne 0 ]; then
        echo "==> [FAIL] 部署验证失败，输出现场"
        "${COMPOSE[@]}" ps -a || true
        "${COMPOSE[@]}" logs --tail=120 || true
    fi
    if [ "$KEEP" = 1 ]; then
        echo "==> --keep：保留现场；调试后手动清理："
        echo "    ${COMPOSE[*]} down -v --remove-orphans"
    else
        echo "==> 清理 Compose 栈（含数据卷）"
        "${COMPOSE[@]}" down -v --remove-orphans || true
    fi
    exit "$code"
}
trap cleanup EXIT

echo "==> 1/4 启动全栈并等待（迁移/入库 Job 成功退出 -> 应用 healthy）"
up_args=(-d --wait --wait-timeout 2400)
[ "$BUILD" = 1 ] && up_args+=(--build)
"${COMPOSE[@]}" up "${up_args[@]}"

echo "==> 2/4 校验一次性 Job 退出码"
for svc in db-migrate milvus-init; do
    cid=$("${COMPOSE[@]}" ps -aq "$svc")
    if [ -z "$cid" ]; then
        echo "    $svc：容器不存在" >&2
        exit 1
    fi
    code=$(docker inspect -f '{{.State.ExitCode}}' "$cid")
    if [ "$code" != "0" ]; then
        echo "    $svc：退出码 $code != 0" >&2
        exit 1
    fi
    echo "    $svc：exit 0"
done

echo "==> 3/4 应用健康接口（NodePort 等价端口）"
port="${APP_NODE_PORT:-}"
if [ -z "$port" ] && grep -qE '^APP_NODE_PORT=' .env; then
    port=$(grep -E '^APP_NODE_PORT=' .env | tail -n 1 | cut -d= -f2- | tr -d "\"'")
fi
port=${port:-30201}
curl --fail --silent --show-error --retry 10 --retry-delay 3 --retry-connrefused \
    "http://127.0.0.1:${port}/smart-bot/health" > /dev/null
curl --fail --silent --show-error \
    "http://127.0.0.1:${port}/smart-bot/ready" > /dev/null
echo "    http://127.0.0.1:${port}/smart-bot/health 与 /ready 均 200"

echo "==> [PASS] compose 全栈部署验证通过（迁移 -> 入库 -> 应用就绪）"
