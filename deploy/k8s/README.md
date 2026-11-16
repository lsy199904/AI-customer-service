# SmartTITU 匿名客服 · Kubernetes 部署

面向 `release-anonymous-20261111` 及后续同构版本。目标形态：

- **有状态依赖全部外置**：PostgreSQL 走托管实例，Milvus 独立部署，三个模型服务外置。
- 集群内只跑**一个单副本 Deployment**，外加按需触发的一次性 ingest Job。
- 单机 compose 那套 `deploy/*.yaml` 保持不动，两套并存互不影响。

## 1 目录结构

```
deploy/k8s/
├── Makefile                  # 唯一操作入口，靠 ENV 切换环境
├── base/                     # 环境无关
│   ├── kustomization.yaml
│   ├── config/               # ConfigMap 生成器（独立目录，jobs 复用）
│   │   ├── kustomization.yaml
│   │   └── config.env
│   ├── deployment.yaml       # 单副本 + Recreate + 4 个 subPath 挂载
│   ├── service.yaml
│   ├── ingress.yaml
│   └── pvc.yaml              # 两块 RWO 云盘
├── components/netpol/        # 可选组件：NetworkPolicy
├── overlays/
│   ├── dev/                  # 开发：默认 SC、无 TLS、正文日志
│   ├── uat/                  # 验收：与 prod 同构，独立数据
│   └── prod/                 # 生产
├── jobs/
│   ├── base/                 # Job 模板
│   ├── ingest/               # 增量入库
│   └── rebuild/              # 全量重建（只有 args 不同）
└── sql/bootstrap-db.sql      # 外部 PostgreSQL 初始化
```

`base` 不写 namespace，由 overlay 注入。每个 overlay 只有 4~5 个文件：`kustomization.yaml`、`namespace.yaml`、`config-patch.yaml`、`ingress-patch.yaml`，dev 多一个 `storage.yaml`。

三个环境的 PVC **只差 `storageClassName` 一个字段**（容量、访问模式完全相同），所以这个值定在 `base/pvc.yaml` 里作为生产基准（云盘），只有 dev 用一个 patch 覆盖成集群默认 SC。uat 与 prod 共用 base 的值、在各自命名空间里创建独立实例，不需要额外文件。

## 2 结构决策

### 2.1 单副本是本项目的目标形态

业务是内部客服，并发个位数；而且代码里有三处依赖"单写者"：

| 机制 | 位置 | 多副本会怎样 |
|---|---|---|
| `fcntl.flock` 会话日志锁 | `conversation_logs.py:32` | 共享 NFS 上 flock 不可靠 |
| `os.replace` 原子重写 | `conversation_logs.py:72` | 两个 Pod 互相覆盖 |
| 日志文件名含 pid | `observability.py:112` | 容器内 pid 恒为 1，文件名撞 |

所以 `strategy: Recreate` + 单副本，接受更新时 20~30 秒中断。扩副本的前置改造见 §8。

### 2.2 Job 不进 base

Job 进 base 的话，`apply` 每次都会碰它。配合 `ttlSecondsAfterFinished`，Job 被 GC 后下一次 apply 会**重新入库一遍**。所以入库是独立入口 `jobs/ingest`、`jobs/rebuild`。

两个入口共用 `jobs/base`，差异只有 `args`，用 JSON6902 patch 表达：

```yaml
patches:
  - target: {kind: Job, name: assistant-ingest}
    patch: |-
      - op: replace
        path: /metadata/name
        value: assistant-ingest-rebuild
      - op: replace
        path: /spec/template/spec/containers/0/args
        value: ["ingest", "--rebuild"]
```

改名字是必须的：Job 的 `spec` 不可变，同名改 args 会报 `field is immutable`。

### 2.3 ConfigMap 关掉名字哈希

`configMapGenerator` 默认给名字加内容哈希，好处是改配置自动滚更，但它让 overlay 无法用稳定名 patch 单个键。这里选稳定名字：

