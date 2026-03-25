#!/usr/bin/env bash
# launch.sh — Auto-restart dashboard server
# Runs forever. If server crashes, restarts automatically.
# Writes URL to DASHBOARD.txt at root level.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
DASH_TXT="$ROOT_DIR/DASHBOARD.txt"

echo "[DASHBOARD] Starting with auto-restart..."
while true; do
    python3 "$SCRIPT_DIR/server.py" "$@"
    EXIT_CODE=$?
    echo "[DASHBOARD] Server exited (code $EXIT_CODE). Restarting in 3s..."
    echo "Server restarted at $(date)" >> "$DASH_TXT"
    sleep 3
done
