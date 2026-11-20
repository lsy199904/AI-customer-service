# Milvus on Kubernetes（Milvus Operator）

本实例使用 Milvus Operator 在 K8s 上部署 Milvus 集群。

> 官方建议用 Milvus Sizing Tool 按数据量估算资源：https://milvus.io/tools/sizing

## 1. 前置条件

- K8s 集群已就绪，`kubectl` 可操作集群。
- 已有一个 S3 兼容对象存储（AWS S3 / MinIO / 阿里云 OSS / 腾讯云 COS / Ceph RGW 等），并满足：
  - 有可用的 AK/SK（或 IAM 角色）。
  - 已提前创建好 bucket（Operator 不会自动创建）。
- 已安装 Helm（若选择 Helm 方式安装 Operator）。
- 集群已安装 StorageClass（详见下方"StorageClass 要求"）。

## 2. StorageClass 要求

官方前置条件只要求"集群已安装 StorageClass"。在本实例场景（**外部对象存储 + Woodpecker**）下，需要 PVC 的只有 **etcd**，因此 StorageClass 的要求集中在 etcd 上：

| 要求项 | 说明 |
|---|---|
| 至少有一个可用 SC | 集群需有默认 StorageClass，或在 CR 中显式指定 |
| 访问模式 | etcd 用 `ReadWriteOnce`（RWO），普通块存储即可，不需要 RWX |
| 容量 | etcd 默认每个副本 10Gi，3 副本 = 3 个 PVC（可按需调 `size`） |
| 动态供给 | 需支持动态 PV 创建（`provisioner` 可用），否则 PVC 会 Pending |
| 卷绑定模式 | 推荐 `WaitForFirstConsumer`（多节点/多可用区时避免调度错位） |
| reclaimPolicy | 建议 `Retain`，避免误删实例时丢 etcd 数据 |

**本集群可用**：`longhorn-postgres`（Longhorn，RWO，`WaitForFirstConsumer`，`Retain`，SSD）满足要求；

> 若你的对象存储不是外部的（用 Operator 内置 MinIO），MinIO 也会申请 PVC，此时同样需要 RWO 的 SC。

检查与确认：

```bash
kubectl get sc                        # 查看可用 StorageClass 及 default 标记
kubectl get pvc -A                    # 部署后确认 etcd 的 PVC 已绑定
```

## 3. 准备镜像（使用私有仓库时，本环境必做）

集群节点无法直连 Docker Hub（见下方 DNS 污染说明），因此**必须把所有用到的镜像同步到 harbor**，否则 Pod 会 `ImagePullBackOff`。

在一台能联网的机器上用加速器拉取，再 tag/push 到 harbor：

```bash
# ---- 1) Milvus Operator 镜像（helm install 前先备好）----
docker pull docker.m.daocloud.io/milvusdb/milvus-operator:v1.3.7
docker tag docker.m.daocloud.io/milvusdb/milvus-operator:v1.3.7 harbor.rd.dsi/docker.io/milvusdb/milvus-operator:v1.3.7
docker push harbor.rd.dsi/docker.io/milvusdb/milvus-operator:v1.3.7

# ---- 2) Milvus 镜像（创建 CR 前备好）----
docker pull docker.m.daocloud.io/milvusdb/milvus:v2.6.4
docker tag docker.m.daocloud.io/milvusdb/milvus:v2.6.4 harbor.rd.dsi/docker.io/milvusdb/milvus:v2.6.4
docker push harbor.rd.dsi/docker.io/milvusdb/milvus:v2.6.4

# ---- 3) etcd 镜像（创建 CR 前备好）----
docker pull docker.m.daocloud.io/milvusdb/etcd:3.5.25-r1
docker tag docker.m.daocloud.io/milvusdb/etcd:3.5.25-r1 harbor.rd.dsi/docker.io/milvusdb/etcd:3.5.25-r1
docker push harbor.rd.dsi/docker.io/milvusdb/etcd:3.5.25-r1

# ---- 4) MinIO 镜像（仅方案 A：内置 MinIO 需要）----
# 注意：DaoCloud/1ms 等加速器对 minio 热门镜像有限制(denied/403)，
#       实测华为云 SWR 镜像源可用：
docker pull swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/minio/minio:RELEASE.2024-12-18T13-15-44Z
docker tag swr.cn-north-4.myhuaweicloud.com/ddn-k8s/docker.io/minio/minio:RELEASE.2024-12-18T13-15-44Z harbor.rd.dsi/docker.io/minio/minio:RELEASE.2024-12-18T13-15-44Z
docker push harbor.rd.dsi/docker.io/minio/minio:RELEASE.2024-12-18T13-15-44Z
```

