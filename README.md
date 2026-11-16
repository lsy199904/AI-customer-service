# SmartTITU 匿名智能客服

本分支 `deploy-external-api-20261116` 用于连接已有PostgreSQL、Milvus以及外部LLM、Embedding、Rerank API。仅部署App，不迁移研发数据库，不启动模型或数据库容器。知识文件采用已审核v20，异常兜底文案已更新。

## 部署

正式步骤、必填配置和研发服务器8201独立测试见 [部署说明](docs/部署说明.md)。

```bash
sh scripts/external.sh init
# 编辑.env：填写三个模型接口及Key、独立PG业务库、Milvus连接信息。
sh scripts/external.sh deploy
```

已有兼容应用镜像时：`sh scripts/external.sh deploy --image 镜像名`。首次初始化会调用Embedding生成知识向量，不需要本地模型或GPU。

## 接入

```html
<script src="https://客服实际域名/smart-bot/iframe-anonymous.js"></script>
```

配置平台`FRAME_ORIGINS`，网关保留`/smart-bot`前缀并关闭SSE缓冲。脚本自动获取匿名凭证及加载浮窗；不向前端提供模型API Key。演示页为`/smart-bot/widget/anonymous-demo`。

## 目录

| 路径 | 用途 |
|---|---|
| `app/` | 问答、检索、流程编排、匿名身份及部署前检查 |
| `knowledge_sources/` | 正式Word、PDF知识源 |
| `app/static/media/`、`data/media.json` | 图片文件及登记 |
| `compose.external.yaml` | 连接外部服务，仅启动App |
| `.env.external.example` | 注释完整的外部服务配置模板 |
| `scripts/external.sh` | 一键部署、检查、入库、重启及日志 |
| `docs/部署说明.md` | 部署人员操作入口 |
| `docs/知识库版本说明.md` | 当前知识内容及配图清理说明 |
| `var/` | 运行日志、PDF提取图片；需要持久化，不提交Git |

真实.env、数据库数据与备份不进入Git。旧`compose.v3.yaml`及`v3.sh`只保留兼容历史自建环境，不与新入口混用。
