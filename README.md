# SmartTITU 智能客服（titu-assistant）

面向企业客户的智能客服服务：基于检索增强生成（RAG）回答问题，输出可核验的知识引用与配图，资料不足时明确说明并引导转人工。服务只调用外部的 LLM / Embedding / Rerank 接口与已开通的 PostgreSQL、Milvus，**不在仓库内部署模型、数据库或对象存储**。

| 项 | 说明 |
|---|---|
| 运行形态 | FastAPI + Uvicorn 单进程（可扩展到多 worker），生产运行于 Kubernetes |
| 检索链路 | Milvus 向量召回 + BM25 词法召回 + RRF 融合 + 外部 Rerank 重排 |
| 数据存储 | PostgreSQL 16（会话、知识正文与修订、配额、LangGraph 检查点）、Milvus 2.6（知识向量） |
| 前端接入 | 一行 `<script>` 的匿名浮窗；已登录业务系统可用同源 token 浮窗 |
| Python | 3.12（`requires-python = ">=3.12,<3.13"`） |

## 功能特性

- **有据可依的回答**：仅使用本轮检索到的证据与已注册的业务工具生成正文，服务器负责引用编号、配图与链接，模型不输出原始 URL。
- **混合检索**：语义向量与 BM25 双路召回，RRF 融合后按需重排；相似度门槛、候选数与上下文条数均可配置。
- **知识版本化**：文档按 `document_id + revision` 管理，可停用、回切历史修订；Embedding 配置变化由 `fingerprint` 强制校验，避免新旧向量混用。
- **会话与历史**：会话级上下文、空闲切段、跨轮追问改写、历史分页与重试幂等（`request_id`）。
- **配额与限流**：企业级 60 秒滚动窗口限流 + 全局每日 RAG 额度（北京时间零点重置，落库持久化）。
- **匿名身份**：签名 Cookie 下发访客身份，无需业务系统登录；凭证只存内存，不暴露模型 Key。
- **流式输出**：SSE 分阶段推送（`status` / `delta` / `metadata` / `complete` / `error`），支持断连取消。
- **可观测性**：结构化 JSONL 运行日志与完整排障日志、按会话归档的内容快照、Prometheus 文本格式指标。
- **确定性工作流**：LangGraph 固定节点编排，无自主循环、无写入型工具，检查点持久化到 PostgreSQL。

## 架构概览

```text
浏览器（业务页面）
   │  ① 加载 /smart-bot/iframe-anonymous.js（或 iframe.js）
   ▼
客服浮窗 iframe ── ② POST /widget/anonymous-auth   取得匿名 Bearer
   │            ── ③ POST /v1/sessions             创建会话
   │            ── ④ POST /v1/sessions/{sid}/messages/stream（SSE）
   ▼
FastAPI（app/server.py）
   │  鉴权 / 体积与来源校验 / 限流 / 每日额度
   ▼
LangGraph 工作流（app/workflow.py）
   route → retrieve → generate → validate
   │           │            │
   │           │            └─ 外部 LLM（OpenAI 兼容接口）
   │           └─ Embedding → Milvus 向量召回 + BM25 → RRF → Rerank
   ▼
PostgreSQL（会话 / 知识正文 / 检查点） + var/logs（JSONL 日志）
```

## 环境要求

