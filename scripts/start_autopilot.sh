#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
TARGET_REPO=${1:-${LOCAL_AGENT_TARGET_REPO:-$REPO_ROOT}}
PID_PATH="$REPO_ROOT/state/autopilot.pid"
LOG_PATH="$REPO_ROOT/logs/autopilot.log"

mkdir -p "$REPO_ROOT/state" "$REPO_ROOT/logs"

if [ -f "$PID_PATH" ]; then
  EXISTING_PID=$(cat "$PID_PATH" 2>/dev/null || true)
  if [ -n "${EXISTING_PID:-}" ] && kill -0 "$EXISTING_PID" 2>/dev/null; then
    echo "Autopilot already running: pid=$EXISTING_PID log=$LOG_PATH target=$TARGET_REPO"
    exit 0
  fi
  rm -f "$PID_PATH"
fi

PID=$(python3 - "$SCRIPT_DIR" "$TARGET_REPO" "$LOG_PATH" <<'PY'
import os
import pathlib
import subprocess
import sys

script_dir = pathlib.Path(sys.argv[1])
target_repo = sys.argv[2]
log_path = pathlib.Path(sys.argv[3])
env = os.environ.copy()
env["LOCAL_AGENT_TARGET_REPO"] = target_repo
env.setdefault("LOCAL_AGENT_MODE", "exhaustive")
env.setdefault("LOCAL_AGENT_MAX_CPU_PERCENT", "70")
env.setdefault("LOCAL_AGENT_MAX_MEMORY_PERCENT", "70")
env["LOCAL_AGENT_AUTO_REVIEW"] = "1"
with log_path.open("ab") as handle:
    proc = subprocess.Popen(
        ["bash", str(script_dir / "run_auto_upgrade_loop.sh")],
        stdin=subprocess.DEVNULL,
        stdout=handle,
        stderr=subprocess.STDOUT,
        start_new_session=True,
        env=env,
    )
print(proc.pid)
PY
)

echo "$PID" > "$PID_PATH"
echo "Autopilot started: pid=$PID log=$LOG_PATH target=$TARGET_REPO"
