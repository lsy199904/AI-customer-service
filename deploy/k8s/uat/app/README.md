# 应用部署（Dev）：镜像打包与 Kubernetes 运维

应用镜像通过项目根目录的 `../../../../docker/Dockerfile` 构建，使用标准 `docker` 命令手工打包并推送到公司镜像仓库；部署与日常运维全部使用原生 `kubectl` 命令操作本目录的清单文件，**不依赖 `../../../../scripts` 下的任何脚本**。

| 位置 | 说明 |
|---|---|
| `../../../../docker/Dockerfile`（项目根） | 应用镜像构建定义 |
| `../../../../.dockerignore`（项目根） | 构建上下文排除项（`.env`、`../../../../var`、`../../../../../tests` 等，密钥与运行时数据不进镜像） |
| `requirements.lock` | 镜像内 Python 依赖的锁定版本清单 |
| `.env.example` | 运行时配置模板（模型 API、PostgreSQL、Milvus 地址等），仅本地验证时使用 |
| `00-*.yml` ~ `90-*.yml` | 手写 K8s 部署清单，按资源类型拆分（Namespace / ConfigMap / Secret / PVC / Deployment / Service / 初始化 Job），见「六」 |
| `init-job.md` | 初始化 Job 的阶段说明（建表、知识入库、体检） |

## 一、镜像内容（Dockerfile 说明）

- **基础镜像**：`python:3.12-slim`。
- **系统依赖**：`libgl1`、`libglib2.0-0`、`libgomp1`。
- **Python 依赖**：按 `requirements.lock` 锁定版本安装，保证不同时间构建出的镜像依赖一致。
- **随镜像交付**：`../../../../app`（问答、检索、匿名身份等代码）、`data/`（含 `media.json` 图片登记）、`knowledge_sources/`（正式知识源）、`../../../../../database/milvus/manage.py`。知识文档与配图打进镜像，内容变更需重新打镜像。
- **运行身份**：非 root 用户 `assistant`（uid 10001）；`../../../../var`（日志、PDF 图片等）运行时生成，生产环境挂 PVC。
- **入口**：默认监听 `8000` 端口（`PORT` 环境变量可覆盖），启动命令 `python -m app.server`。

## 二、构建前置条件

1. 构建机已安装 Docker，且能访问公司镜像仓库 `harbor.rd.dsi`（未登录时先执行 `docker login harbor.rd.dsi`）。
2. 在**项目根目录**执行构建：构建上下文必须包含 `../../../../app`、`data/`、`knowledge_sources/`、`../../../../../database/milvus/manage.py`、`requirements.lock`，这些路径在 `../../../docker/Dockerfile` 中固定引用，换目录会导致 COPY 失败。
3. 确定镜像标签。必须使用**仓库完整地址 + 唯一版本标签**，采用**语义版本 + 日期后缀**格式（如 `v1.0.0-20261118`）：
   - 语义版本按 `主版本.次版本.修订号` 递增：不兼容的配置/接口变更升主版本，新增功能升次版本，问题修复升修订号；
   - 同一语义版本一天内多次构建时递增修订号（如 `v1.0.1-20261118`），保证标签唯一；
   - 禁止 `latest`——集群节点 `imagePullPolicy: IfNotPresent`，同名标签覆盖后节点可能一直拉到旧镜像；
   - dev 集群不通外网，镜像必须推送到集群可达的内网仓库（与 postgres / milvus 镜像同步到 `harbor.rd.dsi` 的做法一致）；仓库需要认证时，部署侧还需配置对应的 imagePullSecret。

下文以 `harbor.rd.dsi/smarttitu/assistant:v1.0.0-20261118` 为例，实际使用时替换为自己的仓库地址与标签。

## 三、构建镜像

```bash
cd /path/to/titu-assistant
docker build -t harbor.rd.dsi/smarttitu/assistant:v1.0.0-20261118 .
```

- `-t` 后面是完整镜像名：`仓库地址/项目/名称:标签`；
- 结尾的 `.` 指定构建上下文为项目根目录，**不能省略也不能换成子目录**；
- 构建过程依次执行：装系统依赖 → 按 `requirements.lock` 装 Python 依赖 → COPY 代码与知识文件 → 创建非 root 用户。