| 依赖 | 版本 / 要求 |
|---|---|
| Python | 3.12.x（`pyproject.toml` 锁定 `<3.13`） |
| 依赖管理 | [uv](https://docs.astral.sh/uv/)；依赖清单 `pyproject.toml` + `uv.lock` |
| PostgreSQL | 16（生产）。仅本地试跑可省略，回退到 SQLite |
| Milvus | 2.6（生产，需 Token 与已分配的业务数据库）。仅本地试跑可用 `VECTOR_BACKEND=sqlite` |
| 模型接口 | 三个 OpenAI 兼容接口：LLM（`/v1/chat/completions`）、Embedding（`/v1/embeddings`）、Rerank（`/v1/rerank`） |
| 部署（可选） | Docker 23+；Kubernetes 集群 + Ingress（需关闭 SSE 缓冲） |

## 快速开始

### 1. 安装依赖

```bash
git clone <仓库地址> && cd titu-assistant
uv sync                  # 创建 .venv 并安装生产 + dev 依赖
```

不修改锁文件时请使用 `uv sync --locked`；更新依赖后需提交同步过的 `uv.lock`。

### 2. 准备配置

配置模板是 [`docs/app.env.example`](docs/app.env.example)，逐项带注释说明取值来源。本地开发复制为仓库根目录的 `.env`（已被 `.gitignore` 忽略）：

```bash
cp docs/app.env.example .env
python3 -c 'import secrets; print(secrets.token_urlsafe(48))'   # 填入 AUTH_SECRET
```

最小可运行配置（仅本地、无外部依赖）：

```dotenv
AUTH_SECRET=<至少 32 字节的随机串>
ANSWER_MODE=extractive          # 不调用 LLM，使用抽取式回答
RETRIEVAL_BACKEND=lexical       # 读取 data/knowledge.jsonl，不连接 Milvus
```

> `.env` 只由 `manage.py` 读取（内部按行解析，不执行 shell）。直接运行 `python -m app.server` 时，配置需通过进程环境变量注入。

### 3. 启动

```bash
# 推荐：由 manage.py 加载 .env 后启动
python database/milvus/manage.py serve --host 127.0.0.1 --port 8000

# 等价：环境变量已就绪时直接启动 ASGI 应用
python -m app.server
```

本地默认监听 `127.0.0.1:8000`；应用镜像内为 `0.0.0.0:8000`；K8s 清单使用 `0.0.0.0:8201`。

### 4. 验证

```bash
curl -s http://127.0.0.1:8000/health          # {"status":"ok"}
curl -s http://127.0.0.1:8000/ready           # {"status":"ready"}
```

`/ready` 会校验数据库连通性、知识条数与 Milvus 集合是否存在，比 `/health` 更接近「真的能用」。

业务接口需要凭证。本地签发一个调试令牌，再调用问答接口：

```bash
TOKEN=$(python database/milvus/manage.py token --tenant demo --user alice)
SID=$(curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
      -d '{}' http://127.0.0.1:8000/v1/sessions | python3 -c 'import sys,json;print(json.load(sys.stdin)["session_id"])')

curl -s -X POST -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' \
  -d '{"message":"如何注册企业账号","request_id":"req-demo-0001"}' \
  http://127.0.0.1:8000/v1/sessions/$SID/messages
```

浏览器演示页：`http://127.0.0.1:8000/widget/anonymous-demo`（页面可直出，但要完成匿名提问需 `ANONYMOUS_WIDGET_ENABLED=true`）。

### 可选：用 Docker Compose 启动单个应用容器

```bash
export ASSISTANT_UID=$(id -u) ASSISTANT_GID=$(id -g)
docker compose --project-directory . -f deploy/compose/compose.dev.yaml up -d --wait
```

compose 只启动应用容器，挂载当前仓库并读取根目录 `.env`；数据库与模型服务仍需由外部提供。

## 目录结构

```text
titu-assistant/
├── app/                        # 应用代码（FastAPI + 业务逻辑）
│   ├── server.py               # 路由、中间件、SSE、/metrics、进程入口
│   ├── core.py                 # Settings、Service、令牌签发/校验、限流与每日额度
│   ├── workflow.py             # LangGraph 工作流：route → retrieve → generate → validate
│   ├── retrieval.py            # 混合检索：向量 + BM25 + RRF
│   ├── rag.py                  # RAGSettings、文档库、入库与语义检索
│   ├── vectors.py              # Milvus 适配（按 fingerprint 命名集合）
│   ├── ingestion.py            # docx / pdf / md / txt 解析与切片
│   ├── pdf_media.py            # PDF 图片与二维码提取、登记
│   ├── evidence_selection.py   # 证据选择（LLM 选择 + 覆盖率兜底）
│   ├── grounding.py            # 引用编号回填与校验
│   ├── conversation.py         # 意图识别、固定回复、图片目录
│   ├── assistance.py           # 陪办（分阶段指导）
│   ├── observability.py        # 结构化 JSONL 日志与事件
│   ├── storage.py              # PostgreSQL / SQLite 连接、会话行锁
│   ├── schema.py               # 数据库结构版本校验
│   └── static/                 # 浮窗 JS/CSS/HTML、演示页与知识配图
├── data/
│   ├── knowledge.jsonl         # 词法检索知识源（无数据库时的回退路径）
│   ├── media.json              # 知识配图登记（文档中「配图」引用的 ID）
│   └── business_flows.json     # 快捷问题与业务流程绑定
├── database/
│   ├── postgres/               # Flyway 配置、版本迁移、回调、模板与检查 SQL
│   └── milvus/                 # manage.py、02_milvus.py、knowledge-init.sh
├── deploy/
│   ├── compose/                # 本地应用容器编排
│   ├── docker/app|db-migrate/  # 两个镜像的 Dockerfile 与 build.sh
│   └── k8s/dev|uat|prod/       # 原生 YAML 清单与发布说明
├── docs/                       # 部署说明、SQL 规范、技术方案、配置模板
├── knowledge_sources/          # 正式知识文档（随镜像交付）
├── scripts/                    # 配置生成、模型探针、日志查询、SQL 门禁
├── tests/                      # pytest 与 Node 前端脚本测试
├── var/                        # 运行时产物：日志、SQLite、PDF 图片（不入库）
├── pyproject.toml
├── uv.lock
└── README.md
```

## 核心功能与使用方法

### 前端嵌入

**匿名浮窗**（访客无需登录，推荐对外站点使用）：

```html
<script src="https://客服实际域名/smart-bot/iframe-anonymous.js"></script>
```

**登录态浮窗**（业务系统已登录，需提供同源 token 接口）：

```html
<script src="https://客服实际域名/smart-bot/iframe.js"
        data-auth-url="/api/assistant/token"></script>
```

`data-auth-url` 必须与业务页面同源，返回 `{"token": "<客服凭证>"}`；凭证由业务后端调用 `issue_token`（`app/core.py`）签发，密钥为 `AUTH_SECRET`，**不得下发到浏览器端自行签发**。

两种脚本都自动创建按钮与 iframe，隐藏模型接口细节；`FRAME_ORIGINS` 需包含嵌入页面的精确来源（协议 + 主机 + 端口，不支持通配符与路径）。

### HTTP API

所有路径同时支持带 `/smart-bot` 前缀访问（平台 Ingress 原样转发该前缀，公网链接均带前缀）；无 `/docs`、`/redoc`，OpenAPI 需携带凭证访问。

| 方法与路径 | 鉴权 | 说明 |
|---|---|---|
| `GET/HEAD /health` | 否 | 存活探针 |
| `GET /ready` | 否 | 就绪检查：数据库、知识行数、Milvus 集合 |
| `GET /widget/config` | 否 | 前端可读的 `frame_origins` 与匿名开关 |
| `POST /widget/anonymous-auth` | 否 | 签发匿名 Bearer，并写入签名 Cookie |
| `GET /v1/bootstrap` | 是 | 欢迎语、快捷问题、配额策略、能力清单 |
| `GET /v1/sessions` | 是 | 当前用户的会话列表（最近 100 条） |
| `POST /v1/sessions` | 是 | 创建会话，可带 `context`（`page_path` / `page_title` / `product`） |
| `GET /v1/sessions/{sid}/messages` | 是 | 历史消息，支持 `before` 游标分页（每页 100 条） |
| `POST /v1/sessions/{sid}/messages` | 是 | 单轮问答，返回 `answer` / `citations` / `images` / `suggestions` |
| `POST /v1/sessions/{sid}/messages/stream` | 是 | 同上，SSE 流式返回 |
| `DELETE /v1/sessions/{sid}` | 是 | 删除会话及其检查点 |
| `GET /v1/sources/{key}` | 是 | 查询引用来源正文 |
| `GET /metrics` | 运维头 | Prometheus 文本格式指标，需 `x-operations-token` |
| `GET /openapi.json` | 是 | OpenAPI 描述 |

鉴权使用 HMAC-SHA256 签名令牌：`base64url(claims).base64url(signature)`，`iss=smarttitu-console`、`aud=smarttitu-assistant`，有效期 1–86400 秒。匿名租户固定为 `__smarttitu_anonymous__`。

请求体上限 16 KB、仅接受 `application/json`、`extra=forbid`；`message` 限 1–2000 字，`request_id` 限 8–80 位字母数字下划线或连字符，相同 `request_id` 重试会命中缓存而非重复计费。

所有 `POST` 请求都必须带唯一的 `Content-Length` 与 JSON 请求体，最小可用请求体为 `{}`：缺少 `Content-Length` 返回 `400 invalid_length`，长度为 0 返回 `413 body_too_large`（匿名鉴权接口同样如此）。

### 命令行（`manage.py`）

生产镜像把 `database/milvus/manage.py` 复制为 `/srv/assistant/manage.py` 并通过 `PYTHONPATH=/srv/assistant` 运行。本地执行 `python database/milvus/manage.py <command>` 时，`uv sync` 已把本项目以可编辑方式装入 `.venv`，可直接运行；若 venv 是 `--no-install-project` 创建的，请加 `PYTHONPATH=.` 前缀。

| 命令 | 用途 |
|---|---|
| `serve [--host] [--port]` | 加载 `.env` 后启动服务 |
| `token --tenant T --user U [--ttl S]` | 本地签发调试令牌 |
| `ingest [--rebuild]` | 增量入库；Embedding 配置变化时加 `--rebuild` |
| `documents` / `revisions <doc_id>` | 查看文档与修订记录 |
| `deactivate <doc_id>` / `activate <doc_id> --revision R` | 停用文档 / 回切历史修订 |
| `retrieve --query Q [--no-rerank]` | 检索诊断，不调用聊天模型 |
| `check` | 校验配置与知识，不访问外网 |
| `doctor [--models]` | 检查数据库、Milvus、LangGraph 与三个模型接口 |
| `vector-init [--dimension 1024] [--check-only]` | 按当前指纹创建或严格核对 Milvus 集合 |
| `sync-vectors` | 把已有向量同步进 Milvus，不调用 Embedding |
| `prune-sessions` / `prune-checkpoints --days N` | 按保留期清理会话与检查点 |
| `backup [--output]` | 一致性备份 SQLite（PostgreSQL 模式请用平台备份） |
| `migrate-storage` / `export-storage` | SQLite 与 PostgreSQL 之间的历史数据迁移 |
| `evaluate` / `prepare-evaluation` | 私有评测集召回评估与问法生成 |

### 知识入库流程

1. 把正式文档放入 `knowledge_sources/`（支持 `.docx`、`.pdf`、`.md`、`.txt`，单文件 ≤ 25 MB）。
2. 需要配图时，图片放入 `app/static/media/`，并在 `data/media.json` 登记 ID；文档中通过 `配图：<id>` 引用，未登记的 ID 会让入库失败。
3. 执行 `manage.py ingest`：解析 → 切片（1000 字 / 100 字重叠）→ Embedding → 写入 PostgreSQL 与 Milvus。
4. 同一 fingerprint 下重复执行只处理变化文档；匹配的切片复用 `rag_embedding_cache`，不重复计费。

> Embedding 地址、模型、版本或切片参数变化时，`ingest` 会在写入前报错，需显式执行 `ingest --rebuild`。
> 从 `knowledge_sources/` 删除文件**不会**停用已入库知识，必须显式 `deactivate`。

## 配置项说明

配置分两层：应用配置（`app/core.py: Settings`）与检索配置（`app/rag.py: RAGSettings`），启动时统一校验（`Settings.validate()`、`RAGSettings.validate()`），非法值直接拒绝启动。完整注释见 [`docs/app.env.example`](docs/app.env.example)；生产实际值在 `deploy/k8s/dev/10-configmap.yml` 与 `20-secret.yml`。

### 运行与认证

| 变量 | 默认值 | 说明 |
|---|---|---|
| `HOST` / `PORT` | `127.0.0.1` / `8000` | 监听地址与端口 |
| `APP_WORKERS` | `1` | 进程数，取值 1–4；大于 1 时必须配置 `DATABASE_URL` |
| `AUTH_SECRET` | 无 | **必填**，≥ 32 字节；令牌与日志身份映射的签名密钥 |
| `OPERATIONS_TOKEN` | 空 | `/metrics` 的访问密钥，≥ 32 字节，未配置则该接口不可用 |
| `DEPLOYMENT_ID` | 空 | 数据库归属标识，App 与迁移 Job 必须一致，首次部署后不变 |

### 数据库与向量

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DATABASE_URL` | 空 | PostgreSQL 连接串；为空时回退 SQLite（`DATABASE_PATH`） |
| `VECTOR_BACKEND` | `sqlite` | `milvus`（生产）/ `sqlite`（本地） |
| `MILVUS_URI` | `http://127.0.0.1:19530` | Milvus Endpoint，含协议与端口 |
| `MILVUS_TOKEN` | 空 | `VECTOR_BACKEND=milvus` 时必填 |
| `MILVUS_DATABASE` | `default` | Milvus 业务数据库名 |
| `MILVUS_COLLECTION` | `smarttitu_knowledge` | 集合前缀，实际集合名为 `<前缀>_<fingerprint 前 16 位>` |
| `MILVUS_INDEX_TYPE` | `HNSW` | `HNSW` 或 `AUTOINDEX`（按平台能力选择） |

### 模型接口

| 变量 | 默认值 | 说明 |
|---|---|---|
| `ANSWER_MODE` | `extractive` | `llm` 调用外部 LLM；`extractive` 为离线抽取式回答 |
| `MODEL_BASE_URL` | `https://api.smarttitu.cn/v1` | OpenAI 兼容地址，不带 `/chat/completions` |
| `MODEL_API_KEY` / `MODEL_NAME` | 空 | `ANSWER_MODE=llm` 时必填 |
| `MODEL_MAX_TOKENS` | `2048` | 单次调用最大输出 Token |
| `MODEL_DISABLE_THINKING` | `true` | 是否请求关闭思考 |
| `MODEL_THINKING_FORMAT` | `vllm` | `vllm` / `enable_thinking` / `none`，按供应商选择 |
| `EMBEDDING_PROVIDER` | `ollama` | `openai`（生产）/ `ollama`（本地） |
| `EMBEDDING_URL` | `http://127.0.0.1:11434/api/embed` | 完整接口地址 |
| `EMBEDDING_MODEL` / `EMBEDDING_REVISION` | `bge-m3:latest` / `v1` | 模型 ID 与本地维护的版本标记 |
| `EMBEDDING_TIMEOUT` | `30` | 单次调用超时（1–120 秒） |
| `RERANK_ENABLED` | `true` | 关闭时跳过重排，直接使用 RRF 分数 |
| `RERANK_URL` / `RERANK_API_KEY` / `RERANK_MODEL` | 空 | 启用重排时 `RERANK_URL` 必填 |
| `RERANK_TIMEOUT` | `30` | 单次重排超时（1–120 秒） |
| `MODEL_HTTP_ORIGINS` | 空 | 允许的明文 HTTP 模型来源，逗号分隔；全 HTTPS 时留空 |

### 检索

| 变量 | 默认值 | 说明 |
|---|---|---|
| `RETRIEVAL_BACKEND` | `semantic` | `semantic` 走 RAG 链路；`lexical` 读取 `data/knowledge.jsonl` |
| `SEMANTIC_MIN_SIMILARITY` | `0.60` | 语义召回门槛（0–1） |
| `RERANK_MIN_SCORE` | `0.6` | 重排分数门槛，随模型分布调整 |
| `RAG_TOP_K` / `RAG_CONTEXT_K` | `12` / `3` | 候选数与最终证据条数，要求 `RAG_CONTEXT_K ≤ RAG_TOP_K ≤ 100` |
| `RETRIEVAL_TIMEOUT_SECONDS` | `15` | 在线检索总预算（Embedding + 召回 + 重排共享） |
| `RETRIEVAL_MIN_SIMILARITY` | `0.14` | 仅 `lexical` 模式使用的相似度门槛 |
| `KNOWLEDGE_PATH` | `data/knowledge.jsonl` | `lexical` 模式的知识文件 |

### 会话、限流与匿名接入

| 变量 | 默认值 | 说明 |
|---|---|---|
| `SESSION_RETENTION_DAYS` | `7` | 在线历史保留天数（1–365） |
| `SESSION_CONTEXT_ROUNDS` | `20` | 参与上下文的历史轮数（1–1000） |
| `SESSION_IDLE_SECONDS` | `1800` | 空闲超过该值即视为新上下文段 |
| `SESSION_CLEANUP_INTERVAL_SECONDS` | `300` | 过期会话清理周期 |
| `TENANT_MESSAGES_PER_MINUTE` | `20` | 企业级 60 秒滚动窗口额度（1–10000） |
| `GLOBAL_RAG_QUESTIONS_PER_DAY` | `1000` | 全库共享的每日 RAG 上限，北京时间零点重置 |
| `ANONYMOUS_WIDGET_ENABLED` | `false` | 是否开放匿名入口 |
| `ANONYMOUS_COOKIE_NAME` | `smarttitu_anonymous_visitor` | 匿名 Cookie 名，需匹配 `[A-Za-z][A-Za-z0-9_]{0,79}` |
| `ANONYMOUS_COOKIE_SECURE` | `false` | HTTPS 部署须设为 `true` |
| `FRAME_ORIGINS` / `CORS_ORIGINS` | 空 | 允许嵌入的页面来源 / 允许跨域调用 API 的来源；禁止通配符 |

### 日志与文件路径

| 变量 | 默认值 | 说明 |
|---|---|---|
| `LOG_DIR` | `var/logs` | 日志目录（容器内 `/srv/assistant/var/logs`） |
| `LOG_TIMEZONE` | `Asia/Shanghai` | 日志日期与时区 |
| `LOG_RETENTION_DAYS` | `30` | 普通日志保留天数 |
| `LOG_DEBUG_CONTENT` | `false` | 是否记录完整问答内容（生产模板为 `true`） |
| `LOG_DEBUG_RETENTION_DAYS` | `7` | 排障日志保留天数（1–30） |
| `LOG_TRACE_DETAIL` | `compact` | `compact` 精简 / `full` 详细 |
| `PDF_MEDIA_ENABLED` | `true` | 入库时是否提取 PDF 图片 |
| `PDF_MEDIA_DIR` | `var/pdf_media` | PDF 图片输出目录 |
| `MEDIA_PATH` | `data/media.json` | 配图登记文件 |
| `KNOWLEDGE_SOURCE_DIR` | `knowledge_sources` | 入库源目录 |
| `SUPPORT_QR_URL` | 空 | 人工客服二维码地址（HTTPS 或 `/media/...`） |
| `CUSTOMER_LINK_HOSTS` | 内置官网域名 | 答案中允许出现的链接域名白名单 |
| `DATABASE_PATH` / `RAG_INDEX_PATH` | `var/assistant.db` / `var/rag.sqlite3` | 未配置 PostgreSQL 时的回退路径 |

## 部署

### 镜像

两个镜像职责分离，**使用同一个 tag 配套构建**，构建上下文均为仓库根目录：

```bash
deploy/docker/db-migrate/build.sh -t v1.0.0-20261120 --push   # Flyway + SQL 资产
deploy/docker/app/build.sh       -t v1.0.0-20261120 --push    # 纯 Python 应用
```

- `assistant`：应用镜像，含依赖、`app/`、`data/`、`knowledge_sources/`、`manage.py`；不含 Java 与迁移脚本，同时被知识初始化 Job 复用。
- `db-migrate`：只含 Flyway 运行时、`flyway.conf` 与 `database/postgres/migrations/`。
- 内网构建可通过 `--python-image`、`--uv-image`、`--apt-mirror`、`--flyway-image` 换源。

### Kubernetes 发布顺序

清单位于 `deploy/k8s/dev/`（命名空间 `app-zone`，容器端口 `8201`），**顺序不能调换**：

```text
scale 0 停 App（释放 ReadWriteOnce 卷）
   → db-migrate Job 执行 flyway migrate
   → 知识初始化 Job（建集合 → ingest → doctor --models）
   → 删除 Job 并等 Pod 退出
   → apply Deployment → rollout status
   → Pod 内冒烟 /smart-bot/ready
```

Job 阶段失败时只把旧版本 `scale` 回 1，不要 `rollout undo`（会多退一个版本）；Deployment 阶段失败才使用 `rollout undo`。完整步骤、失败恢复矩阵与排查表见 [`deploy/k8s/dev/README.md`](deploy/k8s/dev/README.md)。

### 对外访问

`70-service.yml` 是 `ClusterIP 8201`，只做集群内入口；对外由 `75-ingress.yml` 走 443 提供，**不要使用 NodePort**（本集群 Cilium `devices: eth1`，nodePort 的 BPF 不覆盖对外网卡 eth0，外网访问会被 RST，详见 dev README）。

Ingress 规格：host `titu-assistant.k8s.ird`、`ingressClassName: nginx`、TLS 由 `cert-manager.io/cluster-issuer: internal-cluster-issuer` 自动签发（`titu-assistant-tls`）、关闭 `proxy-buffering` 并放大 `proxy-read/send-timeout` 以支持 SSE。

验证（DNS 未接入时用节点 IP + `Host` 头）：

```bash
curl -k -H 'Host: titu-assistant.k8s.ird' https://<节点IP>/smart-bot/ready
```

## 数据库与迁移

生产使用平台已开通的 PostgreSQL 16，`database/postgres/` 是 SQL 变更的唯一来源：

- 基线 `V1.0.0__baseline.sql` 已发布，**不可修改**；变更一律新增下一个版本。
- 版本记录表为 `assistant.flyway_schema_history`，回调负责迁移前后的归属校验与结构体检。
- 现有 17 张表：`assistant`（会话、配额、工作流）与 `knowledge`（知识库）两个 schema。
- 配置 `DATABASE_URL` 时，应用启动只做只读结构校验，不建表、不改表；建表与升级由 `db-migrate` 镜像/Job 完成。

新增或修改 SQL 的完整流程、命名规范与门禁见 [`database/postgres/README.md`](database/postgres/README.md) 与 [`docs/SQL规范与门禁.md`](docs/SQL规范与门禁.md)。改完先跑：

```bash
python3 scripts/ci/check_sql.py
```

## 日志与可观测性

运行时产物统一落在 `var/`（生产为 PVC `/srv/assistant/var`）：

| 路径 | 内容 | 保留 |
|---|---|---|
| `var/logs/app-YYYY-MM-DD-<pid>.jsonl` | 结构化运行日志（事件、耗时、结果码） | `LOG_RETENTION_DAYS` |
| `var/logs/debug-*.jsonl` | 完整问答与处理过程（含模型输入输出） | `LOG_DEBUG_RETENTION_DAYS` |
| `var/logs/conversations/年-月/tenant-*/user-*/session-*.jsonl` | 按会话归档的排障快照 | 同上 |
| `var/pdf_media/` | PDF 提取的图片与报告 | 长期保留 |
| `var/assistant.db`、`var/rag.sqlite3` | SQLite 回退数据与知识索引 | 随会话策略 |

日志用 `scripts/query_logs.py` 查询与汇总：

```bash
python scripts/query_logs.py var/logs --report <request_id>
```

`GET /metrics` 输出 `smarttitu_*` 前缀的计数器与耗时汇总，需请求头 `x-operations-token`；未配置 `OPERATIONS_TOKEN` 时该接口一律返回 401。

## 测试与代码质量

```bash
uv sync                                   # 含 dev 依赖（pytest、ruff、mypy）
.venv/bin/python -m pytest tests -q       # Python 测试
node tests/test_widget_ui.js              # 浮窗 UI 交互测试（可选，需 playwright）
python3 scripts/ci/check_sql.py           # SQL 命名/版本/文件头/镜像 COPY 一致性

uv pip install pre-commit sqlfluff        # 以下两项不在 dev 依赖中
pre-commit install && pre-commit run --all-files
```

测试默认不访问真实数据库与付费接口；模型探针单独提供：

```bash
python scripts/probe_models.py --expect-dim 1024
python scripts/probe_models.py --only embeddings
```

## 常见问题

**启动报 `AUTH_SECRET 必须至少 32 字节`**
密钥长度不足。用 `python3 -c 'import secrets; print(secrets.token_urlsafe(48))'` 生成，并保证同一部署的所有 Pod 使用同一个值（否则匿名身份与日志映射会漂移）。

**接口返回 401 `unauthorized`**
令牌由业务后端用 `issue_token` 签发，`iss`/`aud` 固定为 `smarttitu-console` / `smarttitu-assistant`，默认 1 小时过期。本地可用 `manage.py token --tenant demo --user alice` 对比排查。

**`/ready` 返回 503 `index_empty`**
知识尚未入库，先执行知识初始化 Job 或 `manage.py ingest`。

**`/ready` 返回 503 `index_unavailable`**
当前 `fingerprint` 对应的 Milvus 集合不存在。依次核对 `EMBEDDING_*`（模型、地址、版本）与 `MILVUS_COLLECTION` 是否与 App 一致，然后重跑知识 Job。

**改动 Embedding 配置后报 `当前Embedding配置与索引不一致,请先重建`**
向量维度或模型已变化，需 `manage.py ingest --rebuild` 全量重建；不要混用旧向量。

**回退镜像后检索报同一错误**
曾用新指纹执行过 `--rebuild`，库内 `rag_state.fingerprint` 已指向新配置。必须用**旧镜像**重跑一次知识初始化 Job 让指纹回到旧值；`/ready` 此时可能仍返回 200（旧集合还在），问题会推迟到第一次提问才暴露。

**更新了知识文档但线上搜不到**
知识随镜像交付。放入 `knowledge_sources/` → 构建新 tag 镜像 → 跑知识 Job → 再更新 Deployment；仅上传文件到服务器不会生效。

**删除源文件后内容仍被检索到**
删除文件不改变已入库状态，需 `manage.py deactivate <document_id>` 显式停用。

**SSE 看起来卡住后一次性输出**
Ingress 开了响应缓冲。需关闭 `proxy-buffering`（规格见 `deploy/k8s/dev/README.md` 的「对外访问」），并确认读超时足够覆盖一次完整回答。

**前端浮窗被浏览器拒绝嵌入**
`FRAME_ORIGINS` 必须是精确来源（协议 + 主机 + 端口），不支持通配符、路径与尾斜杠；修改后需重建 Pod 才生效。

**匿名入口返回 404 / 401**
`ANONYMOUS_WIDGET_ENABLED` 未设为 `true`，或 HTTPS 环境下 `ANONYMOUS_COOKIE_SECURE` 与协议不匹配。

**数据库报「属于其他部署或 Milvus 配置已变更」**
`DEPLOYMENT_ID`、`MILVUS_URI`、`MILVUS_DATABASE`、`MILVUS_COLLECTION` 与库内归属记录不一致。**不要**删除归属记录绕过校验，应恢复原配置或改用独立新库。

**`docker build` 拉不到基础镜像**
国内网络无法直连 Docker Hub，按提示换源，例如 `--python-image docker.m.daocloud.io/library/python:3.12-slim-bookworm`、`--flyway-image docker.m.daocloud.io/flyway/flyway:11.20.3-alpine`。

**`pytest` 收集阶段报 `No module named 'kubernetes'` 或缺少 `.env.example`**
`tests/test_production_deployment.py`、`tests/test_external_deployment.py` 仍引用已随目录重构删除的部署脚本与配置模板，属于历史遗留，可用 `--ignore` 跳过；其余用例与本次发布代码保持一致。

## 已知限制

- 单副本 + `strategy: Recreate`：`var/` 使用 ReadWriteOnce 卷，发布存在维护窗口，暂不支持零停机（方案见 [`docs/不停机升级与自动回退方案.md`](docs/不停机升级与自动回退方案.md)）。
- 数据库迁移无 undo：SQL 必须保持 N-1 兼容，破坏性变更拆两次发布。
- 业务工具默认全部禁用：`ToolRegistry` 只允许注册只读工具，写入型工具需先接入人工确认与幂等适配器。
- 文档下载接口未开放（`/v1/documents/.../download` 返回 404），正文通过 `/v1/sources/{key}` 提供。
- `manage.py init` 与 `scripts/configure_external.py` 仍从仓库根读取 `.env.example`，该文件已随目录重构移除；请以 `docs/app.env.example` 为模板手工创建 `.env`。

## 贡献指南

1. **分支与提交**：从 `main` 切分支，提交信息用 `feat:` / `fix:` / `docs:` / `refactor:` 前缀，一次提交只做一件事。
2. **代码风格**：`ruff check` 与 `mypy`（dev 依赖已包含），保持现有模块边界，不把业务逻辑塞进 `server.py`。
3. **SQL 变更**：只新增版本文件，不修改已执行的 `V__`；先跑 `scripts/ci/check_sql.py`，再在空库执行一次 `flyway migrate` 验证完整链路。
4. **配置变更**：新增环境变量必须同时更新 `docs/app.env.example`、`deploy/k8s/dev/10-configmap.yml`（或 Secret）与本文档配置表，并在 `Settings`/`RAGSettings` 中给出默认值与校验。
5. **测试**：涉及协议、配额、检索或前端脚本的改动需补测试；提交前本地跑通 `pytest`、`check_sql.py` 与 `pre-commit`。
6. **禁止入库**：`.env`、真实密钥、日志、数据库导出、备份文件、客户会话导出。正式知识文档与配图按现有方式纳入版本管理，新增前先评审。

## 相关文档

| 文档 | 内容 |
|---|---|
| [`docs/app.env.example`](docs/app.env.example) | 唯一带注释的配置模板 |
| [`deploy/k8s/dev/README.md`](deploy/k8s/dev/README.md) | K8s 发布顺序、幂等、失败恢复与排查 |
| [`database/postgres/README.md`](database/postgres/README.md) | SQL 资产结构、版本管理与变更流程 |
| [`docs/SQL规范与门禁.md`](docs/SQL规范与门禁.md) | SQL 命名、格式与 CI 门禁 |
| [`docs/不停机升级与自动回退方案.md`](docs/不停机升级与自动回退方案.md) | 探针配置、阶段划分与验收标准 |
| [`docs/知识向量化模块技术方案.md`](docs/知识向量化模块技术方案.md) | 入库、切分与向量化设计 |
| [`docs/Milvus初始化与知识向量化Job封装方案.md`](docs/Milvus初始化与知识向量化Job封装方案.md) | 集合初始化与知识 Job 封装 |
| [`deploy/docker/app/README.md`](deploy/docker/app/README.md) / [`deploy/docker/db-migrate/README.md`](deploy/docker/db-migrate/README.md) | 两个镜像的构建与内网换源 |
| [`docs/部署说明.md`](docs/部署说明.md) | 部署背景与历史流程（SQL 执行以 K8s README 为准） |
