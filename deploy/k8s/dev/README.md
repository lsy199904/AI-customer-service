# K8s dev 原生 YAML：数据库/Milvus 初始化与 App 发布

发布顺序固定为：

```text
分别构建 assistant 应用镜像与 db-migrate 迁移镜像（同一 tag，Flyway 与 SQL 资产只在后者）
        │
        ▼
停掉 App（scale 0），释放 ReadWriteOnce 卷 titu-assistant-var
        │
        ▼
运行 db-migrate Job（独立 db-migrate 镜像，Flyway migrate，幂等；不挂卷）
        │  失败 → 停止，不启动 App
        ▼
运行知识初始化 Job（复用 assistant 镜像 + 同一块 PVC）
  脚本 `database/milvus/knowledge-init.sh` 四步串行：算集合名 → 建/核对集合 → ingest 入库 → doctor --models
        │  失败 → 停止，不启动 App
        ▼
删除 Job，等 Pod 退出（彻底释放 RWO 卷）
        │
        ▼
apply Deployment
        │
        ▼
App 启动（读取 PVC 上 /srv/assistant/var 的数据）
```

SQL 侧的目录、命名、版本规范见 [`../../../database/postgres/README.md`](../../../database/postgres/README.md)。

## 资源一览

| 资源 | 作用 | 执行时机 |
|---|---|---|
| `40-job-db-migrate.yaml` | 独立 Job，使用独立的 db-migrate 镜像执行 `flyway migrate` | 每次发布前先删除旧 Job、apply 本清单并等待完成；先于 Deployment 执行 |
| `50-job-milvus-init.yaml` | 独立 Job，复用 assistant 应用镜像执行 `database/milvus/knowledge-init.sh`：建/核对集合 → `manage.py ingest` → `doctor --models`；挂载与 App **相同的 PVC** `titu-assistant-var`（`/srv/assistant/var`） | 每次发布前先删除旧 Job、apply 本清单并等待完成；结束并删除 Job 后再启动 Deployment |
| `60-deployment.yml` | App Pod | 每次 apply / Pod 重启；当前清单未启用 `db-verify` / `knowledge-ingest` Init 容器 |

当前阶段使用 K8s 原生 YAML，不启用 Kustomize。`40-job-db-migrate.yaml` 与 `50-job-milvus-init.yaml` 保持独立清单，由发布流程显式按顺序先执行并等待完成；顺序不依赖目录批量 apply。

镜像引用分两类：**db-migrate Job 用独立的 db-migrate 镜像**（Flyway 运行时 + SQL 资产）；**app Deployment 与 milvus Job 用同一个 assistant 应用镜像**。两个镜像用同一 tag 配套构建，但镜像名不同，不能混用。

**Milvus 任务为什么复用 assistant 镜像**：集合名 = `MILVUS_COLLECTION` 前缀 + `RAGSettings.fingerprint[:16]`，指纹依赖 app 中的代码常量；入库用的解析器、切片参数、Embedding 协议也必须与 App 完全一致，否则 `revision` / `fingerprint` 会漂移。用同一镜像、同一个 `manage.py` 完成全部四步，可以消除跨镜像传字符串和第二套实现；任务本身仍是独立 Job，与 App 生命周期解耦。

**四步为什么必须串行**：集合未就绪时 `ingest` 会自己 `ensure`，但那样就跳过了 `02_milvus.py` 的索引参数严格核对；`doctor --models` 又要求集合可检索、知识已写入。所以顺序固定为「建集合 → 入库 → 自检」，任一步失败即退出，Job 失败即发布失败。

**为什么还要挂同一块 PVC**：入库与 PDF 解析的产物（`var/pdf_media/`、`var/rag.sqlite3`、`var/assistant.db`）都写在 `/srv/assistant/var`，App 启动后直接从该目录读取。Job 与 App 挂同一个 `titu-assistant-var`、同一个 `mountPath`，路径与属主（UID/GID 10001）完全一致，Job 内产生的文件 App 能直接读到。

