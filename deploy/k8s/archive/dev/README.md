# SmartTITU Assistant 部署说明文档

## 一、前置条件

* Postgres 数据库 参考 [](postgres/README.md)
* Milvus 向量数据库 参考 [](milvus/README.md)
* 一个正在运行的 Kubernetes 集群
* 一个可用的 StorageClass

## 二、 部署 app

### 2.1 准备工作

#### 1. 生成认证token

```python
python3 -c 'import secrets; print(secrets.token_urlsafe(24))'
```

#### 2. 创建专属数据库和账号

postgresql://smarttitu_assistant:dasb386cwwEUChfi#*!jdsadh=@postgres-14-cluster-rw.postgres.svc.cluster.local:5432/smarttitu_assistant?sslmode=disable

```sql
-- 1. 创建专用账号
CREATE ROLE smarttitu_assistant WITH LOGIN PASSWORD 'dasb386cwwEUChfi#*!jdsadh=';

-- 2. 创建数据库并指定所有者
CREATE DATABASE smarttitu_assistant
  WITH OWNER    = smarttitu_assistant
       ENCODING = 'UTF8'
       TEMPLATE = template0;

```