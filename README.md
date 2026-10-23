# SmartTITU 智能客服 一期 MVP

提供可部署的 Python 后端与自带窗口的悬浮客服脚本。正式问答使用 **文档解析 → BGE-M3 语义向量召回 → Qwen3 Reranker 重排 → Qwen3-32B 依据资料回答**。无需 Dify 或单独开发聊天窗口。历史会话与知识版本存入 SQLite，适合单实例、小规模知识库。

首份入库资料为 `knowledge_sources/SmartTITU客户问答.docx`：71 个外部客户问答，按总目录编号2、3、4、5、9、10、11、13、14、15整理；前三问为官网、在线文件、模型清单，第四问为注册认证流程，其余同源连续。保留原图、图片URL、原文PDF链接和出处。Embedding 接收解析后的文本片段，不直接接收 Word 二进制，也不会训练或修改模型权重。旧 `data/knowledge.jsonl` 仅用于兼容模式和离线原型，**默认语义问答不读取它**。

## 服务器上最快启动

以下操作在已验证 Embedding 和 Reranker 的 `cnglus065` 主机、`~/ai_customer` 目录执行。复用现有模型服务，不重新下载模型，不额外启动 GPU 模型副本。

```bash
cd ~/ai_customer
python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements.txt
# 仅首次、没有.env时执行；已有配置不要覆盖
python manage.py init
```

`.env` 至少确认：

```dotenv
AUTH_SECRET=初始化时自动生成的原值
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
RERANK_API_KEY=真实重排密钥
SUPPORT_QR_URL=
HOST=127.0.0.1
PORT=8000
```

上面的中文说明不能作为实际密钥。保留原 `AUTH_SECRET`；首次 `init` 会自动生成。现有 Reranker 密钥不知道时，在有 Docker 访问权限的模型主机执行：

```bash
python scripts/configure_existing_services.py
python manage.py check
python manage.py ingest
python manage.py serve
```

辅助脚本从 `qwen3-reranker-4b` 的本机 Docker 配置读取密钥和当前容器 IP，仅写入本机 `.env`，不打印密钥，不重启模型。若该容器没有配置可读取的密钥，请找服务管理员；不能用聊天模型的 `not-empty` 代替。容器 IP 改变后重新运行辅助脚本并确认配置；Embedding 端点变更会要求重建索引。

`check` 不调用模型，仅校验配置和索引数量。第一次入库前知识数为 0；`ingest` 成功后本份 Word 应产生 71 个片段。首次入库需要实际调用 Embedding。`serve` 自动读取 `.env`，系统环境变量优先，修改配置后需重启进程。默认数据库为 `var/assistant.db` 和 `var/rag.sqlite3`。

另开终端，在项目内使用同一虚拟环境：

```bash
python manage.py token --tenant demo-company --user demo-user
```

打开 `http://127.0.0.1:8000/widget/demo`，填入输出的短期凭证。凭证默认一小时有效，是登录身份凭证，不是模型 API Key。远程访问可使用获准的 SSH 隧道或 HTTPS 反向代理，默认端口只监听回环地址。

## 文档日常维护

日常只维护 `knowledge_sources/`；新增 Word/PDF/Markdown/TXT 后执行：

```bash
python manage.py ingest
python manage.py documents
```

修改文档时覆盖原路径。文件未变化会跳过推理；正文片段未变化会复用已有向量。新版本准备完整后一次发布，新问题立即使用新索引，无需重启客服。解析或模型请求失败时保留之前的可用版本。首份 Word 可继续修改，也可新增独立主题文件。

```bash
# 把实际文档ID替换下列占位符，documents可查
python manage.py revisions DOC-实际ID
python manage.py deactivate DOC-实际ID
python manage.py activate DOC-实际ID --revision 实际完整修订哈希
```

停用后不会参与新回答，批量入库不会自动恢复。误删文件不会自动删除知识；需要主动停用。恢复旧修订不改磁盘文件，下次入库会以磁盘文件内容为准。改名视为新文档，需停用旧条目。历史引用保留对应版本的文档快照，下载需要登录凭证。

更换 Embedding 模型、同名模型权重、版本或切分方式后，全量重建：

```bash
# 同名模型权重变化时，先修改.env中的EMBEDDING_REVISION
python manage.py ingest --rebuild
```

详细格式、更新规则、备份与限制见 [知识文档管理](docs/知识文档管理.md)。这些是服务端管理命令；本期没有公开上传入口或管理后台。

## 接入大模型与检索参数

`.env.example` 包含完整配置。聊天模型兼容非流式 Chat Completions，`MODEL_BASE_URL` 包含 `/v1`，不含 `/chat/completions`。本次使用用户已验证的 Qwen 接口。模型输出经过 JSON 与引用校验，依据不足或异常会引导人工。客户窗口不展示“未调用大模型”等内部诊断。

