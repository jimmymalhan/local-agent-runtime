#!/bin/bash
# health_check_action.sh — Run every 30 minutes + take automated action
# =====================================================================
# This script:
# 1. Runs health check
# 2. Detects blockers
# 3. Takes automatic corrective action
# 4. Reports to Claude session if human intervention needed

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

HEALTH_CHECK_OUTPUT="$REPO_DIR/state/health_check_latest.txt"
HEALTH_CHECK_ACTIONS="$REPO_DIR/state/health_check_actions.jsonl"

echo "[HEALTH] Running health check at $(date)"

# Run comprehensive dashboard (generates COMPREHENSIVE_DASHBOARD.json)
echo "[HEALTH] Generating comprehensive dashboard..."
python3 scripts/comprehensive_dashboard.py > /dev/null 2>&1

# Merge comprehensive data into dashboard/state.json (for localhost:3001 frontend)
echo "[HEALTH] Updating dashboard state..."
python3 scripts/update_dashboard_state.py > /dev/null 2>&1

# Run status reporter (generates LIVE_STATUS files)
echo "[HEALTH] Generating live status report..."
python3 scripts/status_reporter.py > /dev/null 2>&1

# Run health check
python3 scripts/health_check.py > "$HEALTH_CHECK_OUTPUT" 2>&1

# Read output
HEALTH_OUTPUT=$(cat "$HEALTH_CHECK_OUTPUT")
echo "$HEALTH_OUTPUT"

# Parse blockers
if grep -q "❌ BLOCKER: Orchestrator not running" "$HEALTH_CHECK_OUTPUT"; then
    echo "[ACTION] ❌ BLOCKER DETECTED: Orchestrator crashed"
    echo "[ACTION] Restarting orchestrator..."

    # Kill any hanging processes
    pkill -f "orchestrator/main.py" || true
    pkill -f "orchestrator.continuous_loop" || true
    sleep 2

    # Start orchestrator
    nohup python3 orchestrator/main.py --auto 5 > "$REPO_DIR/logs/orchestrator.log" 2>&1 &
    ORCH_PID=$!
    echo "$ORCH_PID" > "$REPO_DIR/.agent_pid"

    echo "[ACTION] ✅ Orchestrator restarted (PID: $ORCH_PID)"

    # Log action
    echo "{\"timestamp\": \"$(date -u +%Y-%m-%dT%H:%M:%SZ)\", \"action\": \"restart_orchestrator\", \"pid\": $ORCH_PID}" >> "$HEALTH_CHECK_ACTIONS"
fi

if grep -q "⚠️  WARNING: Dashboard state has issues" "$HEALTH_CHECK_OUTPUT"; then
    echo "[ACTION] ⚠️  WARNING: Dashboard state invalid"

    # Try to restart dashboard
    echo "[ACTION] Restarting dashboard state writer..."
    pkill -f "state_writer" || true
    sleep 1

    # State writer restarts with next dashboard update
    echo "[ACTION] Dashboard will reinitialize on next state write"
fi

if grep -q "⚠️  WARNING: Only.*primary agents loaded" "$HEALTH_CHECK_OUTPUT"; then
    echo "[ACTION] ⚠️  WARNING: Not all agents loaded"
    echo "[ACTION] This may be normal during startup. Monitoring..."
fi

if grep -q "⚠️  WARNING: No sub-agents spawned" "$HEALTH_CHECK_OUTPUT"; then
    echo "[ACTION] ⚠️  WARNING: No sub-agents spawned"
    echo "[ACTION] Sub-agents spawn when parallel tasks are queued. This is normal."
fi

# Check orchestrator again
echo ""
echo "[HEALTH] Final orchestrator status:"
pgrep -f "orchestrator" && echo "✅ Orchestrator running" || echo "❌ Orchestrator NOT running"

echo ""
echo "[HEALTH] Health check complete. Next check in 30 minutes."
echo ""

# Append full report to log
echo "---" >> "$HEALTH_CHECK_ACTIONS"
echo "$(cat "$HEALTH_CHECK_OUTPUT")" >> "$HEALTH_CHECK_ACTIONS"
echo "---" >> "$HEALTH_CHECK_ACTIONS"
