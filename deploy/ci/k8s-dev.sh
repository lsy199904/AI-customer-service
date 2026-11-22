#!/usr/bin/env bash
# GitLab CI 对 dev（app-zone）环境的发布 / 回退 / 冒烟入口。
# 发布顺序与 deploy/k8s/dev/README.md 的手工流程一一对应：
#   停 App 释放 RWO 卷 → db-migrate Job → milvus-init Job → 删 Job 释放卷
#   → apply Deployment → rollout → /smart-bot/ready 冒烟；任一阶段失败即停，
#   Job 阶段失败恢复旧版副本，Deployment 阶段失败自动 rollout undo。
#
# 用法：k8s-dev.sh deploy | rollback | smoke
# 依赖：kubectl（KUBECONFIG 由 CI 的 file 型变量 KUBE_CONFIG_DEV 注入）、bash、sed、grep。
set -euo pipefail

NS="${K8S_NS:-app-zone}"
REGISTRY="${REGISTRY:-harbor.rd.dsi/smarttitu}"
APP_IMAGE="${APP_IMAGE:-$REGISTRY/smarttitu-assistant}"
MIGRATE_IMAGE="${MIGRATE_IMAGE:-$REGISTRY/db-migrate}"
MANIFEST_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/k8s/dev"
APP_POD_LABEL="app.kubernetes.io/name=titu-assistant,smarttitu-role=app"
MIGRATE_JOB="titu-db-migrate"
MILVUS_JOB="titu-milvus-init"
TMP_MANIFEST_DIR=""

die() {
    echo "ERROR: $*" >&2
    exit 1
}

log() {
    printf '\n==> %s\n' "$*"
}

trap '[[ -n "$TMP_MANIFEST_DIR" ]] && rm -rf "$TMP_MANIFEST_DIR"' EXIT

command -v kubectl >/dev/null 2>&1 || die "未找到 kubectl"

have_deployment() {
    kubectl -n "$NS" get deployment/titu-assistant >/dev/null 2>&1
}

scale_app() {
    local n="$1"
    if have_deployment; then
        kubectl -n "$NS" scale deployment/titu-assistant --replicas="$n"
    else
        log "集群中还没有 Deployment，跳过 scale $n"
    fi
}

wait_pods_gone() { # $1=selector $2=超时秒
    local sel="$1" limit="$2" elapsed=0 n
    while :; do
        n="$(kubectl -n "$NS" get pod -l "$sel" -o name 2>/dev/null | wc -l)"
        [[ "$n" -eq 0 ]] && return 0
        [[ "$elapsed" -ge "$limit" ]] && die "等待 Pod 退出超时：$sel（仍有 $n 个）"
        sleep 5
        elapsed=$((elapsed + 5))
    done
}

job_conditions() {
    kubectl -n "$NS" get job "$1" \
        -o jsonpath='{range .status.conditions[*]}{.type}={.status}{"\n"}{end}' 2>/dev/null || true
}

# kubectl wait --for=condition=complete 在 Job 失败时永远不为真，这里轮询两种终态
wait_job_done() { # $1=job $2=超时秒；Failed 或超时返回 1
    local job="$1" limit="$2" elapsed=0 cond
    while :; do
        cond="$(job_conditions "$job")"
        case "$cond" in
            *Complete=True*) return 0 ;;
            *Failed=True*) return 1 ;;
        esac
        [[ "$elapsed" -ge "$limit" ]] && {
            echo "等待 Job $job 超时（${limit}s）"
            return 1
        }
        sleep 10
        elapsed=$((elapsed + 10))
    done
}

job_logs() {
    kubectl -n "$NS" logs "job/$1" --all-containers=true --tail=200 2>&1 || true
}

run_job() { # $1=job 名 $2=清单文件 $3=超时秒
    local job="$1" file="$2" limit="$3"
    kubectl -n "$NS" delete job "$job" --ignore-not-found
    kubectl -n "$NS" apply -f "$file"
    if wait_job_done "$job" "$limit"; then
        job_logs "$job"
        return 0
    fi
    job_logs "$job"
    return 1
}

