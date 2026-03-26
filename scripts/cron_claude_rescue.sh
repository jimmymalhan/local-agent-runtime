#!/usr/bin/env bash
# cron_claude_rescue.sh — Fires Claude rescue when local agents are blocked
# Cron: */5 * * * * /path/to/scripts/cron_claude_rescue.sh
# Budget: 10% of tasks — Claude upgrades agent prompts only (never direct task execution)
# Trigger: local agent writes reports/rescue_needed.json after 3 failures

set -euo pipefail

REPO="/Users/jimmymalhan/Documents/local-agent-runtime"
RESCUE_LOG="$REPO/local-agents/reports/claude_rescue_upgrades.jsonl"
TRIGGER_FILE="$REPO/local-agents/reports/rescue_needed.json"
LOG="$REPO/local-agents/logs/cron_rescue.log"

mkdir -p "$(dirname "$LOG")"
echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] cron_rescue: checking..." >> "$LOG"

# No trigger = nothing to do
if [[ ! -f "$TRIGGER_FILE" ]]; then
    exit 0
fi

# Parse trigger
TASK_ID=$(python3 -c "import json; d=json.load(open('$TRIGGER_FILE')); print(d.get('task_id','unknown'))")
TASK_TITLE=$(python3 -c "import json; d=json.load(open('$TRIGGER_FILE')); print(d.get('title','unknown'))")
FAILURES=$(python3 -c "import json; d=json.load(open('$TRIGGER_FILE')); print(d.get('failures',0))")

# Enforce 10% budget cap
RESCUE_USED=$(python3 -c "
import json
count = 0
try:
    for line in open('$RESCUE_LOG'):
        d = json.loads(line)
        if d.get('upgrade_applied'):
            count += 1
except: pass
print(count)
" 2>/dev/null || echo 0)

TOTAL=$(wc -l < "$RESCUE_LOG" 2>/dev/null || echo 0)
BUDGET_PCT=$(python3 -c "print(round($RESCUE_USED / max($TOTAL, 1) * 100, 1))" 2>/dev/null || echo 0)

echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] rescue: task=$TASK_ID failures=$FAILURES budget=${BUDGET_PCT}%" >> "$LOG"

if python3 -c "import sys; sys.exit(0 if float('$BUDGET_PCT') < 10 else 1)" 2>/dev/null; then
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] RESCUE FIRING: '$TASK_TITLE'" >> "$LOG"
    cd "$REPO"
    python3 local-agents/upgrade_agent.py \
        --task-id "$TASK_ID" \
        --task-title "$TASK_TITLE" \
        --failures "$FAILURES" \
        --mode upgrade-prompt-only >> "$LOG" 2>&1 && rm -f "$TRIGGER_FILE"
else
    echo "[$(date -u +%Y-%m-%dT%H:%M:%SZ)] SKIP: budget ${BUDGET_PCT}% >= 10%" >> "$LOG"
fi
