-- =====================================================================
-- 结构指纹（只读）
--
-- 用途：
--   对比「Flyway 建出的库」与「应用自建出的库」是否结构等价。
--   两边执行本文件，输出的 md5 必须相同。
--
-- 用法：
--   psql "$DATABASE_URL" -At -v ON_ERROR_STOP=1 \
--     -f database/postgres/checks/schema_fingerprint.sql
--
-- 覆盖：
--   - 列：schema.table.column、类型、NOT NULL、默认值
--   - 约束：主键、唯一、外键、CHECK
--   - 索引：pg_indexes.indexdef
--
-- 排除：
--   - assistant.flyway_schema_history（仅 Flyway 侧存在）
--   - assistant.external_deployment（应用启动路径不创建，由 claim/迁移创建）
--
-- 注意：
--   本文件是快速一致性校验；最终验收仍以
--   `pg_dump --schema-only` 归一化后的 diff 为准。
-- =====================================================================
WITH excluded_tables (name) AS (
    VALUES
        ('flyway_schema_history'),
        ('external_deployment')
),
col_lines AS (
    SELECT format(
               'COL %s.%s.%s %s notnull=%s default=%s',
               n.nspname,
               c.relname,
               a.attname,
               format_type(a.atttypid, a.atttypmod),
               a.attnotnull,
               coalesce(pg_get_expr(d.adbin, d.adrelid), '-')
           ) AS line
      FROM pg_attribute a
      JOIN pg_class c
        ON c.oid = a.attrelid
      JOIN pg_namespace n
        ON n.oid = c.relnamespace
      LEFT JOIN pg_attrdef d
        ON d.adrelid = a.attrelid
       AND d.adnum = a.attnum
     WHERE n.nspname IN ('assistant', 'knowledge')
       AND c.relkind = 'r'
       AND a.attnum > 0
       AND NOT a.attisdropped
       AND c.relname NOT IN (SELECT name FROM excluded_tables)
),
con_lines AS (
    SELECT format(
               'CON %s.%s %s %s',
               n.nspname,
               c.relname,
               con.conname,
               pg_get_constraintdef(con.oid)
           ) AS line
      FROM pg_constraint con
      JOIN pg_class c
        ON c.oid = con.conrelid
      JOIN pg_namespace n
        ON n.oid = c.relnamespace
     WHERE n.nspname IN ('assistant', 'knowledge')
       AND c.relkind = 'r'
       AND c.relname NOT IN (SELECT name FROM excluded_tables)
),
idx_lines AS (
    SELECT format(
               'IDX %s.%s %s',
               schemaname,
               tablename,
               indexdef
           ) AS line
      FROM pg_indexes
     WHERE schemaname IN ('assistant', 'knowledge')
       AND tablename NOT IN (SELECT name FROM excluded_tables)
)
SELECT md5(string_agg(line, E'\n' ORDER BY line)) AS schema_fingerprint
  FROM (
        SELECT line FROM col_lines
        UNION ALL
        SELECT line FROM con_lines
        UNION ALL
        SELECT line FROM idx_lines
       ) s;
