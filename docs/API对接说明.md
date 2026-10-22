# HTTP接口约定

除GET /health及公开组件静态文件外,业务接口全部需要 `Authorization: Bearer <短期凭证>`。POST使用application/json,请求体最大16KiB。统一失败结构:`{"error":{"code":"...","message":"..."}}`。错误码包括400输入错误、401登录失效、403来源不允许、404资源不存在、409会话忙/幂等冲突、413请求过大、415媒体类型错误、429限流、500内部异常。模型异常作为正常HTTP200的handoff结果返回,reason=model_unavailable。

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

所有时间是Unix秒。answer_mode=extractive时answer明确标记为知识原文摘录,reason=extractive。handoff=true时前端应展示contact,而非显示“已转接成功”。理由包括no_knowledge、insufficient_evidence、model_unavailable、requested_handoff、business_tool_unavailable。contact中的wechat_qr_url未配置时为null,应隐藏二维码区域并展示电话和邮箱。

前端显示模型或知识文本时应作为纯文本或经过安全过滤的Markdown处理,不要直接作为HTML渲染。读取来源需附带同一Bearer凭证。API没有自动执行来源正文中的命令或跳转的能力。

## 自带悬浮组件

GET /widget.js:可嵌入脚本;GET /widget/demo:本地验证页面;GET /widget/demo.js与GET /widget/demo.css:演示页资源。均不含业务数据,无需Bearer。问答、历史和知识来源接口仍需认证。静态资源使用固定路由映射,不开放任意目录读取。

## 意图、命中与图片回复

回答新增intent(如greeting、knowledge、image、handoff)、retrieval(是否命中、算法、阈值和最高相似度)、images数组。问候没有知识引用也可以status=answered;status不再依赖是否存在citation。业务问题未达到知识命中条件时直接handoff=true,不调用模型生成。知识命中后模型answerable=false也返回人工卡片。

images每项包含id、url、title、alt,只来自data/media.json中已登记资源,模型不能创建任意图片URL。本地图片通过公开的固定/media/文件名提供,仅适合可公开的客户资料,不是内部文档下载服务。当前支持PNG/JPEG/WebP/GIF。

二维码当前未提供,SUPPORT_QR_URL保持空白,contact.wechat_qr_url为null;窗口不显示二维码、占位或扫码引导。后台图片能力仍可提供普通产品图片。

answer_mode仍保留给开发者诊断,客户聊天界面不展示“未调用大模型”等技术提示。历史中旧的摘录前缀只在界面隐藏,数据库原始记录不被篡改。
