# GitLab CI → Harbor → K8s dev 发布方案

流水线定义在仓库根的 [`../../.gitlab-ci.yml`](../../.gitlab-ci.yml)，发布动作封装在本目录
[`k8s-dev.sh`](k8s-dev.sh)，CI 账号权限在本目录 [`rbac-ci-dev.yaml`](rbac-ci-dev.yaml)。
K8s 清单与发布语义（六个步骤、幂等、失败恢复）见 [`../k8s/dev/README.md`](../k8s/dev/README.md)，
本文件只讲 CI 侧：**怎么配、怎么第一次跑通、出问题先查哪**。

## 1. 总览

```text
push main / MR
   │
   ├─ test        uv lock --check → ruff → pytest（junit 报告）    所有分支/MR
   ├─ sql-check   sqlfluff 门禁（scripts/ci/check_sql.py）          所有分支/MR
   │
   ▼ main（v* tag 只构建不发布）
build-images  deploy/docker/app/build.sh        → harbor.rd.dsi/smarttitu/smarttitu-assistant:<tag>
              deploy/docker/db-migrate/build.sh → harbor.rd.dsi/smarttitu/db-migrate:<tag>
              tag = v<pyproject版本>-<YYYYMMDD>-<短SHA>，dotenv artifact 传给下游
   │
   ▼ 自动（on_success）
deploy-dev    bash deploy/ci/k8s-dev.sh deploy（resource_group 防并发，不可 interrupt）
   │
   ▼
K8s app-zone：停 App 释放 RWO 卷 → db-migrate Job → milvus-init Job → 删 Job 释放卷
              → apply Deployment → rollout status → 冒烟 /smart-bot/ready
              Job 阶段失败 scale 回 1；Deployment/冒烟失败自动 rollout undo
   │
   └─ rollback-dev（手动 job）：k8s-dev.sh rollback
```

| 设计点 | 落地位置 |
|---|---|
| feature 分支只跑检查，不构建不发布 | `.gitlab-ci.yml` build/deploy 的 `rules` |
| 镜像 tag 全局唯一（`IfNotPresent` 下同名 tag = 没发版） | tag 含日期 + 短 SHA |
| 两个镜像同 tag 配套（db-migrate 独立镜像，App 纯 Python） | build job 串行调用两个 build.sh |
| tag 不改仓库文件 | `k8s-dev.sh prepare_manifests` 复制到 mktemp 目录后 sed 替换 |
| 并发发布互踩 | `resource_group: deploy-dev` + `interruptible: false` |
| 发布中途断线不留下 0 副本 | 脚本各失败分支均恢复旧版副本（见 k8s-dev.sh 注释） |

## 2. 一次性配置（共 5 步）

### 第 1 步：GitLab Runner（shell executor）

Runner 主机需要能访问：GitLab、Harbor（harbor.rd.dsi）、K8s API（16443）、PyPI（或内网镜像源）。

```bash
# Docker（23+ 自带 BuildKit；Dockerfile 用了 RUN --mount=type=cache，必须 BuildKit）
curl -fsSL https://get.docker.com | sudo bash

# gitlab-runner
curl -L "https://packages.gitlab.com/install/repositories/runner/gitlab-runner/script.deb.sh" | sudo bash
sudo apt install gitlab-runner

# 注册：token 取自 GitLab 项目 Settings → CI/CD → Runners → New project runner
sudo gitlab-runner register \
  --url https://<你的GitLab地址> \
  --token <runner-token> \
  --executor shell \
  --description k8s-dev-runner

# shell executor 以 gitlab-runner 用户执行，docker/kubectl/uv 必须对该用户可用
sudo usermod -aG docker gitlab-runner
sudo systemctl restart gitlab-runner   # usermod 后必须重启服务，组身份才生效

# kubectl 与 uv 放进全局 PATH（CI 是非登录 shell，不一定读 ~/.bashrc / ~/.local/bin）
sudo install -o root -g root -m 0755 kubectl /usr/local/bin/kubectl   # 二进制按需从 dl.k8s.io 或内网镜像获取
sudo -u gitlab-runner -H bash -c 'curl -LsSf https://astral.sh/uv/install.sh | sh'
sudo ln -sf ~gitlab-runner/.local/bin/uv /usr/local/bin/uv
```

验证（模拟 CI 用户环境）：

```bash
sudo -u gitlab-runner -H bash -c 'docker info >/dev/null && echo docker-ok; kubectl version --client=true; uv --version'
```

内网装不了 packages.gitlab.com / astral.sh 时，手动下载 deb 与 uv 单文件二进制放进 `/usr/local/bin` 即可，不影响其余步骤。

### 第 2 步：Harbor 凭证

Harbor 上建 robot 账号（或普通用户），对项目 `smarttitu` 有 push 权限，然后到
**Settings → CI/CD → Variables** 添加：

| Key | Type | 备注 |
|---|---|---|
| `HARBOR_USER` | variable | 明文即可 |
| `HARBOR_PASSWORD` | variable | 勾 **Masked** |

