#!/bin/bash
# Wait for the active local pipeline to complete, then show the summarizer output.
# Use: bash scripts/wait_and_show_result.sh
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
LOCK="$REPO_ROOT/state/run.lock"
LATEST="$REPO_ROOT/logs/latest-response.md"
PROGRESS_JSON="$REPO_ROOT/state/progress.json"

echo "Waiting for local pipeline to complete..."
while [ -f "$LOCK" ]; do
  if [ -f "$PROGRESS_JSON" ]; then
    pct=$(python3 -c "import json; d=json.load(open('$PROGRESS_JSON')); print(d.get('overall',{}).get('percent',0))" 2>/dev/null || echo "?")
    stage=$(python3 -c "import json; d=json.load(open('$PROGRESS_JSON')); print(d.get('current_stage','?'))" 2>/dev/null || echo "?")
    echo "  Progress: ${pct}% | Stage: $stage"
  fi
  sleep 15
done

echo ""
echo "Pipeline complete. Latest response:"
echo "=============================================="
if [ -f "$LATEST" ]; then
  cat "$LATEST"
else
  echo "(No latest-response.md yet; check memory/*.md and logs/)"
fi
echo "=============================================="
echo ""
echo "Review: $REPO_ROOT/logs/review-current-changes.md"
