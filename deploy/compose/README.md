# deploy/compose —— 开发测试环境（Docker Compose 全栈）

开发测试专用单机栈：一条 `up` 完成「起依赖 → 跑迁移 → 知识入库 → 起应用」。
每次基于最新代码打包镜像、彻底摧毁重建，验证干净状态。集群部署见 `deploy/k8s/`。

## 完全重建（唯一标准流程）

```bash
# 首次：生成 .env，填好 MODEL_API_KEY 等密钥
cd deploy/compose && cp .env.example .env

# 之后每次：一条命令完成「最新代码打包镜像 → tag 写回 .env → 彻底摧毁 → 全新起栈」
bash deploy/compose/scripts/dev-rebuild.sh
```

访问入口：`http://<宿主机IP>:30201/smart-bot/`。

脚本自动完成：`uv lock` 依赖同步 → 以 `dev-<日期>-<短sha>` 配套打包双镜像 →
tag 写回 `.env`（`.env` 配一次密钥即可，镜像引用无需再手动改）→ `down -v`
清空数据卷 → `up -d --wait` 等healthy。

- `down -v` 全量重跑迁移与知识入库（预算 ~30 分钟，真实消耗 Embedding 额度）；
  镜像层有缓存时构建只需几十秒。
- 脚本已按国内网络默认走 daocloud 换源：python/uv/flyway 基底镜像与 postgres 镜像
  （postgres 仅在 `.env` 还是官方原始值时自动替换，自定义值不动）。
  网络无障碍时可用环境变量覆盖回官方源，如
  `PYTHON_IMAGE=python:3.12-slim-bookworm bash deploy/compose/scripts/dev-rebuild.sh`。
- 前置：Docker 23+（app 镜像构建需 BuildKit）与 Docker Compose v2.22+；
  `.env` 引用的镜像可拉取（内网 Harbor 或 `docker load`）。

- `down -v` 清空全部数据卷（postgres / milvus / var），每次全量重跑迁移与知识入库
  （预算 ~30 分钟，真实消耗 Embedding 额度）；镜像层有缓存时①通常只需几十秒。
- 前置：Docker 23+（app 镜像构建需 BuildKit）与 Docker Compose v2.22+；
  `.env` 引用的镜像可拉取（内网 Harbor 或 `docker load`）。
