#!/bin/bash
# Agent: Idea Capture
# Captures the user prompt and stores it for learning.

PROMPT="$1"
if [ -z "$PROMPT" ]; then
  echo "idea-capture-agent: no prompt provided" >&2
  exit 1
fi

TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOG_DIR="$(dirname "$0")/../logs"
FEEDBACK_FILE="$(dirname "$0")/../feedback/prompt-log.md"
mkdir -p "$LOG_DIR"

# Append the prompt to the feedback log
echo "$TIMESTAMP – $PROMPT" >> "$FEEDBACK_FILE"

# Log activity
echo "$TIMESTAMP – idea-capture-agent captured prompt" >> "$LOG_DIR/agents.log"

echo "[idea-capture-agent] Delegating to local researcher role" >> "$LOG_DIR/agents.log"

LOCAL_AGENT_ONLY_ROLES=researcher python3 "$(dirname "$0")/../scripts/local_team_run.py" "$PROMPT" "${LOCAL_AGENT_TARGET_REPO:-$PWD}"

exit 0
