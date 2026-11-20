-- =====================================================================
-- Flyway 回调：afterMigrate 结构体检
--
-- 目的：迁移完成后立即验证“应用启动所依赖的最小结构”是否存在。
-- 说明：
--   1. 只读检查，不修改任何数据；
--   2. 任一检查失败即 RAISE EXCEPTION，Flyway 以非零码退出；
--   3. PostgreSQL 下每个迁移独立提交，本回调失败不会回滚已提交的迁移；
--      修正后重跑 migrate 即可（已应用迁移为 no-op，本回调会再次执行）；
--   4. 不校验知识是否已入库（ingest 可能尚未执行），只校验结构。
-- =====================================================================
DO $$
DECLARE
    missing     TEXT;
    v_count     INTEGER;
BEGIN
    -- -----------------------------------------------------------------
    -- 1. 核心表必须存在（应用启动与知识入库的最小集合）
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
        RAISE EXCEPTION 'afterMigrate: 缺少核心表 -> %', missing;
    END IF;

    -- -----------------------------------------------------------------
    -- 2. 关键列必须存在（覆盖应用运行期 DDL 与各仓储读写）
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
                ('assistant', 'tenant_message_limits', 'owner'),
                ('assistant', 'tenant_message_limits', 'events'),
                ('assistant', 'workflow_runs', 'id'),
                ('assistant', 'workflow_runs', 'session'),
                ('assistant', 'workflow_runs', 'request_id'),
                ('assistant', 'workflow_runs', 'status'),
                ('knowledge', 'rag_state', 'id'),
                ('knowledge', 'rag_state', 'fingerprint'),
                ('knowledge', 'rag_state', 'generation'),
                ('knowledge', 'rag_documents', 'id'),
                ('knowledge', 'rag_documents', 'current_revision'),
                ('knowledge', 'rag_documents', 'active'),
                ('knowledge', 'rag_revisions', 'document_id'),
                ('knowledge', 'rag_revisions', 'revision'),
                ('knowledge', 'rag_revisions', 'raw'),
                ('knowledge', 'rag_chunks', 'id'),
                ('knowledge', 'rag_chunks', 'document_id'),
                ('knowledge', 'rag_chunks', 'revision'),
                ('knowledge', 'rag_chunks', 'record'),
                ('knowledge', 'rag_chunks', 'vector'),
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
        RAISE EXCEPTION 'afterMigrate: 缺少关键列 -> %', missing;
    END IF;

    -- -----------------------------------------------------------------
    -- 3. messages.seq 必须是 BIGSERIAL
    --    应用按 rowid/seq 做稳定排序与历史游标
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
        RAISE EXCEPTION 'afterMigrate: assistant.messages.seq 不是 BIGSERIAL（类型或默认值不符）';
    END IF;

    -- -----------------------------------------------------------------
    -- 4. 知识状态必须恰有一行，且 id = 1
    -- -----------------------------------------------------------------
    SELECT count(*)
      INTO v_count
      FROM knowledge.rag_state;

    IF v_count <> 1
       OR NOT EXISTS (SELECT 1 FROM knowledge.rag_state WHERE id = 1)
    THEN
        RAISE EXCEPTION 'afterMigrate: knowledge.rag_state 必须恰有 1 行且 id=1，实际 % 行', v_count;
    END IF;

    -- -----------------------------------------------------------------
    -- 5. 归属登记必须恰有一行，且 4 个字段均非空
    -- -----------------------------------------------------------------
    SELECT count(*)
      INTO v_count
      FROM assistant.external_deployment;

    IF v_count <> 1 THEN
        RAISE EXCEPTION 'afterMigrate: assistant.external_deployment 必须恰有 1 行，实际 % 行', v_count;
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
        RAISE EXCEPTION 'afterMigrate: external_deployment 的 4 个归属字段存在空值';
    END IF;

    -- -----------------------------------------------------------------
    -- 6. LangGraph 检查点迁移版本必须覆盖 0..9
    --    当前 langgraph-checkpoint-postgres 3.2.x 共 10 条迁移（0–9）。
    --    若依赖升级且 MIGRATIONS 变长，应用 setup() 会自行补迁移；
    --    这里只保证基线范围完整。
    -- -----------------------------------------------------------------
    IF EXISTS (
        SELECT v
          FROM generate_series(0, 9) AS g(v)
         WHERE NOT EXISTS (
                   SELECT 1
                     FROM assistant.checkpoint_migrations m
                    WHERE m.v = g.v
               )
    ) THEN
        RAISE EXCEPTION 'afterMigrate: checkpoint_migrations 未覆盖 0..9，检查点表可能不完整';
    END IF;

    -- -----------------------------------------------------------------
    -- 7. Flyway 自身历史不得有失败记录（有则必须先 repair 或排查）
    --
    --    注意：必须先判存在再查询。PL/pgSQL 会解析整个 IF 表达式，
    --    写成 `to_regclass(...) IS NOT NULL AND EXISTS (SELECT ... FROM 表)`
    --    在表不存在时仍会报 relation does not exist。
    -- -----------------------------------------------------------------
    IF to_regclass('assistant.flyway_schema_history') IS NOT NULL THEN
        IF EXISTS (
            SELECT 1
              FROM assistant.flyway_schema_history
             WHERE success = false
        ) THEN
            RAISE EXCEPTION 'afterMigrate: flyway_schema_history 存在失败记录，请先排查并 repair';
        END IF;
    END IF;

    RAISE NOTICE 'afterMigrate: 结构体检通过（17 张表、关键列、seq、rag_state、归属行、检查点版本）';
END
$$;
