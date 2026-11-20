# 数据库 SQL 执行镜像（db-migrate）：只包含 Flyway 运行时、flyway.conf 与 migrations/。
# 不包含 app/ 代码，避免应用与 SQL 执行耦合。
# 构建上下文必须是仓库根目录，例如：
#   deploy/docker/db-migrate/build.sh -t v1.0.0
# 或：
#   docker build -f deploy/docker/db-migrate/Dockerfile \
#     --build-arg FLYWAY_IMAGE=flyway/flyway:11.20.3-alpine \
#     -t harbor.rd.dsi/smarttitu/db-migrate:v1.0.0 .
#
# 国内网络无法直连 Docker Hub 时，把 FLYWAY_IMAGE 换成可达镜像源，例如
# docker.m.daocloud.io/flyway/flyway:11.20.3-alpine；详细说明见同目录 README。

ARG FLYWAY_IMAGE=flyway/flyway:11.20.3-alpine
FROM ${FLYWAY_IMAGE}

LABEL org.opencontainers.image.title="titu-db-migrate" \
      org.opencontainers.image.description="Flyway runtime with titu-assistant PostgreSQL SQL assets"

# Flyway 工作目录是 /flyway；配置里的 locations / callbackLocations 用相对路径 migrations。
#
# 这里逐个目录显式复制，不用 COPY 整个 migrations，目的是让“镜像里有什么”一眼可查。
# 代价：新增业务领域目录时，必须在本文件补一行 COPY，否则不会进入镜像。
# CI 的 check_sql.py 会校验 migrations/ 下的领域目录与这里的 COPY 是否一一对应。

# 配置
COPY database/postgres/flyway.conf /flyway/conf/flyway.conf

# 版本化脚本：根目录下的 V*.sql（当前为 V1.0.0__baseline.sql）
# 新增版本脚本不需要改本文件，通配符自动带入
COPY database/postgres/migrations/*.sql /flyway/migrations/

# 回调：beforeMigrate / afterMigrate
COPY database/postgres/migrations/callbacks/ /flyway/migrations/callbacks/

# 业务领域目录：后续 V1.0.N 的落点
COPY database/postgres/migrations/conversation/ /flyway/migrations/conversation/
COPY database/postgres/migrations/quota/ /flyway/migrations/quota/
COPY database/postgres/migrations/knowledge/ /flyway/migrations/knowledge/
COPY database/postgres/migrations/workflow/ /flyway/migrations/workflow/
COPY database/postgres/migrations/platform/ /flyway/migrations/platform/

# 可重复脚本 R__（当前为空目录，靠 .gitkeep 保留）
COPY database/postgres/migrations/repeatable/ /flyway/migrations/repeatable/

# 入口脚本：把应用唯一的 DATABASE_URL 转成 Flyway 的 JDBC 连接三要素，
# 迁移侧因此不需要再单独维护 FLYWAY_URL / FLYWAY_USER / FLYWAY_PASSWORD。
COPY deploy/docker/db-migrate/entrypoint.sh /flyway/entrypoint.sh
RUN chmod 0755 /flyway/entrypoint.sh

# 以非 root 运行；K8s 的 securityContext 也使用 10001。
USER 10001

ENTRYPOINT ["/flyway/entrypoint.sh"]

# 默认执行 migrate；Job 可以通过 args 覆盖为 validate/info。
CMD ["migrate"]
