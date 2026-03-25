#!/bin/bash
# Agent: Implementation
# Implements one step of the plan using the implement-feature skill.

PROMPT="$1"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOG_DIR="$(dirname "$0")/../logs"
SKILL_FILE="$(dirname "$0")/../skills/implement-feature.md"
mkdir -p "$LOG_DIR"

if [ ! -f "$SKILL_FILE" ]; then
  echo "implementation-agent: missing skill file $SKILL_FILE" >&2
  exit 1
fi

echo "$TIMESTAMP – implementation-agent starting" >> "$LOG_DIR/agents.log"
echo "[implementation-agent] Delegating to local implementer role" >> "$LOG_DIR/agents.log"

LOCAL_AGENT_ONLY_ROLES=implementer python3 "$(dirname "$0")/../scripts/local_team_run.py" "$PROMPT" "${LOCAL_AGENT_TARGET_REPO:-$PWD}"

exit 0
