#!/bin/bash
set -euo pipefail

TARGET_REPO=${1:-${LOCAL_AGENT_TARGET_REPO:-$PWD}}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
OUT_PATH="$REPO_ROOT/logs/self-repair-report.md"

python3 "$SCRIPT_DIR/repair_runtime_state.py" "$TARGET_REPO" >/dev/null || true
bash "$SCRIPT_DIR/qa_suite.sh" "$TARGET_REPO" >/dev/null || true
bash "$SCRIPT_DIR/user_acceptance_suite.sh" "$TARGET_REPO" >/dev/null || true
python3 "$SCRIPT_DIR/review_current_changes.py" "$TARGET_REPO" >/dev/null || true

LOCAL_AGENT_MODE=${LOCAL_AGENT_MODE:-deep} \
LOCAL_AGENT_ONLY_ROLES=reviewer,debugger,optimizer,benchmarker,qa,user_acceptance,summarizer \
python3 "$SCRIPT_DIR/local_team_run.py" \
  "Use the latest QA suite report, user acceptance suite report, current change review, and latest response to diagnose the highest-priority workflow issues in this repo. First list deterministic runtime fixes that can be applied immediately, then produce a self-repair plan ordered by severity, name the exact files to change, and state the validation to rerun after each fix." \
  "$TARGET_REPO" | tee "$OUT_PATH"
