#!/bin/bash
# Run the self-improvement cycle
cd "$(dirname "$0")/.."
echo "Running self-improvement analysis..."
python3 -m local-agents.agents.self_improver --min-samples ${1:-20}
echo "Done. Check .claude/skills/ for updates."
