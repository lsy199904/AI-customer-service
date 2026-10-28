# SmartTITU 企业智能客服

FastAPI + Uvicorn 提供接口，LangChain 连接模型与检索器，LangGraph 编排并持久化问答流程。企业部署使用 PostgreSQL 保存聊天、知识版本和工作流检查点，Milvus 提供向量索引；保留 SQLite 单实例兼容和回退能力。

默认问答链路为：Word/PDF解析 → BGE-M3向量 → Milvus + BM25 混合召回 → RRF融合 → Qwen3-Reranker-4B重排 → Qwen3-32B基于资料流式生成正文 → 附加知识关联图片与来源 → 保存历史。iframe、自带浮窗和直接API共用同一套会话及权限逻辑，无需 Dify。

## 现有服务器升级

完整操作、自检、备份、恢复、回退和质量评测见 [企业升级与迁移](docs/企业升级与迁移.md)；架构见 [企业客服框架](docs/企业部署与框架.md)。以下在 Linux 模型主机 ~/ai_customer 执行。先在旧服务备份，再更新代码；已经拉取新代码时可继续，迁移工具也会保存一致性SQLite副本。

```bash
cd ~/ai_customer
# 尚未拉取时先用旧服务备份
sh scripts/docker-host.sh exec assistant python manage.py backup &&
git pull --ff-only origin main

sh scripts/enterprise.sh configure &&
sh scripts/enterprise.sh build &&
sh scripts/enterprise.sh infrastructure
# 下列步骤进入维护窗口，停止旧客服并迁移数据
sh scripts/enterprise.sh migrate &&
sh scripts/enterprise.sh start &&
sh scripts/enterprise.sh doctor
```

不要删除 .env、var/、models/、knowledge_sources/。configure 保留原 AUTH_SECRET 和三个模型配置，生成本机数据库凭证；新镜像构建成功后才进入维护迁移。已有向量直接同步，不重复下载模型或调用Embedding。迁移不自动把旧 Word 换成新 Word，知识数量以实际活动版本为准。新容器依赖必须 build，restart 不会安装依赖。

默认复用已运行的 Ollama/vLLM 服务，不另起 GPU 模型副本。基础设施额外启动 PostgreSQL、etcd、MinIO、Milvus，关系库和向量服务只绑定宿主机回环端口。模型复制目录仍留在 models/，不提交Git。

## 模型与身份配置

Python使用3.12，安装 requirements.lock 中的锁定依赖；requirements.txt仅描述直接依赖范围。容器通过 env_file 读取 .env，原生 manage.py 自动读取，不需要 source。

```dotenv
AUTH_SECRET=保留你已经生成的至少32字节随机密钥
ANSWER_MODE=llm
RETRIEVAL_BACKEND=semantic
MODEL_BASE_URL=http://10.180.158.23:18080/v1
MODEL_API_KEY=not-empty
MODEL_NAME=Qwen/Qwen3-32B
MODEL_HTTP_ORIGINS=http://10.180.158.23:18080,http://127.0.0.1:11434,http://172.19.0.2:8001
EMBEDDING_PROVIDER=ollama
EMBEDDING_URL=http://127.0.0.1:11434/api/embed
EMBEDDING_MODEL=bge-m3:latest
EMBEDDING_REVISION=v1
RERANK_ENABLED=true
RERANK_URL=http://172.19.0.2:8001/v1/rerank
RERANK_MODEL=Qwen3-Reranker-4B
RERANK_API_KEY=已有重排服务的真实密钥
HOST=127.0.0.1
PORT=8000
```

中文说明不要当作实际密钥填写。现有服务器上重排密钥不知道时，可运行 python3 scripts/configure_existing_services.py 从本机获授权的Docker配置读取并写入.env，不打印密钥、不重启模型。重排密钥不能用not-empty代替。容器IP变更后需要更新地址，重新创建客服容器读取配置；不要重启其他人的模型服务。

DATABASE_URL、MILVUS_TOKEN、OPERATIONS_TOKEN 等企业配置由 enterprise.sh configure 生成，保存在本机，不交给前端。二维码暂无真实地址时 SUPPORT_QR_URL 留空，不展示占位码。Qwen3默认关闭思考输出；若你的服务不支持该模板参数，设置 MODEL_DISABLE_THINKING=false 后重新创建容器。

## 知识文档更新

私有最新版 Word 由维护者**单独上传**，统一覆盖 knowledge_sources/SmartTITU客户问答.docx。仓库历史中的旧种子Word不代表最新业务知识；新镜像不复制来源Word/PDF，部署读取挂载目录。当前维护版为v4去重版，50个主题，包括前三个资源链接、企业注册/认证、开发票、充值结算，以及合并的服务体系与架构。原文及历史引用保留，内部资料不放入这个共享外部客户知识库。

