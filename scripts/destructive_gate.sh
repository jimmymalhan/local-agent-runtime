#!/bin/bash
set -euo pipefail

ACTION=${1:-}
TARGET_REPO=${2:-${LOCAL_AGENT_TARGET_REPO:-$PWD}}
PREVIEW_PATH=${3:-}

if [ -z "$ACTION" ]; then
  echo "Usage: $0 <action> [target-repo] [preview-path]" >&2
  exit 1
fi

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
LOG_DIR="$REPO_ROOT/logs"
mkdir -p "$LOG_DIR"

STAMP=$(date '+%Y%m%d_%H%M%S')
REPORT_PATH="$LOG_DIR/destructive-gate-${ACTION}-${STAMP}.md"

{
  echo "# Destructive Action Gate"
  echo
  echo "- action: $ACTION"
  echo "- target_repo: $TARGET_REPO"
  echo "- generated_at: $(date '+%Y-%m-%d %H:%M:%S')"
  echo
  if [ -n "$PREVIEW_PATH" ] && [ -f "$PREVIEW_PATH" ]; then
    echo "## Preview"
    echo
    echo "Preview artifact: $PREVIEW_PATH"
    echo
    sed -n '1,200p' "$PREVIEW_PATH"
    echo
  fi
  echo "## Git status"
  echo
  git -C "$TARGET_REPO" status --short --branch 2>/dev/null || echo "Target repo is not a git repository."
  echo
  echo "## Git diff --stat"
  echo
  git -C "$TARGET_REPO" diff --stat 2>/dev/null || echo "No git diff available."
} >"$REPORT_PATH"

APPROVED_ACTIONS=${LOCAL_AGENT_APPROVE_ACTIONS:-}
if [ "${LOCAL_AGENT_APPROVE_DESTRUCTIVE:-0}" = "1" ] || printf '%s' "$APPROVED_ACTIONS" | tr ',' '\n' | grep -Fxq "$ACTION"; then
  echo "$REPORT_PATH"
  exit 0
fi

echo "Destructive action blocked pending approval. Review: $REPORT_PATH" >&2
exit 2
