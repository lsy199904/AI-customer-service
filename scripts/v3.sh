#!/bin/sh
# Standalone anonymous release. Never deletes volumes or resets model services.
set -eu
umask 077
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
export ASSISTANT_UID="$(id -u)" ASSISTANT_GID="$(id -g)"
compose() { docker compose --project-directory "$ROOT" -f "$ROOT/compose.v3.yaml" "$@"; }
action=${1:-help}
if [ "$action" = init ]; then
  python3 scripts/configure_release.py
  exit
fi
[ "$action" = help ] || [ -f .env ] || { echo '请先执行 sh scripts/v3.sh init' >&2; exit 2; }
case "$action" in
 build) compose build assistant ;;
 infrastructure) compose up -d --wait postgres etcd minio milvus ;;
 ingest) shift; compose run --rm --no-deps -T assistant python manage.py ingest "$@" ;;
 start) compose up -d --wait --no-deps --force-recreate assistant ;;
 stop) compose stop assistant ;;
 check) compose run --rm --no-deps -T assistant python manage.py check ;;
 doctor) compose run --rm --no-deps -T assistant python manage.py doctor --models ;;
 config) compose run --rm --no-deps -T assistant python manage.py retrieval-config ;;
 documents) compose run --rm --no-deps -T assistant python manage.py documents ;;
 sync-vectors) compose run --rm --no-deps -T assistant python manage.py sync-vectors ;;
 backup)
   # Stop request writers for a consistent DB+knowledge snapshot; resume via trap.
   running=$(compose ps --status running --services assistant)
   [ -z "$running" ] || compose stop assistant
   trap '[ -z "$running" ] || compose start assistant' EXIT
   target="backups/snapshot-$(date +%Y%m%d-%H%M%S)"
   mkdir -p backups
   mkdir "$target"
   compose exec -T postgres sh -c 'pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" --format=custom' > "$target/database.dump.tmp"
   mv "$target/database.dump.tmp" "$target/database.dump"
   python3 scripts/knowledge_bundle.py pack --output "$target/knowledge.tar.gz"
   cp .env "$target/environment.private"
   chmod 600 "$target/environment.private" "$target/database.dump" "$target/knowledge.tar.gz"
   echo "备份完成：$target；包含私密环境配置，仅限授权保管。恢复步骤见docs/部署说明.md。"
   ;;
 restore-db)
   [ "$#" -eq 2 ] && [ -f "$2" ] || { echo '用法：v3.sh restore-db backups/指定目录/database.dump' >&2; exit 2; }
   compose stop assistant
   compose exec -T postgres sh -c 'pg_restore -U "$POSTGRES_USER" -d "$POSTGRES_DB" --exit-on-error --single-transaction --no-owner --role="$APP_DB_USER"' < "$2"
   echo '仅允许恢复至空业务库。接着恢复知识资源、sync-vectors、doctor，再start。'
   ;;
 bundle) shift; python3 scripts/knowledge_bundle.py pack "$@" ;;
 restore-bundle) shift; python3 scripts/knowledge_bundle.py restore "$@" ;;
 logs) compose logs --tail 100 assistant ;;
 ps) compose ps ;;
 *) echo '首次部署：init → 编辑.env → build → infrastructure → ingest → start → doctor'
    echo '日常运维：check | config | documents | stop | logs | ps | backup | restore-db | sync-vectors'
    echo '知识资源迁移：bundle --output 路径 | restore-bundle --archive 路径' ;;
esac
