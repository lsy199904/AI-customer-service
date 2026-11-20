#!/bin/sh
# Milvus 集合初始化 → 知识入库 → 自检：四步严格按顺序执行，任一步失败立即退出。
# 由 deploy/k8s/dev/50-job-milvus-init.yaml 调用；也可在容器内手工执行。
# 依赖同目录的 02_milvus.py，以及 /srv/assistant/manage.py，
# 以及 MILVUS_* / EMBEDDING_* / DATABASE_URL / AUTH_SECRET 等环境变量（与 App 同一套）。
# 产物写入已挂载的 /srv/assistant/var，App 启动后读取同一目录。
set -eu

# 脚本位于 <APP_HOME>/database/milvus/knowledge-init.sh
APP_HOME="${APP_HOME:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$APP_HOME"
MILVUS_DIR="$APP_HOME/database/milvus"

DIMENSION="${DIMENSION:-1024}"

echo "==> 1/4 计算完整集合名（前缀 + fingerprint 前16位）"
COLLECTION=$(python -c 'from app.rag import RAGSettings; s=RAGSettings(); print(s.milvus_collection + "_" + s.fingerprint[:16])')
# 只允许字母数字下划线：名字算错会新建一个空集合，让 App 检索不到数据，这里直接拦住
case "$COLLECTION" in
    ''|*[!A-Za-z0-9_]*) echo "集合名异常：'$COLLECTION'" >&2; exit 1 ;;
esac
echo "    集合名: $COLLECTION"

echo "==> 2/4 创建或核对 Milvus 集合"
python "$MILVUS_DIR/02_milvus.py" --collection "$COLLECTION" --dimension "$DIMENSION"

echo "==> 3/4 知识入库（解析、切片、Embedding，写 PG 与 Milvus）"
python manage.py ingest

echo "==> 4/4 数据库、LangGraph 与模型自检"
python manage.py doctor --models

echo "==> 完成：集合 $COLLECTION 已就绪，知识已入库"
