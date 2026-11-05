#!/bin/sh
# Always target a separate Compose project, never the demonstration project.
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
[ "$(basename "$ROOT")" = ai_customer_pressure ] || {
  echo '请在独立的 ai_customer_pressure 克隆目录运行，不要在演示目录执行。'; exit 1;
}
[ -f .env ] || { echo '请将演示配置复制到本目录 .env，权限设为600。'; exit 1; }
export ASSISTANT_UID=$(id -u) ASSISTANT_GID=$(id -g)
compose() { docker compose --project-directory "$ROOT" -p ai_customer_pressure -f "$ROOT/compose.pressure.yaml" "$@"; }
case "${1:-help}" in
 start)
  python3 - <<'PY'
import socket
with socket.socket() as s:
    try:s.bind(('127.0.0.1',18200))
    except OSError:raise SystemExit('18200已占用；先确认占用者，已有测试实例可直接使用。')
PY
  compose up -d --wait --no-deps --no-build assistant ;;
 token)
  umask 077
  compose exec -T assistant python manage.py token --tenant pressure-test --user tester --ttl 7200 > pressure_test/tokens.txt
  chmod 600 pressure_test/tokens.txt
  echo '测试令牌已保存到 pressure_test/tokens.txt，有效期2小时。' ;;
 check) compose exec -T assistant python manage.py check ;;
 logs) compose logs --tail 80 assistant ;;
 stop) compose stop assistant ;;
 ps) compose ps ;;
 *) echo '用法：sh scripts/pressure.sh start|token|check|logs|stop|ps'; exit 1 ;;
esac
