#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
LABEL=${1:-manual}
SOURCE_DIR=${2:-${LOCAL_AGENT_TARGET_REPO:-$PWD}}

# Checkpoints only for external projects with DB integration; skip for this repo
SOURCE_CANON=$(cd "$SOURCE_DIR" 2>/dev/null && pwd || echo "")
REPO_CANON=$(cd "$REPO_ROOT" 2>/dev/null && pwd || echo "")
if [ -n "$SOURCE_CANON" ] && [ -n "$REPO_CANON" ] && [ "$SOURCE_CANON" = "$REPO_CANON" ]; then
  echo "(skipped)"
  exit 0
fi

STAMP=$(date '+%Y%m%d_%H%M%S')
SAFE_LABEL=$(printf '%s' "$LABEL" | tr '[:space:]/:' '---' | tr -cd '[:alnum:]-_' | cut -c1-40)
CHECKPOINT_ROOT="$REPO_ROOT/checkpoints"
DEST="$CHECKPOINT_ROOT/${STAMP}-${SAFE_LABEL}"

mkdir -p "$DEST/files"

RSYNC_ARGS=(-a --exclude '.DS_Store' --exclude 'checkpoints')
rsync "${RSYNC_ARGS[@]}" "$SOURCE_DIR"/ "$DEST/files"/

cat >"$DEST/metadata.json" <<EOF
{
  "label": "$LABEL",
  "source_dir": "$(cd "$SOURCE_DIR" && pwd)",
  "created_at": "$STAMP",
  "checkpoint_path": "$DEST"
}
EOF

cat >"$DEST/RESTORE.md" <<EOF
# Restore

Checkpoint:
$DEST

Restore into the original source path:
\`\`\`bash
bash "$REPO_ROOT/scripts/restore_checkpoint.sh" "$DEST" "$(cd "$SOURCE_DIR" && pwd)"
\`\`\`
EOF

ln -sfn "$DEST" "$CHECKPOINT_ROOT/latest"
echo "$DEST"
