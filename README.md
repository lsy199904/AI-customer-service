# SmartTITU 智能客服 · 一期 MVP 交付包

本项目包含真实后端、可嵌入业务页面的悬浮客服、134 条客户知识，以及一个可双击打开的独立 HTML 交互原型。不依赖 Dify、前端框架或外部数据库。

> **当前状态**：可本地运行、可按单实例方式部署。历史会话写入 SQLite；知识采用BM25词法检索与TF-IDF余弦相似度门槛,再由模型判断证据能否支持回答。真实大模型和现有企业登录需要按下面的步骤配置。尚未完成真实模型/SSO/生产环境验收，不能把原型效果等同于生产 AI 回答质量。

## 1. 先看功能原型，不用安装环境

直接双击打开：**[prototype/SmartTITU_功能原型.html](prototype/SmartTITU_功能原型.html)**。

可体验悬浮按钮、展开收起、快捷问题、文本提问、知识引用、人工电话/邮箱、新建会话、历史恢复和删除。独立文件内置同一份客户知识；使用本地关键词检索，不发起网络请求、不调用模型。会话仅保存在当前页面内存中，刷新即重置。

要体验真实后端、持久化与模型，请按后面的步骤启动服务，访问 `/widget/demo`。**独立原型不是部署入口，也不会自动连接你的线上系统。**

## 2. 代码目录

```text
smarttitu-assistant/
├── README.md                      本文：启动、模型接入、部署和维护
├── manage.py                      配置初始化、启动、检查、令牌和数据库备份
├── .env.example                   配置模板，无真实密钥
├── Dockerfile / compose.yaml      单实例容器部署
├── app/
│   ├── core.py                    身份、知识检索、模型调用、会话持久化
│   ├── server.py                  HTTP接口与固定静态资源路由
│   └── static/                    正式悬浮组件及真实后端联调页
├── data/knowledge.jsonl            运行时使用的134条客户知识
├── knowledge/                     可读Markdown、来源清单和待核实口径
├── prototype/                     独立HTML原型及原型页面模板
├── scripts/build_prototype.py      由正式组件与知识数据重建独立原型
├── deploy/nginx.conf.example       HTTPS反向代理模板
├── docs/                          API、接入、范围、部署运维与验证记录
└── tests/                         自动化测试
```

原始 PDF、管理员知识、内部销售话术和待确认条目不打入运行数据。知识变更以 `data/knowledge.jsonl` 为运行依据；Markdown 为当前知识快照，不会自动同步成运行数据。

## 3. 本地启动：Python 方式

需要 Python 3.9+，推荐 3.12。没有第三方 Python 依赖，不需要执行 pip install。先解压，并在终端进入包含 `manage.py` 的目录。

### 3.1 初始化配置

```bash
python3 manage.py init
```

自动创建 `.env` 并生成随机 `AUTH_SECRET`，不会覆盖已有 `.env`。密钥不会打印到终端。`.env` 留在服务端，不要交给前端或提交到代码仓库。

### 3.2 检查并启动

```bash
python3 manage.py check
python3 manage.py serve
```

配置会自动从项目目录 `.env` 读取，无需手动 source；已存在的系统环境变量优先于 `.env`。默认监听 `127.0.0.1:8000`，历史数据库写入 `var/assistant.db`。

看到 `backend ready` 后保持终端运行。可访问 `http://127.0.0.1:8000/health`，应返回 `{"status":"ok"}`。在该终端按 Ctrl+C 停止服务。

更换端口：

```bash
python3 manage.py serve --port 8001
```

### 3.3 在浏览器体验真实服务

在另一个终端进入同一项目目录：

```bash
python3 manage.py token --tenant demo-company --user demo-user
```

复制输出的短期凭证，打开 `http://127.0.0.1:8000/widget/demo`，粘贴凭证并点击“连接并打开客服”。这是本地联调入口，不要求填写模型密钥。

默认 `ANSWER_MODE=extractive`：知识命中后返回资料正文,不调用大模型。客户窗口不展示内部模式提示;实际模式保留在接口字段与配置检查中。问候/致谢等走独立会话流程。会话实际保存在 SQLite 中，重启后仍可恢复。短期凭证默认一小时有效，到期重新生成即可。

## 4. 如何接入大模型

编辑 `.env`：

```dotenv
ANSWER_MODE=llm
MODEL_BASE_URL=https://api.smarttitu.cn/v1
MODEL_API_KEY=填写你在平台申请的实际API密钥
MODEL_NAME=填写控制台已开通的实际模型ID
```