## 幂等如何成立

| 场景 | Job 行为 | App 行为 |
|---|---|---|
| 初次部署（空库） | `migrate` 执行 `V1.0.0` 全量建表 + 写入归属凭证行 | `db-verify` 通过；ingest 全量入库 |
| 版本升级 | 只执行新增版本；已执行版本为 no-op | `db-verify` 通过；ingest 增量入库 |
| 重复发布 / Pod 重启 | 再次 `migrate` 为 no-op（Flyway 按版本记录判断） | `db-verify` 通过；ingest 指纹无变化时秒级完成 |
| 未执行 Job 直接发 App | — | `validate` 检测到 pending 或缺少 history，Init 失败，App 不启动 |

发布步骤里都是先 `delete` 再 `apply` 同名 Job，所以可以重复使用；Flyway 本身也通过 `flyway_schema_history` 保证幂等。并发保护由 Flyway 的 PostgreSQL advisory lock 提供。

## 前置条件

1. Secret `titu-assistant-secret` 含 `DATABASE_URL` 与 `AUTH_SECRET`（知识 Job 的 `ingest` / `doctor` 走与 App 相同的 `Settings.validate()`）；db-migrate Job 的 entrypoint 会把 `DATABASE_URL` 转为 Flyway 的 JDBC 三要素。
2. ConfigMap `titu-assistant-config` 含 `DEPLOYMENT_ID`、`MILVUS_URI`、`MILVUS_DATABASE`、`MILVUS_COLLECTION`；它们会作为 `FLYWAY_PLACEHOLDERS_*` 注入 Job。
3. **构建两个镜像**：`assistant` 应用镜像（纯 Python 运行，**不含 Flyway**）与 `db-migrate` 迁移镜像（Flyway 运行时 + `flyway.conf` + `migrations/`），两者使用同一 tag 配套构建推送。app Deployment 与 milvus Job 用 `assistant`，db-migrate Job 用 `db-migrate`，不能混用。
4. ConfigMap `titu-assistant-config` 与 Secret `titu-assistant-secret` 同时供 App 与两个 Job 使用；Milvus 任务需要 `VECTOR_BACKEND=milvus`、`MILVUS_*` 与 `EMBEDDING_*` 与 App 完全一致。
5. PVC `titu-assistant-var` 已存在，**App 与 milvus-init Job 共用**（`ReadWriteOnce`，挂载路径 `/srv/assistant/var`）。RWO 卷只允许同一节点上的多个 Pod 同时挂载，因此发布时先停 App；Job 结束后还要删除 Job，卷才会真正释放。

### 数据库连接从哪来

整个应用只在 Secret `titu-assistant-secret` 里维护**一个** `DATABASE_URL`，迁移与应用共用同一个值，不做第二份配置。

| 使用方 | 变量 | 注入方式 |
|---|---|---|
| App | `DATABASE_URL` | `envFrom` 整包注入 Secret |
| db-migrate Job | `DATABASE_URL` | `secretKeyRef` 单键注入 |

```text
Secret: DATABASE_URL
   postgresql://user:pass@host:5432/db?sslmode=disable
        │
        ├─ App / ingest ────────────────► 直接使用 libpq URI
        │
        └─ db-migrate Job
              │ /flyway/entrypoint.sh
              ├─ FLYWAY_URL      = jdbc:postgresql://host:5432/db?sslmode=disable
              ├─ FLYWAY_USER     = user
              └─ FLYWAY_PASSWORD = pass
                     │
                     └─────────────► flyway migrate / validate
```

转换规则（`../../docker/db-migrate/entrypoint.sh`）：

- 只向 JDBC 透传 `sslmode`，其余 libpq 专有参数忽略，避免 Flyway 报未知参数；
- 密码支持原始字符（`#`、`@`、`!`、`=` 等），也支持 `%XX` 编码，两种都能还原；
- 已显式设置 `FLYWAY_URL` 时优先使用，便于本地调试或临时覆盖；
- `postgres://` 与 `postgresql://` 两种前缀都接受。

