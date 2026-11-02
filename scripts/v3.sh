#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
export ASSISTANT_UID=$(id -u) ASSISTANT_GID=$(id -g)
[ -f .env ] || { echo '请先从v2复制.env'; exit 1; }
compose() { docker compose --project-directory "$ROOT" -f "$ROOT/compose.v3.yaml" "$@"; }
case "${1:-help}" in
 build) compose build assistant ;;
 start) compose up -d --wait assistant ;;
 doctor) compose exec assistant python manage.py doctor --models ;;
 logs) compose logs --tail 100 assistant ;;
 stop) compose stop assistant ;;
 *) echo '用法：sh scripts/v3.sh build|start|doctor|logs|stop' ;;
esac