保存后重新执行 `python3 manage.py check` 并重启服务。check 只校验配置格式与知识文件，不访问外网，不能证明密钥或模型有效。

- `MODEL_BASE_URL` 默认要求 HTTPS 基础地址，不包含 `/chat/completions`；服务会在末尾拼接该路径。例如基础地址为 `https://api.smarttitu.cn/v1`，实际请求地址就是 `https://api.smarttitu.cn/v1/chat/completions`。
- 内网HTTP模型可显式配置准确来源,例如`MODEL_HTTP_ORIGINS=http://10.180.158.23:18080`。仅允许私有IP/localhost的已列出来源,不含`/v1`;不再需要手改core.py。
- `MODEL_API_KEY` 仅保留在服务器，浏览器和原型都不需要模型密钥。含空格或 `#` 的值请使用引号包裹。
- `MODEL_NAME` 使用实际 model ID，不填写页面展示名，不预设某个模型一定可用。
- 兼容非流式 Chat Completions 接口，发送 `model`、`messages`、`stream:false`，使用 `Authorization: Bearer ...` 鉴权。模型应按提示生成 JSON 对象，包含 `answerable`、`answer`、`citation_ids`和可选的`image_ids`。服务会验证 JSON、知识引用及已登记图片ID；格式不符或超时会转人工兜底。
- 当前不强制传 `response_format`，也不使用 Responses API、工具调用或流式输出。请求超时45秒，不跟随重定向。对接其他供应商时，须确认其接口路径、认证及消息格式兼容。