- 三个 overlay 的 `config-patch.yaml` 只写差异键；
- `jobs/*` 能直接用同一份配置；
- 代价是**改完 `config.env` 必须滚动重启**，`make apply` 已内置 `rollout restart`。

> kustomize v5 起，`disableNameSuffixHash` 必须写在生成器的 `options` 下，写到条目顶层的旧写法会报 `unknown field`。

### 2.4 配置生成器单独成目录

`base/config/` 是个只有 `configMapGenerator` 的 kustomization，被 `base/` 和 `jobs/*` 同时引用，避免 Job 把 Deployment 一起渲染进来。

> kustomize 默认的 `LoadRestrictionsRootOnly` 只允许引用上级**目录**，不允许上级**文件**
> （`resources: [../job.yaml]` 报 `security; file ... is not in or below`）。复用只能靠目录化。

## 3 四个硬约束（改之前必读）

### 3.1 模型地址只接受 HTTPS 或私网 IP

`app/core.py` 的 `Settings.validate()`：

```python
try: private = ipaddress.ip_address(parsed.hostname).is_private
except ValueError: private = parsed.hostname == 'localhost'
```

**`http://llm:8000/v1` 和 `http://llm.svc.cluster.local:8000/v1` 都会被拒绝**，Pod 起不来。

| 做法 | 配置 | 代价 |
|---|---|---|
| **A. 模型走 HTTPS** | `MODEL_BASE_URL=https://llm.example.com/v1` | 需证书；无需 `MODEL_HTTP_ORIGINS` |
| **B. 固定 ClusterIP** | Service 写死 `spec.clusterIP: 10.96.0.20`，配置写 IP | IP 进配置 |
| C. 改代码放宽 | 与 `app/rag.py:validate_endpoint` 对齐 | 需回归 |

> Embedding / Rerank 的校验比生成宽松：`http://embed:8000` 能过，`http://llm:8000` 不能。
> 这种不对称容易表现为"向量化通了、生成挂了"。

### 3.2 外部 PostgreSQL 必须给 database 级 CREATE

启动会 `CREATE SCHEMA IF NOT EXISTS assistant|knowledge`、建表、`ALTER TABLE messages ADD COLUMN`。
PostgreSQL 对**已存在**的 schema 执行 `CREATE SCHEMA IF NOT EXISTS` 仍然检查 database 的 CREATE 权限：

```sql
GRANT CONNECT, CREATE ON DATABASE ai_customer TO assistant_runtime;
```

漏掉会以 `permission denied for database` 崩溃重启，日志里看不到直接原因。

### 3.3 连接池上限硬编码

| 用途 | 位置 | max_size |
|---|---|---|
| 会话 / 工作流元数据 | `storage.py:PostgresDB` | 40 |
| 知识元数据 | `storage.py:document_connection` | 12 |
| LangGraph 检查点 | `workflow.py` | 8 |

上限 60/Pod，`min_size=1`，稳态 3~6 条。1C2G 的 RDS 给 200 个可用连接，单副本峰值 60，**够用**。

不要用 PgBouncer 的 transaction 模式省连接：应用靠**会话级** `pg_try_advisory_lock` 做同会话互斥。

### 3.4 `/ready` 是重查询

`/ready` 会 `SELECT 1`、把全部知识 chunk 读进内存（`rag.py:303`）、再查 Milvus collection。数据库是 1C2G 时单核会被打满，所以：

- `readinessProbe.periodSeconds: 60`（不是 30）
- `SESSION_CLEANUP_INTERVAL_SECONDS: 1800`（不是 300）

这两个值在 base 里已调好。要提速的正解是把 `rows` 改成按 `rag_state.generation` 失效的内存缓存。

## 4 存储设计

**两块 RWO 云盘，不是三块。**

