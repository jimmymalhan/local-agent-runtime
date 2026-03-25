#!/bin/bash
# Agent: Architecture
# Generates a high-level plan and system architecture.

PROMPT="$1"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOG_DIR="$(dirname "$0")/../logs"
SKILL_FILE="$(dirname "$0")/../.claude/skills/generate-architecture.md"
mkdir -p "$LOG_DIR"

if [ ! -f "$SKILL_FILE" ]; then
  echo "architecture-agent: missing skill file $SKILL_FILE" >&2
  exit 1
fi

echo "$TIMESTAMP – architecture-agent starting" >> "$LOG_DIR/agents.log"
echo "[architecture-agent] Delegating to local architect role" >> "$LOG_DIR/agents.log"

LOCAL_AGENT_ONLY_ROLES=architect python3 "$(dirname "$0")/../scripts/local_team_run.py" "$PROMPT" "${LOCAL_AGENT_TARGET_REPO:-$PWD}"

exit 0
