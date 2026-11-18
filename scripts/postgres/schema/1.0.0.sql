-- SmartTITU 线上手工建表（结构部分）；适配当前发布代码7942a6f，PostgreSQL 14/16。
-- 本文件只建结构（schema/表/索引/序列），不写业务数据；数据初始化见 ../data/1.0.0.sql。
-- 先由DBA创建独立空业务库、专用业务账号；本文件不创建实例/账号/数据库。
-- 在目标业务库内执行，使用业务账号或先 SET ROLE 到业务账号，保证其拥有表和序列。
-- 执行顺序：先本文件，再 ../data/1.0.0.sql；psql请使用：psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f <文件>
-- 只用于新部署；不是现有数据库的升级/降级脚本。不DROP、不清空、不覆盖已有记录。
-- 新库建索引不使用CONCURRENTLY，便于在一个事务中执行，索引结构与依赖一致。
BEGIN;
DO $manual$
BEGIN
  IF to_regclass('assistant.external_deployment') IS NULL AND EXISTS (
    SELECT 1 FROM information_schema.tables WHERE table_schema IN ('assistant','knowledge')
  ) THEN
    RAISE EXCEPTION '目标库已有未登记的客服/知识表，请停止核对，不自动接管已有库';
  END IF;
  CREATE SCHEMA IF NOT EXISTS assistant;
  CREATE SCHEMA IF NOT EXISTS knowledge;
END;
$manual$;

-- 一、客服业务表（app/core.py -> app/storage.py）
SET LOCAL search_path TO assistant, public;
-- assistant.external_deployment：部署归属登记，防止误连其他部署的库或集合
CREATE TABLE IF NOT EXISTS assistant.external_deployment (
    id INTEGER PRIMARY KEY CHECK(id=1), metadata JSONB NOT NULL
  );
-- assistant.sessions：用户会话及归属
CREATE TABLE IF NOT EXISTS sessions(
                id TEXT PRIMARY KEY, tenant TEXT NOT NULL, "user" TEXT NOT NULL,
                context TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL);
CREATE INDEX IF NOT EXISTS session_owner ON sessions(tenant,"user",updated);
-- assistant.messages：用户问题、客服回答和历史响应
CREATE TABLE IF NOT EXISTS messages(
                id TEXT PRIMARY KEY, session TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
                request_id TEXT NOT NULL, role TEXT NOT NULL, content TEXT NOT NULL,
                payload TEXT NOT NULL, created DOUBLE PRECISION NOT NULL);
CREATE UNIQUE INDEX IF NOT EXISTS message_request ON messages(session,request_id,role);
-- assistant.global_rag_daily_limits：所有用户共享的每日RAG计数
CREATE TABLE IF NOT EXISTS global_rag_daily_limits(day TEXT PRIMARY KEY, used INTEGER NOT NULL CHECK(used>=0), updated DOUBLE PRECISION NOT NULL);
-- assistant.rate_limits：早期通用限流结构，当前仍保留建表
CREATE TABLE IF NOT EXISTS rate_limits(owner TEXT PRIMARY KEY, "window" INTEGER, count INTEGER);
-- assistant.tenant_message_limits：企业共享的滚动60秒提问额度
CREATE TABLE IF NOT EXISTS tenant_message_limits(owner TEXT PRIMARY KEY, events TEXT NOT NULL, updated DOUBLE PRECISION NOT NULL);
CREATE INDEX IF NOT EXISTS message_retention ON messages(created);
CREATE INDEX IF NOT EXISTS session_retention ON sessions(updated);
-- assistant.workflow_runs：单次请求的工作流运行登记
CREATE TABLE IF NOT EXISTS workflow_runs(id TEXT PRIMARY KEY, session TEXT NOT NULL REFERENCES sessions(id) ON DELETE CASCADE, request_id TEXT NOT NULL, status TEXT NOT NULL, created DOUBLE PRECISION NOT NULL, updated DOUBLE PRECISION NOT NULL);
ALTER TABLE messages ADD COLUMN IF NOT EXISTS seq BIGSERIAL UNIQUE;

-- 二、LangGraph检查点表：langgraph-checkpoint-postgres==3.2.0
-- 与该锁定版本MIGRATIONS逐项一致，只把并发建索引改为普通建索引。

-- checkpoint migration 0
-- assistant.checkpoint_migrations：检查点数据库结构的迁移版本记录
CREATE TABLE IF NOT EXISTS checkpoint_migrations (
    v INTEGER PRIMARY KEY
);

-- checkpoint migration 1
-- assistant.checkpoints：LangGraph流程状态快照
CREATE TABLE IF NOT EXISTS checkpoints (
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
CREATE TABLE IF NOT EXISTS checkpoint_blobs (
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
CREATE TABLE IF NOT EXISTS checkpoint_writes (
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
CREATE INDEX IF NOT EXISTS checkpoints_thread_id_idx ON checkpoints(thread_id);

-- checkpoint migration 7
CREATE INDEX IF NOT EXISTS checkpoint_blobs_thread_id_idx ON checkpoint_blobs(thread_id);

-- checkpoint migration 8
CREATE INDEX IF NOT EXISTS checkpoint_writes_thread_id_idx ON checkpoint_writes(thread_id);

-- checkpoint migration 9
ALTER TABLE checkpoint_writes ADD COLUMN IF NOT EXISTS task_path TEXT NOT NULL DEFAULT '';

-- 三、知识文档、切片与Embedding缓存表（app/rag.py）
SET LOCAL search_path TO knowledge, public;
-- knowledge.rag_state：当前知识索引配置指纹和代次
CREATE TABLE IF NOT EXISTS rag_state(id INTEGER PRIMARY KEY CHECK(id=1),fingerprint TEXT,generation INTEGER NOT NULL);
-- knowledge.rag_documents：知识文档登记和当前有效版本
CREATE TABLE IF NOT EXISTS rag_documents(id TEXT PRIMARY KEY,path TEXT UNIQUE,title TEXT,current_revision TEXT,active INTEGER,updated DOUBLE PRECISION);
-- knowledge.rag_revisions：文档各版本及原始文件内容
CREATE TABLE IF NOT EXISTS rag_revisions(document_id TEXT,revision TEXT,filename TEXT,raw BYTEA,metadata TEXT,created DOUBLE PRECISION,PRIMARY KEY(document_id,revision));
-- knowledge.rag_chunks：真实知识切片及关联信息
CREATE TABLE IF NOT EXISTS rag_chunks(id TEXT PRIMARY KEY,document_id TEXT,revision TEXT,ordinal INTEGER,record TEXT,vector TEXT);
CREATE INDEX IF NOT EXISTS rag_chunk_doc ON rag_chunks(document_id,revision);
-- knowledge.rag_events：知识入库、重建、停用、启用等事件
CREATE TABLE IF NOT EXISTS rag_events(id BIGSERIAL PRIMARY KEY,document_id TEXT,action TEXT,revision TEXT,created DOUBLE PRECISION);
-- knowledge.rag_embedding_cache：Embedding计算结果缓存，减少重复向量化
CREATE TABLE IF NOT EXISTS rag_embedding_cache(fingerprint TEXT,text_hash TEXT,vector TEXT,PRIMARY KEY(fingerprint,text_hash));
COMMIT;

-- 建表完成后执行 ../data/1.0.0.sql：登记部署归属、迁移版本0-9及rag_state初始行。
