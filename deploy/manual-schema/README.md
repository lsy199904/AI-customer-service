# SmartTITU线上手工建表

对应正式发布代码：GitHub `deploy-external-api-20261116` / `7942a6f`；GitLab已合入等价三项修改的版本为 `fff55cc`。不含24题常见问题功能。

本目录供DBA与部署人员自行在现有PG业务库、Milvus数据库内建结构，不依赖production.sh、dev.sh或kubernetes.py。不创建云实例，不迁移PG16旧数据。PG14.25已通过应用自动初始化和问答验证；本次交付已完成表结构/迁移逐项比对、SQL与PL/pgSQL语法解析、Milvus创建参数模拟验证；尚未在真实PG14/云Milvus重新执行手工建表验收，发布前需在独立空库验证。

## 0. 具体哪些表、原来怎么创建

PG只需一个业务数据库，在其中分为两个schema：assistant（11张）和knowledge（6张），共17张；不是17个数据库。下列字段是用途摘要，完整字段类型、主键、约束和索引以01_postgresql.sql为准。保留代码原有TEXT/JSON文本、DOUBLE PRECISION时间戳等类型，不自行改成JSONB或TIMESTAMP。

| Schema | 表名 | 用途 | 关键字段 | 原自动创建位置 |
|---|---|---|---|---|
| assistant | `external_deployment` | 部署归属登记，防止误连其他部署的库或集合 | id=1；metadata保存DEPLOYMENT_ID及Milvus连接、库名、前缀 | app/deployment.py：claim |
| assistant | `sessions` | 用户会话及归属 | id；tenant、user、context、创建/更新时间 | app/core.py：Service.__init__ |
| assistant | `messages` | 用户问题、客服回答和历史响应 | id；session关联sessions；request_id用于去重；seq用于排序 | app/core.py：Service.__init__ |
| assistant | `global_rag_daily_limits` | 所有用户共享的每日RAG计数 | day为北京时间日期；used为已进入RAG次数 | app/core.py：Service.__init__ |
| assistant | `rate_limits` | 早期通用限流结构，当前仍保留建表 | owner、window、count；当前每分钟提问限流使用下一张表 | app/core.py：Service.__init__ |
| assistant | `tenant_message_limits` | 企业共享的滚动60秒提问额度 | owner；events为请求时间列表；updated为更新时间 | app/core.py：Service.__init__ |
| assistant | `workflow_runs` | 单次请求的工作流运行登记 | id；session、request_id、status；辅助请求恢复和清理 | app/core.py：Service.__init__ |
| assistant | `checkpoint_migrations` | 检查点数据库结构的迁移版本记录 | v；锁定依赖3.2.0对应0至9，不能只建空表 | app/workflow.py：PostgresSaver.setup / 依赖MIGRATIONS |
| assistant | `checkpoints` | LangGraph流程状态快照 | thread_id、checkpoint_ns、checkpoint_id联合主键；checkpoint和metadata为JSONB | app/workflow.py：PostgresSaver.setup / 依赖MIGRATIONS |
| assistant | `checkpoint_blobs` | 检查点各通道的序列化状态 | thread_id、checkpoint_ns、channel、version联合主键；blob为BYTEA | app/workflow.py：PostgresSaver.setup / 依赖MIGRATIONS |
| assistant | `checkpoint_writes` | 检查点任务的中间写入 | thread_id、checkpoint_ns、checkpoint_id、task_id、idx联合主键；含task_path | app/workflow.py：PostgresSaver.setup / 依赖MIGRATIONS |
| knowledge | `rag_state` | 当前知识索引配置指纹和代次 | id=1；fingerprint、generation；由ingest更新 | app/rag.py：SCHEMA / DocumentStore |
| knowledge | `rag_documents` | 知识文档登记和当前有效版本 | id；path、title、current_revision、active | app/rag.py：SCHEMA / DocumentStore |
| knowledge | `rag_revisions` | 文档各版本及原始文件内容 | document_id、revision联合主键；raw为BYTEA；支持原文下载 | app/rag.py：SCHEMA / DocumentStore |
| knowledge | `rag_chunks` | 真实知识切片及关联信息 | id；document_id、revision；record为JSON文本，vector为向量JSON文本 | app/rag.py：SCHEMA / DocumentStore |
| knowledge | `rag_events` | 知识入库、重建、停用、启用等事件 | 自增id；document_id、action、revision、created | app/rag.py：SCHEMA / DocumentStore |
| knowledge | `rag_embedding_cache` | Embedding计算结果缓存，减少重复向量化 | fingerprint、text_hash联合主键；vector为向量JSON文本 | app/rag.py：SCHEMA / DocumentStore |

