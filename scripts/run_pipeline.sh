#!/bin/bash
set -euo pipefail

if [ -z "${1:-}" ]; then
  echo "Usage: $0 \"<your idea prompt>\""
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
PROMPT="$1"
TARGET_REPO=${LOCAL_AGENT_TARGET_REPO:-$PWD}
LOCAL_AGENT_MODE=${LOCAL_AGENT_MODE:-exhaustive}
TEAM_LABELS="researcher,retriever,planner,architect,implementer,tester,reviewer,debugger,optimizer,benchmarker,qa,user_acceptance,summarizer"

# Always auto-run review at the end (local-only policy)
export LOCAL_AGENT_AUTO_REVIEW=1

echo "Running pipeline for prompt: $PROMPT"
echo "Execution mode: $LOCAL_AGENT_MODE"
# Checkpoints only for external projects with DB integration; skip for this repo and model runs
TARGET_CANON=$(cd "$TARGET_REPO" 2>/dev/null && pwd || echo "")
REPO_CANON=$(cd "$REPO_ROOT" 2>/dev/null && pwd || echo "")
CHECKPOINT_PATH=""
if [ -n "$TARGET_CANON" ] && [ -n "$REPO_CANON" ] && [ "$TARGET_CANON" != "$REPO_CANON" ]; then
  CHECKPOINT_PATH=$(bash "$SCRIPT_DIR/create_checkpoint.sh" "pre-run" "$TARGET_REPO" | tail -n 1)
  echo "Checkpoint created: $CHECKPOINT_PATH"
fi
bash "$SCRIPT_DIR/update_todo.sh" add "$PROMPT" "$TEAM_LABELS" >/dev/null
PIPELINE_EXIT=0
if python3 "$SCRIPT_DIR/local_team_run.py" "$PROMPT" "$TARGET_REPO"; then
  bash "$SCRIPT_DIR/update_todo.sh" done "$PROMPT" >/dev/null || true
  bash "$SCRIPT_DIR/update_ledger.sh" "local-team-run" >/dev/null || true
  [ -n "$CHECKPOINT_PATH" ] && echo "Checkpoint: $CHECKPOINT_PATH"
  echo "Pipeline execution complete."
else
  PIPELINE_EXIT=1
  [ -n "$CHECKPOINT_PATH" ] && echo "Local pipeline failed. Checkpoint available at: $CHECKPOINT_PATH" >&2
fi
# Always run review at the end (success or failure)
echo ""
echo "== auto review =="
python3 "$SCRIPT_DIR/review_current_changes.py" "$TARGET_REPO" || true
exit "$PIPELINE_EXIT"
