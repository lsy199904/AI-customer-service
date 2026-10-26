# SQLite本地测试分支

分支：sqlite-local-testing。以main的13c4658为基础，main不变。

问答逻辑、LangChain/LangGraph、模型服务、iframe/浮窗/API、配图、推荐及人工入口均复用原实现。策略仍为语义候选门槛0.75、消息保留7天、模型上下文20轮、企业20条/滚动60秒、检索总预算15秒。BM25保留补召回。变更仅为部署入口：聊天与检查点使用var/assistant.db，知识及向量使用var/rag.sqlite3，向量在本地扫描，强制单工作进程。

## 切换和启动

现有服务器已经构建过ai_customer-assistant:enterprise，因此默认复用它；整个仓库挂载到/ai_customer，应用运行当前分支源码。仅重建同一项目的assistant容器，与企业版不能同时占用8000端口。不会清空var、models或原数据库卷，也不会修改.env中的企业数据库凭证。

```bash
cd ~/ai_customer
git fetch origin &&
git switch -c sqlite-local-testing --track origin/sqlite-local-testing
# 若该本地分支已经存在，使用 git switch sqlite-local-testing，然后 git pull --ff-only。

sh scripts/sqlite.sh start &&
sh scripts/sqlite.sh check
```

工作区有代码修改时先自行保留改动，勿强制切换。当前私有Word和模型继续手工保管，不从Git更新。

.env保留原模型配置。容器显式设置DATABASE_URL为空、VECTOR_BACKEND=sqlite、APP_WORKERS=1，优先于env_file及manage.py读取.env。不要在宿主机直接运行manage.py来判断SQLite部署状态，应通过sqlite.sh exec在容器内执行。此入口不使用compose.enterprise.yaml，所以不要求企业数据库环境字段或配套服务在线。

默认不拉取镜像，也不构建镜像。镜像不存在会停止并明确提示。其他镜像须包含当前requirements.lock中的依赖；仅把旧版本镜像重命名不能补齐依赖。可在命令前设置SQLITE_APP_IMAGE=兼容的本地镜像名称覆盖默认值。脚本不会安装依赖或重启Docker服务。

## 知识核对及验证

check应显示database为/ai_customer/var/assistant.db、vector_backend为sqlite，policies为约定值。原SQLite文件存在时复用；PostgreSQL中新增的数据不会自动回写SQLite，因而本地历史及知识可能落后。不要删除文件以尝试解决数量差异。

```bash
sh scripts/sqlite.sh exec assistant python manage.py documents
ls -lh knowledge_sources/
```

如果check显示知识数为0，或Word刚更新且尚未入库，确认knowledge_sources保留正确Word，然后执行：

```bash
sh scripts/sqlite.sh exec assistant python manage.py ingest &&
sh scripts/sqlite.sh restart assistant &&
sh scripts/sqlite.sh doctor
```

已有知识无需仅为切换部署重复入库。如提示缺失活动文档，先核对documents中的路径与实际文件，不要随意全量重建。历史保留7天策略仍生效，备份另行保留。

```bash
curl -fsS http://127.0.0.1:8000/ready
sh scripts/sqlite.sh doctor --models
```

浏览器继续访问http://10.180.158.23:8000/widget/demo（前提是.env的HOST=0.0.0.0且网络允许），凭证沿用现有流程：

```bash
sh scripts/sqlite.sh exec assistant python manage.py token --tenant demo --user tester
```

若5项策略未配置，可执行sqlite.sh policies后再start加载，不能只restart读取新的env_file。SQLite不依赖Milvus，但问答仍需要原Embedding、Reranker及聊天模型服务正常运行。

## 返回企业版

```bash
sh scripts/sqlite.sh stop assistant &&
git switch main &&
sh scripts/enterprise.sh infrastructure &&
sh scripts/enterprise.sh start
```

企业版仍需配套镜像与服务。测试期间SQLite产生的新会话不会自动合并到PostgreSQL；数据库迁移须单独核对并使用既有迁移方案，不直接覆盖已有库。

## 本次验证

147项Python回归：146项通过，1项可选PostgreSQL测试跳过。新增启动脚本测试验证：仅选择SQLite Compose文件、本地镜像缺失立即停止、不拉取/构建、不启动依赖、配置和既有文件保留、自定义本地镜像及诊断参数转发。

另使用实际Compose中的环境覆盖值，配合临时SQLite及合成资料执行语义RAG接口集成测试，验证企业.env不会覆盖空DATABASE_URL、未连接Milvus、答案附来源、ready接口以及关闭重启后的历史持久化。模型向量和生成使用测试替身，不调用生产模型。

本地没有Docker守护进程，未声明已经执行真实容器启动；服务器仍需按上文验证本地镜像、模型连通性和实际知识内容。

## v5业务流程及章节来源更新

本次业务流程按注册、登录、企业认证、在线签约、服务订购、星级评定、客户交付、客户充值、账单支付、在线开票整理为10个独立问题（问题4至13）。其余章节保留并连续编号，新Word共57问，独立流程配图由data/media.json登记并随代码同步。私有Word、原始PDF和drawio不推送。

Word标题1作为章节，标题2作为问题。入库片段保存section_title；API在原问题title之外提供display_title，例如用户手册-常用外部链接、用户手册-业务流程。浮窗、iframe共用此展示名，具体来源仍按知识ID打开原问题，不按章节合并正文或把同章节所有配图一并返回。历史中旧版回复缺少章节字段时使用用户手册-相关资料。

解析版本更新为documents-v3，需要一次全量重建。上传v5时覆盖已登记的原Word路径，保留旧文件名即可，不要在knowledge_sources同时保留v4、v5两个文件。当前测试机登记的路径为SmartTITU外部客户知识库_20261023_v4_去重版.docx；文件内部版本会正确读取为2026-10-26 v5。请先将旧Word备份到knowledge_sources之外，再覆盖。

```bash
cd ~/ai_customer/ai_customer_test
git pull --ff-only origin sqlite-local-testing &&
sh scripts/sqlite.sh exec assistant python manage.py ingest --rebuild &&
sh scripts/sqlite.sh start &&
sh scripts/sqlite.sh check &&
sh scripts/sqlite.sh doctor
```

本次151项回归：150项通过，1项可选PostgreSQL测试跳过。核对10个流程问题顺序和各自配图、57问唯一性及原章节保留；验证Word/WPS标题层级、长片段元数据继承、入库后重启的来源查询、章节显示和原问题路由。Word使用内置LibreOffice及临时中文字体配置完成39页渲染和逐页检查。未调用用户服务器的真实模型，不据此声明真实问法的准确率。
