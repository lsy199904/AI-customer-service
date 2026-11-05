#!/bin/sh
set -eu
ROOT=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
cd "$ROOT"
export TZ=Asia/Shanghai
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
       '本次为1、2、5并发，各5次请求的低压力检查，不代表最大容量或长时间稳定性。',
       '测试与演示共用模型和数据库，未修改检索阈值或限流。','']
if summary.exists():
    for r in json.loads(summary.read_text()):
        lines += ['## 并发 '+str(r['concurrency']), '',
          f"请求数：{r['requests']}；正常回答：{r['answered']}；提前停止：{r['stopped_early']}",
          f"正常回答首字P95：{r['answered_ttft_p95_s']} 秒；总耗时P95：{r['answered_total_p95_s']} 秒。",
          '结果分布：'+json.dumps(r['outcomes'],ensure_ascii=False),'']
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
sh scripts/pressure.sh token
python3 pressure_test/load_test.py --base-url http://127.0.0.1:18200 \
  --tokens-file pressure_test/tokens.txt --concurrency 1,2,5 --requests 5 \
  --output "$RUN/results"
