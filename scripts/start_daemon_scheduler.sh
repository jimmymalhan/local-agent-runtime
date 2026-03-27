#!/bin/bash
# scripts/start_daemon_scheduler.sh
# Starts the daemon scheduler (replaces cron entirely)
#
# Usage:
#   ./scripts/start_daemon_scheduler.sh              # Start in background
#   bash ./scripts/start_daemon_scheduler.sh --fg    # Run in foreground (debug)
#
# To run on boot (macOS):
#   launchctl load ~/Library/LaunchAgents/com.local-agent-runtime.plist

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_FILE="$REPO_DIR/reports/daemon_scheduler.log"
PID_FILE="$REPO_DIR/.daemon_scheduler.pid"

cd "$REPO_DIR"

# Create reports dir if needed
mkdir -p reports

echo "🚀 Starting daemon scheduler..."
echo "   Logs: $LOG_FILE"
echo "   PID file: $PID_FILE"
echo ""

if [[ "$1" == "--fg" || "$1" == "--foreground" ]]; then
    # Foreground mode (debug)
    echo "Running in foreground (Ctrl+C to stop)..."
    python3 orchestrator/daemon_scheduler.py --auto
else
    # Background mode (daemon)
    nohup python3 orchestrator/daemon_scheduler.py --auto > "$LOG_FILE" 2>&1 &
    DAEMON_PID=$!
    echo $DAEMON_PID > "$PID_FILE"
    echo "✅ Daemon started (PID: $DAEMON_PID)"
    echo "   View logs: tail -f $LOG_FILE"
    echo "   Stop daemon: kill $DAEMON_PID (or delete $PID_FILE)"
fi
