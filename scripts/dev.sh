#!/bin/sh
# One application container; existing database/model services remain untouched.
set -eu
umask 077
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
export ASSISTANT_UID="$(id -u)" ASSISTANT_GID="$(id -g)"
compose() { docker compose --project-directory "$ROOT" -f "$ROOT/compose.dev.yaml" "$@"; }
run() { compose run --rm --no-deps -T assistant "$@"; }
action=${1:-help}
[ "$#" -eq 0 ] || shift
case "$action" in
 init) exec python3 scripts/configure_external.py "$@" ;;
 help) echo '首次：init → 填写.env → deploy；已有镜像：deploy --image 镜像名；测试自动建库可追加 --create-database'
       echo '其他：build | check | ingest | start | restart | stop | doctor | documents | logs | ps'
       exit 0 ;;
esac
python3 scripts/configure_external.py --check
command -v docker >/dev/null || { echo '请先安装Docker与Compose V2' >&2; exit 2; }
case "$action" in
 deploy)
   create=''; supplied=''
   while [ "$#" -gt 0 ]; do
     case "$1" in
       --create-database) create='--create-database'; shift ;;
       --image) [ "$#" -ge 2 ] || exit 2; supplied=$2; shift 2 ;;
       *) echo '未知参数，支持deploy [--image 镜像名] [--create-database]' >&2; exit 2 ;;
     esac
   done
   mkdir -p var
   mkdir var/external-deploy.lock 2>/dev/null || { echo '部署锁已存在；确认无其他部署后再移除var/external-deploy.lock' >&2; exit 2; }
   trap 'rmdir "$ROOT/var/external-deploy.lock" 2>/dev/null || true' EXIT
   running=$(compose ps --status running -q assistant)
   [ -n "$running" ] || python3 scripts/configure_external.py --check-port
   if [ -n "$supplied" ]; then
     docker image inspect "$supplied" >/dev/null
     python3 scripts/configure_external.py --image "$supplied"
   else
     echo '[1/5] 构建应用镜像（模型、数据库镜像不构建、不拉取）'
     compose build assistant
   fi
   echo '[2/5] 检查独立数据库、图片及三个模型API并初始化数据结构（模型检查有少量用量）'
   run python -m app.deployment initialize ${create:+$create}
   echo '[3/5] 增量入库（调用Embedding，首次可能耗时数分钟）'
   run python manage.py ingest
   echo '[4/5] 验证数据库、索引及三个模型接口'
   run python manage.py doctor --models
   echo '[5/5] 创建或更新本项目App容器，等待ready'
   compose up -d --wait --no-deps --force-recreate assistant
   python3 scripts/configure_external.py --show-url
   ;;
 check) run python -m app.deployment check "$@" ;;
 ingest) run python -m app.deployment initialize; run python manage.py ingest "$@" ;;
 build) compose build assistant ;;
 start|restart) compose up -d --wait --no-deps --force-recreate assistant ;;
 stop) compose stop assistant ;;
 doctor) run python manage.py doctor --models ;;
 documents) run python manage.py documents ;;
 logs) compose logs --tail 100 assistant ;;
 ps) compose ps ;;
 *) echo '未知命令，查看：sh scripts/dev.sh help' >&2; exit 2 ;;
esac