模型适配参考：[OpenAI Chat Completions 官方接口说明](https://developers.openai.com/api/reference/resources/chat/subresources/completions/methods/create)。该引用说明接口格式，不代表所有第三方模型均兼容。

验证方法：打开真实联调页询问“调用出现429错误怎么办？”，返回应标为 `answer_mode=llm` 且具有知识引用。若 `reason=model_unavailable`，检查地址、密钥、模型ID、出口网络和模型输出格式。当前不会向客户端泄露上游原始错误正文或密钥。具体自查见 [部署运维说明](docs/部署运维说明.md)。

## 5. 如何部署：Docker 单实例方式

服务器需先安装 Docker Engine 及 Compose 插件。当前交付使用的本机未安装 Docker，因此容器构建尚未实测；原生 Python 服务与接口已有验证记录。

在解压后的项目目录：

```bash
python3 manage.py init
```

如果服务器没有 Python，可以手动复制 `.env.example` 为 `.env`，并将 `AUTH_SECRET` 设置为独立生成的至少32字节随机值。已有 `.env` 时无需重新初始化。按第4节填入模型配置；再设置真实业务页面来源，例如：

```dotenv
CORS_ORIGINS=https://console.example.com
SUPPORT_QR_URL=
```

来源域名为示例,替换为实际业务页面来源。当前未提供企业微信二维码,保持SUPPORT_QR_URL为空:人工卡片只展示电话和邮箱,不占位、不提示扫码。多个业务来源用逗号分隔，不接受 `*`。

启动、查看状态与日志：

```bash
docker compose up --build -d
docker compose ps
docker compose logs --tail=100 assistant
```

容器以非root用户运行，端口仅绑定宿主机 `127.0.0.1:8000`，数据库写入持久化的 named volume。修改 `.env` 后执行：

```bash
docker compose up -d --force-recreate assistant
```

更新代码后执行 `docker compose up --build -d`。停止使用 `docker compose down`；**不要加 `-v`**，否则会删除数据库卷。项目目录名称或Compose项目名改变会影响默认卷名，运维时应保持一致。

Docker方式生成本地联调凭证：

```bash
docker compose exec assistant python -m app.token --tenant demo-company --user demo-user
```

远程服务器的8000端口默认不对公网开放。使用已有HTTPS代理接入，或通过运维允许的SSH隧道访问联调页；不需要把服务直接暴露到公网。

### HTTPS域名访问

提供 [deploy/nginx.conf.example](deploy/nginx.conf.example)。替换域名、证书路径，在宿主机Nginx中加载并执行 `nginx -t` 验证后再重载。模板转发到 `127.0.0.1:8000`，允许请求等待时间超过模型45秒超时，并阻止公网访问联调页。证书申请与现有网关配置不由该模板自动完成。

参考：[Nginx proxy 模块官方文档](https://nginx.org/en/docs/http/ngx_http_proxy_module.html)。

## 6. 如何接入现有业务页面

在业务页面公共布局加载一段脚本，不需要另外开发聊天窗口：

```html
<script src="https://assistant.example.com/widget.js"
        data-auth-url="/api/assistant/token" defer></script>
```

替换客服服务域名，配置对应的 `CORS_ORIGINS`。`/api/assistant/token` 由现有控制台可信后端提供：先校验已有登录会话，再按真实企业ID和用户ID签发短期凭证，返回 `{"token":"..."}` 并禁止缓存。

后端可复用 `app.core.issue_token(secret, tenant_id, user_id, lifetime=3600)`。协议是双段HMAC签名凭证，不是JWT；如果控制台后端不是Python，需按相同协议实现签发或增加认证适配器。不要开放“浏览器输入任意企业ID即可领凭证”的接口。

主站退出或切换账号时调用 `window.SmartTITUAssistant.reset()` 清理窗口状态。签名密钥只保留在可信后端；前端只拿短期凭证。详细流程及CSP要求见 [悬浮弹窗接入](docs/悬浮弹窗接入.md)。

## 7. 历史会话与上下文记忆

- 正式服务：会话、用户问题和助手回答写入SQLite，按企业与用户隔离；窗口支持查看、恢复、分页和删除。
- 模型回答：最多携带最近12条消息（通常约6轮），并不是永久记住全部聊天。闲置超过30分钟的新问题不携带旧上下文，但历史记录仍保留。
- 独立HTML原型：本页内存保存，刷新重置，不写真实数据库，没有真实模型语义理解。
- 尚未实现跨会话长期记忆、企业专有知识上传、实时业务查询、在线真人接管、图片上传/OCR及评价回流。

## 8. 数据备份与恢复

原生启动后，在项目目录执行：

```bash
python3 manage.py backup
```

默认生成 `backups/assistant-时间.sqlite3`，使用SQLite备份API保证运行中的WAL数据库一致性，并检查完整性，不覆盖同名文件。

Docker部署的备份与恢复步骤见 [部署运维说明](docs/部署运维说明.md)。恢复必须先停止服务；不要只在运行时复制 `assistant.db` 而忽略WAL文件。备份包含对话内容，应由企业控制访问。

## 9. 知识维护、测试与交付边界

运行数据为 `data/knowledge.jsonl`。只接纳 `audience=customer` 且 `status=source_based` 的条目；修改后重启服务。词法检索不等于语义向量检索，同义表达和复杂追问可能漏检，需用真实业务问题验收。

更新独立原型：

```bash
python3 scripts/build_prototype.py
```

运行测试（接口测试需要临时监听本机端口）：

```bash
python3 -m unittest discover -s tests -v
```

验证范围见 [测试结果](docs/测试结果.md)。真实模型、SSO和业务网站嵌入尚待联调；Docker、Nginx和生产容量不在已实测通过范围内。

当前使用标准库HTTP服务、SQLite与进程内会话锁，适合单实例小规模部署验证；不要多实例共享同一SQLite文件。数据库尚无自动保留期清理或应用层加密，尚未交付高可用和生产容量承诺。正式上线前需完成企业身份、模型效果、备份恢复、监控与容量验收。

默认人工电话/邮箱来自原销售FAQ，部署前由运营确认。企业微信二维码未提供时显示电话/邮箱，不能声称已经接通真人。

## 10. 文档导航

- [部署运维说明](docs/部署运维说明.md)：反向代理、常见故障、备份恢复、升级。
- [悬浮弹窗接入](docs/悬浮弹窗接入.md)：现有控制台如何加载脚本、签发登录凭证。
- [API对接说明](docs/API对接说明.md)、[OpenAPI描述](docs/openapi.json)：接口约定。
- [MVP验收清单](docs/MVP验收清单.md)：一期范围及未实现内容。
- [知识整理说明](knowledge/README.md)：知识来源、运行数据和可读文档的关系。

## 本次客服交互修正

问候/身份/能力/致谢/告别先分流;llm模式由系统提示驱动模型友好回应,不检索知识。业务问题先检索并通过主题覆盖、BM25分数及TF-IDF余弦相似度门槛,有效命中才进入模型证据判断与生成;无有效知识直接转人工,模型判定依据不足也转人工。用户主动转人工同样展示联系卡片。

`RETRIEVAL_MIN_SIMILARITY=0.14`可配置,数值是词法向量相似度,不是答案准确率或置信概率,也不是Embedding语义检索。不要盲目调低门槛;实际业务语料仍需验收。错误追问不再自动继承无关的计费上下文。

回复支持已登记图片,详见[图片回复与人工联系](docs/图片回复与人工联系.md)。这不包含图片生成或上传OCR。目前没有企业微信二维码,不展示;无需等待二维码即可使用人工电话/邮箱。
