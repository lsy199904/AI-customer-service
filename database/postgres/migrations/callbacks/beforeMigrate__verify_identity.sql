-- =====================================================================
-- Flyway 回调：每次 migrate 前校验部署归属凭证
--
-- 执行时机：beforeMigrate（失败即迁移终止）。
-- 防护语义（替代原 app/deployment 的 claim，管理链路不依赖任何应用代码）：
--   1. 全新库（表未建）自动放行：V1.0.0 随后建表并经占位符写入凭证行；
--   2. 表存在但凭证行缺失：拒绝（外来库或异常状态，不接管）；
--   3. 凭证行与当前 FLYWAY_PLACEHOLDERS_* 不一致：拒绝
--      （库属于其他部署或 Milvus 配置已变更，需走正规变更流程，不得静默迁移）。
-- 防呆补充：非空库且无 flyway_schema_history 时，Flyway 原生拒绝
--（baselineOnMigrate=false，见 flyway.conf）；cleanDisabled 永久禁用整库删除。
-- =====================================================================
DO $$
DECLARE
    registered  JSONB;
BEGIN
    -- 全新库：表未建，由 V1.0.0 建表并写凭证
    IF to_regclass('assistant.external_deployment') IS NULL THEN
        RETURN;
    END IF;

    SELECT metadata
      INTO registered
      FROM assistant.external_deployment
     WHERE id = 1;

    IF registered IS NULL THEN
        RAISE EXCEPTION 'external_deployment 表存在但凭证行缺失，拒绝迁移（外来库或异常状态）';
    END IF;

    IF registered ->> 'id' IS DISTINCT FROM '${deployment_id}'
       OR rtrim(registered ->> 'milvus_uri', '/') IS DISTINCT FROM rtrim('${milvus_uri}', '/')
       OR registered ->> 'milvus_database' IS DISTINCT FROM '${milvus_database}'
       OR registered ->> 'milvus_prefix' IS DISTINCT FROM '${milvus_prefix}'
    THEN
        RAISE EXCEPTION '归属凭证与当前部署环境不一致：库属于其他部署或 Milvus 配置已变更，拒绝迁移';
    END IF;
END
$$;
