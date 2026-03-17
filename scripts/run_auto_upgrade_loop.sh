#!/bin/bash
# Auto loop: (1) discover features → add to todo, (2) compare+upgrade, (3) poll status, repeat.
# Lead assigns Researcher/Retriever/Planner/Implementer per skills/auto-discover-upgrade-features.md.
# Uses 70% CPU/memory. No API calls.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
export LOCAL_AGENT_MODE=exhaustive
export LOCAL_AGENT_AUTO_REVIEW=1

DISCOVER_TASK="Scan this repo (docs/, config/, scripts/, skills/, README, UPGRADE.md, workflows/, roles/) for features that help local Ollama models exceed Cursor. Lead: assign Researcher+Retriever to scan, Planner to prioritize, Implementer to append new items to state/todo.md under Local Model Upgrade Roadmap. No duplicates. Exhaustive. Follow skills/auto-discover-upgrade-features.md."

UPGRADE_TASK="Compare Cursor highest-reasoning vs local agents. If Cursor better: implement upgrades from state/todo.md Local Model Upgrade Roadmap. Use 70% CPU/memory, RAG+Pinecone+SGLang at scale, common plan, lead coordination. Implement end to end."

# Clear stale lock: pid in lock file no longer running
clear_stale_lock() {
  local lock="$REPO_ROOT/state/run.lock"
  [ ! -f "$lock" ] && return 0
  local pid
  pid=$(grep -o '"pid":[[:space:]]*[0-9]*' "$lock" 2>/dev/null | grep -o '[0-9]*' || true)
  if [ -n "$pid" ] && ! kill -0 "$pid" 2>/dev/null; then
    echo "Clearing stale lock (pid $pid not running)"
    rm -f "$lock"
  fi
}

ITER=0
while true; do
  ITER=$((ITER + 1))
  echo "=== Auto-upgrade iteration $ITER ==="
  bash "$SCRIPT_DIR/cleanup_repo_checkpoints.sh" 2>/dev/null || true
  clear_stale_lock
  while test -f "$REPO_ROOT/state/run.lock"; do
    echo "Waiting for active run..."
    sleep 10
    clear_stale_lock
  done

  echo "[Phase 1] Discover features → add to todo"
  bash "$SCRIPT_DIR/run_pipeline.sh" "$DISCOVER_TASK" || true

  while test -f "$REPO_ROOT/state/run.lock"; do
    clear_stale_lock
    sleep 5
  done
  sleep 3

  echo "[Phase 2] Compare + upgrade"
  bash "$SCRIPT_DIR/run_pipeline.sh" "$UPGRADE_TASK" || true

  echo "Iteration $ITER done. Polling status... Re-run in 10s."
  sleep 10
done