原来的创建链路：

```text
python -m app.deployment initialize
  ├─ 部署归属校验/登记 → assistant.external_deployment
  ├─ Service初始化 → assistant下6张业务表
  ├─ DocumentStore初始化 → knowledge下6张知识表
  └─ PostgresSaver.setup() → assistant下4张检查点表及迁移记录

python manage.py ingest
  ├─ 原始文档解析、切片，调用Embedding生成向量
  ├─ MilvusVectors.ensure() → 必要时创建完整集合及向量索引
  └─ 向Milvus写向量，向PG发布知识记录及版本
```

现在改为DBA自行建结构时，不必执行上述建表链路，按后文01_postgresql.sql、02_milvus.py/控制台字段定义预建结构；知识数据仍必须通过ingest生成。

Milvus不是PG的第18张表：是在指定MILVUS_DATABASE下为这套Embedding配置创建1个知识Collection。它存id、document_id、revision、vector，id对应PG的knowledge.rag_chunks.id；Milvus负责向量检索，PG负责取回完整知识片段。配置变化可能产生其他后缀集合，不预先创建研发历史集合。

## 1. PG：01_postgresql.sql

先由DBA创建专用业务账号和独立空业务数据库。使用业务账号执行本SQL，或DBA先切换到该业务角色（SET ROLE）再执行，确保应用账号拥有两个schema、表与序列；不要全部建在DBA名下再只授予SELECT/INSERT/UPDATE/DELETE。

替换SQL顶部4个占位值，均取自正式App实际环境变量：

| SQL占位值 | 对应配置 |
|---|---|
| REPLACE_DEPLOYMENT_ID | DEPLOYMENT_ID，部署固定标识，后续不能随意重新生成 |
| REPLACE_MILVUS_URI | MILVUS_URI，与App一致、去掉末尾斜杠 |
| REPLACE_MILVUS_DATABASE | MILVUS_DATABASE，例如default；这个数据库需平台预先准备 |
| REPLACE_MILVUS_COLLECTION_PREFIX | MILVUS_COLLECTION，只填写前缀，不含指纹后缀 |

这些是部署对应信息，不是密码。SQL字符串如包含单引号需按SQL规则转义。未替换占位符会报错并回滚。SQL包含BEGIN/COMMIT，执行工具应遇错停止；psql可用：

```sh
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 01_postgresql.sql
```

DATABASE_URL由操作人员安全注入，不要将真实密码写入文件或提交Git。

共17张表：

- assistant：external_deployment、sessions、messages、global_rag_daily_limits、rate_limits、tenant_message_limits、workflow_runs、checkpoint_migrations、checkpoints、checkpoint_blobs、checkpoint_writes。
- knowledge：rag_state、rag_documents、rag_revisions、rag_chunks、rag_events、rag_embedding_cache。

SQL来自app/core.py、app/rag.py，经app/storage.py同样的PG类型适配，并补充app/deployment.py的部署归属记录。检查点语句来自requirements.lock锁定的langgraph-checkpoint-postgres==3.2.0实际MIGRATIONS，包含0至9迁移及记录；普通CREATE INDEX替代CONCURRENTLY，仅针对新空库便于事务执行，不改变索引字段。

