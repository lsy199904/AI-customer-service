# HTTP接口约定

企业版 PostgreSQL + Milvus 部署、迁移与日常命令请先看 [企业升级与迁移](企业升级与迁移.md)。下文原容器/SQLite命令保留作兼容参考，企业升级后使用 enterprise.sh。

除GET /health及公开组件静态文件外,业务接口全部需要 `Authorization: Bearer <短期凭证>`。POST使用application/json,请求体最大16KiB。统一失败结构:`{"error":{"code":"...","message":"..."}}`。错误码包括400输入错误、401登录失效、403来源不允许、404资源不存在、409会话忙/幂等冲突、413请求过大、415媒体类型错误、429限流、500内部异常。模型异常作为正常HTTP200的suggestions结果返回,reason=model_unavailable；用户选择人工后才返回handoff。

|方法|路径|用途|
|---|---|---|
|GET|/health|存活检查,不含敏感配置|
|GET|/v1/bootstrap|欢迎语、快捷问题、联系信息、知识数和能力|
|POST|/v1/sessions|创建会话,可传context|
|GET|/v1/sessions|本人最近100个会话|
|GET|/v1/sessions/{id}/messages?before={message_id}|历史消息,每页100条|
|POST|/v1/sessions/{id}/messages|提问|
|DELETE|/v1/sessions/{id}|删除本人会话及全部消息|
|GET|/v1/sources/{knowledge_id}|查看允许客户访问的引用条目|
|GET|/v1/documents/{document_id}/revisions/{revision}/download|认证下载引用所对应的原文版本|

创建会话示例:

```json
{"context":{"page_path":"/billing","page_title":"账单页面","product":"TITU Hub"}}
```

context仅允许上述三个字符串字段,每字段最多200字符。企业ID和用户ID来自凭证,不能通过body或页面上下文覆盖;页面上下文不会触发业务查询或授权。

提问示例:

```json
{"message":"调用出现429怎么办?","request_id":"your-uuid-per-message"}
```

回答结构示例(知识ID和会话ID以实际结果为准):

```json
{
  "session_id":"...",
  "request_id":"your-uuid-per-message",
  "message_id":"...",
  "answer":"请降低请求频率,检查RPM/TPM上限...",
  "status":"answered",
  "reason":"knowledge",
  "answer_mode":"llm",
  "citations":[{
    "id":"KB-...",
    "title":"常见错误码",
    "source_file":"原资料文件名.pdf",
    "pages":[8,9],
    "version":"2026-10-08 v1",
    "url":"/v1/sources/KB-...",
    "document_url":null
  }],
  "handoff":false,
  "contact":null,
  "created_at":1790000000.0
}
```

所有时间是Unix秒。answer_mode=extractive时返回资料正文,reason=extractive,客户窗口不显示模式提示。handoff=true时前端应展示contact,而非显示“已转接成功”。当前自动无法回答时返回status=suggestions、handoff=false、contact=null；只有用户明确要求人工或拒绝上一轮推荐时返回reason=requested_handoff、handoff=true。contact中的wechat_qr_url未配置时为null,应隐藏二维码区域并展示电话和邮箱。

前端显示模型或知识文本时应作为纯文本或经过安全过滤的Markdown处理,不要直接作为HTML渲染。读取来源需附带同一Bearer凭证。API没有自动执行来源正文中的命令或跳转的能力。

## 自带悬浮组件

GET /widget.js:可嵌入脚本;GET /widget/demo:本地验证页面;GET /widget/demo.js与GET /widget/demo.css:演示页资源。均不含业务数据,无需Bearer。问答、历史和知识来源接口仍需认证。静态资源使用固定路由映射,不开放任意目录读取。

## 意图、命中与图片回复

回答新增intent(如greeting、knowledge、image、handoff)、retrieval(是否命中、算法、阈值和最高相似度)、images数组。问候没有知识引用也可以status=answered;status不再依赖是否存在citation。业务问题未达到知识命中条件时不调用模型生成，返回推荐问题；知识命中后模型answerable=false也先返回推荐，不立即展示人工卡片。

images每项包含id、url、title、alt,只来自data/media.json中已登记资源,模型不能创建任意图片URL。本地图片通过公开的固定/media/文件名提供,仅适合可公开的客户资料,不是内部文档下载服务。当前支持PNG/JPEG/WebP/GIF。

二维码当前未提供,SUPPORT_QR_URL保持空白,contact.wechat_qr_url为null;窗口不显示二维码、占位或扫码引导。后台图片能力仍可提供普通产品图片。

answer_mode仍保留给开发者诊断,客户聊天界面不展示“未调用大模型”等技术提示。历史中旧的摘录前缀只在界面隐藏,数据库原始记录不被篡改。

## 语义检索与版本引用

默认retrieval.method为embedding_rerank，明确禁用重排时为embedding。问候跳过检索。threshold为余弦门槛，similarity为最高召回分数，都不是正确率。检索服务不可用时reason=retrieval_unavailable、status=suggestions，提供重试提示、常用问题和人工入口，不把系统故障描述为没有相关知识。

