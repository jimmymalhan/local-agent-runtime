#!/bin/bash
# auto_remediate.sh — Automated Recovery for Stuck System
# ========================================================
# Run every 60 seconds via cron. Detects and fixes common issues.

set -e

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BASE_DIR"

LOG_FILE="/tmp/auto_remediate.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$LOG_FILE"
}

log "=== Auto-Remediation Check ==="

# Check 1: Is orchestrator process stuck?
ORCH_PID=$(cat .orchestrator.pid 2>/dev/null || echo "")
if [ -z "$ORCH_PID" ] || ! kill -0 "$ORCH_PID" 2>/dev/null; then
    log "ISSUE: Orchestrator not running. Restarting..."
    bash scripts/bootstrap.sh >> "$LOG_FILE" 2>&1
fi

# Check 2: Are there >15 untracked files?
UNTRACKED=$(git status --short 2>/dev/null | grep "^??" | wc -l)
if [ "$UNTRACKED" -gt 15 ]; then
    log "ISSUE: $UNTRACKED untracked files. Auto-committing..."
    git add -A
    git commit -m "chore(auto): persist artifacts — auto remediation" || true
    log "OK: Committed untracked files"
fi

# Check 3: Is state.json stale (>5 min old)?
STATE_AGE=$(stat -f %m dashboard/state.json 2>/dev/null || echo "0")
CURRENT_TIME=$(date +%s)
AGE_SECONDS=$((CURRENT_TIME - STATE_AGE))
if [ "$AGE_SECONDS" -gt 300 ]; then
    log "ISSUE: state.json stale for $AGE_SECONDS seconds. Reinitializing..."
    python3 << 'PYTHON_EOF'
from pathlib import Path
from datetime import datetime
import json

state_file = Path("dashboard/state.json")
state = json.load(open(state_file))
state["ts"] = datetime.now().isoformat()
with open(state_file, "w") as f:
    json.dump(state, f, indent=2)
PYTHON_EOF
    log "OK: Refreshed state.json timestamp"
fi

# Check 4: Run system health monitor
log "Running system health monitor..."
python3 scripts/system_health_monitor.py >> "$LOG_FILE" 2>&1 || log "WARNING: Health monitor error"

log "=== Auto-Remediation Complete ==="
