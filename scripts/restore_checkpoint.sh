#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
. "$SCRIPT_DIR/checkpoint_paths.sh"
CHECKPOINT_REF=${1:-}
DRY_RUN=0
if [ "$CHECKPOINT_REF" = "--dry-run" ]; then
  DRY_RUN=1
  CHECKPOINT_REF=${2:-}
  TARGET_DIR=${3:-${LOCAL_AGENT_TARGET_REPO:-$PWD}}
else
  TARGET_DIR=${2:-${LOCAL_AGENT_TARGET_REPO:-$PWD}}
fi

if [ -z "$CHECKPOINT_REF" ]; then
  echo "Usage: $0 [--dry-run] <checkpoint-path-or-name> [target-dir]" >&2
  exit 1
fi

migrate_legacy_checkpoints "$TARGET_DIR"
CHECKPOINT_ROOT=$(checkpoint_root "$TARGET_DIR")

if [ -d "$CHECKPOINT_REF/files" ]; then
  CHECKPOINT_DIR=$(canonical_path "$CHECKPOINT_REF")
elif [ -d "$CHECKPOINT_ROOT/$CHECKPOINT_REF/files" ]; then
  CHECKPOINT_DIR=$(canonical_path "$CHECKPOINT_ROOT/$CHECKPOINT_REF")
else
  echo "Checkpoint not found: $CHECKPOINT_REF" >&2
  exit 1
fi

PREVIEW_PATH="$REPO_ROOT/logs/restore-dry-run-$(date '+%Y%m%d_%H%M%S').md"
mkdir -p "$REPO_ROOT/logs"
{
  echo "# Restore Dry Run"
  echo
  echo "- checkpoint: $CHECKPOINT_DIR"
  echo "- target_dir: $TARGET_DIR"
  echo "- generated_at: $(date '+%Y-%m-%d %H:%M:%S')"
  echo
  echo '```diff'
  rsync -ani --delete --exclude '.local-agent/checkpoints' "$CHECKPOINT_DIR/files"/ "$TARGET_DIR"/
  echo '```'
} >"$PREVIEW_PATH"

if [ "$DRY_RUN" -eq 1 ]; then
  echo "$PREVIEW_PATH"
  exit 0
fi

bash "$SCRIPT_DIR/destructive_gate.sh" "restore" "$TARGET_DIR" "$PREVIEW_PATH" >/dev/null
bash "$SCRIPT_DIR/create_checkpoint.sh" "pre-restore" "$TARGET_DIR" >/dev/null
rsync -a --checksum --delete --exclude '.local-agent/checkpoints' "$CHECKPOINT_DIR/files"/ "$TARGET_DIR"/
echo "Restored $CHECKPOINT_DIR into $TARGET_DIR"
