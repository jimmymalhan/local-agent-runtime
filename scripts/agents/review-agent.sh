#!/bin/bash
# Agent: Review
# Validates the implementation and identifies logical issues.

PROMPT="$1"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOG_DIR="$(dirname "$0")/../logs"
SKILL_FILE="$(dirname "$0")/../.claude/skills/validate-logic.md"
mkdir -p "$LOG_DIR"

if [ ! -f "$SKILL_FILE" ]; then
  echo "review-agent: missing skill file $SKILL_FILE" >&2
  exit 1
fi

echo "$TIMESTAMP – review-agent starting" >> "$LOG_DIR/agents.log"
echo "[review-agent] Delegating to local reviewer role" >> "$LOG_DIR/agents.log"

LOCAL_AGENT_ONLY_ROLES=reviewer python3 "$(dirname "$0")/../scripts/local_team_run.py" "$PROMPT" "${LOCAL_AGENT_TARGET_REPO:-$PWD}"

exit 0
