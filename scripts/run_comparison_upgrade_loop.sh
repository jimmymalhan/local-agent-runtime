#!/bin/bash
# Runs Cursor vs local comparison + upgrade in a loop until local agents match or exceed.
# Uses 70% CPU/memory, max parallelism, no API calls.
set -euo pipefail
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
export LOCAL_AGENT_MODE=exhaustive
export LOCAL_AGENT_AUTO_REVIEW=1
TASK="Compare Cursor's highest-reasoning cloud model vs this repo's local Ollama agents for coding tasks. Which is better? If Cursor/cloud is stronger: (1) Recommend and implement specific upgrades to local models, config, skills, and MCP to close the gap. (2) Use up to 70% CPU/memory, scale agents/skills/MCP for parallel coordination so work finishes simultaneously and responses are faster. (3) Design for RAG + Pinecone + SGLang at scale (see https://www.linkedin.com/blog/engineering/ai/scaling-llm-based-ranking-systems-with-sglang-at-linkedin/) - exhaustive option, quick response, no quality compromise. (4) Make local agents coordinate like sub-agents working simultaneously. Be thorough and actionable. Implement upgrades end to end."
ITER=0
while true; do
  ITER=$((ITER + 1))
  echo "=== Comparison+upgrade iteration $ITER ==="
  while test -f "$REPO_ROOT/state/run.lock"; do
    echo "Waiting for active run to finish..."
    sleep 10
  done
  echo "Starting pipeline: $TASK"
  if bash "$SCRIPT_DIR/run_pipeline.sh" "$TASK"; then
    echo "Pipeline completed. Check logs/latest-response.md for output."
  else
    echo "Pipeline failed (exit $?). Check checkpoints and logs."
  fi
  echo "Iteration $ITER done. Re-running in 5s (loop until local >= cloud)..."
  sleep 5
done
