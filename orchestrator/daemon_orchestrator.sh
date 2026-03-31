#!/bin/bash
# daemon_orchestrator.sh - Persistent orchestrator with auto-restart

BASE_DIR="/Users/jimmymalhan/Documents/local-agent-runtime"
LOG_FILE="$BASE_DIR/local-agents/logs/orchestrator_daemon.log"

# Ensure log directory exists
mkdir -p "$(dirname "$LOG_FILE")"

# Function to restart orchestrator
restart_orchestrator() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] Starting orchestrator --auto 1" >> "$LOG_FILE"
    nohup python3 "$BASE_DIR/orchestrator/main.py" --auto 1 >> "$LOG_FILE" 2>&1 &
    echo $! > "$BASE_DIR/.orchestrator_pid"
}

# Infinite loop with health check
while true; do
    # Check if orchestrator is running
    if [ ! -f "$BASE_DIR/.orchestrator_pid" ] || ! kill -0 $(cat "$BASE_DIR/.orchestrator_pid" 2>/dev/null) 2>/dev/null; then
        restart_orchestrator
    fi
    
    # Check every 30 seconds
    sleep 30
done