| 盘 | 挂载点（subPath） | 内容 | 实际占用 | 可丢性 |
|---|---|---|---|---|
| `assistant-var` 20Gi | `/ai_customer/var/logs`（`logs`）<br>`/ai_customer/var/cost-reports`（`cost-reports`） | 运行日志、会话归档、成本报表 | < 3GiB | 可丢 |
| `assistant-data` 20Gi | `/ai_customer/var/pdf_media`（`pdf_media`）<br>`/ai_customer/knowledge_sources`（`knowledge_sources`） | PDF 提取图片、源文档 | < 300MiB | **不可丢** |

`/ai_customer/var` 根目录是 emptyDir（代码启动时会 `mkdir`，而根文件系统只读），真正持久化的四个目录从两块盘按 subPath 挂进来。

**为什么不用 NAS（RWX）**：`conversation_logs.py` 用 `flock` + `os.replace` 做会话日志互斥与原子重写，NFS 上这两件事都不可靠；而单副本根本用不到共享语义。同理**不能挂对象存储**（TOS/s3fs），rename/unlink 语义不对。

**容量说明**：日志 30 天 < 3GiB（单文件上限 20MB × `backupCount=4` × 30 天），图片+文档 < 300MiB。云盘只能扩不能缩，20Gi 起步是对的。

### ingest 与卷的互斥

`assistant-data` 是 RWO。应用占着这块盘时，ingest Job 若被调度到别的节点会挂载失败（Multi-Attach）。

`make ingest` / `make rebuild` 已经内置处理：**先缩容到 0 → 跑 Job → 恢复副本**。ingest 是几周一次的偶发操作，停 1~2 分钟可接受。跑完的 `scale-up` 同时让 `MediaCatalog` 重新加载新图片（它只在启动时加载一次，`core.py:346`）。

## 5 环境差异

| 项 | dev | uat | prod |
|---|---|---|---|
| namespace | `smarttitu-dev` | `smarttitu-uat` | `smarttitu` |
| 域名 | `assistant-dev.example.com` | `assistant-uat.example.com` | `assistant.smarttitu.cn` |
| TLS | 无 | 有 | 有 |
| Cookie Secure | false | true | true |
| 正文日志 | 开（保留 1 天） | 关 | 关 |
| 日志保留 | 7 天 | 14 天 | 30 天 |
| 限流 | 60/min | 20/min | 20/min |
| StorageClass | 集群默认（`standard`，dev 覆盖） | 云盘 SC（继承 base） | 云盘 SC（继承 base） |
| `MILVUS_COLLECTION` | `..._dev` | `..._uat` | `smarttitu_knowledge` |
| 镜像 tag | `:dev` | `:uat` | `:release-20261111` |

### 环境隔离三件套，缺一不可

| 资源 | 隔离方式 | 漏了会怎样 |
|---|---|---|
| 会话/知识数据 | **三个独立的 PostgreSQL 库**（或实例） | dev 的会话污染生产历史 |
| 向量 | **每个 overlay 不同的 `MILVUS_COLLECTION`** | 见下 |
| 对象/配置 | namespace + ConfigMap | 端口、域名串环境 |

`MILVUS_COLLECTION` 这条最容易漏：最终 collection 名是 **`该值 + '_' + embedding fingerprint 前 16 位`**（`vectors.py:14`）。三个环境若用同一个 embedding 模型，fingerprint 相同，**collection 名就完全一样**，共用 Milvus 实例时向量会互相污染。所以每个 overlay 都覆盖了这个值。

## 6 首次部署

