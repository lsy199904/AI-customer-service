#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
export ASSISTANT_UID=$(id -u) ASSISTANT_GID=$(id -g)
[ -f .env ] || { echo '请先从v2复制.env'; exit 1; }
compose() { docker compose --project-directory "$ROOT" -f "$ROOT/compose.v3.yaml" "$@"; }
case "${1:-help}" in
 anonymous) shift; python3 scripts/configure_anonymous.py "$@" ;;
 retrieval) shift; python3 scripts/configure_retrieval.py "$@" ;;
 bundle) shift; python3 scripts/knowledge_bundle.py pack "$@" ;;
 restore-bundle) shift; python3 scripts/knowledge_bundle.py restore "$@" ;;
 migration-export)
  stamp=$(date +%Y%m%d-%H%M%S)
  target="backups/migration-$stamp"
  compose stop assistant
  trap 'compose start assistant' EXIT
  compose run --rm --no-deps -T assistant python manage.py export-storage --output-dir "/ai_customer/$target/storage"
  python3 scripts/knowledge_bundle.py pack --output "$target/knowledge-and-history.tar.gz" --storage-dir "$target/storage"
  ;;
 build) compose build assistant ;;
 upgrade)
  compose build assistant
  compose run --rm --no-deps -T assistant python manage.py ingest
  compose up -d --wait --no-deps --force-recreate assistant
  compose exec -T assistant python manage.py check
  ;;
 start) compose up -d --wait --no-deps --force-recreate assistant ;;
 ingest) shift; compose exec -T assistant python manage.py ingest "$@" ;;
 media-report) shift; compose exec -T assistant python manage.py pdf-media-report "$@" ;;
 check) compose exec -T assistant python manage.py check ;;
 config) compose exec -T assistant python manage.py retrieval-config ;;
 doctor) compose exec assistant python manage.py doctor --models ;;
 logs) compose logs --tail 100 assistant ;;
 stop) compose stop assistant ;;
 *) echo '用法：sh scripts/v3.sh anonymous|retrieval|build|upgrade|start|ingest|media-report|bundle|restore-bundle|migration-export|check|config|doctor|logs|stop' ;;
esac
