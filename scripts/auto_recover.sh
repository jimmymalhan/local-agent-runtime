#!/bin/bash
# auto_recover.sh — Keep agent system alive and commit progress
# ===============================================================
# This script runs every 2 minutes (via cron or watchdog).
# It ensures:
#   1. All agent processes are running (restart if dead)
#   2. Any untracked files are committed
#   3. A heartbeat is written so external systems know we're alive
#   4. Dashboard state is valid
#
# Purpose: Make agent progress visible and keep the system running
# without external intervention.

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
STATE_DIR="$REPO_ROOT/state"
HEARTBEAT_FILE="$STATE_DIR/watchdog_heartbeat.json"
FAILURES_FILE="$STATE_DIR/failures.json"

# Ensure state directory exists
mkdir -p "$STATE_DIR"

# ============================================================================
# Step 1: Check and restart agent processes
# ============================================================================
check_and_restart_processes() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✓ Checking agent processes..."

    # List of critical processes to monitor (add more as needed)
    # This is a simple check; replace with actual process names in your setup
    cd "$REPO_ROOT"

    # unified_daemon.py — core scheduler (all task execution, branch cycles, health checks)
    if ! pgrep -f "unified_daemon.py" > /dev/null 2>&1; then
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] ⚠️  unified_daemon.py DOWN — restarting..."
        nohup python3 orchestrator/unified_daemon.py >> reports/unified_daemon.log 2>&1 &
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✓ Restarted unified_daemon.py (PID $!)"
    else
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✓ unified_daemon.py running"
    fi

    # dashboard/server.py — FastAPI dashboard + chat backend
    if ! pgrep -f "dashboard/server.py" > /dev/null 2>&1; then
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] ⚠️  dashboard/server.py DOWN — restarting..."
        nohup python3 dashboard/server.py --port 3001 >> reports/dashboard.log 2>&1 &
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✓ Restarted dashboard/server.py (PID $!)"
    else
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✓ dashboard/server.py running"
    fi
}

# ============================================================================
# Step 2: Auto-commit untracked work
# ============================================================================
auto_commit_untracked() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✓ Checking for untracked files..."

    cd "$REPO_ROOT"

    # Get count of untracked files
    local untracked_count=$(git ls-files --others --exclude-standard 2>/dev/null | wc -l)

    if [ "$untracked_count" -gt 0 ]; then
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] Found $untracked_count untracked files, committing..."

        # Add all untracked files
        git add -A 2>/dev/null || true

        # Commit with timestamp message
        local timestamp=$(date +'%Y-%m-%d %H:%M:%S')
        git commit -m "auto: commit untracked progress at $timestamp" \
            --author="LocalAgent <noreply@local>" \
            2>/dev/null || true

        echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✓ Committed untracked files"
    else
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✓ No untracked files to commit"
    fi
}

# ============================================================================
# Step 3: Write heartbeat
# ============================================================================
write_heartbeat() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✓ Writing heartbeat..."

    local timestamp=$(date -u +'%Y-%m-%dT%H:%M:%SZ')
    local hostname=$(hostname)
    local uptime=$(uptime -p 2>/dev/null || echo "unknown")

    # Get basic system stats
    local cpu_pct=$(ps aux | awk '{sum += $3} END {print int(sum)}' 2>/dev/null || echo "0")
    local mem_pct=$(ps aux | awk '{sum += $4} END {print int(sum)}' 2>/dev/null || echo "0")

    # Build heartbeat JSON
    cat > "$HEARTBEAT_FILE" <<EOF
{
  "timestamp": "$timestamp",
  "hostname": "$hostname",
  "uptime": "$uptime",
  "status": "alive",
  "system": {
    "cpu_pct": $cpu_pct,
    "mem_pct": $mem_pct
  },
  "last_commit": "$(cd "$REPO_ROOT" && git log -1 --format=%H 2>/dev/null || echo "unknown")",
  "untracked_files": $(cd "$REPO_ROOT" && git ls-files --others --exclude-standard 2>/dev/null | wc -l)
}
EOF

    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✓ Heartbeat written to $HEARTBEAT_FILE"
}

# ============================================================================
# Step 4: Validate dashboard state
# ============================================================================
validate_dashboard_state() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✓ Validating dashboard state..."

    local state_file="$REPO_ROOT/dashboard/state.json"

    if [ ! -f "$state_file" ]; then
        echo "[$(date +'%Y-%m-%d %H:%M:%S')] ⚠️  Dashboard state file not found, initializing..."
        python3 -c "
import json
from pathlib import Path
state = {
    'ts': '$(date -u +%Y-%m-%dT%H:%M:%SZ)',
    'version': {'current': 0, 'total': 0, 'pct_complete': 0.0, 'label': ''},
    'agents': {},
    'task_queue': {'total': 0, 'completed': 0, 'in_progress': 0, 'failed': 0, 'pending': 0},
    'benchmark_scores': {},
    'token_usage': {'claude_tokens': 0, 'local_tokens': 0, 'budget_pct': 0.0, 'warning': False, 'hard_limit_hit': False},
    'hardware': {'cpu_pct': 0.0, 'ram_pct': 0.0, 'disk_pct': 0.0, 'gpu_pct': None, 'alert_level': 'ok'},
    'failures': [],
    'research_feed': [],
    'version_changelog': {}
}
with open('$state_file', 'w') as f:
    json.dump(state, f, indent=2)
" || true
    fi
}

# ============================================================================
# Main: Run all checks
# ============================================================================
main() {
    echo "========================================"
    echo "auto_recover.sh — Agent System Watchdog"
    echo "========================================"

    check_and_restart_processes
    auto_commit_untracked
    write_heartbeat
    validate_dashboard_state

    echo "========================================"
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] ✓ Recovery check complete"
    echo "========================================"
}

main "$@"
