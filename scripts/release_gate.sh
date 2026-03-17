#!/bin/bash
set -euo pipefail

TARGET_REPO=${1:-${LOCAL_AGENT_TARGET_REPO:-$PWD}}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
OUT_PATH="$REPO_ROOT/logs/release-gate-report.md"
STATUS=0

bash "$SCRIPT_DIR/create_checkpoint.sh" "release-gate" "$TARGET_REPO" >/dev/null
python3 "$SCRIPT_DIR/repair_runtime_state.py" "$TARGET_REPO" >/dev/null || true
if ! bash "$SCRIPT_DIR/qa_suite.sh" "$TARGET_REPO"; then
  STATUS=1
fi
if ! bash "$SCRIPT_DIR/user_acceptance_suite.sh" "$TARGET_REPO"; then
  STATUS=1
fi
python3 "$SCRIPT_DIR/review_current_changes.py" "$TARGET_REPO" >/dev/null || true
if [ "$STATUS" -ne 0 ]; then
  bash "$SCRIPT_DIR/self_repair.sh" "$TARGET_REPO" >/dev/null || true
  echo "Release gate blocked. See logs/qa-suite-report.md, logs/uat-suite-report.md, and logs/self-repair-report.md." >&2
  exit 1
fi
LOCAL_AGENT_MODE=${LOCAL_AGENT_MODE:-deep} \
LOCAL_AGENT_ONLY_ROLES=qa,user_acceptance,summarizer \
python3 "$SCRIPT_DIR/local_team_run.py" \
  "Perform final QA validation and non-technical user acceptance review for the current workflow or changes. Use the latest QA suite report and change review. Be concrete and decide if this is ready for user handoff." \
  "$TARGET_REPO" | tee "$OUT_PATH"
