#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
. "$SCRIPT_DIR/checkpoint_paths.sh"
CHECKPOINT_REF=${1:-}
TARGET_DIR=${2:-${LOCAL_AGENT_TARGET_REPO:-$PWD}}

if [ -z "$CHECKPOINT_REF" ]; then
  echo "Usage: $0 <checkpoint-path-or-name> [target-dir]" >&2
  exit 1
fi

migrate_legacy_checkpoints
CHECKPOINT_ROOT=$(checkpoint_root)

if [ -d "$CHECKPOINT_REF/files" ]; then
  CHECKPOINT_DIR="$CHECKPOINT_REF"
elif [ -d "$CHECKPOINT_ROOT/$CHECKPOINT_REF/files" ]; then
  CHECKPOINT_DIR="$CHECKPOINT_ROOT/$CHECKPOINT_REF"
else
  echo "Checkpoint not found: $CHECKPOINT_REF" >&2
  exit 1
fi

bash "$SCRIPT_DIR/create_checkpoint.sh" "pre-restore" "$TARGET_DIR" >/dev/null
rsync -a "$CHECKPOINT_DIR/files"/ "$TARGET_DIR"/
echo "Restored $CHECKPOINT_DIR into $TARGET_DIR"
