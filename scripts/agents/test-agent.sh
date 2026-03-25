#!/bin/bash
# Agent: Test
# Generates and runs tests for the implemented feature.

PROMPT="$1"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOG_DIR="$(dirname "$0")/../logs"
mkdir -p "$LOG_DIR"

echo "$TIMESTAMP – test-agent starting" >> "$LOG_DIR/agents.log"
echo "[test-agent] Delegating to local tester role" >> "$LOG_DIR/agents.log"

LOCAL_AGENT_ONLY_ROLES=tester python3 "$(dirname "$0")/../scripts/local_team_run.py" "$PROMPT" "${LOCAL_AGENT_TARGET_REPO:-$PWD}"

exit 0