`../../../database/postgres/flyway.conf` 不含任何连接信息，凭证不会进入镜像层。

> 密码里含 `#` 时，标准 URI 会把它当作片段分隔符。当前入口脚本按最后一个 `@` 切分凭证、不做片段解析，因此能正确还原；但如果换用其它按 RFC 3986 解析的工具，建议把 `#` 写成 `%23`。

## 构建镜像

两个镜像各占一个目录，Dockerfile 与构建脚本同放其中；构建上下文都是仓库根目录：

```text
deploy/docker/
├── app/
│   ├── Dockerfile            # assistant 应用镜像：纯 Python，不含 Flyway
│   └── build.sh
└── db-migrate/
    ├── Dockerfile            # db-migrate 镜像：Flyway + flyway.conf + migrations/
    ├── entrypoint.sh         # 把 DATABASE_URL 转成 FLYWAY_URL / USER / PASSWORD
    └── build.sh
```

```bash
# 1. SQL 执行镜像（Flyway）
deploy/docker/db-migrate/build.sh -t v1.0.0-20261120 --push

# 2. 应用镜像：与 db-migrate 使用同一个 tag
deploy/docker/app/build.sh -t v1.0.0-20261120 --push
```

职责边界：**Flyway 只存在于 db-migrate 镜像**；app 镜像只装 Python 依赖与应用代码，不装 Java 与迁移资产。db-migrate 镜像内 `/flyway/` 布局：

```text
/flyway/conf/flyway.conf
/flyway/flyway                 # Flyway CLI 启动脚本
/flyway/migrations/            # V*.sql、callbacks/、conversation/、quota/ 等领域目录
/flyway/entrypoint.sh          # 把 DATABASE_URL 转成 FLYWAY_URL / USER / PASSWORD
```

`db-migrate/build.sh` 构建后会自动列出镜像内 `/flyway/migrations`，确认 SQL 资产已打入。`REGISTRY` / `IMAGE_REF` 可按环境覆盖，`FLYWAY_IMAGE` 仅对 db-migrate 有效，`build.sh --help` 查看全部选项。

## 发布步骤

手工执行，顺序不能调换。命令以仓库 `deploy/` 为当前目录；`NS` 必须与清单里写死的 `namespace: app-zone` 一致，不要另起命名空间。

### 0. 预检

```bash
NS=app-zone

# 清单里的命名空间应全部是 app-zone
grep -h '^  namespace:' k8s/dev/*.yml | sort -u

# 本次要发的镜像 vs 集群里正在跑的镜像；两行相同说明 tag 没换
grep -m1 'image:' k8s/dev/60-deployment.yml
kubectl -n $NS get deploy titu-assistant \
  -o jsonpath='{.spec.template.spec.containers[0].image}' 2>/dev/null; echo
```

两个镜像必须用同一个新 tag 配套构建。`imagePullPolicy: IfNotPresent` 下同名 tag 不会重新拉取——tag 没换就等于没发版。

### 1. 停 App，释放 ReadWriteOnce 卷

```bash
if kubectl -n $NS get deployment/titu-assistant >/dev/null 2>&1; then
  kubectl -n $NS scale deployment/titu-assistant --replicas=0
fi

# 列表必须为空：Terminating / Completed 的 Pod 仍占着卷
kubectl -n $NS get pod -l app.kubernetes.io/name=titu-assistant,smarttitu-role=app
# 还有 Pod 就等它退出
kubectl -n $NS wait --for=delete pod \
  -l app.kubernetes.io/name=titu-assistant,smarttitu-role=app --timeout=300s
```

`kubectl scale` 不支持 `--ignore-not-found`（只有 `delete` 支持），首次发布要先 `get` 判断。也不要用 `2>/dev/null || true` 吞错——静默失败会带着卷占用去跑 Job，后面必然 `Multi-Attach`。

