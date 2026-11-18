-- =====================================================================
-- SmartTITU Flyway 基线迁移（版本 1.0.0）
-- 来源：scripts/postgres/schema/1.0.0.sql + scripts/postgres/data/1.0.0.sql
--       （两文件已冻结归档）按 docs/工程化方案.md §6.2 转换规则合并生成。
--       结构适配发布代码 7942a6f，PostgreSQL 14/16。
-- 用途：全新环境 `flyway migrate` 一次建库；存量环境先 `flyway baseline`
--       （只登记版本，不执行本文件），此后 migrate 只应用 >1.0.0 的增量。
-- 转换说明：
--   1. 移除 BEGIN/COMMIT：Flyway 每条迁移自带事务，失败整体回滚、可重跑；
--   2. SET LOCAL search_path 改为会话级 SET search_path（单连接内生效）；
--   3. 移除外来表检查 DO 块：该防护职责在应用 claim 步骤；
--   4. 移除 IF NOT EXISTS（仅保留 CREATE SCHEMA）：工具保证一次执行，
--      防御式写法会掩盖 schema 漂移；
--   5. assistant.external_deployment（部署归属登记表）及其登记行不在本文件：
--      由应用 claim 步骤在 migrate 之前创建并写入（含部署 ID 与 Milvus
--      元数据），作为发布门禁的所有权凭据与失败重试依据。
-- 验收：空库执行 claim + migrate 后，与生产 pg_dump --schema-only 对比
--       应零差异（external_deployment 由 claim 生成，需一并执行）。
-- =====================================================================

-- 一、Schema（研发流程中 claim 步骤可能已创建 assistant，此处幂等无害）
CREATE SCHEMA IF NOT EXISTS assistant;
CREATE SCHEMA IF NOT EXISTS knowledge;

-- 二、客服业务表（app/core.py -> app/storage.py；external_deployment 由 claim 创建，见头部说明）
SET search_path TO assistant, public;

-- assistant.sessions：用户会话及归属
CREATE TABLE sessions(
                id TEXT PRIMARY KEY, tenant TEXT NOT NULL, "user" TEXT NOT NULL,
                context TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL);
CREATE INDEX session_owner ON sessions(tenant,"user",updated);
-- assistant.messages：用户问题、客服回答和历史响应
CREATE TABLE messages(
                id TEXT PRIMARY KEY, session TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                request_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
                payload TEXT NOT NULL, created DOUBLE PRECISION NOT NULL);
CREATE UNIQUE INDEX message_request ON messages(session,request_id,role);
-- assistant.global_rag_daily_limits：所有用户共享的每日RAG计数
CREATE TABLE global_rag_daily_limits(day TEXT PRIMARY KEY, used INTEGER NOT NULL CHECK(used>=0), updated DOUBLE PRECISION NOT NULL);
-- assistant.rate_limits：早期通用限流结构，当前仍保留建表
CREATE TABLE rate_limits(owner TEXT PRIMARY KEY, "window" INTEGER, count INTEGER);
-- assistant.tenant_message_limits：企业共享的滚动60秒提问额度
CREATE TABLE tenant_message_limits(owner TEXT PRIMARY KEY, events TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL);
CREATE INDEX message_retention ON messages(created);
CREATE INDEX session_retention ON sessions(updated);
-- assistant.workflow_runs：单次请求的工作流运行登记
CREATE TABLE workflow_runs(id TEXT PRIMARY KEY, session TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, request_id TEXT NOT NULL, status TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL);
ALTER TABLE messages ADD COLUMN seq BIGSERIAL UNIQUE;

-- 三、LangGraph检查点表：langgraph-checkpoint-postgres==3.2.0
-- 与该锁定版本MIGRATIONS逐项一致，只把并发建索引改为普通建索引。

-- checkpoint migration 0
-- assistant.checkpoint_migrations：检查点数据库结构的迁移版本记录
CREATE TABLE checkpoint_migrations (
    v INTEGER PRIMARY KEY
);

