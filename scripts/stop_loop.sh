#!/bin/bash
# stop_loop.sh -- Send stop signal to the continuous task loop.
# Creates local-agents/.stop so ContinuousLoop.stop_conditions() returns True.
# The loop finishes the current task then exits.
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
STOP_FILE="$REPO_ROOT/local-agents/.stop"
touch "$STOP_FILE"
echo "Stop signal sent. Loop will exit after current task."
echo "Stop file: $STOP_FILE"
echo "To restart:  rm $STOP_FILE && python3 -m orchestrator.continuous_loop --forever"

