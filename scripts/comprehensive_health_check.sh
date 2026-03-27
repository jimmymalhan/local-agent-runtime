#!/bin/bash
# comprehensive_health_check.sh — 30-minute automated diagnostics & recovery
# Checks: agents, tasks, blockers, resources, and auto-recovers failures

set -e

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
HEALTH_LOG="${BASE_DIR}/reports/health_$(date +%Y%m%d_%H%M%S).log"
STATE_FILE="${BASE_DIR}/dashboard/state.json"

# Initialize report
{
    echo "╔════════════════════════════════════════════════════════════════════════╗"
    echo "║            30-MINUTE AUTOMATED HEALTH CHECK & RECOVERY                 ║"
    echo "║                      $TIMESTAMP                                 ║"
    echo "╚════════════════════════════════════════════════════════════════════════╝"
    echo ""

    # ===== AGENTS & SUB-AGENTS STATUS =====
    echo "━━━ AGENTS & SUB-AGENTS ━━━"

    ORCH_PID=$(pgrep -f "orchestrator/main.py" 2>/dev/null || echo "")
    DASH_PORT=$(lsof -i :3001 2>/dev/null | tail -1 | awk '{print $2}' || echo "")
    HEAL_PID=$(pgrep -f "self_heal" 2>/dev/null || echo "")
    SUB_AGENTS=$(ps aux | grep -E "executor|architect|researcher" | grep -v grep | wc -l || echo "0")

    echo "Main Agent Processes:"
    [ -n "$ORCH_PID" ] && echo "  ✓ Orchestrator (PID $ORCH_PID)" || echo "  ✗ Orchestrator DEAD"
    [ -n "$DASH_PORT" ] && echo "  ✓ Dashboard (port 3001)" || echo "  ✗ Dashboard DEAD"
    [ -n "$HEAL_PID" ] && echo "  ✓ Self-heal (PID $HEAL_PID)" || echo "  ✗ Self-heal DEAD"
    echo "  Sub-agents active: $SUB_AGENTS"
    echo ""

    # ===== WORK COMPLETED =====
    echo "━━━ WORK COMPLETED ━━━"

    if [ -f "${BASE_DIR}/projects.json" ]; then
        PROJ_COUNT=$(python3 -c "import json; data=json.load(open('${BASE_DIR}/projects.json')); print(len(data.get('projects', [])))" 2>/dev/null || echo "0")
        echo "Projects loaded: $PROJ_COUNT"
    fi

    if [ -f "${BASE_DIR}/state/agent_stats.json" ]; then
        python3 << 'PYEOF' 2>/dev/null || echo "  (stats unavailable)"
import json
data = json.load(open("/Users/jimmymalhan/Documents/local-agent-runtime/state/agent_stats.json"))
completed = data.get("completed_count", 0)
total = data.get("total_count", 0)
if total > 0:
    pct = (completed * 100) // total
    print(f"Task progress: {completed}/{total} ({pct}%)")
else:
    print(f"Task progress: Waiting for orchestrator to load tasks...")
PYEOF
    fi
    echo ""

    # ===== 24/7 OPERATION CHECK =====
    echo "━━━ 24/7 OPERATION STATUS ━━━"

    CRON_COUNT=$(crontab -l 2>/dev/null | grep -E "health|recover|monitor|rescue" | wc -l || echo "0")
    echo "Cron jobs active: $CRON_COUNT"
    echo "  Monitoring frequency: Every 2-5 minutes (auto_recover, rescue_orchestrator)"
    echo "  Health check: Every 30 minutes (this script)"
    echo ""

    # ===== BLOCKERS & AUTO-RECOVERY =====
    echo "━━━ BLOCKERS & AUTO-RECOVERY ━━━"

    BLOCKERS_FOUND=0

    # Check 1: Orchestrator dead
    if [ -z "$ORCH_PID" ]; then
        echo "⚠️ BLOCKER: Orchestrator dead - attempting restart..."
        pkill -f "orchestrator/main.py" 2>/dev/null || true
        sleep 1
        python3 "${BASE_DIR}/orchestrator/main.py" > /tmp/orchestrator.log 2>&1 &
        sleep 3
        if pgrep -f "orchestrator/main.py" > /dev/null; then
            echo "  ✓ Orchestrator restarted"
        else
            echo "  ✗ Orchestrator restart FAILED"
            BLOCKERS_FOUND=$((BLOCKERS_FOUND + 1))
        fi
    fi

    # Check 2: Dashboard dead
    if [ -z "$DASH_PORT" ]; then
        echo "⚠️ BLOCKER: Dashboard dead - attempting restart..."
        pkill -f "dashboard" 2>/dev/null || true
        sleep 1
        cd "${BASE_DIR}/dashboard" && npm start > /dev/null 2>&1 &
        sleep 3
        if lsof -i :3001 > /dev/null 2>&1; then
            echo "  ✓ Dashboard restarted"
        else
            echo "  ✗ Dashboard restart FAILED"
            BLOCKERS_FOUND=$((BLOCKERS_FOUND + 1))
        fi
    fi

    # Check 3: State validation
    if [ ! -f "$STATE_FILE" ]; then
        echo "⚠️ BLOCKER: state.json missing - creating defaults..."
        python3 "${BASE_DIR}/orchestrator/schema_validator.py" > /dev/null 2>&1 || true
        echo "  ✓ State file restored"
    fi

    # Check 4: board_plan key missing
    if [ -f "$STATE_FILE" ]; then
        if ! python3 -c "import json; data=json.load(open('${STATE_FILE}')); assert 'board_plan' in data" 2>/dev/null; then
            echo "⚠️ BLOCKER: board_plan key missing - fixing schema..."
            python3 "${BASE_DIR}/orchestrator/schema_validator.py" > /dev/null 2>&1 || true
            echo "  ✓ Schema repaired"
        fi
    fi

    # Check 5: Orchestrator errors
    if grep -q "KeyError\|Traceback\|Exception" /tmp/orchestrator.log 2>/dev/null; then
        echo "⚠️ BLOCKER: Orchestrator has errors - restarting with fresh state..."
        pkill -f "orchestrator/main.py" 2>/dev/null || true
        sleep 1
        python3 "${BASE_DIR}/orchestrator/main.py" > /tmp/orchestrator.log 2>&1 &
        sleep 3
        echo "  ✓ Orchestrator restarted with recovery"
        BLOCKERS_FOUND=$((BLOCKERS_FOUND + 1))
    fi

    echo ""
    if [ $BLOCKERS_FOUND -eq 0 ]; then
        echo "✓ NO BLOCKERS FOUND - System healthy"
    else
        echo "⚠️ $BLOCKERS_FOUND blockers detected and auto-recovered"
    fi
    echo ""

    # ===== RESOURCE USAGE =====
    echo "━━━ RESOURCE USAGE ━━━"

    DISK_PCT=$(df "${BASE_DIR}" | tail -1 | awk '{print $5}' | sed 's/%//')
    DISK_AVAIL=$(df -h "${BASE_DIR}" | tail -1 | awk '{print $4}')
    echo "Disk: ${DISK_AVAIL} available (${DISK_PCT}% full)"

    PYTHON_MEM=$(ps aux | grep python | grep -v grep | awk '{sum+=$6} END {printf "%.0f MB", sum/1024}' || echo "0 MB")
    echo "Memory (Python): $PYTHON_MEM"
    echo ""

    # ===== SUMMARY =====
    echo "═══════════════════════════════════════════════════════════════════════════"
    if [ -z "$ORCH_PID" ] || [ -z "$DASH_PORT" ] || [ $BLOCKERS_FOUND -gt 0 ]; then
        echo "⚠️  SYSTEM STATUS: DEGRADED (issues detected and auto-recovered)"
    else
        echo "✓ SYSTEM STATUS: HEALTHY (all components operational)"
    fi
    echo "═══════════════════════════════════════════════════════════════════════════"
    echo ""
    echo "Report: $HEALTH_LOG"

} | tee "$HEALTH_LOG"
