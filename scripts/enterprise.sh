#!/bin/sh
# Explicit phases: no automatic destructive reset, downgrade, or model-service restart.
set -eu
umask 077
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
if [ "$(uname -s)" != Linux ]; then echo '请在Linux模型主机执行企业部署脚本。' >&2;exit 2;fi
ASSISTANT_UID=$(id -u);ASSISTANT_GID=$(id -g);export ASSISTANT_UID ASSISTANT_GID
if [ ! -f .env ]; then echo '请先恢复现有.env。' >&2;exit 2;fi
compose() { docker compose --project-directory "$ROOT" -f "$ROOT/compose.enterprise.yaml" "$@"; }
command=${1:-help}
case "$command" in
  configure) python3 scripts/configure_enterprise.py ;;
  policies) python3 scripts/configure_policies.py ;;
  build) compose build assistant ;;
  infrastructure) compose up -d --wait postgres etcd minio milvus ;;
  migrate)
    # Stop the old service before taking SQLite WAL-consistent backups.
    compose stop assistant
    compose run --rm --no-deps assistant python manage.py migrate-storage
    compose run --rm --no-deps assistant python manage.py sync-vectors
    compose run --rm --no-deps assistant python manage.py doctor
    ;;
  start) compose up -d --no-deps --force-recreate assistant ;;
  doctor) compose exec assistant python manage.py doctor --models ;;
  backup)
    mkdir -p backups
    output="backups/postgres-$(date +%Y%m%d-%H%M%S).dump"
    compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$output.tmp"
    mv "$output.tmp" "$output"
    echo "数据库及工作流备份：$output"
    echo 'Milvus可由该备份中的向量重新sync-vectors；请同时保管.env和knowledge_sources。'
    ;;
  restore)
    if [ "$#" -ne 2 ] || [ ! -f "$2" ]; then echo '用法：enterprise.sh restore backups/指定备份.dump' >&2;exit 2;fi
    # A clean destination is required. Never drop an existing database automatically.
    compose stop assistant
    compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --exit-on-error' < "$2"
    compose run --rm --no-deps assistant python manage.py sync-vectors
    compose run --rm --no-deps assistant python manage.py doctor
    echo '恢复完成；检查后执行 enterprise.sh start。'
    ;;
  export-sqlite)
    if [ "$#" -ne 2 ]; then echo '用法：enterprise.sh export-sqlite backups/新目录' >&2;exit 2;fi
    compose stop assistant
    compose run --rm --no-deps assistant python manage.py export-storage --output-dir "$2"
    echo '导出完成，服务保持停止；核对后按迁移文档切换，不覆盖原SQLite。'
    ;;
  exec|logs|ps|restart) shift;compose "$command" "$@" ;;
  *) echo '顺序：configure → build → infrastructure → migrate → start → doctor'
     echo '日常：enterprise.sh exec assistant python manage.py ingest'
     echo '备份：enterprise.sh backup；恢复到空库：enterprise.sh restore backups/文件.dump' ;;
esac