构建完成后先做本地导入验证，确认镜像完整可用：

```bash
docker run --rm harbor.rd.dsi/smarttitu/assistant:v1.0.0-20261118 \
  python -c "import app.server; print('ok')"
```

## 四、推送镜像

```bash
docker push harbor.rd.dsi/smarttitu/assistant:v1.0.0-20261118
```

推送成功后，可在集群任一节点（或能访问仓库的机器）拉取验证：

```bash
docker pull harbor.rd.dsi/smarttitu/assistant:v1.0.0-20261118
```

## 五、本地运行验证（可选）

部署前可在本机把容器跑起来冒烟测试。先按 `.env.example` 准备配置（填写外部模型 API、PostgreSQL、Milvus 地址）：

```bash
cp .env.example .env        # 按注释填写真实地址与密钥，.env 不会进镜像
docker run --rm -p 8000:8000 --env-file .env \
  harbor.rd.dsi/smarttitu/assistant:v1.0.0-20261118
# 另开终端验证就绪接口
curl http://127.0.0.1:8000/smart-bot/ready
```

> 注意 PG / Milvus 地址的可达性：容器默认使用桥接网络，`localhost` 指向容器自身；依赖服务在本机时，地址应写宿主机 IP 或改用 `--network host`。

## 六、Kubernetes 部署与运维（原生 kubectl）

使用本目录的 K8s 清单手工部署与运维，参数含义见 [`../../../../docs/app.env.example`](../../../../docs/app.env.example)。清单按资源拆分为独立文件，**文件名带序号，`kubectl apply -f .` 按序号依次应用**：

| 文件 | 资源 | 说明 |
|---|---|---|
| `00-namespace.yml` | Namespace `app-zone` | 应用命名空间（PG 在 `postgres`、Milvus 在 `milvus`，跨 ns 通过 Service 域名访问） |
| `../10-configmap.yml` | ConfigMap `titu-assistant-config` | 非敏感运行配置 |
| `../20-secret.yml` | Secret `titu-assistant-secret` | 7 个密钥（数据库连接串、AUTH_SECRET、各模型 API Key 等） |
| `../30-pvc.yml` | PVC `titu-assistant-var` | 运行时数据（日志、PDF 图片），挂载到 `/srv/assistant/var` |
| `../40-deployment.yml` | Deployment `titu-assistant` | 单副本；RWO 卷故使用 `Recreate` 更新策略 |
| `../50-service.yml` | Service `titu-assistant` | ClusterIP，`80` → 容器 `8201` |
| `90-init-job.yml` | Job `titu-assistant-init` | 一次性初始化：建表 + 知识入库 + 模型连通检查，阶段细节见 [`init-job.md`](init-job.md) |

> 前置依赖：PostgreSQL（`postgres` 命名空间）与 Milvus（`milvus` 命名空间）需已就绪并可跨 ns 访问，`MILVUS_URI` 填集群内 Service 域名（如 `http://milvus-26-milvus.milvus.svc.cluster.local:19530`），`DATABASE_URL` 填 `postgres-14-cluster-rw` 的连接串。参见上级 [README](../README.md)。

### 6.1 首次部署

1. 填写所有【必填】项：`../20-secret.yml` 中的 7 个密钥、`../10-configmap.yml` 中的 `DEPLOYMENT_ID` / `MILVUS_URI` / 模型接口地址等，并将 `../40-deployment.yml` 与 `90-init-job.yml` 中的 `image` 改为实际推送的镜像标签。
2. 应用并等待初始化完成：

   ```bash
   kubectl apply -f .
   kubectl -n app-zone wait --for=condition=complete job/titu-assistant-init --timeout=1800s
   kubectl -n app-zone rollout status deployment/titu-assistant --timeout=600s
   ```

3. 入口：平台 Ingress 将 HTTPS `/smart-bot` 原样转发到 Service `titu-assistant.app-zone:80`，并关闭 SSE 缓冲。

### 6.2 发版：更新应用镜像（代码 / 依赖 / 知识文档变更）