```bash
# 1) 镜像（三个环境用同一仓库，不同 tag）
docker build -t harbor.example.com/ai/smarttitu-assistant:release-20261111 .
docker push  harbor.example.com/ai/smarttitu-assistant:release-20261111
docker tag    harbor.example.com/ai/smarttitu-assistant:release-20261111 \
              harbor.example.com/ai/smarttitu-assistant:uat
docker tag    harbor.example.com/ai/smarttitu-assistant:release-20261111 \
              harbor.example.com/ai/smarttitu-assistant:dev

# 2) 每个环境一套独立的 PostgreSQL
psql "postgresql://postgres@pg.internal:5432/postgres" -f deploy/k8s/sql/bootstrap-db.sql

# 3) 改配置：base/config/config.env 的模型与 Milvus 地址；
#            overlays/<env>/ 的域名与 collection 前缀；
#            base/pvc.yaml 的 storageClassName 换成集群实际云盘 SC 名（dev 在 storage.yaml 覆盖）
make -C deploy/k8s diff ENV=dev
make -C deploy/k8s apply ENV=dev      # 首次 Pod 会因缺 Secret 而 Pending，属预期

# 4) 密钥：刻意不纳入 kustomize，避免落进 Git
kubectl -n smarttitu-dev create secret generic assistant-secret \
  --from-literal=AUTH_SECRET="$(openssl rand -base64 48 | tr -d '\n')" \
  --from-literal=OPERATIONS_TOKEN="$(openssl rand -base64 32 | tr -d '\n')" \
  --from-literal=DATABASE_URL='postgresql://assistant_runtime:密码@pg.internal:5432/ai_customer?sslmode=require' \
  --from-literal=MILVUS_TOKEN='用户名:密码' \
  --from-literal=MODEL_API_KEY='...' \
  --from-literal=EMBEDDING_API_KEY='...' \
  --from-literal=RERANK_API_KEY='...'
#   MILVUS_TOKEN 注意：自建 Milvus 是 root:密码；火山 Milvus Serverless 的
#   用户名由系统自动生成，要去实例详情页看，不能照抄 root。

# 5) 灌知识源
kubectl -n smarttitu-dev apply -f - <<'EOF'
apiVersion: v1
kind: Pod
metadata: {name: knowledge-loader, namespace: smarttitu-dev}
spec:
  restartPolicy: Never
  containers:
  - name: loader
    image: busybox:1.36
    command: ["sh","-c","sleep 3600"]
    volumeMounts: [{name: d, mountPath: /data, subPath: knowledge_sources}]
  volumes:
  - name: d
    persistentVolumeClaim: {claimName: assistant-data}
EOF
kubectl -n smarttitu-dev wait --for=condition=Ready pod/knowledge-loader --timeout=120s
kubectl -n smarttitu-dev cp ./knowledge_sources/. knowledge-loader:/data/
kubectl -n smarttitu-dev delete pod knowledge-loader

# 6) 入库 → 起应用（make ingest 会自动缩容/恢复）
make -C deploy/k8s ingest ENV=dev
make -C deploy/k8s apply  ENV=dev

# 7) 验收
kubectl -n smarttitu-dev port-forward svc/assistant 8200:8200 &
curl -fsS http://127.0.0.1:8200/smart-bot/health
curl -fsS http://127.0.0.1:8200/smart-bot/ready
```

上线顺序：**dev 跑通 → uat 用真实域名和证书复验 → prod**。uat 与 prod 的配置差异应该只剩域名、collection 前缀和日志保留期，任何其它差异都会让验收失去意义。

## 7 日常操作

| 场景 | 命令 |
|---|---|
| 看渲染结果（不碰集群） | `make render ENV=prod` |
| 与集群对比 | `make diff ENV=uat` |
| 发布 | `make apply ENV=prod` |
| 只改配置后生效 | `make apply ENV=prod`（含 rollout restart） |
| 新增/修改文档 | `make ingest ENV=prod` |
| 换 Embedding 模型 | 改 `EMBEDDING_REVISION` 与模型名 → `make rebuild ENV=prod` |
| 临时下线 | `make scale-down ENV=dev` |
| 回滚 | 见 §10 |

验证模型链路（等价单机 `v3.sh doctor --models`，会真实打三个模型接口）：

