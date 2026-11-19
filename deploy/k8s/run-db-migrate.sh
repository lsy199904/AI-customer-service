#!/usr/bin/env bash
# 在 App 滚动前执行一次数据库 SQL 任务，并等待完成。
# 用法：deploy/k8s/run-db-migrate.sh
# 环境变量：NAMESPACE（默认 app-zone）、TIMEOUT（默认 600 秒）、JOB_MANIFEST
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
NAMESPACE="${NAMESPACE:-app-zone}"
JOB_NAME="titu-db-migrate"
TIMEOUT="${TIMEOUT:-600}"
MANIFEST="${JOB_MANIFEST:-$ROOT/deploy/k8s/base/job-db-migrate.yaml}"

die() {
    echo "ERROR: $*" >&2
    exit 1
}

command -v kubectl >/dev/null 2>&1 || die "未找到 kubectl"
[[ -f "$MANIFEST" ]] || die "缺少 Job 清单：$MANIFEST"

echo "==> 删除旧 Job（如存在）"
kubectl -n "$NAMESPACE" delete job "$JOB_NAME" --ignore-not-found

echo "==> 创建 Job"
kubectl -n "$NAMESPACE" apply -f "$MANIFEST"

echo "==> 等待 Job 完成（最长 ${TIMEOUT}s）"
deadline=$((SECONDS + TIMEOUT))
while (( SECONDS < deadline )); do
    complete="$(kubectl -n "$NAMESPACE" get job "$JOB_NAME" \
        -o jsonpath='{range .status.conditions[?(@.type=="Complete")]}{.status}{end}' 2>/dev/null || true)"
    failed="$(kubectl -n "$NAMESPACE" get job "$JOB_NAME" \
        -o jsonpath='{range .status.conditions[?(@.type=="Failed")]}{.status}{end}' 2>/dev/null || true)"

    if [[ "$complete" == "True" ]]; then
        echo "==> Job 完成"
        kubectl -n "$NAMESPACE" logs -l "job-name=$JOB_NAME" --all-containers=true --tail=20 || true
        exit 0
    fi
    if [[ "$failed" == "True" ]]; then
        break
    fi
    sleep 5
done

echo "ERROR: Job 未在 ${TIMEOUT}s 内成功完成" >&2
kubectl -n "$NAMESPACE" describe job "$JOB_NAME" || true
kubectl -n "$NAMESPACE" logs -l "job-name=$JOB_NAME" --all-containers=true --tail=200 || true
exit 1
