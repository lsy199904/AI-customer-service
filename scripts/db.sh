#!/usr/bin/env bash
# PostgreSQL 迁移封装：给不熟悉 Flyway 的开发者使用。
# 只暴露 new / check / info / migrate / validate / baseline / repair 七个子命令。
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DB_DIR="$ROOT/database/postgres"
MIG_DIR="$DB_DIR/migrations"
TEMPLATE="$DB_DIR/templates/V__migration.sql.tmpl"
IMAGE="${FLYWAY_IMAGE:-flyway/flyway:11-alpine}"
DOMAINS=(conversation quota knowledge workflow platform)

usage() {
    cat <<'EOF'
用法：scripts/db.sh <命令> [参数]

命令：
  new <domain> <desc>   创建下一个版本的迁移文件
                        domain: conversation|quota|knowledge|workflow|platform
                        desc:   小写字母、数字、下划线
  check                 运行 SQL 命名/版本/格式/不可变性检查
  info                  查看 Flyway 迁移状态（需要 FLYWAY_URL）
  migrate               执行迁移（需要 FLYWAY_URL 与四个归属占位符）
  validate              校验已应用迁移（需要 FLYWAY_URL）
  baseline              存量库登记基线（仅人工接入时使用）
  repair                修复 Flyway 历史中的失败记录（谨慎）

环境变量：
  FLYWAY_IMAGE          Flyway 镜像，默认 flyway/flyway:11-alpine
  FLYWAY_URL            JDBC URL，例如 jdbc:postgresql://127.0.0.1:5432/assistant
  FLYWAY_USER           数据库用户（也可写在 URL 中）
  FLYWAY_PASSWORD       数据库密码（也可写在 URL 中）
  FLYWAY_PLACEHOLDERS_* 四个归属占位符（migrate 需要）
  FLYWAY_DOCKER_ARGS    额外的 docker run 参数，例如 "--network host"

示例：
  scripts/db.sh new conversation add_message_client_id
  scripts/db.sh check
  FLYWAY_URL=jdbc:postgresql://127.0.0.1:5432/assistant \
  FLYWAY_USER=postgres FLYWAY_PASSWORD=postgres \
  FLYWAY_PLACEHOLDERS_DEPLOYMENT_ID=local \
  FLYWAY_PLACEHOLDERS_MILVUS_URI=http://127.0.0.1:19530 \
  FLYWAY_PLACEHOLDERS_MILVUS_DATABASE=default \
  FLYWAY_PLACEHOLDERS_MILVUS_PREFIX=local \
    scripts/db.sh migrate
EOF
}

die() {
    echo "ERROR: $*" >&2
    exit 1
}

next_version() {
    python3 - "$MIG_DIR" <<'PY'
import re
import sys
from pathlib import Path

root = Path(sys.argv[1])
versions = []
for path in root.rglob("V*.sql"):
    match = re.match(r"V(\d+)\.(\d+)\.(\d+)__", path.name)
    if match:
        versions.append(tuple(int(part) for part in match.groups()))
if versions:
    major, minor, patch = max(versions)
    print(f"{major}.{minor}.{patch + 1}")
else:
    print("1.0.0")
PY
}

cmd_new() {
    local domain="${1:-}"
    local desc="${2:-}"
    [[ -n "$domain" && -n "$desc" ]] || die "用法：scripts/db.sh new <domain> <desc>"

    local allowed=0
    for item in "${DOMAINS[@]}"; do
        if [[ "$domain" == "$item" ]]; then
            allowed=1
        fi
    done
    [[ "$allowed" == "1" ]] || die "domain 必须是：${DOMAINS[*]}"

    [[ "$desc" =~ ^[a-z0-9_]+$ ]] || die "desc 只能包含小写字母、数字、下划线"

    local version
    version="$(next_version)"
    local file="$MIG_DIR/$domain/V${version}__${domain}_${desc}.sql"
    [[ ! -e "$file" ]] || die "文件已存在：$file"

    mkdir -p "$MIG_DIR/$domain"
    python3 - "$TEMPLATE" "$file" "$domain" "$desc" <<'PY'
import pathlib
import sys

source, target, domain, desc = sys.argv[1:]
text = pathlib.Path(source).read_text(encoding="utf-8")
text = text.replace("<conversation|quota|knowledge|workflow|platform>", domain)
text = text.replace("-- 目的：", f"-- 目的：{desc}", 1)
pathlib.Path(target).write_text(text, encoding="utf-8")
PY

    echo "已创建：${file#"$ROOT/"}"
    echo "下一步：编辑 SQL -> scripts/db.sh check -> 提 PR（版本顺序由 CI 校验）"
}

cmd_check() {
    python3 "$ROOT/scripts/ci/check_sql.py"
}

flyway() {
    [[ -n "${FLYWAY_URL:-}" ]] || die "请设置 FLYWAY_URL（JDBC URL）"

    local docker_args=()
    if [[ "$(uname -s)" == "Linux" ]]; then
        docker_args+=(--network host)
    fi
    if [[ -n "${FLYWAY_DOCKER_ARGS:-}" ]]; then
        # 允许用户覆盖网络模式，例如 macOS 使用 host.docker.internal。
        # shellcheck disable=SC2206
        docker_args+=(${FLYWAY_DOCKER_ARGS})
    fi

    local env_args=(-e FLYWAY_URL)
    local name value
    for name in \
        FLYWAY_USER \
        FLYWAY_PASSWORD \
        FLYWAY_PLACEHOLDERS_DEPLOYMENT_ID \
        FLYWAY_PLACEHOLDERS_MILVUS_URI \
        FLYWAY_PLACEHOLDERS_MILVUS_DATABASE \
        FLYWAY_PLACEHOLDERS_MILVUS_PREFIX; do
        value="${!name-}"
        if [[ -n "$value" ]]; then
            env_args+=(-e "$name")
        fi
    done

    docker run --rm "${docker_args[@]}" "${env_args[@]}" \
        -v "$DB_DIR/flyway.conf:/flyway/conf/flyway.conf:ro" \
        -v "$MIG_DIR:/flyway/migrations:ro" \
        "$IMAGE" "$@"
}

main() {
    local command="${1:-}"
    shift || true
    case "$command" in
        new) cmd_new "$@" ;;
        check) cmd_check ;;
        info) flyway info "$@" ;;
        migrate) flyway -connectRetries=10 migrate "$@" ;;
        validate) flyway validate "$@" ;;
        baseline) flyway baseline "$@" ;;
        repair) flyway repair "$@" ;;
        help|-h|--help|"") usage ;;
        *) usage; die "未知命令：$command" ;;
    esac
}

main "$@"
