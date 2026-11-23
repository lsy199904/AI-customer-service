# deploy/docker —— 生产镜像构建与版本发布

两个生产镜像的构建脚本，构建上下文恒为仓库根目录。
前置：Docker 23+（BuildKit / buildx 插件就绪）。

| 目录          | 镜像                  | 内容                                           |
|---------------|-----------------------|------------------------------------------------|
| `app/`        | `smarttitu-assistant` | 应用 + 知识入库 Job 复用（uv.lock 两阶段构建） |
| `db-migrate/` | `db-migrate`          | Flyway + SQL 迁移脚本                          |

## 版本发布（CI 自动，标准路径）

push 到 `main`（或打 `v*` tag）触发 GitLab CI：`build-images` 以
`v<pyproject 版本>-<YYYYMMDD>-<git短sha>` 为 tag，两个镜像**同一 tag 配套**
构建并推送 Harbor（`harbor.rd.dsi/smarttitu/`），随后 `deploy-dev` 自动发布 K8s dev。
选项与变量见 `.gitlab-ci.yml` 与各脚本 `-h`。

## 手动构建推送（CI 不可用时）

两个脚本不传 `-t` 时自动生成相同规则、且互相一致的 tag，直接配套推送：

```bash
deploy/docker/app/build.sh -n smarttitu-assistant --push
deploy/docker/db-migrate/build.sh --push
```

- `-n smarttitu-assistant` 与 CI / K8s 清单引用的镜像名一致，不要改。
- tag 必须唯一：同名 tag 覆盖推送后，节点因 `imagePullPolicy: IfNotPresent`
  不会重新拉取，表现为「发布成功但行为没变」。
- 两个镜像必须同一 tag 配套：app 镜像不含 Flyway、db-migrate 镜像不含应用代码，
  SQL 与 App 版本靠同 tag 对齐。