- Embedding：默认 Ollama `/api/embed`；也支持 `EMBEDDING_PROVIDER=openai` 与兼容的 `/v1/embeddings` 完整地址。模型名和向量维度必须与索引一致。
- Reranker：兼容本次已验证的 `/v1/rerank`，返回 `results[index,relevance_score]`。可显式设置 `RERANK_ENABLED=false` 只用向量召回。
- 内网 HTTP 必须在 `MODEL_HTTP_ORIGINS` 中列出准确来源，不含路径；HTTPS 可直接配置。密钥只在可信后端保存。
- `SEMANTIC_MIN_SIMILARITY=0.45` 是待真实问题校准的初始余弦门槛，不代表 45% 正确率。`RAG_TOP_K=12`、`RAG_CONTEXT_K=3` 控制候选和最终证据数量。
- `RERANK_MIN_SCORE=0` 默认只重排，不把重排分数当置信度。你之前测试中无关资料也有约 0.81 的分数，不能直接设置 0.8 为可信命中线。要同时检查实际召回和最终模型的依据判断。

问候、身份、致谢等先做意图分流，无需查知识；业务咨询用语义检索。未过门槛、模型认为资料不足、检索异常或用户主动转人工，都显示人工联系卡片。未提供企业微信二维码时保持 `SUPPORT_QR_URL` 为空，只展示电话和邮箱。

`ANSWER_MODE=extractive` 可作为运维对照，仍使用配置的语义召回，但直接返回资料正文。仅在明确设置 `RETRIEVAL_BACKEND=lexical` 时使用旧 JSONL 与词法检索；语义服务异常不会悄悄降级为词法检索。

## Docker 部署

当前这台 Linux 模型主机可直接把整个 `~/ai_customer` 挂载到容器 `/ai_customer`，保留原有模型、会话和知识文件。使用宿主机网络，无需改变Ollama的回环监听：

```bash
cd ~/ai_customer
python3 scripts/configure_existing_services.py
# 确认.env中ANSWER_MODE=llm；停止原来占用8000端口的Python客服后执行
sh scripts/docker-host.sh up --build -d
sh scripts/docker-host.sh exec assistant python manage.py ingest
sh scripts/docker-host.sh exec assistant python manage.py check
```

依赖在镜像构建时自动安装；宿主机不用pip安装。当前方案通过 `compose.host.yaml` 整目录挂载，不创建新的数据卷。详细日志、凭证、更新和备份命令见 [容器部署](docs/容器部署.md)。以下桥接网络方式为另一种部署选择，选定一种后保持使用同一套配置。

先准备 `.env`。普通 `compose.yaml` 需要填容器可访问的模型地址，容器中的 `127.0.0.1` 是容器自己。在用户当前模型主机上，可使用复用模型网络的叠加配置：

```bash
docker compose -f compose.yaml -f compose.rag-existing.yaml build
docker compose -f compose.yaml -f compose.rag-existing.yaml run --rm assistant python manage.py check
docker compose -f compose.yaml -f compose.rag-existing.yaml run --rm assistant python manage.py ingest
docker compose -f compose.yaml -f compose.rag-existing.yaml up -d
```

叠加配置使用 `host.docker.internal:11434` 访问现有 Ollama，用同一 `model-serving_model-net` 内的 `qwen3-reranker-4b:8001` 访问重排。Ollama 必须监听容器可访问的宿主机地址；若只监听宿主机回环，应先由运维配置可达地址并限定网络权限，或直接采用上面的原生 Python 方式。不要为了本应用重启其他人使用的模型。网络名不同可设置 `MODEL_NETWORK`。

后续命令保持相同的两个 `-f` 参数，才能使用同一服务配置。日常更新文档可以执行 `exec assistant python manage.py ingest`；启动前用 `run --rm`。知识目录只读挂载，两个数据库存入同一持久化卷。不要 `down -v`。更换 Compose 项目名会改变默认卷名。

提供 [Nginx 模板](deploy/nginx.conf.example)，替换域名和证书后由运维加载。公网使用 HTTPS；联调页应限制访问。容器、GPU 服务和目标主机的真实问答还需要在部署环境验收，本机没有 Docker，未实测容器构建。

## 悬浮窗口与历史记录

业务页面公共布局只需加载：

```html
<script src="https://assistant.example.com/iframe.js"
        data-auth-url="/api/assistant/token" defer></script>
```

脚本自己创建悬浮按钮和 iframe 聊天窗。父页面真实来源加入 `FRAME_ORIGINS`。`/api/assistant/token` 由已有业务后端校验登录身份后签发短期凭证，禁止接受浏览器自报企业身份直接签发。凭证不是 JWT，Python 可复用 `app.core.issue_token`。退出或切换账号调用 `window.SmartTITUEmbed.reset()`。详见 [悬浮弹窗接入](docs/悬浮弹窗接入.md)。

会话按企业和用户隔离保存；支持历史、恢复、分页和删除。模型上下文最多最近 12 条消息；闲置超过 30 分钟不再带入旧上下文，历史仍保留。当前知识库是所有已认证客户共享的公开客服资料，**不能放内部密钥或企业专有文档**；企业私有知识的权限分区尚未实现。

独立 `prototype/SmartTITU_功能原型.html` 可双击预览窗口交互，使用旧知识快照和本地词法检索，无真实模型、持久化或新 Word 语义检索。真实效果请使用 `/widget/demo`。