```bash
sh scripts/enterprise.sh exec assistant python manage.py documents
sh scripts/enterprise.sh exec assistant python manage.py ingest &&
sh scripts/enterprise.sh restart assistant &&
sh scripts/enterprise.sh doctor
```

同一份Word不要同时保留长文件名和固定文件名两个副本。文件改名不自动识别为替换；用 documents 核对并显式 deactivate 不再使用的旧文档ID。普通正文/条目增删用 ingest；模型、Embedding处理版本或切分配置改变才 ingest --rebuild。全量重建遇到缺失活动文件会停止，不擅自删除知识。

支持 docx、文本型pdf、md、txt；扫描PDF需先OCR，不支持旧doc格式。Embedding接收解析切分后的文本，不直接接收Word二进制，不训练或修改模型。短问答按标题保留完整，长段按1000字符/100重叠切分，来源版本和页码随片段保存。

图片必须登记在 data/media.json 并提供对应 app/static/media/ 文件，Word使用“配图：图片ID”绑定当前章节。已发布的23张当前配图随代码同步，历史登记图片保留以支持旧消息。新增图片需同步登记和资源，不能只粘贴进Word。回答附本轮实际引用章节的图，最多4张，不沿用上一题配图。原始PDF不上传公开仓库；需要客户下载时使用受控地址或认证的版本下载接口。

## 页面与API接入

- **iframe**：独立窗口地址 /chatbot，或通过 /iframe.js 自动创建悬浮iframe。
- **自带浮窗**：加载 /widget.js，由脚本创建按钮和完整窗口。
- **直接API**：前端已有聊天界面时调用 /v1/bootstrap、/v1/sessions、messages、sources 等接口。

接入示例、iframe登录桥接和来源配置见 [悬浮弹窗接入](docs/悬浮弹窗接入.md)，接口见 [API说明](docs/API对接说明.md) 和 [OpenAPI](docs/openapi.json)。GET /openapi.json 需要Bearer凭证，默认不公开Swagger。

三种方式统一使用平台后端签发的租户/用户短期凭证。业务后端必须先验证真实平台登录态，从可信服务端会话取得企业ID和用户ID，再调用 issue_token；不能由浏览器自报企业身份。AUTH_SECRET只留可信后端，token不放iframe URL。真实平台的登录凭证接口、登出联动和权限联调需要接入你现有网站，仓库不包含那个平台的账号系统。

联调页 /widget/demo 提供平台背景和可用客服浮窗，凭证可通过以下命令生成：

```bash
sh scripts/enterprise.sh exec assistant python manage.py token --tenant demo --user tester
```

填入的是短期登录凭证，不是模型API Key，默认一小时有效。HOST=127.0.0.1仅本机访问；获准内网访问设HOST=0.0.0.0并执行 enterprise.sh start，当前目标主机地址为 http://10.180.158.23:8000/widget/demo。正式网站应使用HTTPS代理，联调页禁止对公众开放。配置 FRAME_ORIGINS 为iframe父页面精确来源；CORS_ORIGINS 为浏览器API来源，二者不能替代登录身份校验。

## 对话流程与准确率

问候直接用模型友好回应，不检索知识；业务知识问题先检索，有足够证据才生成，无有效知识或无法回答时先给推荐问题及“以上都不是，转人工”按钮；用户选择或明确要求人工后才展示联系方式。敏感话题不生成内容，使用同样推荐引导。二维码没配置就不显示。历史按企业和用户隔离，重启后保留；默认携带最近20轮（40条消息），在线历史保留7天，空闲30分钟后保留历史但不携带旧上下文。明确指代追问可参考前一个问题，切换主题不叠加旧图片。

默认向量余弦起始门槛0.75，每路top12、融合最多24、最终最多3段证据；BM25和章节主题保护能补候选漏召回，不要求用户逐字命中，更没有把50个问题写成固定答案分支。Reranker默认门槛0.6，过滤低分候选后排序，两个分数都不是准确率。需要用真实语义问法、知识外负例和答案审阅校准。

诊断命令不调用聊天模型：

```bash
sh scripts/enterprise.sh exec assistant python manage.py retrieve --query '企业注册与认证流程是什么'
```

完整 [语义评测步骤](docs/企业升级与迁移.md) 支持为全部主题生成多样问法、人工审阅后分别统计召回、选中文档、引用、关键事实、图片与耗时；私有数据集和报告不推Git。自动测试通过不等于目标模型业务准确率通过，也不承诺任意问法100%正确。

SSE接口 /v1/sessions/{sid}/messages/stream 先推处理进度与心跳，模型生成正文时即时发送delta，生成结束后发送附带来源、图片的complete；原JSON接口保持兼容。相同request_id重试返回已保存结果，不重复写聊天；更换问题必须换请求ID。

## 运维与测试

```bash
sh scripts/enterprise.sh ps
sh scripts/enterprise.sh exec assistant python manage.py check
sh scripts/enterprise.sh doctor
sh scripts/enterprise.sh backup
sh scripts/enterprise.sh logs --tail=60 assistant
```