适用：修改了应用代码、依赖、`../../../../knowledge_sources` 知识文档、`data/media.json` 图片登记，打了新镜像。发版固定五步，**顺序不能乱**：

```bash
# 1) 缩容旧版本（RWO 卷不允许两个 Pod 同时挂载，且避免初始化与旧版本并发写库）
kubectl -n app-zone scale deployment/titu-assistant --replicas=0
kubectl -n app-zone wait --for=delete pod -l smarttitu-role=app --timeout=240s

# 2) 删除上次的一次性 Job（Job 模板不可变更，不删无法重新 apply）
kubectl -n app-zone delete job titu-assistant-init --ignore-not-found

# 3) 修改清单：40-deployment.yml 与 90-init-job.yml 的 image 换成新标签
#    （知识文档变更是随镜像交付的，改完镜像标签即可，无需改其他文件）

# 4) 重新应用并初始化（ingest 为增量：未变化的文档直接跳过）
kubectl apply -f .

# 5) 等待初始化与新版本就绪
kubectl -n app-zone wait --for=condition=complete job/titu-assistant-init --timeout=1800s
kubectl -n app-zone rollout status deployment/titu-assistant --timeout=600s
```

> 为什么发版要重跑 init Job：新镜像可能带了新知识文档需要增量入库，且 Job 最后的 `doctor --models` 会确认新镜像内的知识与向量索引兼容，再放行新版本 Pod。

### 6.3 仅更新配置（镜像不变）

只调整运行参数（限流阈值、FRAME_ORIGINS、日志保留天数等）时，**不需要打新镜像**，走与 6.2 相同的五步流程——因为 Job 模板不可变更，改配置同样要先删 Job 再 apply，只是第 3 步改为修改 `../10-configmap.yml` 或 `../20-secret.yml`：

```bash
# 1) 2) 同 6.2：缩容、删旧 Job
# 3) 修改 10-configmap.yml / 20-secret.yml 中的配置值
# 4) 5) 同 6.2：apply、等待 Job 完成与新 Pod 就绪
```

重跑 init Job 在这里的作用是**校验新配置**：阶段一检查配置完整性、PG/Milvus/模型接口连通性，最后 `doctor` 做端到端体检，全部通过才放行新 Pod；知识入库因增量缓存执行很快。

> **修改 Embedding 相关配置的特殊处理**：变更 `EMBEDDING_MODEL`、`EMBEDDING_REVISION` 或切片参数后，既有向量索引与新配置指纹不一致，增量 ingest 会拒绝执行。需同时把 `90-init-job.yml` 中命令的 `python manage.py ingest` 改为 `python manage.py ingest --rebuild` 做全量重建（ Milvus 维度不一致时按提示更换 `MILVUS_COLLECTION` 前缀）。重建完成、新版本就绪后，把 `--rebuild` 从命令中去掉，避免以后每次发版都全量重建。

### 6.4 日常运维：状态与日志

```bash
# 总览：Deployment / Service / PVC / Job / Pod（按应用标签过滤）
kubectl -n app-zone get deployment,service,pvc,job,pod -l app.kubernetes.io/name=titu-assistant

# 初始化 Job 日志（部署/发版卡住时先看这里）
kubectl -n app-zone logs job/titu-assistant-init

# 应用运行日志
kubectl -n app-zone logs deployment/titu-assistant --tail=100 -f

# 资源占用与事件
kubectl -n app-zone top pod -l smarttitu-role=app
kubectl -n app-zone describe pod -l smarttitu-role=app      # 镜像拉取、PVC 挂载事件
```

### 6.5 停止与恢复

```bash
# 停止服务（Pod 退出后 RWO 卷自动释放；ConfigMap/Secret/PVC/Job 记录均保留）
kubectl -n app-zone scale deployment/titu-assistant --replicas=0
kubectl -n app-zone wait --for=delete pod -l smarttitu-role=app --timeout=240s

# 恢复服务（配置与镜像未变时，直接扩容即可，无需重跑 init Job）
kubectl -n app-zone scale deployment/titu-assistant --replicas=1
kubectl -n app-zone rollout status deployment/titu-assistant --timeout=600s
```

