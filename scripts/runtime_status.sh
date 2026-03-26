#!/usr/bin/env bash
# =============================================================================
# runtime_status.sh — One-shot runtime health check
# =============================================================================
# Usage: bash scripts/runtime_status.sh
# =============================================================================

REPO="/Users/jimmymalhan/Documents/local-agent-runtime"
HEALTH="$REPO/local-agents/reports/health.json"
LOGS="$REPO/local-agents/logs"

echo ""
echo "══════════════════════════════════════════"
echo "  Agent Runtime Status"
echo "══════════════════════════════════════════"

# Processes
LOOP_PID=$(pgrep -f "orchestrator/main.py" 2>/dev/null | head -1 || true)
RESEARCHER_PID=$(pgrep -f "research_loop.py" 2>/dev/null | head -1 || true)
WATCHDOG_CRON=$(crontab -l 2>/dev/null | grep "agent_watchdog" | head -1 || true)

[[ -n "$LOOP_PID" ]]        && echo "  ✓ Agent loop        running (pid $LOOP_PID)" \
                             || echo "  ✗ Agent loop        STOPPED"
[[ -n "$RESEARCHER_PID" ]]  && echo "  ✓ Researcher        running (pid $RESEARCHER_PID)" \
                             || echo "  ✗ Researcher        STOPPED"
[[ -n "$WATCHDOG_CRON" ]]   && echo "  ✓ Watchdog cron     active (every 5 min)" \
                             || echo "  ✗ Watchdog cron     NOT SCHEDULED"

# Stop file
[[ -f "$REPO/local-agents/.stop" ]] && echo "  ⚠ .stop file present — all auto-starts PAUSED"

echo ""

# Last watchdog check
if [[ -f "$LOGS/watchdog.log" ]]; then
  echo "  Last watchdog:  $(tail -1 $LOGS/watchdog.log)"
fi

# Last 3 events
if [[ -f "$LOGS/watchdog.jsonl" ]]; then
  echo ""
  echo "  Recent events:"
  tail -3 "$LOGS/watchdog.jsonl" | python3 -c "
import sys, json
for line in sys.stdin:
    try:
        d = json.loads(line)
        print(f\"    {d['ts'][:19]}  {d['event']:<22} {d.get('detail','')}\" )
    except: pass
"
fi

# Version progress
LATEST_V=$(ls "$REPO/local-agents/reports"/v*_compare.jsonl 2>/dev/null | tail -1 | grep -o 'v[0-9]*' | tail -1 || echo "none")
echo ""
echo "  Latest version:  $LATEST_V"

echo ""
echo "  Commands:"
echo "    bash scripts/stop_loop.sh           → pause agents"
echo "    rm local-agents/.stop               → resume agents"
echo "    tail -f local-agents/logs/loop.log  → live agent output"
echo ""
echo "══════════════════════════════════════════"
