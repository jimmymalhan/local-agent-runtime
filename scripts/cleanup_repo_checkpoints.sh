#!/bin/bash
# Remove checkpoints whose source_dir is this repo.
# Checkpoints are only for external projects with DB integration.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
CHECKPOINT_ROOT="$REPO_ROOT/checkpoints"
REPO_CANON=$(cd "$REPO_ROOT" && pwd)

removed=0
for dir in "$CHECKPOINT_ROOT"/*/; do
  [ -d "$dir" ] || continue
  meta="$dir/metadata.json"
  [ -f "$meta" ] || continue
  src=$(grep -o '"source_dir":[[:space:]]*"[^"]*"' "$meta" 2>/dev/null | sed 's/.*: *"\([^"]*\)".*/\1/' || true)
  [ -z "$src" ] && continue
  src_canon=$(cd "$src" 2>/dev/null && pwd || echo "")
  if [ -n "$src_canon" ] && [ "$src_canon" = "$REPO_CANON" ]; then
    echo "Removing repo checkpoint: $dir"
    rm -rf "$dir"
    removed=$((removed + 1))
  fi
done

# Fix 'latest' symlink if it pointed to removed checkpoint
if [ -L "$CHECKPOINT_ROOT/latest" ] && [ ! -e "$CHECKPOINT_ROOT/latest" ]; then
  newest=$(ls -td "$CHECKPOINT_ROOT"/*/ 2>/dev/null | head -n1)
  if [ -n "$newest" ]; then
    ln -sfn "$newest" "$CHECKPOINT_ROOT/latest"
  else
    rm -f "$CHECKPOINT_ROOT/latest"
  fi
fi

echo "Removed $removed checkpoint(s) for this repo."
