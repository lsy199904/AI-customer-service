#!/bin/sh
# Same application and models; override only storage and enforce one worker.
set -eu
umask 077
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
if [ "$(uname -s)" != Linux ]; then echo '请在Linux模型主机执行SQLite部署脚本。' >&2;exit 2;fi
if [ ! -f .env ]; then echo '未找到.env，请先恢复现有配置。' >&2;exit 2;fi
ASSISTANT_UID=$(id -u);ASSISTANT_GID=$(id -g);export ASSISTANT_UID ASSISTANT_GID
compose() { docker compose --project-directory "$ROOT" -f "$ROOT/compose.sqlite.yaml" "$@"; }
command=${1:-help}
case "$command" in
  start)
    image=$(compose config --images)
    if ! docker image inspect "$image" >/dev/null 2>&1; then
      echo "未找到本地镜像：$image。请先准备包含当前requirements.lock依赖的应用镜像。" >&2
      echo '本脚本不会自动拉取或构建镜像；可用SQLITE_APP_IMAGE指定已有兼容镜像。' >&2
      exit 2
    fi
    mkdir -p var
    compose up -d --no-deps --pull never --force-recreate assistant
    ;;
  check) compose exec assistant python manage.py check ;;
  doctor) shift;compose exec assistant python manage.py doctor "$@" ;;
  policies) python3 scripts/configure_policies.py ;;
  exec|logs|ps|restart|stop) shift;compose "$command" "$@" ;;
  *) echo '启动：sh scripts/sqlite.sh start；检查：sh scripts/sqlite.sh check'
     echo '入库：sh scripts/sqlite.sh exec assistant python manage.py ingest'
     echo '诊断：sh scripts/sqlite.sh doctor；模型连接诊断追加 --models'
     echo '只重建assistant容器；不启动或删除PostgreSQL/Milvus及其数据。' ;;
esac