### 2. 数据库迁移 Job（不挂卷）

```bash
kubectl -n $NS delete job titu-db-migrate --ignore-not-found
kubectl -n $NS apply -f k8s/dev/40-job-db-migrate.yaml
kubectl -n $NS wait --for=condition=complete job/titu-db-migrate --timeout=600s
```

### 3. 知识初始化 Job（同一镜像、同一 PVC）

```bash
kubectl -n $NS delete job titu-milvus-init --ignore-not-found
kubectl -n $NS apply -f k8s/dev/50-job-milvus-init.yaml
kubectl -n $NS wait --for=condition=complete job/titu-milvus-init --timeout=1800s
kubectl -n $NS logs -l job-name=titu-milvus-init --all-containers=true --tail=200
```

首次全量入库要解析 PDF 并调 Embedding，可能十几分钟；超时上限与清单的 `activeDeadlineSeconds: 1800` 对齐。

> **注意**：`kubectl wait --for=condition=complete` 在 Job 失败时永远不为真，会白等到超时。另开窗口看进度，或直接查条件：
>
> ```bash
> kubectl -n $NS get job titu-db-migrate \
>   -o jsonpath='{range .status.conditions[*]}{.type}={.status}{"\n"}{end}'
> kubectl -n $NS get job titu-milvus-init \
>   -o jsonpath='{range .status.conditions[*]}{.type}={.status}{"\n"}{end}'
> ```
>
> 出现 `Failed=True` 就不要再往下走，先看日志定位问题。

### 4. 删 Job 并等 Pod 退出（彻底释放卷）

```bash
kubectl -n $NS delete job titu-milvus-init
kubectl -n $NS get pod -l job-name=titu-milvus-init    # 必须为空
```

`kubectl delete job` 是异步的：Pod 还在 Terminating 时卷仍被占用，紧接着起 App 一定卡在 `Multi-Attach`。`ttlSecondsAfterFinished: 600` 只是兜底，不能依赖。

### 5. 起新版

```bash
kubectl -n $NS apply -f k8s/dev/60-deployment.yml
kubectl -n $NS rollout status deployment/titu-assistant --timeout=900s
```

`apply` 会把副本数恢复为 1。`readinessProbe` 通过并再观察 `minReadySeconds: 10` 才算可用；到 `progressDeadlineSeconds: 900` 仍未就绪即判定失败。

### 6. 冒烟

```bash
# 在 Pod 内请求：不依赖 Ingress/DNS，也不要求镜像里有 curl
kubectl -n $NS exec deploy/titu-assistant -- python -c '
import urllib.request
r = urllib.request.urlopen("http://127.0.0.1:8201/smart-bot/ready", timeout=10)
print(r.status, r.read().decode("utf-8", "replace")[:200])
'
```

`/smart-bot/ready` 会查数据库连通性、知识行数、Milvus 集合是否存在，比 `/health` 更接近「真的能用」。宿主机 `curl https://域名/smart-bot/ready` 也可以，但会连带验证 Ingress/DNS，排障时要能区分是哪一层的问题。

当前 `60-deployment.yml` 没有 `db-verify` / `knowledge-ingest` Init 容器，顺序完全由人保证：不要跳过 Job 直接 apply Deployment。

## 失败恢复与回退

发布中断时先判断卡在哪一步，再按阶段选恢复方式——**两种阶段不能混用同一种恢复动作**。