-- checkpoint migration 1
-- assistant.checkpoints：LangGraph流程状态快照
CREATE TABLE checkpoints (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    parent_checkpoint_id TEXT,
    type TEXT,
    checkpoint JSONB NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}',
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id)
);

-- checkpoint migration 2
-- assistant.checkpoint_blobs：检查点各通道的序列化状态
CREATE TABLE checkpoint_blobs (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL,
    version TEXT NOT NULL,
    type TEXT NOT NULL,
    blob BYTEA,
    PRIMARY KEY (thread_id, checkpoint_ns, channel, version)
);

-- checkpoint migration 3
-- assistant.checkpoint_writes：检查点任务的中间写入
CREATE TABLE checkpoint_writes (
    thread_id TEXT NOT NULL,
    checkpoint_ns TEXT NOT NULL DEFAULT '',
    checkpoint_id TEXT NOT NULL,
    task_id TEXT NOT NULL,
    idx INTEGER NOT NULL,
    channel TEXT NOT NULL,
    type TEXT,
    blob BYTEA NOT NULL,
    PRIMARY KEY (thread_id, checkpoint_ns, checkpoint_id, task_id, idx)
);

-- checkpoint migration 4
ALTER TABLE checkpoint_blobs ALTER COLUMN blob DROP not null;

-- checkpoint migration 5
SELECT 1;

-- checkpoint migration 6
CREATE INDEX checkpoints_thread_id_idx ON checkpoints(thread_id);

-- checkpoint migration 7
CREATE INDEX checkpoint_blobs_thread_id_idx ON checkpoint_blobs(thread_id);

-- checkpoint migration 8
CREATE INDEX checkpoint_writes_thread_id_idx ON checkpoint_writes(thread_id);

-- checkpoint migration 9
ALTER TABLE checkpoint_writes ADD COLUMN task_path TEXT NOT NULL DEFAULT '';

-- 四、知识文档、切片与Embedding缓存表（app/rag.py）
SET search_path TO knowledge, public;
-- knowledge.rag_state：当前知识索引配置指纹和代次
CREATE TABLE rag_state(id INTEGER PRIMARY KEY CHECK(id=1),fingerprint TEXT,generation INTEGER NOT NULL);
-- knowledge.rag_documents：知识文档登记和当前有效版本
CREATE TABLE rag_documents(id TEXT PRIMARY KEY,path TEXT UNIQUE,title TEXT,current_revision TEXT,active INTEGER,updated DOUBLE PRECISION);
-- knowledge.rag_revisions：文档各版本及原始文件内容
CREATE TABLE rag_revisions(document_id TEXT,revision TEXT,filename TEXT,raw BYTEA,metadata TEXT,created DOUBLE PRECISION,PRIMARY KEY(document_id,revision));
-- knowledge.rag_chunks：真实知识切片及关联信息
CREATE TABLE rag_chunks(id TEXT PRIMARY KEY,document_id TEXT,revision TEXT,ordinal INTEGER,record TEXT,vector TEXT);
CREATE INDEX rag_chunk_doc ON rag_chunks(document_id,revision);
-- knowledge.rag_events：知识入库、重建、停用、启用等事件
CREATE TABLE rag_events(id BIGSERIAL PRIMARY KEY,document_id TEXT,action TEXT,revision TEXT,created DOUBLE PRECISION);
-- knowledge.rag_embedding_cache：Embedding计算结果缓存，减少重复向量化
CREATE TABLE rag_embedding_cache(fingerprint TEXT,text_hash TEXT,vector TEXT,PRIMARY KEY(fingerprint,text_hash));

-- 五、初始数据（原 data/1.0.0.sql；external_deployment 登记行由 claim 写入，不在本文件）

-- assistant.checkpoint_migrations：登记LangGraph检查点迁移版本0-9，与上文migration 0-9一致
INSERT INTO assistant.checkpoint_migrations(v)
SELECT v FROM generate_series(0,9) AS v ON CONFLICT DO NOTHING;

-- knowledge.rag_state：初始fingerprint为空；ingest后才会登记实际知识配置及数据
INSERT INTO knowledge.rag_state(id,fingerprint,generation) VALUES(1,'',0) ON CONFLICT DO NOTHING;
