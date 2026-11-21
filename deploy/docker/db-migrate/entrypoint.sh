#!/bin/sh
# 把应用唯一的数据库配置 DATABASE_URL 转换成 Flyway 需要的 JDBC 连接三要素。
#
# 设计前提：整个应用只在 Secret 里维护一个 DATABASE_URL（libpq URI），
# 迁移侧不再要求额外配置 FLYWAY_*，避免同一份连接信息存两遍、轮换时漏改。
#
# 已显式设置 FLYWAY_URL 时直接使用，便于本地调试或特殊场景覆盖。
set -eu

# libpq 会对 %XX 解码，Flyway 不会；两边必须拿到同一个密码，这里做等价还原。
# 只覆盖密码里常见的保留字符，够用且不引入额外依赖。
urldecode() {
    printf '%s' "$1" | sed \
        -e 's/%23/#/g' \
        -e 's/%40/@/g' \
        -e 's/%3[Aa]/:/g' \
        -e 's/%2[Ff]/\//g' \
        -e 's/%3[Ff]/?/g' \
        -e 's/%26/\&/g' \
        -e 's/%3[Dd]/=/g' \
        -e 's/%25/%/g'
}

FLYWAY_USER=""
FLYWAY_PASSWORD=""

if [ -z "${FLYWAY_URL:-}" ] && [ -n "${DATABASE_URL:-}" ]; then
    raw="$DATABASE_URL"

    case "$raw" in
        jdbc:postgresql://*)
            # 已经是 JDBC URL，直接透传
            FLYWAY_URL="$raw"
            ;;
        postgresql://*|postgres://*)
            rest="${raw#*://}"

            # 1. 拆出 query
            query=""
            case "$rest" in
                *\?*)
                    query="${rest#*\?}"
                    rest="${rest%%\?*}"
                    ;;
            esac

            # 2. 拆出凭证与主机段（密码可能含 @，取最后一个 @ 之前为凭证）
            hostpart="$rest"
            case "$rest" in
                *@*)
                    creds="${rest%@*}"
                    hostpart="${rest##*@}"
                    case "$creds" in
                        *:*)
                            FLYWAY_USER="$(urldecode "${creds%%:*}")"
                            FLYWAY_PASSWORD="$(urldecode "${creds#*:}")"
                            ;;
                        *)
                            FLYWAY_USER="$(urldecode "$creds")"
                            ;;
                    esac
                    ;;
            esac

            # 3. 拆出主机、端口、库名
            dbname=""
            case "$hostpart" in
                */*)
                    hostport="${hostpart%%/*}"
                    dbname="${hostpart#*/}"
                    ;;
                *)
                    hostport="$hostpart"
                    ;;
            esac

            host="$hostport"
            port="5432"
            case "$hostport" in
                *:*)
                    host="${hostport%:*}"
                    port="${hostport##*:}"
                    ;;
            esac

            if [ -z "$host" ] || [ -z "$dbname" ]; then
                echo "ERROR: 无法从 DATABASE_URL 解析出 host 或库名" >&2
                exit 1
            fi

            # 4. 只保留 JDBC 认识的参数，避免 libpq 专有参数导致连接失败
            jdbc_query=""
            if [ -n "$query" ]; then
                old_ifs="$IFS"
                IFS='&'
                for kv in $query; do
                    if [ "${kv%%=*}" = "sslmode" ]; then
                        jdbc_query="${jdbc_query:+$jdbc_query&}$kv"
                    fi
                done
                IFS="$old_ifs"
            fi

            FLYWAY_URL="jdbc:postgresql://${host}:${port}/${dbname}"
            if [ -n "$jdbc_query" ]; then
                FLYWAY_URL="${FLYWAY_URL}?${jdbc_query}"
            fi
            ;;
        *)
            echo "ERROR: DATABASE_URL 必须以 postgresql:// 、postgres:// 或 jdbc:postgresql:// 开头" >&2
            exit 1
            ;;
    esac

    export FLYWAY_URL
    if [ -n "$FLYWAY_USER" ]; then
        export FLYWAY_USER
    fi
    if [ -n "$FLYWAY_PASSWORD" ]; then
        export FLYWAY_PASSWORD
    fi
fi

exec flyway "$@"