| 卡住的位置 | App 状态 | Pod 模板 | 恢复动作 |
|---|---|---|---|
| 第 1 步：旧 Pod 没退出 | 0 副本 | 旧版 | 查 `kubectl describe pod` 的 Terminating 原因；必要时 `kubectl delete pod --force --grace-period=0` 后重试，**不要**带着占用跑 Job |
| 第 2/3 步：Job 失败 | 0 副本 | 旧版 | `scale --replicas=1` 把旧版拉回来；修好 SQL/配置后重跑对应 Job |
| 第 5 步：rollout 超时 | 有 Pod 但 `0/1 READY` | 新版 | `rollout undo` 回上一版 → 等就绪 → 冒烟 |
| 第 6 步：冒烟失败 | Pod Running | 新版 | 同上，`rollout undo` |
| 手工 Ctrl-C 打断 | 可能停在 0 副本 | 旧版 | `scale --replicas=1` |

**Job 阶段失败：只 `scale` 回 1，不要 `rollout undo`。** 此时 Pod 模板还没换过，`undo` 会退到更早的一版，等于多退一个版本。

```bash
# Job 阶段失败：恢复旧版（Pod 模板未变）
kubectl -n $NS scale deployment/titu-assistant --replicas=1
kubectl -n $NS rollout status deployment/titu-assistant --timeout=900s
kubectl -n $NS logs -l job-name=titu-db-migrate --all-containers=true --tail=200
```

**Deployment 阶段失败：`rollout undo` 后再复验。**

```bash
kubectl -n $NS rollout undo deployment/titu-assistant
kubectl -n $NS rollout status deployment/titu-assistant --timeout=900s
# 然后重跑「第 6 步」的冒烟
```

首次发布（`app-zone` 里还没有 Deployment）没有上一版：`rollout undo` 会报 `no rollout history found`，只能修好原因重发。`revisionHistoryLimit: 5` 决定最多能退几个版本。

两个 Job 都可安全重跑：Flyway 靠 `flyway_schema_history` 判重，ingest 在指纹未变时秒级 no-op，重复发布不会产生重复数据。

### 回退边界

| 对象 | 是否回退 | 说明 |
|---|---|---|
| 应用镜像 / Pod 模板 | ✅ `rollout undo` | 需 `revisionHistoryLimit > 0`（当前 5） |
| ConfigMap / Secret | ❌ 手工 | `rollout undo` 不改配置；本次若手工 apply 过配置，回退的 Pod 读到的仍是新配置，要另行回滚配置并重新 apply |
| 数据库 | ❌ | Flyway 无 undo。SQL 必须 N-1 兼容：只加表/加列/加索引，破坏性变更拆两次发布 |
| 知识库（PG + Milvus） | ❌ 也不需要 | `fingerprint` 变化时 `ingest` 在写入前就报错（`app/rag.py`），知识库保持原状，旧镜像可直接启动 |

唯一需要人工的特殊情况：曾手工执行过 `ingest --rebuild` 且 `fingerprint` 已改变。此时回退镜像后 `/ready` 会返回 `index_mismatch`，必须用**旧镜像**重跑一次知识 Job：

```bash
kubectl -n $NS delete job titu-milvus-init --ignore-not-found
sed "s#^\( *\)image: .*#\1image: <上一版镜像>#" deploy/k8s/dev/50-job-milvus-init.yaml \
  | kubectl -n $NS apply -f -
kubectl -n $NS logs -l job-name=titu-milvus-init -f
```

探针配置、阶段划分与验收标准见 [`docs/不停机升级与自动回退方案.md`](../../../docs/不停机升级与自动回退方案.md)。

### 停机更新验收清单

| 项 | 落地位置 | 状态 |
|---|---|---|
| 单副本 + 先停后起，不争 RWO 卷 | `60-deployment.yml` 的 `replicas: 1` + `strategy: Recreate` | ✅ |
| 停 App 早于挂卷 Job | 发布步骤第 1 步（`scale --replicas=0`） | ✅ |
| 卷真正释放（Pod 退出，而非容器结束） | 第 1、4 步都要求 Pod 列表为空 | ✅ |
| 迁移/入库失败不带着半成品启动 | 第 2/3 步确认 `Failed=True` 即停，不 apply Deployment | ✅ |
| 新版必须真的能服务才发流量 | `startupProbe` / `readinessProbe` + `minReadySeconds` | ✅ |
| 失败能回到可服务状态 | Job 阶段 scale 回 1；Deployment 阶段 `rollout undo` | ✅ |
| 回退后仍坏要能发现 | 回退后再等就绪 + 冒烟，不通过则人工介入 | ✅ |
| 同名 tag 不会静默用旧镜像 | 第 0 步比对镜像 + 每次构建唯一 tag | ⚠️ 靠纪律，非强制 |

