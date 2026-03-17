#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
PID_PATH="$REPO_ROOT/state/autopilot.pid"
LOG_PATH="$REPO_ROOT/logs/autopilot.log"
RUN_LOCK="$REPO_ROOT/state/run.lock"

if [ ! -f "$PID_PATH" ]; then
  echo "Autopilot is not running."
  exit 0
fi

PID=$(cat "$PID_PATH" 2>/dev/null || true)
if [ -z "${PID:-}" ] || ! kill -0 "$PID" 2>/dev/null; then
  rm -f "$PID_PATH"
  echo "Autopilot is not running."
  exit 0
fi

echo "Autopilot running: pid=$PID"
if [ -f "$RUN_LOCK" ]; then
  echo
  echo "Active local run lock:"
  cat "$RUN_LOCK"
fi

if [ -f "$REPO_ROOT/state/progress.json" ]; then
  echo
  python3 "$SCRIPT_DIR/team_status.py" "$REPO_ROOT"
fi

if [ -f "$LOG_PATH" ]; then
  echo
  echo "Latest autopilot log:"
  tail -n 20 "$LOG_PATH"
fi
