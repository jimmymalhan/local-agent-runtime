#!/usr/bin/env bash
# Cron rescue: fires every 5 min, writes lesson to memory/ (0 API tokens).
# Cron: */5 * * * * /Users/jimmymalhan/Documents/local-agent-runtime/scripts/cron_claude_rescue.sh
REPO="/Users/jimmymalhan/Documents/local-agent-runtime"
TRIGGER="$REPO/local-agents/reports/rescue_needed.json"
LOG="$REPO/local-agents/logs/cron_rescue.log"
MEMORY="$REPO/local-agents/memory/rescue_lessons.jsonl"
RESCUE_LOG="$REPO/local-agents/reports/claude_rescue_upgrades.jsonl"
mkdir -p "$(dirname "$LOG")" "$(dirname "$MEMORY")"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] check" >> "$LOG"
[[ -f "$TRIGGER" ]] || exit 0
TASK=$(python3 -c "import json; d=json.load(open('$TRIGGER')); print(d.get('task_id','?'))" 2>/dev/null)
FAIL=$(python3 -c "import json; d=json.load(open('$TRIGGER')); print(d.get('failure_pattern','?'))" 2>/dev/null)
CAT=$(python3 -c "import json; d=json.load(open('$TRIGGER')); print(d.get('category','general'))" 2>/dev/null)
BUDGET=$(python3 -c "
import json
try:
    ls=[json.loads(l) for l in open('$RESCUE_LOG') if l.strip()]
    print(round(sum(1 for l in ls if l.get('upgrade_applied'))/max(len(ls),1)*100,1))
except: print(0)
" 2>/dev/null || echo 0)
python3 -c "import sys; sys.exit(0 if float('$BUDGET')<10 else 1)" || { echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] SKIP: budget ${BUDGET}%" >> "$LOG"; exit 0; }
python3 -c "
import json,os; from datetime import datetime,timezone
l={'ts':datetime.now(timezone.utc).isoformat(),'task_id':'$TASK','failure_pattern':'$FAIL',
   'category':'$CAT','lesson':f'[$CAT] $FAIL: check completeness, signatures, output.','tokens':0,'upgrade_applied':True}
os.makedirs(os.path.dirname('$MEMORY'),exist_ok=True)
open('$MEMORY','a').write(json.dumps(l)+chr(10))
open('$RESCUE_LOG','a').write(json.dumps(l)+chr(10))
print(l['lesson'])
" >> "$LOG" 2>&1
rm -f "$TRIGGER"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] done" >> "$LOG"