## 失败排查

| 现象 | 查看位置 | 处理 |
|---|---|---|
| SQL Job 失败 | `kubectl -n app-zone logs -l job-name=titu-db-migrate --all-containers=true --tail=200` | 修复 SQL/配置后重新执行；若 `flyway_schema_history` 留下 failed 行，先用同一 db-migrate 镜像执行 `repair`，再重跑 Job |
| Milvus Job 失败 | `kubectl -n app-zone logs -l job-name=titu-milvus-init --all-containers=true --tail=200` | 日志里看 `==> N/4` 定位阶段：1 算集合名（检查 `MILVUS_*` / `EMBEDDING_*`）、2 建集合（集合结构与索引不符时只读报错，不要手工改集合）、3 入库（PG/Milvus 连通性、Embedding 额度）、4 自检（模型可达性） |
| 知识为空 | `kubectl -n app-zone exec deploy/titu-assistant -- python manage.py doctor` | 说明第 3 步没成功或写入的不是同一块卷；先确认 Job 已完成且 App 挂载的是 `titu-assistant-var` |
| Milvus Job 卡在 `ContainerCreating`，事件报 `Multi-Attach error for volume` | `kubectl -n app-zone describe pod -l job-name=titu-milvus-init` | `titu-assistant-var` 是 RWO 卷，仍被其它节点上的 App Pod 占用：先 `kubectl scale deployment/titu-assistant --replicas=0` 再重跑 Job，或临时用 `nodeSelector` 把 Job 固定到 App 所在节点 |
| App 卡在 `ContainerCreating`，事件报 `Multi-Attach error for volume` | `kubectl -n app-zone describe pod -l app.kubernetes.io/name=titu-assistant,smarttitu-role=app` | 发布第 3 步没删 Job，或 Job Pod 还没退出：`kubectl delete job titu-milvus-init` 并等 Pod 消失后再起 App |
| App 起不来 | `kubectl -n app-zone logs deploy/titu-assistant --tail=200` | 确认两个 Job 已成功完成；db-migrate Job 须用 db-migrate 镜像，App 与 milvus Job 用 assistant 镜像，两者 tag 一致 |
| Pod `Running` 但 `0/1 READY`，rollout 一直不结束 | `kubectl -n app-zone describe pod -l app.kubernetes.io/name=titu-assistant` 的 Readiness 事件 | `readinessProbe` 打的是 `/smart-bot/ready`：`index_empty` = 知识未入库（先跑知识 Job）；`index_unavailable` = 当前 fingerprint 算出的 Milvus 集合不存在（核对 `EMBEDDING_*` / `MILVUS_COLLECTION` 是否与镜像内代码一致）。这类 Pod 不会重启，只被摘流量 |
| db-migrate Job 里看不到 `callbacks/` 或领域目录 | 见下方“确认镜像内容” | 九成是用了旧镜像：同名 tag 未重新构建/推送，或节点缓存未刷新 |

**确认 db-migrate 镜像内容**（不要用 `docker run 镜像 ls`，`ls` 会被当成 Flyway 子命令）：

```bash
# 本地镜像
docker run --rm --entrypoint sh <db-migrate 镜像> -c 'ls -la /flyway/migrations /flyway/migrations/callbacks'

# 集群里实际拉到的镜像
kubectl -n app-zone run probe --rm -it --restart=Never --imagePullPolicy=Always \
  --image=<db-migrate 镜像> --command -- ls -la /flyway/migrations
```

