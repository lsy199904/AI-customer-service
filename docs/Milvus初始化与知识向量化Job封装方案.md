# Milvus 初始化与知识向量化 Job：落地说明

> **状态：已落地（2026-11-20）。** 实现为 `database/milvus/knowledge-init.sh`（与 `02_milvus.py`、`manage.py` 同目录），随 app 镜像一起打包，由 `deploy/k8s/dev/50-job-milvus-init.yaml` 调用。
> 目标读者：部署/运维、后端。
> 相关文件：`database/milvus/knowledge-init.sh`、`database/milvus/02_milvus.py`、`database/milvus/manage.py`、`deploy/docker/app/Dockerfile`、`deploy/k8s/dev/50-job-milvus-init.yaml`。

---

## 1. 结论先说

一个脚本、四步串行、任一步失败即退出：

```text
1. 算集合名     python -c '... RAGSettings ...'          → MILVUS_COLLECTION_<fingerprint前16位>
2. 建/核对集合  python database/milvus/02_milvus.py --collection <名字> --dimension 1024
3. 知识入库     python manage.py ingest                  → 写 PG + Milvus + var/pdf_media
4. 自检         python manage.py doctor --models          → 数据库 / LangGraph / 模型可达
```

脚本在镜像内固定为 `/srv/assistant/database/milvus/knowledge-init.sh`，Job 用
`command: ["sh", "/srv/assistant/database/milvus/knowledge-init.sh"]` 调用。

**为什么不合并第 2 步和第 3 步**：`ingest` 内部也会 `MilvusVectors.ensure()` 自动建集合，但它只核对向量维度，**不核对索引类型与 HNSW 参数**。先跑 `02_milvus.py` 是为了让索引配置错误在灌数据之前就暴露——索引建错时检索效果会悄悄变差，很难事后发现。第 4 步放在最后，是因为 `doctor` 要求集合可检索、知识已写入才可能通过。

**为什么用 `02_milvus.py` 而不是 `manage.py vector-init`**：两者能力等价（`vector-init` 是前者的封装，自动算集合名）。本次按运维手册的交付方式走 SDK 脚本，同时保留 `vector-init` 作为手工巡检命令（`--check-only`），Job 不再使用它。

---

## 2. 脚本

`database/milvus/knowledge-init.sh`（完整内容）：

```sh
#!/bin/sh
# Milvus 集合初始化 → 知识入库 → 自检：四步严格按顺序执行，任一步失败立即退出。
# 由 deploy/k8s/dev/50-job-milvus-init.yaml 调用；也可在容器内手工执行。
# 依赖同目录的 02_milvus.py，以及 /srv/assistant/manage.py，
# 以及 MILVUS_* / EMBEDDING_* / DATABASE_URL / AUTH_SECRET 等环境变量（与 App 同一套）。
# 产物写入已挂载的 /srv/assistant/var，App 启动后读取同一目录。
set -eu

# 脚本位于 <APP_HOME>/database/milvus/knowledge-init.sh
APP_HOME="${APP_HOME:-$(cd "$(dirname "$0")/../.." && pwd)}"
cd "$APP_HOME"
MILVUS_DIR="$APP_HOME/database/milvus"

DIMENSION="${DIMENSION:-1024}"

echo "==> 1/4 计算完整集合名（前缀 + fingerprint 前16位）"
COLLECTION=$(python -c 'from app.rag import RAGSettings; s=RAGSettings(); print(s.milvus_collection + "_" + s.fingerprint[:16])')
# 只允许字母数字下划线：名字算错会新建一个空集合，让 App 检索不到数据，这里直接拦住
case "$COLLECTION" in
    ''|*[!A-Za-z0-9_]*) echo "集合名异常：'$COLLECTION'" >&2; exit 1 ;;
esac
echo "    集合名: $COLLECTION"

echo "==> 2/4 创建或核对 Milvus 集合"
python "$MILVUS_DIR/02_milvus.py" --collection "$COLLECTION" --dimension "$DIMENSION"

echo "==> 3/4 知识入库（解析、切片、Embedding，写 PG 与 Milvus）"
python manage.py ingest

echo "==> 4/4 数据库、LangGraph 与模型自检"
python manage.py doctor --models

echo "==> 完成：集合 $COLLECTION 已就绪，知识已入库"
```

设计取舍：

