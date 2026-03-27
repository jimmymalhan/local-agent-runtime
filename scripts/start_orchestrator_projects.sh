#!/bin/bash
"""
start_orchestrator_projects.sh — Start orchestrator to execute projects.json tasks

This script ensures the orchestrator runs and picks up pending tasks from projects.json
It checks if orchestrator is already running, and if not, starts it with proper logging.
"""

set -e

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$BASE_DIR/logs"
ORCHESTRATOR_LOG="$LOG_DIR/orchestrator_projects.log"

mkdir -p "$LOG_DIR"

echo "[$(date)] Starting orchestrator for projects.json task execution..." >> "$ORCHESTRATOR_LOG"

# Check if orchestrator is already running
if pgrep -f "python.*orchestrator/main.py" > /dev/null; then
    echo "[$(date)] ✅ Orchestrator already running" | tee -a "$ORCHESTRATOR_LOG"
    exit 0
fi

echo "[$(date)] Orchestrator not running, starting..." >> "$ORCHESTRATOR_LOG"

# Start orchestrator in background with projects.json integration
cd "$BASE_DIR"
nohup python3 orchestrator/main.py --quick 10 >> "$ORCHESTRATOR_LOG" 2>&1 &
ORCHESTRATOR_PID=$!

echo "[$(date)] ✅ Orchestrator started (PID: $ORCHESTRATOR_PID)" | tee -a "$ORCHESTRATOR_LOG"
echo "[$(date)] Log: $ORCHESTRATOR_LOG" | tee -a "$ORCHESTRATOR_LOG"

# Wait a moment for it to start
sleep 2

# Verify it's running
if pgrep -f "python.*orchestrator/main.py" > /dev/null; then
    echo "[$(date)] ✅ Orchestrator verified running" | tee -a "$ORCHESTRATOR_LOG"
else
    echo "[$(date)] ❌ Failed to start orchestrator" | tee -a "$ORCHESTRATOR_LOG"
    exit 1
fi
