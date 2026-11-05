#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
export TZ=Asia/Shanghai
export ASSISTANT_UID=$(id -u) ASSISTANT_GID=$(id -g)
[ "$(basename "$ROOT")" = ai_customer_pressure ] || exit 1
[ "$(date +%F)" = 2026-11-05 ] || exit 0
mkdir -p var/pressure-reports
RUN="$ROOT/var/pressure-reports/2026-11-05-2100"
# Atomic one-shot guard: never repeat a partially completed test automatically.
mkdir "$RUN" 2>/dev/null || exit 0
exec >"$RUN/run.log" 2>&1
started=0
finish() {
  rc=$?
  trap - EXIT
  rm -f "$RUN/tokens.txt"
  stop_result='未启动测试实例'
  if [ "$started" = 1 ]; then
    if sh scripts/pressure.sh stop; then stop_result='测试实例已停止'; else stop_result='停止失败，请人工检查测试实例'; fi
  fi
  python3 - "$RUN" "$rc" "$stop_result" <<'PY'
import json,sys
from pathlib import Path
from datetime import datetime
p=Path(sys.argv[1]); summary=p/'results/summary.json'
lines=['# SmartTITU 夜间压力测试报告','', '完成时间：'+datetime.now().isoformat(timespec='seconds'),
       '','执行退出码：'+sys.argv[2], '',sys.argv[3], '',
       '计划包含每企业20条/分钟、21次限流边界，以及5/10/20/50/100并发。保护触发后未执行的阶段不能视为通过；单轮不证明长期容量。',
       '测试与演示共用模型和数据库，未修改检索阈值或限流。','']
if summary.exists():
    for r in json.loads(summary.read_text()):
        lines += ['## '+r.get('phase', '并发 '+str(r['concurrency'])), '',
          f"请求数：{r['requests']}；正常回答：{r['answered']}；提前停止：{r['stopped_early']}",
          f"正常回答首字P95：{r['answered_ttft_p95_s']} 秒；总耗时P95：{r['answered_total_p95_s']} 秒。",
          '结果分布：'+json.dumps(r['outcomes'],ensure_ascii=False), '客户端观察到的最高在途请求：'+str(r.get('observed_peak_client_requests')), '限流边界是否通过：'+str(r.get('quota_boundary_pass','不适用')), '']
    lines += ['状态answered不代表答案内容一定正确；429代表企业限流，不能据此判断模型上限。', '']
else:
    lines += ['测试没有生成汇总，可能在启动、凭证或请求阶段失败。请查看同目录 run.log。','']
lines += ['明细：results/requests.jsonl；汇总：results/summary.json；完整执行日志：run.log。',
          '请求编号可用于关联服务日志。报告未记录凭证。']
(p/'报告.md').write_text('\n'.join(lines)+'\n')
PY
  exit "$rc"
}
trap finish EXIT
printf '开始时间：%s\n' "$(date '+%F %T %Z')"
# Do not claim ownership or stop an already running instance/occupied port.
python3 - <<'PY'
import socket
with socket.socket() as s:s.bind(('127.0.0.1',18200))
PY
started=1
sh scripts/pressure.sh start
sh scripts/pressure.sh check
umask 077
docker compose -p ai_customer_pressure -f compose.pressure.yaml exec -T assistant python - <<'PYTOK' > "$RUN/tokens.txt"
import uuid
from app.core import Settings,issue_token
config=Settings(); prefix='pressure-'+uuid.uuid4().hex
for i in range(102):print(issue_token(config.secret,prefix+'-'+str(i),'tester',7200))
PYTOK
python3 pressure_test/night_suite.py --base-url http://127.0.0.1:18200 \
  --tokens-file "$RUN/tokens.txt" --output "$RUN/results"