| 决定 | 原因 |
|---|---|
| `set -eu`，不写 `trap` | 任一步非 0 退出，Job 立即失败；不需要额外清理逻辑（产物在 PVC 上，重跑幂等） |
| 集合名走 `RAGSettings` | 与 App 同一套代码算指纹，避免手工传错；`MILVUS_COLLECTION` 仍只填前缀 |
| 校验集合名字符集 | 防止 Python 侧的警告/日志混入 stdout，导致建出一个"看起来对"的空集合 |
| `DIMENSION` 可覆盖 | 更换 Embedding 模型时只改环境变量，不改脚本；默认 1024（BGE-M3） |
| 阶段号 `==> N/4` | 失败时用 `kubectl logs` 一眼定位是集合、入库还是模型问题 |
| 不打印凭证 | 脚本不 `echo` 任何 `MILVUS_TOKEN` / `DATABASE_URL`；`02_milvus.py` 自身也不打印底层异常 |

---

## 3. 镜像打包

`deploy/docker/app/Dockerfile` 改两处，新增体积不到 10 KB。

builder 阶段：

```dockerfile
COPY database/milvus/manage.py ./manage.py
# Milvus 建集合 SDK 脚本与 Job 封装同放 database/milvus/，镜像内路径与仓库一致
COPY database/milvus/02_milvus.py ./database/milvus/02_milvus.py
COPY database/milvus/knowledge-init.sh ./database/milvus/knowledge-init.sh
```

runtime 阶段：

```dockerfile
COPY --from=builder --chown=assistant:assistant /srv/assistant/manage.py /srv/assistant/manage.py
COPY --from=builder --chown=assistant:assistant /srv/assistant/database/milvus/02_milvus.py /srv/assistant/database/milvus/02_milvus.py
COPY --from=builder --chmod=0755 --chown=assistant:assistant /srv/assistant/database/milvus/knowledge-init.sh /srv/assistant/database/milvus/knowledge-init.sh
```

落位结果（镜像内保持与仓库相同的相对结构）：

```text
/srv/assistant/manage.py                              # 已有，CLI 入口
/srv/assistant/database/milvus/02_milvus.py           # 新增，SDK 建集合
/srv/assistant/database/milvus/knowledge-init.sh      # 新增，0755，属主 assistant:assistant
/srv/assistant/knowledge_sources/                     # 已有，ingest 的默认来源目录
/srv/assistant/var/                                   # PVC 挂载点，入库产物在这里
```

脚本靠 `dirname "$0"/../..` 定位 `APP_HOME`，因此在镜像内和仓库里都能直接执行，不依赖调用方的当前目录。

`.dockerignore` 排除的是 `.env`、`.git`、`.venv`、`var`、`tests`、`docs` 等，**不排除** `scripts/` 与 `database/`，无需改动。

---

## 4. Job 清单

`deploy/k8s/dev/50-job-milvus-init.yaml` 关键字段：

```yaml
spec:
  backoffLimit: 1                    # 重试会重复调用 Embedding（有成本），只留 1 次
  activeDeadlineSeconds: 1800        # 首次全量入库：PDF 解析 + 批量 Embedding
  ttlSecondsAfterFinished: 600       # 尽快释放 RWO 卷
  template:
    spec:
      containers:
        - name: knowledge-init
          image: <与 60-deployment.yml 完全相同的 assistant 镜像>
          command: ["sh", "/srv/assistant/database/milvus/knowledge-init.sh"]
          envFrom:
            - configMapRef: { name: titu-assistant-config }
            - secretRef:    { name: titu-assistant-secret }
          volumeMounts:
            - name: var
              mountPath: /srv/assistant/var
          resources:
            requests: { cpu: 500m, memory: 1Gi }
            limits:   { cpu: "2",  memory: 4Gi }
      volumes:
        - name: var
          persistentVolumeClaim:
            claimName: titu-assistant-var
```

与 App 的关系：

| 项 | 是否一致 | 说明 |
|---|---|---|
| 镜像 | 完全一致 | 集合名/解析器/切片参数同源，不会漂移 |
| PVC 与 mountPath | 完全一致 | `titu-assistant-var` → `/srv/assistant/var` |
| 环境变量 | 完全一致 | 同一个 ConfigMap + Secret |
| UID/GID | 完全一致 | 10001，`fsGroup: 10001` + `fsGroupChangePolicy: OnRootMismatch` |
| 生命周期 | 独立 | 一次性 Job，跑完即退出，不占常驻资源 |

