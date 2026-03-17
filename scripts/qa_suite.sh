#!/bin/bash
set -euo pipefail

TARGET_REPO=${1:-${LOCAL_AGENT_TARGET_REPO:-$PWD}}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
LOG_DIR="$REPO_ROOT/logs"
REPORT_PATH="$LOG_DIR/qa-suite-report.md"
SMOKE_PATH="$LOG_DIR/qa-session-smoke.log"
MODEL_SMOKE_PATH="$LOG_DIR/qa-model-smoke.md"
RUNTIME_JSON="$REPO_ROOT/config/runtime.json"

mkdir -p "$LOG_DIR" "$REPO_ROOT/state"

STATUS="pass"
FAILURES=()
NOTES=()

record_failure() {
  STATUS="fail"
  FAILURES+=("$1")
}

record_note() {
  NOTES+=("$1")
}

wait_for_idle() {
  local timeout=${QA_WAIT_FOR_IDLE_SECONDS:-180}
  local elapsed=0
  local lock="$REPO_ROOT/state/run.lock"
  while [ -f "$lock" ]; do
    if ! python3 - "$lock" <<'PY'
import json
import os
import pathlib
import sys

path = pathlib.Path(sys.argv[1])
try:
    data = json.loads(path.read_text())
except Exception:
    raise SystemExit(1)
pid = int(data.get("pid", 0) or 0)
if not pid:
    raise SystemExit(1)
try:
    os.kill(pid, 0)
except OSError:
    raise SystemExit(1)
raise SystemExit(0)
PY
    then
      rm -f "$lock"
      break
    fi
    if [ "$elapsed" -ge "$timeout" ]; then
      return 1
    fi
    sleep 2
    elapsed=$((elapsed + 2))
  done
  return 0
}

record_note "Target repo: $TARGET_REPO"
record_note "Checkpoint before QA: $(bash "$SCRIPT_DIR/create_checkpoint.sh" "qa-suite" "$TARGET_REPO" | tail -n 1)"

if ! wait_for_idle; then
  record_failure "another local run stayed active longer than ${QA_WAIT_FOR_IDLE_SECONDS:-180}s"
fi

if ! bash "$SCRIPT_DIR/bootstrap_local_runtime.sh" >/dev/null; then
  record_failure "bootstrap_local_runtime.sh failed"
fi

if ! bash -n "$REPO_ROOT/Local" "$SCRIPT_DIR"/*.sh; then
  record_failure "shell syntax validation failed"
else
  record_note "shell syntax validation passed"
fi

if ! python3 -m py_compile "$SCRIPT_DIR"/*.py; then
  record_failure "python compile validation failed"
else
  record_note "python compile validation passed"
fi

if ! python3 "$SCRIPT_DIR/validate_session_policy.py"; then
  record_failure "session policy validation failed"
else
  record_note "session policy validation passed"
fi

if ! python3 - "$RUNTIME_JSON" <<'PY'
import json
import sys
cfg = json.load(open(sys.argv[1]))
limits = cfg.get("resource_limits", {})
raise SystemExit(0 if limits.get("cpu_percent") == 70 and limits.get("memory_percent") == 70 else 1)
PY
then
  record_failure "resource limits are not pinned to 70% CPU and 70% memory"
else
  record_note "resource limits verified at 70% CPU and 70% memory"
fi

if ! LOCAL_AGENT_TARGET_REPO="$TARGET_REPO" LOCAL_AGENT_MODE=fast bash "$REPO_ROOT/Local" >"$SMOKE_PATH" 2>&1 <<'EOF'
/help
/models
/team
/doctor
/exit
EOF
then
  record_failure "interactive CLI smoke test failed"
else
  record_note "interactive CLI smoke test passed"
fi

if ! LOCAL_AGENT_MODE=fast LOCAL_AGENT_MAX_PARALLEL=1 LOCAL_AGENT_ONLY_ROLES=researcher,retriever,planner,summarizer \
  python3 "$SCRIPT_DIR/local_team_run.py" \
  "what is the exact local start command and key CLI commands for this repo" \
  "$TARGET_REPO" >"$MODEL_SMOKE_PATH" 2>&1; then
  record_failure "model-backed smoke run failed"
else
  record_note "model-backed smoke run passed"
fi

{
  echo "# QA Suite Report"
  echo
  echo "- generated_at: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "- target_repo: $TARGET_REPO"
  echo "- release_status: $STATUS"
  echo
  echo "## Notes"
  if [ ${#NOTES[@]} -eq 0 ]; then
    echo "- none"
  else
    for item in "${NOTES[@]}"; do
      echo "- $item"
    done
  fi
  echo
  echo "## Failures"
  if [ ${#FAILURES[@]} -eq 0 ]; then
    echo "- none"
  else
    for item in "${FAILURES[@]}"; do
      echo "- $item"
    done
  fi
  echo
  echo "## Artifacts"
  echo "- session smoke: $SMOKE_PATH"
  echo "- model smoke: $MODEL_SMOKE_PATH"
} >"$REPORT_PATH"

cat "$REPORT_PATH"

if [ "$STATUS" != "pass" ]; then
  exit 1
fi
