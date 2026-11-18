# SmartTITU匿名智能客服

本分支`deploy-external-api-20261116`采用外部LLM、Embedding、Rerank API，以及已开通的PostgreSQL 16和Milvus 2.6服务。生产运行于Kubernetes，研发可用Docker独立验证。不部署模型、PG、Milvus、etcd或MinIO容器。

## 操作入口

完整配置、执行顺序和验收方式见[部署说明](docs/部署说明.md)。

```bash
sh scripts/production.sh init
# 填写.env：三个模型接口、PG、Milvus、公司镜像地址及Kubernetes参数。
sh scripts/production.sh build
sh scripts/cloud.sh init
# 如需自动准备业务库，填写私有.env.cloud。
sh scripts/cloud.sh prepare
sh scripts/production.sh deploy
```

已由平台准备业务库时，可跳过cloud步骤。研发服务器验证使用`scripts/dev.sh`，见部署说明。

## 交付目录

| 路径 | 用途 |
|---|---|
| `app/` | 原有问答、检索、匿名身份、日志及初始化代码 |
| `knowledge_sources/` | 正式Word、PDF知识源，随镜像交付 |
| `app/static/media/`、`data/media.json` | 图片及知识配图登记，随镜像交付 |
| `.env.example` | 唯一配置模板；生成的真实.env不提交Git |
| `scripts/cloud.sh`、`docs/cloud` | 云端业务库及专用账号准备 |
| `scripts/production.sh`、`docs/kubernetes` | Kubernetes初始化、部署、更新、日志及停止 |
| `scripts/dev.sh`、`compose.dev.yaml` | 研发环境仅启动App的验证入口 |
| `docs/部署说明.md` | 部署及日常维护说明 |
| `var/` | 运行时生成；生产挂载PVC，保存原有日志和PDF图片 |
| `tests/` | 部署隔离及原有功能回归测试 |

## 前端接入

```html
<script src="https://客服实际域名/smart-bot/iframe-anonymous.js"></script>
```

平台Ingress保留`/smart-bot`前缀并关闭SSE缓冲；配置`FRAME_ORIGINS`和需要的`CORS_ORIGINS`。JS自动获取匿名凭证和加载浮窗，不向前端暴露模型Key。演示页：`/smart-bot/widget/anonymous-demo`。

`.gitignore`用于保护密钥、日志、数据库导出及备份。代码、正式知识文件、图片和登记文件均在仓库中；原有问答和日志结构保持不变。