# 清单里的镜像 tag 是写死的；复制到临时目录后替换为本次发布的 tag，不污染工作区
prepare_manifests() { # $1=tag → 输出临时目录路径
    local tag="$1" tmp
    tmp="$(mktemp -d)"
    cp "$MANIFEST_DIR/40-job-db-migrate.yaml" \
        "$MANIFEST_DIR/50-job-milvus-init.yaml" \
        "$MANIFEST_DIR/60-deployment.yml" "$tmp/"
    sed -E -i "s#^( +image: +.*db-migrate:)[^ ]+#\1${tag}#" "$tmp/40-job-db-migrate.yaml"
    sed -E -i "s#^( +image: +.*assistant:)[^ ]+#\1${tag}#" \
        "$tmp/50-job-milvus-init.yaml" "$tmp/60-deployment.yml"
    grep -Fq "image: ${MIGRATE_IMAGE}:${tag}" "$tmp/40-job-db-migrate.yaml" ||
        { rm -rf "$tmp"; die "40 清单没有匹配到 db-migrate 镜像行"; }
    grep -Fq "image: ${APP_IMAGE}:${tag}" "$tmp/50-job-milvus-init.yaml" ||
        { rm -rf "$tmp"; die "50 清单没有匹配到 assistant 镜像行"; }
    grep -Fq "image: ${APP_IMAGE}:${tag}" "$tmp/60-deployment.yml" ||
        { rm -rf "$tmp"; die "60 清单没有匹配到 assistant 镜像行"; }
    echo "$tmp"
}

smoke() {
    local i
    for i in 1 2 3 4 5 6; do
        if kubectl -n "$NS" exec deploy/titu-assistant -- python -c '
import urllib.request
r = urllib.request.urlopen("http://127.0.0.1:8201/smart-bot/ready", timeout=10)
print(r.status, r.read().decode("utf-8", "replace")[:200])
assert r.status == 200
'; then
            log "冒烟通过"
            return 0
        fi
        echo "冒烟第 ${i}/6 次未通过，15s 后重试"
        sleep 15
    done
    return 1
}

rollback_app() {
    log "回退 Deployment 到上一版本"
    if ! kubectl -n "$NS" rollout undo deployment/titu-assistant; then
        die "rollout undo 失败（首次发布没有历史版本？），需人工介入"
    fi
    kubectl -n "$NS" rollout status deployment/titu-assistant --timeout=900s ||
        die "回退后 rollout 未就绪"
    smoke || die "回退后冒烟仍失败，需人工介入"
    log "已回到上一版本"
}

deploy() {
    [[ -n "${IMAGE_TAG:-}" ]] || die "缺少 IMAGE_TAG（由 build-images 的 dotenv artifact 注入）"
    kubectl -n "$NS" get namespace "$NS" >/dev/null ||
        die "K8s 连通性预检失败（检查 KUBE_CONFIG_DEV 与 API 地址）"
    log "本次发布镜像 tag：$IMAGE_TAG"

    TMP_MANIFEST_DIR="$(prepare_manifests "$IMAGE_TAG")"
    local tmp="$TMP_MANIFEST_DIR"

    log "1/6 停 App，释放 RWO 卷"
    scale_app 0
    wait_pods_gone "$APP_POD_LABEL" 300

    log "2/6 数据库迁移 Job（不挂卷）"
    if ! run_job "$MIGRATE_JOB" "$tmp/40-job-db-migrate.yaml" 800; then
        scale_app 1
        die "db-migrate 失败，已恢复旧版 1 副本；原因见上方日志"
    fi

    log "3/6 知识初始化 Job（同镜像、同 PVC）"
    if ! run_job "$MILVUS_JOB" "$tmp/50-job-milvus-init.yaml" 1900; then
        kubectl -n "$NS" delete job "$MILVUS_JOB" --ignore-not-found
        wait_pods_gone "job-name=$MILVUS_JOB" 300
        scale_app 1
        die "milvus-init 失败，已删 Job 释放卷并恢复旧版；原因见上方日志"
    fi

    log "4/6 删 Job，等 Pod 退出彻底释放卷"
    kubectl -n "$NS" delete job "$MILVUS_JOB" --ignore-not-found
    wait_pods_gone "job-name=$MILVUS_JOB" 300

    log "5/6 发布 Deployment"
    kubectl -n "$NS" apply -f "$tmp/60-deployment.yml"
    if ! kubectl -n "$NS" rollout status deployment/titu-assistant --timeout=900s; then
        kubectl -n "$NS" logs deploy/titu-assistant --tail=200 2>&1 || true
        rollback_app
        die "新版 rollout 失败，已自动回退到上一版本"
    fi

    log "6/6 冒烟 /smart-bot/ready"
    if ! smoke; then
        kubectl -n "$NS" logs deploy/titu-assistant --tail=200 2>&1 || true
        rollback_app
        die "新版冒烟失败，已自动回退到上一版本"
    fi

    log "发布成功：$APP_IMAGE:$IMAGE_TAG"
}

case "${1:-}" in
    deploy) deploy ;;
    rollback) rollback_app ;;
    smoke) smoke || exit 1 ;;
    *) die "用法：$0 deploy | rollback | smoke" ;;
esac
