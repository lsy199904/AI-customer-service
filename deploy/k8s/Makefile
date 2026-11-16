# SmartTITU 匿名客服 · Kubernetes 入口
# 三个环境共用同一套 base，靠 ENV 切换 overlay。
#
#   make render  ENV=dev     # 只渲染，不碰集群
#   make diff    ENV=uat     # 与集群现状对比
#   make apply   ENV=prod    # 应用 + 强制重启（配置改了不会自动滚更，见 README）
#   make ingest  ENV=uat     # 增量入库（自动缩容再恢复，见下）
#   make rebuild ENV=prod    # 全量重建（换 Embedding 模型 / 切分参数后）
#
# 默认 ENV=prod，是为了防止误操作把 dev 清单打到生产。

SHELL   := /bin/sh
KUBECTL ?= kubectl
ENV     ?= prod

ifeq ($(ENV),dev)
NS := smarttitu-dev
else ifeq ($(ENV),uat)
NS := smarttitu-uat
else ifeq ($(ENV),prod)
NS := smarttitu
else
$(error 未知的 ENV=$(ENV)，可选 dev / uat / prod)
endif

.PHONY: help render diff apply restart scale-down scale-up ingest rebuild

help:
	@echo "用法: make <target> ENV=<dev|uat|prod>"
	@echo "  render | diff | apply | restart"
	@echo "  ingest | rebuild        （入库/重建，自动处理 RWO 卷的交接）"
	@echo "  scale-down | scale-up   （手工缩容/恢复）"
	@echo ""
	@echo "当前 ENV=$(ENV)  NS=$(NS)"

render:
	$(KUBECTL) kustomize overlays/$(ENV)

diff:
	$(KUBECTL) diff -k overlays/$(ENV) || true

# ConfigMap 关了名字哈希，改配置不会自动滚更，所以这里显式 restart
apply:
	$(KUBECTL) apply -k overlays/$(ENV)
	$(KUBECTL) -n $(NS) rollout restart deploy/assistant
	$(KUBECTL) -n $(NS) rollout status deploy/assistant --timeout=300s

restart:
	$(KUBECTL) -n $(NS) rollout restart deploy/assistant
	$(KUBECTL) -n $(NS) rollout status deploy/assistant --timeout=300s

scale-down:
	$(KUBECTL) -n $(NS) scale deploy/assistant --replicas=0
	$(KUBECTL) -n $(NS) wait --for=delete pod -l app.kubernetes.io/name=smarttitu-assistant --timeout=200s

scale-up:
	$(KUBECTL) -n $(NS) scale deploy/assistant --replicas=1
	$(KUBECTL) -n $(NS) rollout status deploy/assistant --timeout=300s

# 先缩容：assistant-data 是 RWO 云盘，应用占着的时候 Job 可能调度到别的节点
# 而挂载失败（Multi-Attach）。入库是几周一次的偶发操作，停 1~2 分钟可接受。
# 跑完再滚回来，顺带让 MediaCatalog 重新加载新图片。
ingest:
	$(MAKE) scale-down ENV=$(ENV)
	$(KUBECTL) -n $(NS) delete job assistant-ingest --ignore-not-found
	$(KUBECTL) -n $(NS) apply -k jobs/ingest
	$(KUBECTL) -n $(NS) logs -f job/assistant-ingest
	$(MAKE) scale-up ENV=$(ENV)

rebuild:
	$(MAKE) scale-down ENV=$(ENV)
	$(KUBECTL) -n $(NS) delete job assistant-ingest-rebuild --ignore-not-found
	$(KUBECTL) -n $(NS) apply -k jobs/rebuild
	$(KUBECTL) -n $(NS) logs -f job/assistant-ingest-rebuild
	$(MAKE) scale-up ENV=$(ENV)