命令以外的差别只有资源与超时：Job 按"首次全量入库"给资源，App 按常驻服务给资源。

---

## 5. 幂等与重跑

| 场景 | 行为 |
|---|---|
| 集合已存在且结构一致 | `02_milvus.py` 只读核对，打印"核对通过"，不清空、不重建 |
| 集合已存在但字段/维度/索引不符 | 报错退出，不自动修改；先核对 `EMBEDDING_MODEL` / `MILVUS_INDEX_TYPE` / `DIMENSION` |
| 知识未变化 | `ingest` 指纹未变时秒级 no-op，不重复调 Embedding |
| 知识有变化 | 只对新文档/变更文档生成新 revision 与向量 |
| 中途失败 | 直接修配置后重跑同一 Job：已完成的集合创建与已入库文档都不会重复处理 |

重跑方式：

```bash
kubectl -n $NS delete job titu-milvus-init --ignore-not-found
kubectl -n $NS apply -f k8s/dev/50-job-milvus-init.yaml
kubectl -n $NS wait --for=condition=complete job/titu-milvus-init --timeout=1800s
kubectl -n $NS logs -l job-name=titu-milvus-init --all-containers=true --tail=200
```

---

## 6. 需要哪些环境变量

| 阶段 | 必需变量 | 来源 |
|---|---|---|
| 1 算集合名 | `MILVUS_COLLECTION`、`EMBEDDING_*`、`RAG_*`（指纹输入） | ConfigMap |
| 2 建集合 | 增加 `MILVUS_URI`、`MILVUS_TOKEN`；`MILVUS_DATABASE` 建议显式；`MILVUS_INDEX_TYPE` 与平台能力一致 | ConfigMap + Secret |
| 3 入库 | 增加 `DATABASE_URL`、`AUTH_SECRET`、`MODEL_*`/`EMBEDDING_*` | Secret + ConfigMap |
| 4 自检 | 同上（`doctor --models` 会真实调用模型接口） | Secret + ConfigMap |

`envFrom` 整包注入后这些都已覆盖；本地手工执行时至少要 `export` 到同一套值。脚本只检查"变量是否为空"由各个 Python 命令自己完成，不在 shell 里重复实现。

---

## 7. 验证记录

已在本地完成（未实际构建镜像、未连集群）：

| 检查 | 结果 |
|---|---|
| `sh -n database/milvus/knowledge-init.sh` | 通过 |
| 用 python 测试桩模拟四步 | 顺序正确，输出 `==> 1/4` … `==> 4/4`，退出 0 |
| 桩在第 3 步返回 3 | 脚本立即退出 3，不执行第 4 步 |
| 桩在 stdout 混入警告行 | 集合名校验拦截，退出 1（不会建错集合） |
| `50-job-milvus-init.yaml` YAML 解析 | 通过，command/镜像/PVC/资源/超时符合预期 |
| Dockerfile 非 `--from` 的 COPY 源路径 | 全部存在，`.dockerignore` 未排除 |

上线前还需要：重新构建并推送 assistant 镜像（当前清单里的 tag 是旧镜像，里面没有 `02_milvus.py` 与脚本），然后同步三个清单的 image tag。

---

## 8. 运维注意

- **必须重新构建镜像**：脚本与 `02_milvus.py` 是新打进镜像的，旧 tag 里没有；`imagePullPolicy: IfNotPresent` 下用同名 tag 覆盖推送不会被拉取。
- **Job 会调模型**：第 3、4 步消耗 Embedding 与模型 API 额度；`backoffLimit: 1` 是为了避免失败重试重复计费。
- **RWO 卷**：Job 与 App 必须同节点，发布流程先 `scale 0` 停 App，Job 结束后删除 Job 并等 Pod 退出，再起 App。
- **超时**：首次全量入库可能十几分钟，`activeDeadlineSeconds: 1800` 与 README 里 `kubectl wait` 的 `--timeout` 要保持一致。
- **失败定位**：日志里的 `==> N/4` 就是阶段号；第 2 步失败先看集合结构与索引参数，第 3 步失败先看 PG/Milvus 连通性与模型额度。
