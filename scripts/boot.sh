#!/usr/bin/env bash
# boot.sh — Single ordered boot script for the Nexus runtime.
#
# Starts: watchdog → live_state_updater → dashboard/server → continuous_loop
# Each component is idempotent (won't double-start if already running).
#
# Usage:
#   bash scripts/boot.sh              # start all components
#   bash scripts/boot.sh --status     # show what's running
#   bash scripts/boot.sh --stop       # stop all components

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOCAL_AGENTS="$REPO_ROOT/local-agents"
LOG_DIR="/tmp/nexus-logs"
mkdir -p "$LOG_DIR"

is_running() {
    pgrep -f "$1" > /dev/null 2>&1
}

start_component() {
    local name="$1"
    local pattern="$2"
    local cmd="$3"
    local logfile="$LOG_DIR/${name}.log"

    if is_running "$pattern"; then
        echo "  [ok]  $name already running"
    else
        echo "  [start] $name"
        nohup bash -c "cd $LOCAL_AGENTS && $cmd" >> "$logfile" 2>&1 &
        sleep 1
        if is_running "$pattern"; then
            echo "  [up]  $name started (log: $logfile)"
        else
            echo "  [err] $name failed to start — check $logfile"
        fi
    fi
}

cmd_start() {
    echo "=== Nexus Boot ==="

    # 1. Watchdog daemon (monitors all other components)
    start_component "watchdog" \
        "watchdog_daemon.py" \
        "python3 $REPO_ROOT/scripts/watchdog_daemon.py"

    # 2. Live state updater (writes dashboard/state.json every 2s)
    start_component "live_state_updater" \
        "live_state_updater.py" \
        "python3 $LOCAL_AGENTS/dashboard/live_state_updater.py"

    # 3. Dashboard server (web UI on port 3001)
    start_component "dashboard_server" \
        "dashboard/server.py" \
        "python3 $LOCAL_AGENTS/dashboard/server.py"

    # 4. Continuous loop (task execution engine)
    start_component "continuous_loop" \
        "orchestrator.continuous_loop" \
        "python3 -m orchestrator.continuous_loop --forever --project all"

    echo ""
    echo "Runtime started. Dashboard: http://localhost:3001"
    echo "Logs: $LOG_DIR/"
    echo "Stop: bash $REPO_ROOT/scripts/stop_loop.sh  or  bash $0 --stop"
}

cmd_status() {
    echo "=== Nexus Runtime Status ==="
    for name in "watchdog_daemon.py" "live_state_updater.py" "dashboard/server.py" "continuous_loop"; do
        if is_running "$name"; then
            pid=$(pgrep -f "$name" | head -1)
            echo "  [up]   $name  (pid $pid)"
        else
            echo "  [down] $name"
        fi
    done

    # Show dashboard state freshness
    state_file="$LOCAL_AGENTS/dashboard/state.json"
    if [ -f "$state_file" ]; then
        ts=$(python3 -c "
import json, sys
from datetime import datetime, timezone
try:
    s = json.load(open('$state_file'))
    ts = s.get('ts','')
    if ts:
        dt = datetime.fromisoformat(ts)
        if dt.tzinfo is None: dt = dt.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - dt).total_seconds()
        print(f'state.json age: {age:.0f}s')
    else:
        print('state.json: no ts')
except Exception as e:
    print(f'state.json: error ({e})')
" 2>/dev/null)
        echo "  $ts"
    fi
}

cmd_stop() {
    echo "=== Stopping Nexus Runtime ==="
    for pattern in "continuous_loop" "dashboard/server.py" "live_state_updater.py" "watchdog_daemon.py"; do
        if is_running "$pattern"; then
            pkill -f "$pattern" && echo "  [stopped] $pattern" || true
        else
            echo "  [skip]    $pattern (not running)"
        fi
    done
}

case "${1:-start}" in
    --status|status) cmd_status ;;
    --stop|stop)     cmd_stop ;;
    *)               cmd_start ;;
esac
