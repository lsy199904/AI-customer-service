-- =====================================================================
-- 只读结构体检（psql 执行，不依赖 Flyway）
--
-- 用法：
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f database/postgres/checks/health.sql
--
-- 适用：
--   1. 迁移后验收；
--   2. 存量库 baseline 前的结构核对；
--   3. 应用发版前的快速自检。
--
-- 说明：
--   - 任一检查失败即抛异常，配合 ON_ERROR_STOP=1 返回非零退出码；
--   - 不检查业务数据量、知识是否入库、Milvus 是否可达；
--   - 不修改任何对象。
-- =====================================================================
DO $$
DECLARE
    missing     TEXT;
    v_count     INTEGER;
BEGIN
    -- -----------------------------------------------------------------
    -- 1. Flyway 历史（baseline 前允许不存在）
    -- -----------------------------------------------------------------
    IF to_regclass('assistant.flyway_schema_history') IS NULL THEN
        RAISE NOTICE 'health: 未发现 flyway_schema_history（baseline 前检查可忽略此项）';
    ELSIF EXISTS (
        SELECT 1
          FROM assistant.flyway_schema_history
         WHERE success = false
    ) THEN
        RAISE EXCEPTION 'health: flyway_schema_history 存在失败记录，请先排查并 repair';
    END IF;

    -- -----------------------------------------------------------------
    -- 2. 核心表
    -- -----------------------------------------------------------------
    SELECT string_agg(req.name, ', ' ORDER BY req.name)
      INTO missing
      FROM (VALUES
                ('assistant.sessions'),
                ('assistant.messages'),
                ('assistant.global_rag_daily_limits'),
                ('assistant.rate_limits'),
                ('assistant.tenant_message_limits'),
                ('assistant.workflow_runs'),
                ('assistant.checkpoint_migrations'),
                ('assistant.checkpoints'),
                ('assistant.checkpoint_blobs'),
                ('assistant.checkpoint_writes'),
                ('assistant.external_deployment'),
                ('knowledge.rag_state'),
                ('knowledge.rag_documents'),
                ('knowledge.rag_revisions'),
                ('knowledge.rag_chunks'),
                ('knowledge.rag_events'),
                ('knowledge.rag_embedding_cache')
           ) AS req(name)
     WHERE to_regclass(req.name) IS NULL;

    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'health: 缺少核心表 -> %', missing;
    END IF;

    -- -----------------------------------------------------------------
    -- 3. 关键列（含保留字列 user / window）
    -- -----------------------------------------------------------------
    SELECT string_agg(
               format(
                   '%s.%s.%s',
                   req.schema_name,
                   req.table_name,
                   req.column_name
               ),
               ', '
               ORDER BY req.schema_name, req.table_name, req.column_name
           )
      INTO missing
      FROM (VALUES
                ('assistant', 'sessions', 'id'),
                ('assistant', 'sessions', 'tenant'),
                ('assistant', 'sessions', 'user'),
                ('assistant', 'sessions', 'context'),
                ('assistant', 'sessions', 'created'),
                ('assistant', 'sessions', 'updated'),
                ('assistant', 'messages', 'id'),
                ('assistant', 'messages', 'session'),
                ('assistant', 'messages', 'request_id'),
                ('assistant', 'messages', 'role'),
                ('assistant', 'messages', 'content'),
                ('assistant', 'messages', 'payload'),
                ('assistant', 'messages', 'created'),
                ('assistant', 'messages', 'seq'),
                ('assistant', 'global_rag_daily_limits', 'day'),
                ('assistant', 'global_rag_daily_limits', 'used'),
                ('assistant', 'global_rag_daily_limits', 'updated'),
                ('assistant', 'rate_limits', 'owner'),
                ('assistant', 'rate_limits', 'window'),
                ('assistant', 'rate_limits', 'count'),
                ('assistant', 'tenant_message_limits', 'owner'),
                ('assistant', 'tenant_message_limits', 'events'),
                ('assistant', 'tenant_message_limits', 'updated'),
                ('assistant', 'workflow_runs', 'id'),
                ('assistant', 'workflow_runs', 'session'),
                ('assistant', 'workflow_runs', 'request_id'),
                ('assistant', 'workflow_runs', 'status'),
                ('assistant', 'workflow_runs', 'created'),
                ('assistant', 'workflow_runs', 'updated'),
                ('assistant', 'checkpoints', 'thread_id'),
                ('assistant', 'checkpoints', 'checkpoint_ns'),
                ('assistant', 'checkpoints', 'checkpoint_id'),
                ('assistant', 'checkpoints', 'checkpoint'),
                ('assistant', 'checkpoints', 'metadata'),
                ('assistant', 'checkpoint_blobs', 'channel'),
                ('assistant', 'checkpoint_blobs', 'version'),
                ('assistant', 'checkpoint_blobs', 'blob'),
                ('assistant', 'checkpoint_writes', 'task_id'),
                ('assistant', 'checkpoint_writes', 'idx'),
                ('assistant', 'checkpoint_writes', 'task_path'),
                ('knowledge', 'rag_state', 'id'),
                ('knowledge', 'rag_state', 'fingerprint'),
                ('knowledge', 'rag_state', 'generation'),
                ('knowledge', 'rag_documents', 'id'),
                ('knowledge', 'rag_documents', 'path'),
                ('knowledge', 'rag_documents', 'title'),
                ('knowledge', 'rag_documents', 'current_revision'),
                ('knowledge', 'rag_documents', 'active'),
                ('knowledge', 'rag_documents', 'updated'),
                ('knowledge', 'rag_revisions', 'document_id'),
                ('knowledge', 'rag_revisions', 'revision'),
                ('knowledge', 'rag_revisions', 'filename'),
                ('knowledge', 'rag_revisions', 'raw'),
                ('knowledge', 'rag_revisions', 'metadata'),
                ('knowledge', 'rag_revisions', 'created'),
                ('knowledge', 'rag_chunks', 'id'),
                ('knowledge', 'rag_chunks', 'document_id'),
                ('knowledge', 'rag_chunks', 'revision'),
                ('knowledge', 'rag_chunks', 'ordinal'),
                ('knowledge', 'rag_chunks', 'record'),
                ('knowledge', 'rag_chunks', 'vector'),
                ('knowledge', 'rag_events', 'id'),
                ('knowledge', 'rag_events', 'document_id'),
                ('knowledge', 'rag_events', 'action'),
                ('knowledge', 'rag_events', 'revision'),
                ('knowledge', 'rag_events', 'created'),
                ('knowledge', 'rag_embedding_cache', 'fingerprint'),
                ('knowledge', 'rag_embedding_cache', 'text_hash'),
                ('knowledge', 'rag_embedding_cache', 'vector')
           ) AS req(schema_name, table_name, column_name)
     WHERE NOT EXISTS (
               SELECT 1
                 FROM information_schema.columns c
                WHERE c.table_schema = req.schema_name
                  AND c.table_name   = req.table_name
                  AND c.column_name  = req.column_name
           );

    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'health: 缺少关键列 -> %', missing;
    END IF;

    -- -----------------------------------------------------------------
    -- 4. messages.seq 必须是 BIGSERIAL，且存在唯一约束
    -- -----------------------------------------------------------------
    IF NOT EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'assistant'
           AND table_name   = 'messages'
           AND column_name  = 'seq'
           AND data_type    = 'bigint'
           AND column_default LIKE 'nextval(%'
    ) THEN
        RAISE EXCEPTION 'health: assistant.messages.seq 不是 BIGSERIAL（类型或默认值不符）';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM pg_indexes
         WHERE schemaname = 'assistant'
           AND tablename  = 'messages'
           AND indexdef ILIKE '%UNIQUE%'
           AND indexdef ILIKE '%(seq)%'
    ) THEN
        RAISE EXCEPTION 'health: assistant.messages.seq 缺少唯一索引/约束';
    END IF;

    -- -----------------------------------------------------------------
    -- 5. 检查点表必须与 langgraph-checkpoint-postgres 3.2.x 对齐
    -- -----------------------------------------------------------------
    IF NOT EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'assistant'
           AND table_name   = 'checkpoint_blobs'
           AND column_name  = 'blob'
           AND is_nullable  = 'YES'
    ) THEN
        RAISE EXCEPTION 'health: assistant.checkpoint_blobs.blob 应为可空（migration 4 未生效）';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema = 'assistant'
           AND table_name   = 'checkpoint_writes'
           AND column_name  = 'task_path'
           AND is_nullable  = 'NO'
           AND column_default LIKE '''%'
    ) THEN
        RAISE EXCEPTION 'health: assistant.checkpoint_writes.task_path 缺失或默认值不符（migration 9 未生效）';
    END IF;

    IF EXISTS (
        SELECT v
          FROM generate_series(0, 9) AS g(v)
         WHERE NOT EXISTS (
                   SELECT 1
                     FROM assistant.checkpoint_migrations m
                    WHERE m.v = g.v
               )
    ) THEN
        RAISE EXCEPTION 'health: checkpoint_migrations 未覆盖 0..9';
    END IF;

    -- -----------------------------------------------------------------
    -- 6. 关键索引
    -- -----------------------------------------------------------------
    SELECT string_agg(req.name, ', ' ORDER BY req.name)
      INTO missing
      FROM (VALUES
                ('assistant.session_owner'),
                ('assistant.session_retention'),
                ('assistant.message_request'),
                ('assistant.message_retention'),
                ('assistant.checkpoints_thread_id_idx'),
                ('assistant.checkpoint_blobs_thread_id_idx'),
                ('assistant.checkpoint_writes_thread_id_idx'),
                ('knowledge.rag_chunk_doc')
           ) AS req(name)
     WHERE to_regclass(req.name) IS NULL;

    IF missing IS NOT NULL THEN
        RAISE EXCEPTION 'health: 缺少关键索引 -> %', missing;
    END IF;

    -- -----------------------------------------------------------------
    -- 7. 外键必须保持 ON DELETE CASCADE
    --    会话删除时清理消息与工作流记录
    -- -----------------------------------------------------------------
    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint c
          JOIN pg_class t
            ON t.oid = c.conrelid
          JOIN pg_namespace n
            ON n.oid = t.relnamespace
         WHERE c.contype = 'f'
           AND n.nspname = 'assistant'
           AND t.relname = 'messages'
           AND c.confrelid = 'assistant.sessions'::regclass
           AND pg_get_constraintdef(c.oid) ILIKE '%ON DELETE CASCADE%'
    ) THEN
        RAISE EXCEPTION 'health: assistant.messages.session 外键缺失或未设置 ON DELETE CASCADE';
    END IF;

    IF NOT EXISTS (
        SELECT 1
          FROM pg_constraint c
          JOIN pg_class t
            ON t.oid = c.conrelid
          JOIN pg_namespace n
            ON n.oid = t.relnamespace
         WHERE c.contype = 'f'
           AND n.nspname = 'assistant'
           AND t.relname = 'workflow_runs'
           AND c.confrelid = 'assistant.sessions'::regclass
           AND pg_get_constraintdef(c.oid) ILIKE '%ON DELETE CASCADE%'
    ) THEN
        RAISE EXCEPTION 'health: assistant.workflow_runs.session 外键缺失或未设置 ON DELETE CASCADE';
    END IF;

    -- -----------------------------------------------------------------
    -- 8. 知识状态与部署归属
    -- -----------------------------------------------------------------
    SELECT count(*)
      INTO v_count
      FROM knowledge.rag_state;

    IF v_count <> 1
       OR NOT EXISTS (SELECT 1 FROM knowledge.rag_state WHERE id = 1)
    THEN
        RAISE EXCEPTION 'health: knowledge.rag_state 必须恰有 1 行且 id=1，实际 % 行', v_count;
    END IF;

    SELECT count(*)
      INTO v_count
      FROM assistant.external_deployment;

    IF v_count <> 1 THEN
        RAISE EXCEPTION 'health: assistant.external_deployment 必须恰有 1 行，实际 % 行', v_count;
    END IF;

    IF EXISTS (
        SELECT 1
          FROM assistant.external_deployment
         WHERE id = 1
           AND (
                   metadata ->> 'id'              IS NULL
                OR btrim(metadata ->> 'id')              = ''
                OR metadata ->> 'milvus_uri'      IS NULL
                OR btrim(metadata ->> 'milvus_uri')      = ''
                OR metadata ->> 'milvus_database' IS NULL
                OR btrim(metadata ->> 'milvus_database') = ''
                OR metadata ->> 'milvus_prefix'   IS NULL
                OR btrim(metadata ->> 'milvus_prefix')   = ''
           )
    ) THEN
        RAISE EXCEPTION 'health: external_deployment 的 4 个归属字段存在空值';
    END IF;

    RAISE NOTICE 'health: 结构体检通过（表、列、seq、检查点、索引、外键、归属行）';
END
$$;

SELECT 'health: ok' AS result;
