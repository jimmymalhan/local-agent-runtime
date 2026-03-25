#!/bin/bash
# Agent: Summary
# Summarises the pipeline, updates skills/workflows, and logs results.

PROMPT="$1"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
LOG_DIR="$(dirname "$0")/../logs"
FEEDBACK_EVOLUTION="$(dirname "$0")/../feedback/workflow-evolution.md"
mkdir -p "$LOG_DIR"

echo "$TIMESTAMP – summary-agent starting" >> "$LOG_DIR/agents.log"

echo "[summary-agent] Delegating to local summarizer role" >> "$LOG_DIR/agents.log"

# Append a simple evolution note for demonstration purposes.
echo "$TIMESTAMP – Updated skills and workflows based on prompt: $PROMPT" >> "$FEEDBACK_EVOLUTION"

# Automatically generate new skills from feedback logs.  This script examines
# feedback/prompt-log.md for recurring tasks and creates skeleton skill files
# under skills/.  See scripts/skill_generator.sh for details.  Suppress
# output unless running in verbose mode.
"$(dirname "$0")/../scripts/skill_generator.sh" >/dev/null 2>&1

# If environment variable AUTO_UPDATE_TOOLS is set to "1", run the external tool
# update script to discover and integrate new tools.  This script requires
# EXTERNAL_TOOL_SOURCE to be set to a URL or file containing tool definitions.
if [ "${AUTO_UPDATE_TOOLS:-0}" = "1" ]; then
  "$(dirname "$0")/../scripts/update_external_tools.sh" >/dev/null 2>&1
fi

# If environment variable AUTO_SELF_UPDATE is set to "1", run the self‑update
# script to fetch repository or dependency updates when network access is
# available.  See scripts/self_update.sh for details.
if [ "${AUTO_SELF_UPDATE:-0}" = "1" ]; then
  "$(dirname "$0")/../scripts/self_update.sh" >/dev/null 2>&1
fi

LOCAL_AGENT_ONLY_ROLES=summarizer python3 "$(dirname "$0")/../scripts/local_team_run.py" "$PROMPT" "${LOCAL_AGENT_TARGET_REPO:-$PWD}"

exit 0
