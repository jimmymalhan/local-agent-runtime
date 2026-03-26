#!/usr/bin/env bash
# cron_claude_rescue.sh - 0 API tokens. Writes lesson to memory/. Teach not solve.
# Cron: */5 * * * * /Users/jimmymalhan/Documents/local-agent-runtime/scripts/cron_claude_rescue.sh
REPO="/Users/jimmymalhan/Documents/local-agent-runtime"
TRIGGER="$REPO/local-agents/reports/rescue_needed.json"
RESCUE_LOG="$REPO/local-agents/reports/claude_rescue_upgrades.jsonl"
MEMORY="$REPO/local-agents/memory/rescue_lessons.jsonl"
LOG="$REPO/local-agents/logs/cron_rescue.log"
TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
mkdir -p "$(dirname "$MEMORY")" "$(dirname "$LOG")"
echo "[$TS] check" >> "$LOG"
[[ -f "$TRIGGER" ]] || exit 0
TASK=$(python3 -c "import json; print(json.load(open('$TRIGGER')).get('task_id','?'))" 2>/dev/null)
TITLE=$(python3 -c "import json; print(json.load(open('$TRIGGER')).get('title','?'))" 2>/dev/null)
FAIL=$(python3 -c "import json; print(json.load(open('$TRIGGER')).get('failure_pattern','unknown'))" 2>/dev/null)
CAT=$(python3 -c "import json; print(json.load(open('$TRIGGER')).get('category','general'))" 2>/dev/null)
BUDGET=$(python3 -c "
import json
try:
    lines=[json.loads(l) for l in open('"'"'$RESCUE_LOG'"'"') if l.strip()]
    used=sum(1 for l in lines if l.get('"'"'upgrade_applied'"'"'))
    print(round(used/max(len(lines),1)*100,1))
except: print(0)
" 2>/dev/null || echo 0)
python3 -c "import sys; sys.exit(0 if float('"'"'$BUDGET'"'"')<10 else 1)" 2>/dev/null || {
    echo "[$TS] SKIP: budget ${BUDGET}%" >> "$LOG"; exit 0; }
echo "[$TS] TEACH: $TITLE" >> "$LOG"
python3 -c "
import json,os; from datetime import datetime,timezone
lesson={'ts':datetime.now(timezone.utc).isoformat(),'task_id':'$TASK','title':'$TITLE',
        'failure_pattern':'$FAIL','category':'$CAT','upgrade_applied':True,'tokens':0,
        'lesson':f'[$CAT] Pattern $FAIL: check completeness, signatures, output format.'}
os.makedirs(os.path.dirname('"'"'$MEMORY'"'"'),exist_ok=True)
open('"'"'$MEMORY'"'"','a').write(json.dumps(lesson)+chr(10))
open('"'"'$RESCUE_LOG'"'"','a').write(json.dumps(lesson)+chr(10))
" 2>> "$LOG"
rm -f "$TRIGGER"
echo "[$TS] done" >> "$LOG"
