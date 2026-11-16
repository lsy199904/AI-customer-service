-- 外部 PostgreSQL 一次性初始化。用超级用户在目标实例上执行：
--   psql "postgresql://postgres@pg.internal.example.com:5432/postgres" -f bootstrap-db.sql
--
-- 关键点：应用启动时会执行 CREATE SCHEMA IF NOT EXISTS assistant|knowledge，
-- 并对 knowledge schema 建表、对 messages 表做 ALTER TABLE ADD COLUMN。
-- PostgreSQL 对已存在的 schema 做 CREATE SCHEMA IF NOT EXISTS 时**仍然检查
-- database 级 CREATE 权限**，所以只给 schema owner 不够，必须
-- GRANT CREATE ON DATABASE，否则 Pod 启动直接报 permission denied for database。
-- 若 DBA 不允许该权限，替代方案是预建全部表结构并改造 app/core.py 的初始化逻辑，
-- 不属于本次部署范围。

CREATE ROLE assistant_admin  LOGIN PASSWORD 'REPLACE_ADMIN_PASSWORD';
CREATE ROLE assistant_runtime LOGIN PASSWORD 'REPLACE_RUNTIME_PASSWORD'
  NOSUPERUSER NOCREATEDB NOCREATEROLE;

CREATE DATABASE ai_customer
  OWNER assistant_admin
  ENCODING 'UTF8'
  TEMPLATE template0;

\connect ai_customer

-- 应用运行账号：可建 schema/表，但不是数据库管理员
GRANT CONNECT, CREATE ON DATABASE ai_customer TO assistant_runtime;

CREATE SCHEMA IF NOT EXISTS assistant AUTHORIZATION assistant_runtime;
CREATE SCHEMA IF NOT EXISTS knowledge AUTHORIZATION assistant_runtime;

-- LangGraph 检查点与业务表都落在 assistant schema（连接串 search_path 已限定），
-- knowledge schema 存知识元数据与向量副本。
ALTER ROLE assistant_runtime SET search_path TO assistant, public;

-- 备份账号只读能力（可选，按公司备份方案取舍）
GRANT USAGE ON SCHEMA assistant, knowledge TO assistant_admin;

-- 校验：应看到两个 schema 与正确 owner
-- \dn+
-- SELECT rolname, rolsuper FROM pg_roles WHERE rolname LIKE 'assistant%';
