#!/usr/bin/env bash
# scripts/start_local_agents.sh — Boot local agent runtime with all 5 tasks
# Usage: bash scripts/start_local_agents.sh [--tasks N] [--check-only]

set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

TASKS_TO_RUN=${1:-5}
CHECK_ONLY=${2:-false}

echo "╔════════════════════════════════════════════════════════════╗"
echo "║           LOCAL AGENT RUNTIME STARTUP                      ║"
echo "╚════════════════════════════════════════════════════════════╝"
echo ""

# Check prerequisites
echo "[startup] Checking prerequisites..."
command -v python3 >/dev/null || { echo "✗ python3 not found"; exit 1; }
command -v git >/dev/null || { echo "✗ git not found"; exit 1; }
[[ -f "orchestrator/main.py" ]] || { echo "✗ orchestrator/main.py not found"; exit 1; }
[[ -f "projects.json" ]] || { echo "✗ projects.json not found"; exit 1; }
[[ -f "HANDOFF.md" ]] || { echo "✗ HANDOFF.md not found"; exit 1; }
echo "✓ All prerequisites found"
echo ""

# Verify git is clean
echo "[startup] Checking git state..."
if [[ -n "$(git status --short)" ]]; then
  echo "⚠ Uncommitted changes detected:"
  git status --short | head -5
  echo "  Run 'git add -A && git commit ...' before starting"
  exit 1
fi
echo "✓ Git state clean"
echo ""

# Show task list
echo "[startup] Tasks to execute ($TASKS_TO_RUN):"
jq -r '.projects[].tasks[] | "  #\(.id) — \(.title)"' projects.json | head -"$TASKS_TO_RUN"
echo ""

if [[ "$CHECK_ONLY" == "--check-only" ]]; then
  echo "✓ Check complete. Ready to start."
  exit 0
fi

# Start orchestrator
echo "[startup] Starting orchestrator with --auto $TASKS_TO_RUN..."
echo "          Run: python3 orchestrator/main.py --auto $TASKS_TO_RUN"
echo ""
echo "Monitor progress:"
echo "  • Dashboard: http://localhost:3000"
echo "  • State: cat dashboard/state.json"
echo "  • Reports: ls -lah reports/"
echo ""
echo "✅ Starting in 3 seconds..."
sleep 3

python3 orchestrator/main.py --auto "$TASKS_TO_RUN"
