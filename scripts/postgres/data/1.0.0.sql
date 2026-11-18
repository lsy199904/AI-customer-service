-- SmartTITU 线上手工初始化数据；适配当前发布代码7942a6f，PostgreSQL 14/16。
-- 必须在 ../schema/1.0.0.sql 之后执行；本文件只写初始数据，不建任何结构。
-- 下方4个REPLACE值必须与App的环境变量完全一致；URI去除末尾/。
-- 在psql中执行，请使用：psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f 1.0.0.sql
-- 只用于新部署；不是现有数据库的升级/降级脚本。不DROP、不清空、不覆盖已有记录。
BEGIN;
-- assistant.external_deployment：部署归属登记，防止误连其他部署的库或集合
DO $manual$
DECLARE
  expected JSONB := jsonb_build_object(
    'id', 'REPLACE_DEPLOYMENT_ID',
    'milvus_uri', rtrim('REPLACE_MILVUS_URI', '/'),
    'milvus_database', 'REPLACE_MILVUS_DATABASE',
    'milvus_prefix', 'REPLACE_MILVUS_COLLECTION_PREFIX'
  );
  registered JSONB;
BEGIN
  IF expected::TEXT LIKE '%REPLACE_%' THEN
    RAISE EXCEPTION '请先将4个REPLACE值替换为生产App实际配置';
  END IF;
  SELECT metadata INTO registered FROM assistant.external_deployment WHERE id=1;
  IF registered IS NOT NULL AND registered <> expected THEN
    RAISE EXCEPTION '部署归属或Milvus配置不一致，拒绝覆盖';
  END IF;
  INSERT INTO assistant.external_deployment(id,metadata) VALUES(1,expected)
    ON CONFLICT(id) DO NOTHING;
END;
$manual$;

-- assistant.checkpoint_migrations：登记LangGraph检查点迁移版本0-9，与schema/1.0.0.sql中migration 0-9一致
INSERT INTO assistant.checkpoint_migrations(v)
SELECT v FROM generate_series(0,9) AS v ON CONFLICT DO NOTHING;

-- knowledge.rag_state：初始fingerprint为空；ingest后才会登记实际知识配置及数据
INSERT INTO knowledge.rag_state(id,fingerprint,generation) VALUES(1,'',0) ON CONFLICT DO NOTHING;
COMMIT;

-- 只读核对：共17张表，checkpoint_migrations包含0到9。
SELECT table_schema,table_name FROM information_schema.tables
 WHERE table_schema IN ('assistant','knowledge') ORDER BY table_schema,table_name;
SELECT v FROM assistant.checkpoint_migrations ORDER BY v;
