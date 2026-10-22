#!/bin/sh
# Linux host networking reuses the model endpoints already reachable on the host.
set -eu
PROJECT_DIR=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$PROJECT_DIR"
if [ "$(uname -s)" != "Linux" ]; then
  echo "此配置用于现有 Linux 模型主机，请在服务器上执行。" >&2
  exit 2
fi
if [ ! -f .env ]; then
  echo "未找到.env，请先初始化或恢复已有配置。" >&2
  exit 2
fi
# Keep the same ownership as the existing native deployment; never chmod/chown its data.
ASSISTANT_UID=$(id -u)
ASSISTANT_GID=$(id -g)
export ASSISTANT_UID ASSISTANT_GID
mkdir -p var
exec docker compose --project-directory "$PROJECT_DIR" -f "$PROJECT_DIR/compose.host.yaml" "$@"