```bash
kubectl -n smarttitu apply -f - <<'EOF'
apiVersion: batch/v1
kind: Job
metadata: {name: assistant-doctor, namespace: smarttitu}
spec:
  backoffLimit: 0
  ttlSecondsAfterFinished: 3600
  template:
    spec:
      restartPolicy: Never
      securityContext: {runAsNonRoot: true, runAsUser: 10001, fsGroup: 10001}
      containers:
      - name: doctor
        image: harbor.example.com/ai/smarttitu-assistant:release-20261111
        command: ["python", "manage.py", "doctor", "--models"]
        envFrom:
        - configMapRef: {name: assistant-config}
        - secretRef: {name: assistant-secret}
        volumeMounts:
        - {name: v, mountPath: /ai_customer/var}
        - {name: d, mountPath: /ai_customer/var/pdf_media, subPath: pdf_media}
        - {name: t, mountPath: /tmp}
      volumes:
      - {name: v, emptyDir: {}}
      - {name: d, persistentVolumeClaim: {claimName: assistant-data}}
      - {name: t, emptyDir: {}}
EOF
kubectl -n smarttitu logs -f job/assistant-doctor
```

## 8 扩到多副本之前

跨 Pod 的正确性已经具备（会话互斥走 PG advisory lock，限流在 `tenant_message_limits` 表里 `SELECT ... FOR UPDATE`，检查点在 PG）。但**先做日志外置，再扩副本**，顺序反过来会立刻踩 §2.1 的三个坑：

1. 日志改走 stdout → 火山 TLS/CLS，容器不挂日志卷（`observability.configure()` 本来就有 `StreamHandler`，`kubectl logs` 已能看到，只是没有 30 天留存）
2. `pdf_media` 换 RWX 或加 sidecar 同步到对象存储
3. 副本数 2 + PDB（此时才有意义）+ 核对 PG 连接数（2 × 60 = 120，仍 < 200）
4. 把 readiness 的 `periodSeconds` 再放宽，避免 N 倍扫描

## 9 排障对照

| 现象 | 先看哪里 |
|---|---|
| CrashLoop，"内网HTTP模型需将准确来源…" | §3.1，模型地址用了 Service 短名 |
| CrashLoop，`permission denied for database` | §3.2，缺 `GRANT CREATE ON DATABASE` |
| Pending，事件里 `secret "assistant-secret" not found` | 第 4 步没做，或做在了别的 namespace |
| Pending，`Multi-Attach error` | RWO 云盘被占：用 `make ingest` 而不是直接 apply Job |
| 长期 `NotReady`，`/ready` 返回 `index_empty` | 没跑 ingest，或知识没灌进 `assistant-data` |
| `/ready` 返回 `index_unavailable` | Milvus 没有当前 fingerprint 的 collection |
| 回答正确但引用了 dev 的知识 | `MILVUS_COLLECTION` 三个环境撞名（§5） |
| 图片 404 | ingest 后没触发 `scale-up`，`MediaCatalog` 只在启动时加载 |
| 前端收到整段回答而非流式 | Ingress 丢了 `proxy-buffering: "off"` |
| 所有接口 404 | Ingress 加了 rewrite，把 `/smart-bot` strip 掉了 |
| 改了 config.env 但行为没变 | 哈希已关闭，不会自动滚更，执行 `make apply` |
| 日志里出现 `用量报告写入失败` | `COST_REPORT_DIR` 不是绝对路径，见 `config.env` |
| Job 报 `field is immutable` | Job spec 不可变，先 `delete job` 再 apply |

## 10 回滚

```bash
# 镜像回滚
kubectl -n smarttitu set image deploy/assistant \
  assistant=harbor.example.com/ai/smarttitu-assistant:<旧标签>
kubectl -n smarttitu rollout status deploy/assistant

# 清单回滚（如果用了 GitOps 之外的直接 apply）
kubectl -n smarttitu apply -k deploy/k8s/overlays/prod   # 切回对应 commit
```

同时改过 Embedding 模型或 `EMBEDDING_REVISION` 时，回滚后 collection 名回到旧 fingerprint，旧向量仍可查；新版写入的 chunk 留在 PG 里，按文档用 `manage.py deactivate` 处理，不要直接删表。

**不要删 PVC**：`assistant-data` 里有被回答引用的图片和源文档，删了只能重跑 ingest 并重新灌文档。日志盘可丢。