/health检查存活；/ready检查关系库、活动知识和当前向量集合；doctor --models实测Embedding、重排和聊天协议。/metrics使用独立X-Operations-Token，输出进程级计数和耗时。PostgreSQL备份包含检查点、原文版本和向量副本，Milvus可从关系库重建。恢复与无损回退按 [迁移文档](docs/企业升级与迁移.md) 执行，不删卷、不覆盖旧SQLite。需定期备份来源、媒体、.env并演练恢复。

本地开发验证：

```bash
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
python -m unittest discover -s tests -v
```

私有Word核对测试默认跳过；本地资料就绪可设置 RUN_PRIVATE_KNOWLEDGE_TESTS=1。真实PostgreSQL集成测试使用 SMARTTITU_TEST_POSTGRES_URL，必须指向有CREATEDB及CREATEROLE权限的测试服务器；测试只创建和删除独立随机测试库。测试不使用生产凭证、不依赖真实模型。

SQLite兼容部署不设置DATABASE_URL，VECTOR_BACKEND=sqlite、APP_WORKERS=1；原生 manage.py init（仅首次）、配置.env、ingest、serve，或使用原 compose.host.yaml / docker-host.sh。容器企业升级后统一使用enterprise.sh，避免混用。原生serve自动读取.env，直接 python -m app.server 需要已设置环境。

## 已交付范围与后续集成

PostgreSQL模式提供共享会话锁、幂等消息、持久化工作流，可在容量允许时使用2至4worker；默认1。线程和worker数不能替代模型并发能力，需要目标主机压测。当前Compose是单机基础设施，尚未交付多机高可用或具体QPS承诺。

只读业务工具注册边界已提供，租户权限来自后端；真实余额、订单、工单接口未接入时明确提示人工，不伪造业务数据。写入工具仍禁用，接入确认、审计与幂等后才能开放。尚无在线人工工作台、文件上传/OCR、管理后台、跨会话用户画像或企业私有知识分区。共享外部资料与内部资料需分开治理。


### 会话、限流与检索策略

当前默认：语义余弦候选门槛 `0.75`；在线聊天消息保留 `7` 天；模型携带最近 `20` 轮；同一企业所有用户、会话共享滚动60秒内 `20` 条提问；检索链路总预算 `15` 秒。20轮不是会话强制结束上限，7天内仍可查看更早的轮次。空闲30分钟后新一轮不携带空闲前的上下文。

已有部署的 `.env` 会覆盖代码默认值，更新代码后需要显式应用新值：

```bash
cd ~/ai_customer
git pull --ff-only origin main &&
sh scripts/enterprise.sh policies &&
sh scripts/enterprise.sh start &&
sh scripts/enterprise.sh exec assistant python manage.py check
```

该命令仅更新上述5项策略并私密备份原 `.env`，保留模型和数据库凭证。`start` 重建应用容器加载环境变量；前提是企业版基础服务健康、企业版镜像已构建完成。无需重新上传Word、生成向量或迁移数据。旧版未完成企业版升级的容器不能直接运行新代码。

环境变量：`SEMANTIC_MIN_SIMILARITY`、`SESSION_RETENTION_DAYS`、`SESSION_CONTEXT_ROUNDS`、`TENANT_MESSAGES_PER_MINUTE`、`RETRIEVAL_TIMEOUT_SECONDS`。正常执行 `configure` 会保留已有值；`policies` 明确设置本次约定值。

企业限流返回HTTP429（SSE流建立后通过错误事件返回）；新建会话不占额度，成功请求使用相同request_id重试不重复占额度，实际失败的提问尝试也占额度。额度保存在关系库，PostgreSQL多工作进程共享，不因应用重启重置。

超时返回可重试提示、常见问题和转人工入口；不会调用LLM编造回答，也不会使用超时后迟到的检索结果。15秒仅约束检索阶段，不是整条HTTP问答总耗时。检索工作线程和待处理数量有界，各I/O使用剩余预算；同步I/O依靠自身超时退出，无法强制中断Python线程。

历史到期后立即从API与模型上下文中排除；启动时及默认每300秒分批清理在线库的过期消息、闲置会话及对应工作流检查点。已完成回答的冗余工作流快照及时删除，幂等结果保留在消息表。手动清理可执行 `python manage.py prune-sessions`；不删除知识库。备份文件不在在线7天自动清理范围，需要单独设置备份保留策略。

0.75是向量候选余弦门槛，不是75%的准确率。保留BM25及章节主题补召回，因此低于向量门槛的候选仍可能经过词法召回、重排进入回答上下文；本次没有加入人工标准问答优先层。

运营日志、日期轮转、问题编号排查和平台身份对接说明见 [运营日志与身份对接](docs/运营日志与身份对接.md)。聊天来源统一显示为“用户手册：章节名”，用户与 AI 消息分别显示人员、机器人头像。
