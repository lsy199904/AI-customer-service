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
