# SmartTITU 匿名智能客服

本仓库交付可嵌入平台页面的匿名客服浮窗，以及新Linux主机独立部署所需的应用与数据服务配置。模型服务由部署方单独提供。当前发布版本为 `release-anonymous-20261111`，旧Demo认证入口已移除。

## 部署入口

完整部署、配置、迁移与回退操作见 [部署说明](docs/部署说明.md)。首次部署按以下顺序执行，配置步骤不可省略：

```bash
sh scripts/v3.sh init
# 编辑.env：填写真实模型接口、访问密钥、平台来源，核对端口。
sh scripts/v3.sh build
sh scripts/v3.sh infrastructure
sh scripts/v3.sh ingest
sh scripts/v3.sh start
sh scripts/v3.sh doctor
```

## 前端接入

平台页面引入下列脚本，将域名替换为实际HTTPS服务域名：

```html
<script src="https://assistant.example.com/smart-bot/iframe-anonymous.js"></script>
```

脚本自动创建浮窗、申请匿名凭证并调用会话及流式问答接口。接入方不配置固定Token，不传账号密码；配置 `FRAME_ORIGINS` 允许实际平台来源。网关保留 `/smart-bot` 前缀并关闭流式响应缓冲。独立检查页为 `/smart-bot/widget/anonymous-demo`。

## 目录

| 路径 | 用途 |
|---|---|
| `app/` | FastAPI服务、LangGraph流程、检索及模型调用 |
| `app/static/` | 浮窗、iframe脚本与正式图片资源 |
| `data/` | 图片登记、业务流程配置及兼容知识数据 |
| `knowledge_sources/` | 正式入库源文档；新部署前核对完整性与版本 |
| `deploy/` | PostgreSQL初始化及Nginx示例；`generated/`仅在本机生成 |
| `scripts/` | 配置、启动、入库、备份恢复和日志查询工具 |
| `docs/部署说明.md` | 唯一正式部署与接入说明 |
| `tests/` | 匿名身份、会话归属、前端接入及部署流程自动回归 |
| `compose.v3.yaml` | 应用、PostgreSQL、etcd、MinIO、Milvus统一入口 |
| `.env.example` | 配置模板，无真实密钥 |
| `Dockerfile`、`requirements.lock` | 应用构建与锁定依赖 |

`var/`、`backups/`、真实`.env`和Docker命名数据卷不进入Git。源文档与图片属于内部知识资产，只推送至授权的公司仓库。旧原型、压测脚本、测试报告及历史部署说明已从本分支移除。
