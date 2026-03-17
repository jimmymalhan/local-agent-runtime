#!/bin/bash
set -euo pipefail

TARGET_REPO=${1:-${LOCAL_AGENT_TARGET_REPO:-$PWD}}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
OUT_PATH="$REPO_ROOT/logs/quality-compare.md"

LOCAL_AGENT_MODE=${LOCAL_AGENT_MODE:-deep} \
LOCAL_AGENT_ONLY_ROLES=debugger,benchmarker,qa,user_acceptance,summarizer \
python3 "$SCRIPT_DIR/local_team_run.py" \
  "Compare the latest local answer, the current workflow, and any validation artifacts against the local quality rubric. Identify quality gaps, upgrade the draft, and explain what still needs improvement." \
  "$TARGET_REPO" | tee "$OUT_PATH"
