#!/usr/bin/env bash
# pre_stage.sh -- Hook that runs before each pipeline stage.
# Called with: pre_stage.sh <stage_id> <target_repo> <stamp>
# Exit 0 to proceed, non-zero to skip the stage.
set -euo pipefail

STAGE_ID="${1:-}"
TARGET_REPO="${2:-}"
STAMP="${3:-}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MAX_FILE_SIZE_KB="${PRE_STAGE_MAX_FILE_KB:-500}"

if [ -z "$STAGE_ID" ] || [ -z "$TARGET_REPO" ]; then
  echo "[pre_stage] usage: pre_stage.sh <stage_id> <target_repo> <stamp>" >&2
  exit 1
fi

echo "[pre_stage] stage=$STAGE_ID repo=$TARGET_REPO stamp=$STAMP"

# --- 1. Check file sizes: warn about oversized files in the target repo ---
LARGE_FILES=$(find "$TARGET_REPO" -maxdepth 4 -type f \
  \( -name "*.py" -o -name "*.js" -o -name "*.ts" -o -name "*.md" -o -name "*.json" \) \
  -size +"${MAX_FILE_SIZE_KB}k" 2>/dev/null | head -20 || true)
if [ -n "$LARGE_FILES" ]; then
  echo "[pre_stage] WARNING: Large files (>${MAX_FILE_SIZE_KB}KB) that may bloat context:"
  echo "$LARGE_FILES" | while read -r f; do
    SIZE_KB=$(du -k "$f" 2>/dev/null | cut -f1)
    echo "  ${SIZE_KB}KB  $f"
  done
fi

# --- 2. Filter test files: list test files so the stage can skip them from context ---
TEST_FILES=$(find "$TARGET_REPO" -maxdepth 4 -type f \
  \( -name "*_test.py" -o -name "test_*.py" -o -name "*.test.js" -o -name "*.test.ts" -o -name "*.spec.js" -o -name "*.spec.ts" \) \
  2>/dev/null | wc -l | tr -d ' ')
echo "[pre_stage] test_files_found=$TEST_FILES (excluded from context by default)"

# --- 3. Prep context: ensure memory and state dirs exist ---
mkdir -p "$REPO_ROOT/memory" "$REPO_ROOT/state" "$REPO_ROOT/logs"

# --- 4. Stage-specific checks ---
case "$STAGE_ID" in
  implementer)
    # Verify target repo is a git repo before implementation
    if [ -d "$TARGET_REPO/.git" ]; then
      echo "[pre_stage] target repo is git-tracked, safe to implement"
    else
      echo "[pre_stage] WARNING: target repo is not git-tracked"
    fi
    ;;
  reviewer|qa)
    # Check that prior outputs exist before review/QA
    PRIOR_COUNT=$(find "$REPO_ROOT/memory" -name "${STAMP}*" -type f 2>/dev/null | wc -l | tr -d ' ')
    echo "[pre_stage] prior_stage_artifacts=$PRIOR_COUNT"
    ;;
esac

echo "[pre_stage] OK - proceeding to $STAGE_ID"
exit 0
