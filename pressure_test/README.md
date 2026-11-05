# 独立端口压力测试

Python 3.9+，无额外依赖。推荐晚上低峰测试。默认1/2/5并发、每阶段5次请求、阶段间隔65秒；通常约3～5分钟，模型很慢时更久。此轮只验证链路，不测定最大容量。逐步升压、长时间稳定性测试和复核建议预留30～60分钟，实际取决于模型耗时和测试规模。

## 隔离范围

独立代码目录、Compose项目、容器、日志和18200端口，不重建、不重启、不更改演示8200实例。18200仅监听服务器127.0.0.1。

复制.env意味着仍共享模型/GPU、PostgreSQL、Milvus。测试会写测试会话、触发现有会话保留清理，并消耗数据库连接、模型资源和额度。无法保证8200响应速度不受影响。禁止在此测试实例执行ingest、migrate或改知识配置。真正不影响演示需要独立数据库、向量库副本以及模型算力/配额，此方案不提供完整资源隔离。下午可以只下载，晚上再启动和压测。

## 部署：不要在正在演示的挂载目录git pull

首次在服务器执行（源配置路径按实际调整）：

```bash
cd ~/ai_customer
git clone --branch v3 --single-branch git@github.com:lsy199904/AI-customer-service.git ai_customer_pressure
cd ai_customer_pressure
umask 077
cp ../ai_customer_v3/.env .env
chmod 600 .env
```

如果 ai_customer_pressure 已存在，请进入它执行 `git pull --ff-only origin v3`，不再clone。

使用本机已经存在的 `ai_customer-assistant:v3` 镜像，不下载、不build；镜像不存在会失败。配置里的模型路径/外部挂载路径须从测试容器可达；本项目现有HTTP模型地址可直接复用。如果PDF图片存于源目录var/pdf_media，可按需复制整个目录到测试目录var/下（可选，压测脚本只测问答接口，不下载图片）。相对SQLite路径不适合复用此方案；本方案针对当前PostgreSQL+Milvus部署。

晚上执行：

```bash
cd ~/ai_customer/ai_customer_pressure
sh scripts/pressure.sh start &&
sh scripts/pressure.sh check &&
sh scripts/pressure.sh token &&
python3 pressure_test/load_test.py \
  --base-url http://127.0.0.1:18200 \
  --tokens-file pressure_test/tokens.txt \
  --concurrency 1,2,5 --requests 5
```

check应显示PostgreSQL、Milvus及现有知识数量；若为空先停止，不要在测试目录重新入库。完成后关闭测试容器，不影响演示容器：

```bash
sh scripts/pressure.sh stop
```

无需重新入库，无需重建镜像。token命令有效期2小时，过期重跑。不要使用 `v3.sh exec`，该脚本没有exec子命令。

## 指标与保护

输出load-results-时间/summary.json及requests.jsonl。包含请求编号供关联日志，无令牌/完整回答。
- 首字时间从聊天请求开始，仅统计非空delta，不将connected/心跳当首字。
- 总耗时包含创建独立会话。每次创建新会话和request_id，不自动重试；不覆盖追问场景。
- 正常回答统计status=answered；HTTP200中的未命中、超时兜底不算正常回答。answered不证明业务正确，需抽查。
- answered_ttft_p95_s、answered_total_p95_s是正常回答P95；all_total_p95_s包含失败样本。少量样本的P95不稳定。
- 多delta数量及stream_span_s辅助检查流式，不单独证明实时模型输出。
- 401/403/429/rate_limited停止新增请求；完成至少5条后非answered比例达到20%停止升压；在途请求仍会收尾。
- Ctrl+C停止提交并等待已开始请求完成/超时。会话创建和聊天各自90秒超时；模型后台未必立即停止。
- 每企业每分钟20条仍生效。429是限流，不是系统容量上限。多用户同企业共享额度。

提高规模前，先确认questions.txt的每条问题在低并发确实可回答。多企业测试可以将经批准的不同测试企业令牌逐行写入tokens.txt，脚本轮询；不要用真实客户身份，不修改线上限流。tokens.txt必须只含令牌、不含终端提示或日志。

例如 `--concurrency 10 --requests 20` 表示最多10个在途请求、总共20次，必须有足够测试身份额度。大规模测试须使用独立压测机，并考虑应用、检索、模型限额。脚本是闭环负载，不模拟瞬间1000请求突发。

同时观察docker stats、GPU利用率和模型队列。当前脚本不下载引用图片、不评测浏览器渲染；本地端口不经过正式网关，正式部署还应验证代理SSE缓冲。容量结论需持续测试，不由本脚本自动宣布。

本地验证：模拟接口覆盖两段SSE、未命中、SSE错误、429、截断和P95；未实际连接服务器压测，未在本机Docker启动实例。

## 夜间增强批次（2026-11-05）

night_suite.py先用专用企业分别测20次/分钟（每3秒发起、不等待上条完成）和21次/60秒限流边界（每秒发起），然后用100个独立测试企业逐级测5、10、20、50、100并发。最多226次问答，阶段间隔65秒。只有前序阶段通过才继续；错误/非正常回答达到20%或配额行为异常会停止。预计约10～30分钟，具体视响应速度而定。

使用服务端签发的临时测试凭证，不修改企业限流。令牌存于权限受限的运行目录，结束时删除。测试会话与数据保留策略一致。100表示目标最大客户端在途请求，报告记录实际观测值；不等于100条模型同时生成。每档只有一轮，不能作为持续稳定支持100人的承诺。模型/数据库仍共享，可能使8200变慢。

已安装的21:00 cron不需要修改，只需在21:00前在独立测试目录git pull更新脚本。没有重新入库、构建或重启演示实例的必要。
