# 数据库 SQL 执行镜像（db-migrate）：只包含 Flyway 运行时、flyway.conf 与 migrations/。
# 不包含 app/ 代码，避免应用与 SQL 执行耦合。
# 构建上下文必须是仓库根目录，例如：
#   deploy/docker/db-migrate/build.sh -t v1.2.0
# 或：
#   docker build -f deploy/docker/db-migrate/Dockerfile \
#     --build-arg FLYWAY_IMAGE=flyway/flyway:11.20.3-alpine \
#     -t harbor.rd.dsi/smarttitu/db-migrate:v1.2.0 .

ARG FLYWAY_IMAGE=flyway/flyway:11.20.3-alpine
FROM ${FLYWAY_IMAGE}

LABEL org.opencontainers.image.title="titu-db-migrate" \
      org.opencontainers.image.description="Flyway runtime with titu-assistant PostgreSQL SQL assets"

# Flyway 镜像的工作目录是 /flyway；配置中的 locations 使用相对路径 migrations。
COPY database/postgres/flyway.conf /flyway/conf/flyway.conf
COPY database/postgres/migrations /flyway/migrations

# 以非 root 运行；K8s 的 securityContext 也使用 10001。
USER 10001

# 默认执行 migrate；Job 可以通过 args 覆盖为 validate/info。
CMD ["migrate"]