不要只建业务表而漏掉checkpoint_migrations或external_deployment。后者metadata必须与App配置一致，否则部署归属保护会拒绝继续。建表后rag_state初始fingerprint为空，要经过ingest才写入实际知识配置。

## 2. Milvus：02_milvus.py

Milvus不执行PostgreSQL建表SQL。可由运维在云控制台按下表创建Collection和索引；也可以参考/执行02_milvus.py中的独立SDK代码（不调用应用初始化函数）。数据库先由平台准备，不需要App直连etcd或MinIO。

| 字段 | 类型 | 配置 |
|---|---|---|
| id | VARCHAR | 主键，max_length=80，auto_id=false |
| document_id | VARCHAR | max_length=80 |
| revision | VARCHAR | max_length=64 |
| vector | FLOAT_VECTOR | 当前BGE-M3为1024维，须以实际模型输出为准 |

集合：enable_dynamic_field=false，consistency_level=Strong。

索引：字段vector、metric_type=COSINE；默认index_type=HNSW，M=16、efConstruction=128。若云平台只支持AUTOINDEX，App环境变量MILVUS_INDEX_TYPE必须同步为AUTOINDEX，不填HNSW专用参数。创建后加载集合。

**完整集合名不是单独的MILVUS_COLLECTION前缀**，实际规则：

```text
MILVUS_COLLECTION + "_" + RAGSettings.fingerprint前16位
```

后缀取决于解析版本、Embedding协议/URL/模型ID/版本、切片参数。请在最终应用镜像、最终生产环境变量下计算，不调用模型、不连接数据库：

```sh
cd /srv/assistant
python -c 'from app.rag import RAGSettings; s=RAGSettings(); print(s.milvus_collection + "_" + s.fingerprint[:16])'
```

不要复制研发集合后缀；不要把完整集合名填回MILVUS_COLLECTION，否则App还会再拼一次后缀。

若选择执行SDK文件，将其挂载到有pymilvus的执行环境（应用镜像已锁定pymilvus==2.6.17），注入与App一致的MILVUS_URI、MILVUS_TOKEN、MILVUS_DATABASE、MILVUS_COLLECTION、MILVUS_INDEX_TYPE：

```sh
python 02_milvus.py --collection 上一步计算的完整集合名 --dimension 1024
```

文件只建结构和索引、加载集合，不调用模型、不插入知识向量。已有集合只核对，不自动清空或改结构。PG和Milvus里的知识编号由入库统一生成，不需要运维预先编造编号；document_id、revision也由入库统一写入。

## 3. 手工建完后还需要什么

1. 同一套App环境变量及同一个var PVC，执行`python manage.py ingest`，写入文档、切片、Embedding结果及Milvus数据，并生成PDF图片。
2. 执行`python manage.py doctor --models`，再做实际问答、历史和重启持久化验证。模型检查和首次入库会产生API用量。
3. 正式App按原命令`python -m app.server`启动。

可选：入库前执行`python -m app.deployment initialize`作归属、文档、模型与结构检查；手工建表和归属值正确时应通过，但它仍会执行幂等建表检查，不是纯只读检查。入库前不要把`app.deployment check`作为首次验收条件，因为尚未登记知识fingerprint。

**当前代码启动和入库仍包含CREATE IF NOT EXISTS、messages序列列的ALTER检查以及LangGraph.setup()。手工建表不会自动关闭这些逻辑。** 仍需保留业务账号对其schema/表/序列的所有权和相应权限；如果生产要求应用完全无DDL权限，需要另行改造并验证，当前交付不声称已支持。

本目录不会自动打包进现有应用镜像，DBA可直接取SQL执行；若在K8s Job运行SDK文件，应单独挂载或复制，不要假设镜像内已有这些文件。
