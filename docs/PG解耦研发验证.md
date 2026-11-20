# PG解耦研发验证

适用分支：review-gitlab-feat-k8s。不影响现有8200/8201服务；使用新目录、独立PG业务库、新Milvus前缀和空闲端口。

## 1. 配置与建库

在Linux研发服务器执行，已有Docker Compose V2、PG、Milvus及模型API：

```bash
cd ~/ai_customer
git clone --branch review-gitlab-feat-k8s --single-branch \
  ssh://git@ssh.github.com:443/lsy199904/AI-customer-service.git \
  ai_customer_pg_decoupling
cd ai_customer_pg_decoupling
sh scripts/dev.sh init --from ../ai_customer_external/.env --database ai_customer_pg_decoupling_test
```

编辑新目录`.env`：`APP_PORT=8203`（确保空闲），核对三个模型接口、PG连接和Milvus连接。init生成新部署ID、匿名Cookie名和独立Milvus集合前缀，后续保持稳定；不要复制旧服务的完整.env覆盖它。

先由管理员创建`ai_customer_pg_decoupling_test`数据库并授权。当前研发服务器如果仍使用`postgres-test`容器，已有业务角色`ai_customer_app`，管理员可执行：

```bash
docker exec postgres-test psql -U postgres -d postgres -v ON_ERROR_STOP=1 \
  -c 'CREATE DATABASE ai_customer_pg_decoupling_test OWNER ai_customer_app;'
```

若库已存在不要删除，先确认是否独立测试库及是否已迁移。云PG由管理员按实际账号建库。这里只创建业务数据库，不部署PG实例。

## 2. 独立PG迁移

```bash
sh scripts/dev.sh migrate-pg
```

本命令读取.env，仅向`bash scripts/db.sh migrate`提供PG连接及四个部署归属值，运行独立Flyway Docker镜像（默认固定11.20.3-alpine）；不运行App、不调用模型。

SQL来自`database/postgres/migrations/`，配置来自`database/postgres/flyway.conf`。由Flyway建立assistant/knowledge业务结构、检查点和版本记录。

研发测试可使用独立库的owner账号迁移并运行App。生产迁移账号与App账号可分开；迁移侧需给App账号两schema的USAGE、全部业务表所需DML、序列所需权限，以及Flyway版本表的SELECT权限。不要用生产App账号去申请DDL权限。

迁移不自动创建业务数据库。不允许对已有业务库直接baseline或伪造版本记录；已有库接入由管理员核对结构后执行。

## 3. 构建、检查和知识入库

```bash
sh scripts/dev.sh build
sh scripts/dev.sh check
sh scripts/dev.sh ingest
sh scripts/dev.sh doctor
sh scripts/dev.sh start
```

- check：只读PG版本/归属校验，并实际检查三个模型API，有少量API用量。
- ingest：先检查环境，然后执行`python manage.py ingest`。PG分支只校验结构，不再建表；正文写入PG，Embedding结果写入Milvus，PDF图片生成到本项目var/pdf_media。
- doctor：检查知识数量、PG、Milvus检索及三个模型API。
- start：启动本项目App容器；上述均由dev.sh进入App镜像执行，不使用宿主机Python跑业务依赖。

根目录manage.py是兼容入口，转调现有`database/milvus/manage.py`；两种入口使用同一业务实现。不要分别维护两份CLI。

## 4. Milvus集合

默认无需独立执行建集合：ingest继续按原逻辑自动创建集合及索引；Milvus服务和database必须已经准备好，账号需要相应集合/索引权限。

若部署人员要求提前创建，可在同一个App镜像环境内执行`database/milvus/02_milvus.py`，必须注入与App相同环境变量，完整集合名先计算：

```python
from app.rag import RAGSettings
s = RAGSettings()
print(s.milvus_collection + '_' + s.fingerprint[:16])
```

随后执行（完整集合名替换为实际结果，1024仅适用于当前BGE-M3）：

```bash
python database/milvus/02_milvus.py --collection 实际完整集合名 --dimension 1024
```

此路径在研发整仓挂载的容器内可用；生产App镜像不包含该SDK脚本时，需单独提供脚本，或直接用ingest自动建集合。此脚本只建/核对空集合，不完成知识入库。

## 5. 验收与更新

```bash
curl -fsS http://127.0.0.1:8203/smart-bot/ready
```

访问`http://服务器IP:8203/smart-bot/widget/anonymous-demo`，验证问答、引用、图片、历史及重启后恢复。

- PG未迁移或版本不符：必须失败，不自动建表，不删除其他库。
- Milvus使用新前缀，不能覆盖旧服务集合。
- 文档更新：dev.sh ingest；Embedding或切分配置变更：dev.sh ingest --rebuild。
- 模型地址/Key配置变化：dev.sh restart（重新创建容器）；仅换LLM不需重建知识向量。
- 本次只新增研发入口兼容；生产仍按独立PG Job → App镜像知识入库Job → 长期App的顺序。Job与App使用相同配置及PDF图片PVC。

本地离线检查不替代真实Flyway、PG权限和Milvus连通性验证；以上真实联调在研发服务器执行。

## 本次离线验证范围

已完成PG校验分支、配置映射、原有适用业务回归和Milvus SDK模拟验证。整套测试中，旧Kubernetes Python执行器已被本分支删除，其旧测试模块跳过；另两项要求Origin拒绝返回403的旧测试与本分支已有的server.py注释不一致，本次未运行，未调整该安全策略。SQL/PLpgSQL解析及SQL门禁通过，SQL格式检查因本地未安装sqlfluff跳过。未执行真实Docker构建、Flyway迁移或远程PG/Milvus写入。
