#!/bin/bash
# stop_loop.sh — Send stop signal to the continuous task loop.
# Usage: bash scripts/stop_loop.sh
#
# Creates local-agents/.stop so ContinuousLoop.stop_conditions() returns True.
# The loop will finish the current task and then exit gracefully.

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
STOP_FILE="$REPO_ROOT/local-agents/.stop"

touch "$STOP_FILE"
echo "Stop signal sent. Loop will exit after current task completes."
echo "Stop file: $STOP_FILE"
echo ""
echo "To restart the loop, delete the stop file:"
echo "  rm $STOP_FILE"
echo "  python3 -m orchestrator.continuous_loop --forever"