### 4. 安装 Milvus Operator

```bash
# 1) 本地下载 chart 包（用 curl 走系统代理，约 200KB）
curl -sSL --retry 3 -o milvus-operator-1.3.7.tgz \
  https://github.com/zilliztech/milvus-operator/releases/download/v1.3.7/milvus-operator-1.3.7.tgz
tar tzf milvus-operator-1.3.7.tgz >/dev/null && echo "包完整"

# 2) 用本地 tgz 安装
helm install milvus-operator \
  -n milvus-operator --create-namespace \
  --wait --wait-for-jobs \
  -f operator-values.yaml \
  ./milvus-operator-1.3.7.tgz

kubectl get pods -n milvus-operator
```

确认 operator Pod 为 `Running` 后再继续。


### 6. 部署 Milvus 实例

```bash
# 创建命名空间
kubectl create ns milvus

kubectl apply -f milvus-test-minimal.yaml

# 查看状态，status.status 变为 Healthy 即就绪
kubectl get milvus milvus-26 -o yaml -n milvus

# 查看 Pod
kubectl get pods -n milvus
```

### 7. 集群内连接 Milvus

#### 连接信息

| 项目 | 值 |
|---|---|
| 集群内 Service | `milvus-26-milvus.milvus.svc.cluster.local` |
| 端口 | `19530`（gRPC，SDK 用）；`9091`（HTTP 健康检查/metrics） |
| 简写（同 namespace 内） | `milvus-26-milvus:19530` |
| 用户名 / 密码 | **无**（未启用认证，连接时不要传 user/password/token） |

> **认证说明**：当前部署的 `spec.config` 中没有 `common.security.authorizationEnabled: true`，Milvus 认证默认关闭，**不需要任何用户名密码**。若未来开启认证，需配置 `spec.config.common.security.authorizationEnabled: true` 并创建用户（用 pymilvus 的 `client.create_user`），连接时再传 `user`/`password`。

#### 方式一：从集群内 Pod 连接（推荐，无需暴露端口）

在任意一个与 Milvus 同集群的 Pod 里用 Python SDK 连接：

```python
from pymilvus import MilvusClient, connections

# 地址：集群内 Service DNS
uri = "http://127.0.0.1:19530"

# 无认证：不要传 user/password/token
client = MilvusClient(uri=uri)

# 验证：列出 database
print(client.list_databases())
```

临时起一个测试 Pod 验证（用你 harbor 里的 python 镜像）：

```bash
kubectl run milvus-client-test -n milvus --rm -it \
  --image=<你的python镜像含pymilvus> -- bash
# 在 Pod 内执行上面的 Python 代码
```

若镜像没有 pymilvus，先 `pip install pymilvus`（或用能联网的镜像）。

#### 方式二：从集群外连接（port-forward）

```bash
kubectl port-forward --address 0.0.0.0 service/milvus-26-milvus 19530:19530 -n milvus
```

然后本机 SDK 连 `localhost:19530`（同样无用户名密码）：

```python
from pymilvus import MilvusClient
client = MilvusClient(uri="http://localhost:19530")
print(client.list_databases())
```

#### 快速连通性验证（无需 SDK）

```bash
# 在任意 Pod 内测试 19530 端口可达
kubectl exec -it <任意pod> -n milvus -- sh -c 'nc -zv milvus-26-milvus 19530'
# 或测试 HTTP 健康检查端口
kubectl exec -it <任意pod> -n milvus -- sh -c 'curl -s http://milvus-26-milvus:9091/healthz'
```

