#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
export ASSISTANT_UID=$(id -u) ASSISTANT_GID=$(id -g)
[ -f .env ] || { echo '请先从v2复制.env'; exit 1; }
compose() { docker compose --project-directory "$ROOT" -f "$ROOT/compose.v3.yaml" "$@"; }
case "${1:-help}" in
 retrieval) shift; python3 scripts/configure_retrieval.py "$@" ;;
 build) compose build assistant ;;
 start) compose up -d --wait --no-deps --force-recreate assistant ;;
 config) compose exec -T assistant python manage.py retrieval-config ;;
 doctor) compose exec assistant python manage.py doctor --models ;;
 logs) compose logs --tail 100 assistant ;;
 stop) compose stop assistant ;;
 *) echo '用法：sh scripts/v3.sh retrieval|build|start|config|doctor|logs|stop' ;;
esac