citations新增document_id、revision、download_url、source_locator、source_references。download_url指向该修订原始Word/PDF等文件快照，需要相同Bearer认证，以附件返回，不是JSON。更新和停用文档后历史快照仍保留。新知识来源接口支持历史片段ID。当前客户知识为所有已认证用户共享，没有企业私有知识分区。

文档新增、停用和版本切换仅通过服务端manage.py命令，未开放面向客户的管理接口。

Word章节的配图标记会被保存为知识元数据image_ids；成功回答实际引用该节时，后端自动合并已登记图片到回复images，即使生成模型未选择图片也会附带。拒答和未引用的候选章节不强制附图。images结构保持不变，前端可用url展示缩略图或打开原图；不需要另外识别Word内嵌图片。


iframe公开入口：`GET /chatbot`、`GET /iframe.js`、`GET /widget/frame.js`、`GET /widget/frame.css`、`GET /widget/config`（仅返回允许嵌入来源）。仅 `/chatbot` 允许配置域名嵌入，其余HTML保留禁止嵌入。业务接口鉴权不变。详见 [iframe 接入](悬浮弹窗接入.md)。


FastAPI升级保持现有业务接口不变。新增GET /ready（应用及数据库就绪）和需Bearer的GET /openapi.json（接口规范）；GET/HEAD /health均支持。响应包含X-Request-ID。Pydantic字段或JSON格式错误维持400；请求体超过16KiB为413，不支持的Content-Type为415；应用并发容量耗尽为503。模型调用在线程池运行，会话和用户鉴权规则不变。


## 流式响应与运维检查

POST /v1/sessions/{sid}/messages/stream 与原 messages 使用相同Bearer、message和request_id；返回 text/event-stream。事件包括 status（stage）、delta（模型实时生成的正文text）、complete（与原JSON接口相同的完整响应）、error（code/message）。HTTP鉴权/归属失败在SSE头之前返回；流内失败以error事件返回，客户端不能只检查HTTP200。断线后重用同一个request_id重试，避免重复消息。

GET /ready 检查关系库、非空活动知识和Milvus当前集合；GET /metrics 需要独立 X-Operations-Token，不使用浏览器登录token。模型协议通过 manage.py doctor --models 检查。iframe、原JSON接口及来源下载路径保持兼容。


## 未回答后的推荐与人工选择

status有三种：answered正常回答；suggestions尚未回答、等待用户选择；handoff显示人工联系方式。JSON、SSE complete及历史response使用相同结构。

```json
{
  "status": "suggestions",
  "answer": "你当前的问题我无法回答哦，你可以向我提问：",
  "suggestions": ["如何创建API密钥", "如何注册企业账号与认证", "如何开发票"],
  "actions": [{"type": "handoff", "label": "以上都不是，转人工", "message": "转人工客服"}],
  "handoff": false,
  "contact": null,
  "images": [],
  "citations": []
}
```

前端点击推荐项，使用新request_id将该问题提交至原messages或stream接口；点击人工选项提交“转人工客服”。用户在推荐后直接回复“都不是”也能触发人工。直接要求人工不必先经过推荐。没有实际转接真人工作台，不能提示“已经接通”。旧历史按原已保存响应展示，只有新请求采用新流程。

推荐优先复用本轮向量近邻和相关的已入库章节标题，不足时补预设常用问题；不降低回答阈值、不把推荐视为已命中。显式敏感话题按本地规则跳过检索与生成，并由模型系统提示约束其他表述；不宣称具有完整的专用内容审核模型。平台的内容安全治理类正常产品问题仍可检索。

## 来源显示与请求排查

来源对象保留原有 `title`，新增 `display_title`（例如 `用户手册：操作审计`）和 `section_title`。前端建议展示 `display_title`，引用 ID 与来源访问权限不变。历史响应没有新字段时，可清理原 `title` 的问题序号再添加“用户手册：”前缀。

聊天请求可将正文 `request_id` 同时放入 `X-Request-ID`，并通过 `X-Widget-ID` 携带每次页面加载生成的随机窗口编号。窗口编号仅用于运营排查，不作为身份或访问权限。接口响应继续返回 `X-Request-ID`，详情见 [运营日志与身份对接](运营日志与身份对接.md)。

正文采用真实模型流式输出，不再要求模型生成JSON，不进行模型答案JSON解析、引用字段校验或格式重试。提示词约束依据本轮资料回答、不要输出思考过程或图片占位。`citations` 来自本轮选用的检索证据，`images` 来自关联的已登记配图，不再由模型生成ID。

前端收到delta后立即追加到当前机器人消息；complete到达后以其中的最终answer定稿并附加图片和来源，不额外新建重复答案。若生成中途失败，complete可能携带降级提示，应以complete结果替换临时正文；如果收到error或流中断且没有complete，移除临时消息并提示重试。同一个请求编号重试仍复用已保存结果。HTTP JSON接口、SSE事件负载和日志文件仍用JSON传输，这与模型直接输出普通文本是两回事。

请确保反向代理关闭该SSE路径的响应缓冲和压缩缓冲。服务已设置 `X-Accel-Buffering: no` 和心跳；若直连能实时显示而经过代理一次出现，应检查代理配置。