`kubectl get pod -o jsonpath='{.status.containerStatuses[*].imageID}'` 可以看 Pod 真正使用的 digest，与 Harbor 上的 digest 对比即可确认是否被替换。

**回滚**：`kubectl -n app-zone rollout undo deployment/titu-assistant`，等就绪后再跑一次冒烟。数据库不回退；`flyway.ignoreMigrationPatterns=*:future` 允许旧镜像忽略未来版本，但依赖“SQL 变更兼容 N-1”的纪律。注意 `ConfigMap`/`Secret` 不受 `rollout undo` 影响——如果本次改过配置，退回去的 Pod 读到的仍是新配置。Job 阶段失败不要用 `rollout undo`，见「失败恢复与回退」。

## 运维注意

- **停机窗口**：`strategy: Recreate` 下旧 Pod 先停止；两个 Job 的耗时计入维护窗口。知识 Job 首次全量入库要解析 PDF 并调 Embedding，可能十几分钟；后续指纹未变时是秒级 no-op。**这不是配置疏漏**：`titu-assistant-var` 是 RWO 卷，`replicas: 2` 或 `RollingUpdate` 会让新 Pod 卡在 `Multi-Attach`。要真正不停机必须先拆卷（media 独立、SQLite 移出），见 `docs/不停机升级与自动回退方案.md` 阶段二。
- **入库也会调模型**：知识 Job 的 `ingest` 与 `doctor --models` 都消耗 Embedding/模型 API 额度；`backoffLimit: 1` 是为了避免失败重试时重复计费，失败先看日志修配置再手工重跑。
- **RWO 卷与 Job**：`titu-assistant-var` 是 `ReadWriteOnce`，同一时刻只能被一个节点挂载。milvus Job 已加「优先与 App 同节点」的软亲和，但跨节点仍会 `Multi-Attach error`；因此发布流程先停 App、Job 结束后删除 Job（`ttlSecondsAfterFinished: 600` 只是兜底）再起 App。单节点集群不受此限制。
- **文件属主**：App 与 Job 都是 UID/GID 10001 + `fsGroup: 10001`，Job 写入 `/srv/assistant/var` 的文件 App 可直接读写；Job 侧已设 `fsGroupChangePolicy: OnRootMismatch`，避免每次启动递归 chown 10Gi 卷。
- **多副本**：Job 在 Deployment 之外各执行一次；当前 `60-deployment.yml` 没有 `db-verify` / `knowledge-ingest` Init 容器，重复发布需手动保证顺序。
- **大变更**：SQL 执行时间可能超过 10 分钟时，调大 `40-job-db-migrate.yaml` 的 `activeDeadlineSeconds`，并同步调大第 2 步 `--timeout`（当前 600s，`activeDeadlineSeconds` 是 700s）；知识 Job 同理（`--timeout=1800s` 对应清单的 1800s）。
- **配置不在发布步骤里**：上面的步骤只 apply 两个 Job 和 Deployment，不碰 ConfigMap/Secret。改了 `10-configmap.yml` 或 `20-secret.yml` 要先单独 apply，否则 Job 和 App 读到的都是集群里的旧值，表现为「发布成功但行为没变」。配置改动不受 `rollout undo` 影响，回退时要手工改回并重新 apply。
- **不要**把 `40-job-db-migrate.yaml` 或 `50-job-milvus-init.yaml` 与其它资源一次性批量 apply：当前使用原生 YAML，Job 与 Deployment 的顺序由发布命令显式保证。
- **tag 必须唯一**：清单使用 `imagePullPolicy: IfNotPresent`，同名 tag 覆盖推送后节点不会重新拉取旧镜像。db-migrate 镜像与 assistant 镜像用同一 tag 配套构建；手工 `-t` 时保证每次构建 tag 与上次不同（两个镜像都要重推），或临时改为 `Always` 并重启 Pod。