手动验证推送通道：Runner 主机上 `docker login harbor.rd.dsi`（用同一账号）。

### 第 3 步：CI 专用 ServiceAccount（最小权限）

```bash
# 1. 应用权限清单（SA + Role + RoleBinding + ClusterRole，见文件头注释）
kubectl apply -f deploy/ci/rbac-ci-dev.yaml
```

```bash
# 2. 生成长期 token（推荐：Secret 型，不过期；CI 变量改起来麻烦，用长期 token）
kubectl -n app-zone apply -f - <<'EOF'
apiVersion: v1
kind: Secret
metadata:
  name: titu-ci-token
  namespace: app-zone
  annotations:
    kubernetes.io/service-account.name: titu-ci
type: kubernetes.io/service-account-token
EOF
TOKEN=$(kubectl -n app-zone get secret titu-ci-token -o jsonpath='{.data.token}' | base64 -d)

# 备选：短期 token（默认 1h，到期要重新换变量，一般不建议用于 CI）
# TOKEN=$(kubectl -n app-zone create token titu-ci --duration=87600h)

# 3. 取集群 CA（当前 kubeconfig 若无 CA 数据，见下方 kubeconfig 里的 insecure 说明）
CA=$(kubectl config view --raw --minify -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')
```

```bash
# 4. 拼 kubeconfig（server 按实际 API 地址填；本集群参考 192.168.100.114:16443）
cat > /tmp/kubeconfig-dev <<EOF
apiVersion: v1
kind: Config
clusters:
  - name: dev
    cluster:
      server: https://<API地址>:16443
      certificate-authority-data: ${CA}
users:
  - name: titu-ci
    user:
      token: ${TOKEN}
contexts:
  - name: dev
    context:
      cluster: dev
      user: titu-ci
      namespace: app-zone
current-context: dev
EOF
```

> 拿不到 CA（例如管理端用的是 `insecure-skip-tls-verify: true`）时，把
> `certificate-authority-data` 一行换成 `insecure-skip-tls-verify: true`；内网自签可接受。

```bash
# 5. 验证权限边界：应只看到 app-zone 内的上述资源，且能 get namespace
KUBECONFIG=/tmp/kubeconfig-dev kubectl -n app-zone auth can-i --list
KUBECONFIG=/tmp/kubeconfig-dev kubectl get namespace app-zone

# 6. GitLab → Settings → CI/CD → Variables 添加：
#    Key:   KUBE_CONFIG_DEV
#    Type:  File                     ← 必须是 File 型，k8s-dev.sh 里 export KUBECONFIG=$KUBE_CONFIG_DEV
#    Value: /tmp/kubeconfig-dev 的内容
#    （多行值不支持 Masked，不勾；建议等 main 设为受保护分支后勾 Protected）
```

### 第 4 步：集群一次性资源（清单已就绪，只需 apply 一次）

```bash
kubectl apply -f deploy/k8s/dev/00-namespace.yml
kubectl apply -f deploy/k8s/dev/10-configmap.yml   # 按环境改 MILVUS_URI / MODEL_BASE_URL / EMBEDDING_URL 等【必填】项
kubectl apply -f deploy/k8s/dev/20-secret.yml      # ⚠️ 安全提醒见第 6 节，先轮换再 apply
kubectl apply -f deploy/k8s/dev/30-pvc.yml
kubectl apply -f deploy/k8s/dev/70-service.yml
kubectl apply -f deploy/k8s/dev/80-ingress.yml     # 对外入口：http://<ingress节点IP>/smart-bot/
```

Postgres 与 Milvus 由集群侧提供（当前配置指向 `postgres-14-cluster-rw.postgres.svc` 与
`milvus-26-milvus.milvus.svc`）；需要自建时用 `deploy/k8s/dev/infra/` 下的清单。

### 第 5 步（可选）：内网基础镜像覆盖

CI 变量会原样传给 build.sh，拉不到官方基础镜像时加变量即可，不用改任何文件：

| Key | 示例值 |
|---|---|
| `PYTHON_IMAGE` | `docker.m.daocloud.io/library/python:3.12-slim-bookworm` |
| `UV_IMAGE` | `ghcr.m.daocloud.io/astral-sh/uv:0.9.5` |
| `FLYWAY_IMAGE` | `docker.m.daocloud.io/flyway/flyway:11.20.3-alpine` |
| `UV_INDEX_URL` | `https://pypi.tuna.tsinghua.edu.cn/simple`（test 阶段 `uv sync` 用） |

## 3. 首次跑通清单

按顺序执行，每步都有明确的预期结果；第 9 步起验证失败路径。

