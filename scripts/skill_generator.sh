#!/bin/bash
# Auto skill generator
#
# This script scans the feedback logs and generates new skill files for
# recurring tasks.  It is a stub and should be extended with custom
# logic to analyse prompts and patterns.  For each new task pattern
# identified in feedback/prompt-log.md, it creates a skeleton skill
# template under skills/ if it does not already exist.

LOG_FILE="$(dirname "$0")/../feedback/prompt-log.md"
SKILLS_DIR="$(dirname "$0")/../.claude/skills"

if [ ! -f "$LOG_FILE" ]; then
  echo "skill_generator: no prompt log found at $LOG_FILE" >&2
  exit 1
fi

mkdir -p "$SKILLS_DIR"

# This example looks for lines starting with "###" in the prompt-log
# as indicators of unique tasks.  Replace this with custom logic to
# detect patterns relevant to your project.  Each task name is
# converted into a kebab-case filename.

grep -oE '^###\s+[^:]+:' "$LOG_FILE" | sed 's/^###\s\+//' | while read -r line; do
  # Strip trailing colon and convert to kebab case
  name="${line%%:*}"
  file="$(echo "$name" | tr '[:upper:]' '[:lower:]' | tr ' ' '-' ).md"
  skill_path="$SKILLS_DIR/$file"
  if [ ! -f "$skill_path" ]; then
    echo "Generating new skill template: $skill_path"
    cat > "$skill_path" <<EOF_SKILL
---
name: ${name}
description: |
  Auto-generated skill template for ${name}.  Replace this text with a
  detailed description of when to trigger this skill.
trigger: |
  # TODO: Specify conditions that should trigger this skill.
inputs:
  # TODO: Define the inputs required (e.g. file paths, variables).
commands:
  # TODO: Describe the steps or actions to perform.
output: |
  # TODO: Describe the expected output and format.
stop_conditions:
  # TODO: Specify when this skill should stop.
---

EOF_SKILL
  fi
done

echo "skill_generator: complete.  Review new skill templates in $SKILLS_DIR."
exit 0