#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
PID_PATH="$REPO_ROOT/state/autopilot.pid"

if [ ! -f "$PID_PATH" ]; then
  echo "Autopilot is not running."
  exit 0
fi

PID=$(cat "$PID_PATH" 2>/dev/null || true)
if [ -n "${PID:-}" ] && kill -0 "$PID" 2>/dev/null; then
  kill "$PID" 2>/dev/null || true
  sleep 1
  if kill -0 "$PID" 2>/dev/null; then
    kill -9 "$PID" 2>/dev/null || true
  fi
fi

rm -f "$PID_PATH"
echo "Autopilot stopped."