| # | 操作 | 预期 |
|---|---|---|
| 1 | 推一个 main 提交（或 CI/CD → Pipelines → Run pipeline，分支 main） | 四个 stage 依次排队 |
| 2 | `test` | 绿；页面能看到 JUnit 报告 |
| 3 | `sql-check` | 绿 |
| 4 | `build-images` | 绿；日志末尾两行 `完成：harbor.rd.dsi/smarttitu/...:v<版本>-<日期>-<sha>`；Harbor 页面能看到两个仓库的新 tag |
| 5 | `deploy-dev` | 绿；日志按 `==> 1/6` 到 `6/6` 输出，最后 `发布成功` |
| 6 | `kubectl -n app-zone get deploy,pods` | Pod 镜像 tag = 本次 IMAGE_TAG，READY 1/1 |
| 7 | `curl http://<ingress节点IP>/smart-bot/ready` | `{"status":"ready"}`；GitLab → Operate → Environments 里 dev 环境有部署记录 |
| 8 | 手动跑 `rollback-dev`，再手动重跑 `deploy-dev` | 回退后 Pod 回到上一镜像且冒烟通过；重新发布恢复正常（回退会留下手动触发的痕迹，属预期） |
| 9 | 推一个故意写错 SQL 的分支 → MR | `sql-check` 红，流水线停，不触发构建 |
| 10 | （可选）在集群里造一次迁移失败（如临时改错 Secret 里的库名）再推 main | `deploy-dev` 在 2/6 失败后自动把旧版 App scale 回 1，job 红；修好后重推即恢复 |

第 10 步做完记得把 Secret 改回真值。失败路径的行为细节见
[`../k8s/dev/README.md`](../k8s/dev/README.md)「失败恢复与回退」。

## 4. 日常使用

- **发布**：合入 main 即自动发布；想攒一批就合并后盯一次 `deploy-dev`。
- **回退**：CI/CD → Pipelines → 找最近一次成功的 main 流水线 → 手动跑 `rollback-dev`
  （它 `needs: []`，不依赖构建，任何一条 main 流水线上都能点）。
- **只跑检查**：任意 feature 分支 push，只跑 `test` + `sql-check`。
- **发布到一半手动取消**：job 标了 `interruptible: false`，GitLab 会等当前 job 跑完再取消；
  真要立刻停，登录 Runner 主机 kill，并按 dev README「失败恢复」表收尾（确认副本数恢复 1）。

## 5. 常见问题速查

| 现象 | 原因 | 处理 |
|---|---|---|
| `docker: permission denied`（test/build） | gitlab-runner 不在 docker 组，或改组后没重启 runner 服务 | `sudo usermod -aG docker gitlab-runner && sudo systemctl restart gitlab-runner` |
| `uv: command not found` / `kubectl: command not found` | 不在 CI 用户的 PATH | 二进制放到 `/usr/local/bin`（见第 1 步） |
| build 拉不到 `python:` / `uv:` / `flyway:` 基础镜像 | 内网不通 docker.io / ghcr.io | 第 5 步的三个镜像覆盖变量 |
| `test` 卡在 `uv sync` 下载依赖 | PyPI 不可达 | 加 `UV_INDEX_URL` 变量指内网/国内源 |
| `ERROR: K8s 连通性预检失败` | KUBE_CONFIG_DEV 没配、不是 File 型、token 过期、API 地址不通 | 按第 3 步重验：`KUBECONFIG=<file> kubectl get ns app-zone` |
| `ERROR: 40 清单没有匹配到 db-migrate 镜像行` | 清单里的 `image:` 行格式被改过（sed 依赖固定格式） | 恢复镜像行原始格式：行首缩进 + `image: <registry>/...db-migrate:<tag>` |
| deploy 卡在 `Multi-Attach error` | RWO 卷被别的 Pod 占着（上次 Job 没删干净 / Pod Terminating） | `kubectl -n app-zone get pods` 找出占用者，按 dev README「失败排查」表处理 |
| 冒烟失败，已自动回退 | 新版起不来或 `/ready` 不过 | 看 deploy job 日志末尾自动附上的 `kubectl logs deploy/titu-assistant`；多为模型网关/知识库未就绪 |
| 发布成功但行为没变 | ConfigMap/Secret 不在发布流程里 | 改过 `10/20` 清单要手动 apply（dev README「运维注意」） |
| `sql-check` 报 `sqlfluff not found` | 没走 `--no-project --with` 包装 | 不要改 `.gitlab-ci.yml` 里这行命令的写法 |

## 6. ⚠️ 安全提醒：真实密钥已提交进 Git

`deploy/k8s/dev/20-secret.yml`（数据库密码、`AUTH_SECRET`、SiliconFlow API Key）与
`deploy/k8s/dev/infra/postgres/01-postgres-secret.yaml` 当前包含**真实值**，且文件头自己标注了
「禁止提交真实值到 Git」。这些值已随提交进入仓库历史，建议尽快：

1. 轮换：SiliconFlow API Key、`DATABASE_URL` 密码、`AUTH_SECRET`、`OPERATIONS_TOKEN`；
2. 仓库里改回占位符，真实值只通过集群侧管理（本地 apply 时临时替换，或后续引入
   SealedSecrets / GitLab 集成变量）；
3. 历史清除需要改写远端历史（`git filter-repo`），成本高，轮换密钥优先于清历史。

注意轮换 `DATABASE_URL` 密码会同时影响连接串：密码含 `#` 时 db-migrate 的 entrypoint 已做兼容，
但更稳妥的做法是 URL 编码（`#` → `%23`）。
