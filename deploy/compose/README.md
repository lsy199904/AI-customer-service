# deploy/compose —— 开发测试环境（Docker Compose 全栈）

开发测试专用单机栈：一条 `up` 完成「起依赖 → 跑迁移 → 知识入库 → 起应用」。
每次基于最新代码打包镜像、彻底摧毁重建，验证干净状态。集群部署见 `deploy/k8s/`。

## 完全重建（唯一标准流程）

```bash
# 首次：生成 .env，填好 MODEL_API_KEY 等密钥
cd deploy/compose && cp .env.example .env

# 之后每次：一条命令完成「最新代码打包镜像 → tag 写回 .env → 彻底摧毁 → 全新起栈」
bash deploy/compose/scripts/dev-rebuild.sh
```

访问入口：`http://<宿主机IP>:30201/smart-bot/`。

脚本自动完成：`uv lock` 依赖同步 → 以 `dev-<日期>-<短sha>` 配套打包双镜像 →
tag 写回 `.env`（`.env` 配一次密钥即可，镜像引用无需再手动改）→ `down -v`
清空数据卷 → `up -d --wait` 等healthy。

- `down -v` 全量重跑迁移与知识入库（预算 ~30 分钟，真实消耗 Embedding 额度）；
  镜像层有缓存时构建只需几十秒。
- 脚本已按国内网络默认走 daocloud 换源：python/uv/flyway 基底镜像与 postgres 镜像
  （postgres 仅在 `.env` 还是官方原始值时自动替换，自定义值不动）。
  网络无障碍时可用环境变量覆盖回官方源，如
  `PYTHON_IMAGE=python:3.12-slim-bookworm bash deploy/compose/scripts/dev-rebuild.sh`。
- 前置：Docker 23+（app 镜像构建需 BuildKit）与 Docker Compose v2.22+；
  `.env` 引用的镜像可拉取（内网 Harbor 或 `docker load`）。

- `down -v` 清空全部数据卷（postgres / milvus / var），每次全量重跑迁移与知识入库
  （预算 ~30 分钟，真实消耗 Embedding 额度）；镜像层有缓存时①通常只需几十秒。
- 前置：Docker 23+（app 镜像构建需 BuildKit）与 Docker Compose v2.22+；
  `.env` 引用的镜像可拉取（内网 Harbor 或 `docker load`）。

## 2026-11-25 功能整合测试

`integrate-main-features-20261125` 以 GitLab main 镜像分支的 `381706e` 为基础，迁入
门户账号绑定、匿名/登录历史隔离、跨窗口实时同步、固定常见问题、多轮意图与追问、
历史回顾、知识内容修正、Token 自动续期、服务重启自动恢复、历史可见期与数据库清理分离。
保留 main 的镜像构建、Compose、K8s、CI、PG 迁移和知识初始化流程。

仅在可信门户接入测试中，在 `deploy/compose/.env` 设置：

```dotenv
WIDGET_TRUST_ACCOUNT_PARAMS=true
WIDGET_ACCOUNT_TENANT=smarttitu_portal
QUERY_CONTEXT_TIMEOUT_SECONDS=30
SESSION_RETENTION_DAYS=7
SESSION_PURGE_AFTER_DAYS=0
```

门户须传递稳定 `userId` 和用于日志的 `userName`。账号参数模式沿用已约定的可信门户
前提，不会验证门户登录 Token。匿名历史与登录历史不合并；同账号不同会话仍各自独立。
实时同步使用应用 `/smart-bot/v1/events`，代理须允许长连接并关闭该路径响应缓冲。

`SESSION_PURGE_AFTER_DAYS=0` 不自动删除数据库历史，用户仍只可读7天内消息；日志独立保留。
此设置不能恢复已被清理的数据，也不能阻止开发环境 `down -v` 删除全部测试卷。

开发测试仍使用本文的 `dev-rebuild.sh`；它会清空 **titu-assistant Compose 项目**的数据卷。
建议从原服务仓库建立独立 worktree，把 `APP_NODE_PORT` 设置为8205先验证，避免占用原8200。
默认会创建一套独立 PG/Milvus，不会复制原测试库的聊天历史。需要测试Milvus2.5.24时，
只在本地 `.env` 设置 `MILVUS_IMAGE=milvusdb/milvus:v2.5.24`，不修改编排文件。
测试完成再停旧8200服务、将本栈 `APP_NODE_PORT` 改为8200并重建应用容器。
K8s 不调用这些开发清卷脚本。

知识重建仍保持原语义：`ingest` 增量处理，`ingest --rebuild` 全量处理但保留旧修订；
本次未新增清空知识表、集合或PDF生成目录的逻辑。

回归记录：Python非浏览器测试82项通过、9个子测试通过；两个来源校验测试在原始main上
同样失败（main把来源拒绝代码注释掉），本次不修改该策略。一个原有UI测试因环境跳过。
Milvus SDK建集合测试在本机缺少可安装的grpcio依赖，未执行；Docker/K8s实部署需要服务器验证。
JS连接、身份桥接和双浏览器模拟后端测试通过，覆盖HTML 502重试、Token续期、回答中断恢复、
原请求ID复用、实时增量同步及最终历史对齐。SQL门禁通过（本机未安装sqlfluff，未执行格式检查）。

### 证据选择模型超时回退修复

`EVIDENCE_SELECTION_TIMEOUT_SECONDS=10` 单独控制证据选择模型，旧代码固定为5秒；
该调用仍受 `RETRIEVAL_TIMEOUT_SECONDS` 的剩余总预算约束。输入理解仍由
`QUERY_CONTEXT_TIMEOUT_SECONDS` 控制，两者独立。需要更大预算时可在本地配置中设置
`RETRIEVAL_TIMEOUT_SECONDS=30`，这是运行配置选择，不改变检索相似度或重排门槛。
超时、空文本、无效JSON会触发有基本词语匹配检查的原相关性排序回退，不再按候选池内
“稀有措辞”重排。模型成功返回空证据数组时仍保持无支持证据，不擅自补选。
日志 `selection_policy=ranked_query_support_fallback` 标识新回退策略。
新增回归复现了旧策略将问题42排除、误选交付/订购流程的案例，不绑定问题编号或业务答案。
