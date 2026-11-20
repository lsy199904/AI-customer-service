# 火山云 UAT 环境 Postgres 数据库信息

网址 https://console.volcengine.com/db/region:db+cn-guangzhou/rds-pg/detail/postgres-909ea8174503?instanceName=billing_db&tabKey=connection


## 1. 创建专用数据库

`smarttitu_assistant`

## 2. 创建专属用户病赋权给数据库

`smarttitu_assistant` 

## 3. JDBC

``

postgresql://smarttitu_assistant:dasb386cwwEUChfi#*!jdsadh=@postgres909ea8174503.rds-pg.ivolces.com:5432/smarttitu_assistant?sslmode=disable


kubectl -n postgres port-forward svc/postgres-14-cluster-rw 5432:5432 -n app-zone


101.96.217.241


export DATABASE_URL='postgresql://smarttitu_assistant:dasb386cwwEUChfi#*!jdsadh=@101.96.217.241:5432/smarttitu_assistant?sslmode=disable'
