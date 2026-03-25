#!/bin/bash
# Agent: Optimisation
# Optimises code performance and resource usage.

PROMPT="$1"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOG_DIR="$(dirname "$0")/../logs"
SKILL_FILE="$(dirname "$0")/../skills/optimize-system.md"
mkdir -p "$LOG_DIR"

if [ ! -f "$SKILL_FILE" ]; then
  echo "optimization-agent: missing skill file $SKILL_FILE" >&2
  exit 1
fi

echo "$TIMESTAMP – optimization-agent starting" >> "$LOG_DIR/agents.log"
echo "[optimization-agent] Delegating to local optimizer role" >> "$LOG_DIR/agents.log"

LOCAL_AGENT_ONLY_ROLES=optimizer python3 "$(dirname "$0")/../scripts/local_team_run.py" "$PROMPT" "${LOCAL_AGENT_TARGET_REPO:-$PWD}"

exit 0