> 若停止期间改过 ConfigMap / Secret，按 6.3 流程走一遍（重跑 init Job 校验新配置）再恢复。

### 6.6 回滚

```bash
# 应用镜像回滚到上一版本（K8s 保留的历史 ReplicaSet 模板）
kubectl -n app-zone rollout undo deployment/titu-assistant
kubectl -n app-zone rollout status deployment/titu-assistant --timeout=600s

# 查看可回滚的历史版本
kubectl -n app-zone rollout history deployment/titu-assistant
```

注意两点：

- `rollout undo` 只回滚 **Deployment 模板**（镜像、探针、资源等）；期间如果改过 ConfigMap / Secret，**不会**自动回滚，需把清单文件改回旧值后 `kubectl apply -f 10-configmap.yml -f 20-secret.yml`（改配置本身不需要重启 Pod，应用在下次请求时读取环境变量仅在 Pod 重建后生效——严格来说环境变量在容器启动时注入，回滚配置后需 `rollout restart deployment/titu-assistant` 让 Pod 重建）。
- 若新版本发版时 init Job 做过知识入库（增量），回滚镜像后知识索引仍兼容（修订机制保证检索命中有效版本）；只有 Embedding 配置发生过全量重建时，旧镜像才会因维度不一致无法使用，此时应按 6.2 发一个回退版本而非 rollout undo。

### 6.7 卸载

```bash
kubectl -n app-zone delete job titu-assistant-init --ignore-not-found
kubectl -n app-zone delete deployment titu-assistant
kubectl -n app-zone delete service titu-assistant
kubectl -n app-zone delete configmap titu-assistant-config
kubectl -n app-zone delete secret titu-assistant-secret

# PVC 保存运行数据（日志、PDF 图片），确认不再需要时才删除
kubectl -n app-zone delete pvc titu-assistant-var

# 命名空间内已无其他资源时，一并删除
kubectl delete namespace app-zone
```

> 卸载只影响 K8s 内的应用资源；PG 中的业务数据与 Milvus 中的知识集合不受影响，如需彻底清理需另行处理（同前缀重建部署时会被初始化检查识别为"属于其他部署"而拒绝，需用新的 `MILVUS_COLLECTION` 前缀或清理旧集合）。

### 6.8 排查速查

| 现象 | 排查命令 |
|---|---|
| init Job 卡住 / 失败 | `kubectl -n app-zone logs job/titu-assistant-init`；失败阶段与原因见 [`init-job.md`](init-job.md) 第三节 |
| Pod 一直 Not Ready | `kubectl -n app-zone describe pod -l smarttitu-role=app`；看镜像拉取、PVC 挂载事件 |
| 镜像拉取失败 | 核对 `../40-deployment.yml` 的 image 与推送标签一致；仓库需认证时启用 `imagePullSecrets` |
| PVC Pending | `kubectl -n app-zone describe pvc titu-assistant-var`；核对 `longhorn-postgres` StorageClass 存在且正常 |
| 服务 502 / 无响应 | `kubectl -n app-zone logs deployment/titu-assistant --tail=200`；检查 Ingress 转发与 SSE 缓冲配置 |

## 七、注意事项

- **内容变化必须换新标签**：修改代码、依赖或知识文件后，用新的标签重新 build + push，并在 `../40-deployment.yml` 与 `90-init-job.yml` 中同步更新镜像地址。
- **知识文档 / 图片更新**：`../../../../knowledge_sources`、`app/static/media/`、`data/media.json` 随镜像交付，更新它们同样要打新镜像；知识入库在发版流程的 init Job 中自动增量执行。
- **依赖变更**：更新 `requirements.txt` 后需同步 `requirements.lock`（镜像按 lock 安装），再打新镜像。
- **密钥安全**：`../../../../.dockerignore` 已排除 `.env`、`var/`、`tests/` 等，配置与密钥不会进入镜像；不要为了"方便"在 Dockerfile 或构建命令中注入密钥。
- **配置即清单**：所有运行配置都在本目录 yml 中维护，改配置 = 改文件 + 按 6.3 重放流程；不要在集群里 `kubectl edit` 直接改，否则下次 apply 会被本地文件覆盖。