## 备份 验证与交付范围

```bash
python manage.py backup
python -m unittest discover -s tests -v
```

备份同时导出会话库和知识库，后者含向量、版本及原文快照。源目录、`.env` 和部署配置也需单独备份；模型文件在 `models/`，不会打包或提交 Git。恢复和迁移见 [部署运维说明](docs/部署运维说明.md)。

本次自动测试覆盖文档解析、增量更新、失败保留旧版本、停用和恢复、语义客户端协议、认证下载、会话隔离及原有模型约束。模拟向量能验证调用链与生命周期，不能代替目标主机的真实语义效果验收。

当前按单实例 SQLite + 小知识库直接计算余弦相似度实现，无需另起向量数据库。规模扩大后可替换向量存储。暂未交付多实例高可用、容量承诺、自动历史清理、在线真人接管、业务工具查询、图片上传/OCR或管理后台。图片回复支持登记过的资料图片；Word章节可通过“配图：图片ID”固定关联流程图，回答实际引用该章节时自动附图，并可打开原图。

代码模块：`app/ingestion.py` 负责清洗切分，`app/rag.py` 负责模型客户端、版本与向量索引，`app/core.py` 负责问答和会话，`app/server.py` 提供接口，`app/static/` 提供正式窗口。

更多说明：[API](docs/API对接说明.md)、[OpenAPI](docs/openapi.json)、[验收范围](docs/MVP验收清单.md)、[测试记录](docs/测试结果.md)、[图片与人工联系](docs/图片回复与人工联系.md)。

## 2026年10月23日外部资料整理

唯一入库文件仍为 `knowledge_sources/SmartTITU客户问答.docx`（v3，71问、71个默认片段、30张引用图片（已登记并发布））。在线PPT实际核对30页；第5及第14份资料第26页标为仅供内部讨论，未收入外部答案。图片文件和原PDF是附件资源，不要复制到knowledge_sources重复入库。历史JSONL仅作兼容；本次外部范围使用默认semantic模式。

已移除旧知识Markdown副本、206条草稿和旧19问生成脚本，后续直接维护Word。Word内原文和图片HTTPS链接指向本仓库main分支附件；下载需要能访问GitHub。部署后客服图片本身从本服务 `/media/` 返回。


## iframe 接入更新

独立聊天地址为 `/chatbot`，生产地址如 `https://assistant.example.com/chatbot`。配置 `.env` 的 `FRAME_ORIGINS=https://console.example.com` 后重启，再将链接交给前端嵌入。悬浮入口推荐加载 `/iframe.js`，自动创建 iframe；登录凭证由业务站同源接口提供，不能放到 iframe URL。完整代码、身份桥接和代理配置见 [iframe 接入说明](docs/悬浮弹窗接入.md)。原 `/widget/demo` 和 `/widget.js` 保留兼容。

本次采用用户删改后的71问版本，原编号保留；Word文件名或文内仍标v3/77问的字样不代表实际数量，入库数量以正文解析为准。标题解析兼容Word/WPS数字样式，避免保存后问答被混合切分。删除的条目在重新入库后停止参与后续检索；已保存的历史消息仍会保留。

本次首次更新请执行 `python manage.py ingest --rebuild`，重新建立兼容标题解析的索引；后续一般文档更新继续使用 `ingest`。


## 代码和知识资料分别更新

本次Git更新仅发布代码、示例配置和开发部署说明，不发布新整理的Word和原始PDF；当前71问引用的30张知识配图及data/media.json已另行发布。仓库历史中已有的旧示例Word与图片保持原样，不代表最新业务知识。部署时请从自己的编辑副本单独覆盖 `knowledge_sources/SmartTITU客户问答.docx`，不要重复放两份Word。当前71问引用的配图和图片登记表由git pull同步，不需要手动上传。后续新增图片需同时更新图片文件和登记表。原始PDF需要提供可点击下载时另行配置受控地址，GitHub新附件链接不会生效。

本次代码升级首次执行 `python manage.py ingest --rebuild`，然后重启；后续仅修改或删除Word文字条目可执行 `ingest`，无需每次重建。私有文档的71问和配图核对测试默认跳过；资料就绪后设置 `RUN_PRIVATE_KNOWLEDGE_TESTS=1` 可开启。通用解析、鉴权、语义检索、会话与iframe测试仍正常执行。


## 平台式演示页与内网访问

`/widget/demo`按原控制台原型提供SmartTITU平台场景：侧栏、产品卡片、快速开始及右下角客服，凭证在连接弹窗中填写。点击产品或指引可以带入对应问题；页面背景仅作平台场景展示，客服实际连接现有后端。

Linux宿主机网络部署支持读取.env的HOST。需要公司内网其他电脑访问时设 `HOST=0.0.0.0`，执行 `sh scripts/docker-host.sh up -d --force-recreate assistant` 使新环境配置生效，然后访问 `http://10.180.158.23:8000/widget/demo`（该IP为当前目标主机）。也可按所在网段测试 `192.168.100.23`。必须具备相应网络路由及TCP端口访问权限；本次不改知识库，无需重新入库。详见 [容器部署](docs/容器部署.md)。
