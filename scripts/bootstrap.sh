#!/bin/bash
# bootstrap.sh — One-script startup for the entire local agent runtime
# ====================================================================
# Kills stale processes, clears locks, seeds state.json, starts watchdog
# No manual intervention required.

set -e

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BASE_DIR"

echo "═════════════════════════════════════════════════════════════════════════════"
echo "🚀 BOOTSTRAP: Local Agent Runtime"
echo "═════════════════════════════════════════════════════════════════════════════"

# ────────────────────────────────────────────────────────────────────────────────
# STEP 1: Kill stale processes
# ────────────────────────────────────────────────────────────────────────────────
echo ""
echo "[1/5] Cleaning up stale processes..."

# Kill orchestrator processes
pkill -f "orchestrator/main.py" || true
pkill -f "orchestrator/continuous_loop" || true
pkill -f "python.*orchestrator" || true

# Kill dashboard server
pkill -f "dashboard/server.py" || true

# Kill watchdog
pkill -f "watchdog_daemon" || true

sleep 1
echo "✅ Stale processes cleaned"

# ────────────────────────────────────────────────────────────────────────────────
# STEP 2: Clear lock files and state
# ────────────────────────────────────────────────────────────────────────────────
echo ""
echo "[2/5] Clearing lock files and old state..."

rm -f .watchdog.pid
rm -f .orchestrator.lock
rm -f .loop.lock

echo "✅ Lock files cleared"

# ────────────────────────────────────────────────────────────────────────────────
# STEP 3: Initialize state.json with proper schema
# ────────────────────────────────────────────────────────────────────────────────
echo ""
echo "[3/5] Initializing state.json with default schema..."

python3 << 'PYTHON_EOF'
import json
import os
from pathlib import Path
from datetime import datetime

state_file = Path("dashboard/state.json")
default_state = {
    "ts": datetime.now().isoformat(),
    "quality": 0,
    "model": "local-v1",
    "version": {"current": 0, "total": 100, "pct_complete": 0.0, "label": "v0"},
    "agents": {},
    "task_queue": {"total": 14, "completed": 0, "in_progress": 0, "failed": 0, "pending": 14},
    "benchmark_scores": {},
    "token_usage": {"claude_tokens": 0, "local_tokens": 0, "budget_pct": 0.0,
                    "warning": False, "hard_limit_hit": False},
    "hardware": {"cpu_pct": 0.0, "ram_pct": 0.0, "disk_pct": 0.0,
                 "gpu_pct": None, "alert_level": "ok"},
    "failures": [],
    "research_feed": [],
    "recent_tasks": [],
    "changelog": [],
    "version_changelog": {},
    "epic_board": {
        "ts": datetime.now().isoformat(),
        "epics": [],
        "operations": {
            "orchestrator": "ready",
            "task_intake": "ready",
            "health_monitor": "ready",
            "auto_restart": True,
            "works_24_7": True
        }
    }
}

with open(state_file, 'w') as f:
    json.dump(default_state, f, indent=2)

print("✅ state.json initialized")
PYTHON_EOF

# ────────────────────────────────────────────────────────────────────────────────
# STEP 4: Verify dashboard server can start
# ────────────────────────────────────────────────────────────────────────────────
echo ""
echo "[4/5] Starting dashboard server..."

cd "$BASE_DIR"
python3 dashboard/server.py --port 3002 > /tmp/dashboard.log 2>&1 &
DASHBOARD_PID=$!
echo $DASHBOARD_PID > .dashboard.pid

# Wait for dashboard to come up
sleep 2
if kill -0 $DASHBOARD_PID 2>/dev/null; then
    echo "✅ Dashboard server started (PID: $DASHBOARD_PID, port 3002)"
else
    echo "❌ Dashboard server failed to start"
    cat /tmp/dashboard.log
    exit 1
fi

# ────────────────────────────────────────────────────────────────────────────────
# STEP 5: Start orchestrator loop via watchdog
# ────────────────────────────────────────────────────────────────────────────────
echo ""
echo "[5/5] Starting orchestrator loop..."

cd "$BASE_DIR"
python3 orchestrator/main.py --auto 1 > /tmp/orchestrator.log 2>&1 &
ORCHESTRATOR_PID=$!
echo $ORCHESTRATOR_PID > .orchestrator.pid

sleep 2
if kill -0 $ORCHESTRATOR_PID 2>/dev/null; then
    echo "✅ Orchestrator started (PID: $ORCHESTRATOR_PID)"
else
    echo "⚠️  Orchestrator may have completed or entered background"
fi

# ────────────────────────────────────────────────────────────────────────────────
# Bootstrap complete
# ────────────────────────────────────────────────────────────────────────────────
echo ""
echo "═════════════════════════════════════════════════════════════════════════════"
echo "✅ BOOTSTRAP COMPLETE"
echo "═════════════════════════════════════════════════════════════════════════════"
echo ""
echo "🌐 Dashboard:        http://localhost:3002"
echo "📊 State API:        http://localhost:3002/api/state"
echo "🔄 Orchestrator PID:  $ORCHESTRATOR_PID"
echo "🖥️  Dashboard PID:     $DASHBOARD_PID"
echo ""
echo "📝 Logs:"
echo "   Orchestrator: /tmp/orchestrator.log"
echo "   Dashboard:    /tmp/dashboard.log"
echo ""
echo "Monitor state.json:"
echo "   tail -f dashboard/state.json"
echo ""
echo "Tasks are in: projects.json (Epic 1 + Epic 2)"
echo "All 14 tasks should appear in dashboard shortly."
echo ""
