#!/usr/bin/env bash
# post_stage.sh -- Hook that runs after each pipeline stage completes.
# Called with: post_stage.sh <stage_id> <target_repo> <stamp> <artifact_path>
# Always exits 0 (post hooks are advisory, never block the pipeline).
set -uo pipefail

STAGE_ID="${1:-}"
TARGET_REPO="${2:-}"
STAMP="${3:-}"
ARTIFACT="${4:-}"
REPO_ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
MAX_OUTPUT_CHARS="${POST_STAGE_MAX_OUTPUT_CHARS:-50000}"

echo "[post_stage] stage=$STAGE_ID repo=$TARGET_REPO stamp=$STAMP"

# --- 1. Log output size ---
if [ -n "$ARTIFACT" ] && [ -f "$ARTIFACT" ]; then
  CHAR_COUNT=$(wc -c < "$ARTIFACT" | tr -d ' ')
  LINE_COUNT=$(wc -l < "$ARTIFACT" | tr -d ' ')
  echo "[post_stage] artifact=$ARTIFACT chars=$CHAR_COUNT lines=$LINE_COUNT"

  # --- 2. Check quality: flag very short or very long outputs ---
  if [ "$CHAR_COUNT" -lt 200 ]; then
    echo "[post_stage] WARNING: output too short (${CHAR_COUNT} chars), may be low quality"
  fi
  if [ "$CHAR_COUNT" -gt "$MAX_OUTPUT_CHARS" ]; then
    echo "[post_stage] WARNING: output exceeds ${MAX_OUTPUT_CHARS} chars (${CHAR_COUNT}), consider trimming context"
  fi

  # --- 3. Trim context: if output is very large, create a summary shard ---
  if [ "$CHAR_COUNT" -gt "$MAX_OUTPUT_CHARS" ]; then
    TRIMMED_PATH="${ARTIFACT%.md}-trimmed.md"
    head -c "$MAX_OUTPUT_CHARS" "$ARTIFACT" > "$TRIMMED_PATH"
    echo "[post_stage] trimmed artifact saved to $TRIMMED_PATH"
  fi
else
  echo "[post_stage] no artifact found at $ARTIFACT"
fi

# --- 4. Log resource state after stage ---
RESOURCE_FILE="$REPO_ROOT/state/resource-status.json"
if [ -f "$RESOURCE_FILE" ]; then
  MEM_PCT=$(python3 -c "import json; d=json.load(open('$RESOURCE_FILE')); print(d.get('memory_percent', 'N/A'))" 2>/dev/null || echo "N/A")
  CPU_PCT=$(python3 -c "import json; d=json.load(open('$RESOURCE_FILE')); print(d.get('cpu_percent', 'N/A'))" 2>/dev/null || echo "N/A")
  echo "[post_stage] resource_after: cpu=${CPU_PCT}% mem=${MEM_PCT}%"
fi

# --- 5. Stage-specific post checks ---
case "$STAGE_ID" in
  planner)
    PLAN_FILE="$REPO_ROOT/state/common-plan.md"
    if [ -f "$PLAN_FILE" ]; then
      PLAN_SIZE=$(wc -c < "$PLAN_FILE" | tr -d ' ')
      echo "[post_stage] common-plan updated: ${PLAN_SIZE} chars"
    fi
    ;;
  summarizer)
    LATEST="$REPO_ROOT/logs/latest-response.md"
    if [ -f "$LATEST" ]; then
      echo "[post_stage] final response written to $LATEST"
    fi
    ;;
esac

echo "[post_stage] done for $STAGE_ID"
exit 0
