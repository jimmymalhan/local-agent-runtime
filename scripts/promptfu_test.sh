#!/bin/bash
# Run Prompt FU unit tests on a prompt file.
#
# This script wraps the Prompt FU tool (https://github.com/normal-computing/promptfu)
# to perform automated red‑team testing on prompt files.  It reads a
# prompt file, executes the tests and writes a report to the logs
# directory.
#
# Usage: ./promptfu_test.sh <prompt-file>

set -e

if [ "$#" -ne 1 ]; then
  echo "Usage: $0 <prompt-file>"
  exit 1
fi

PROMPT_FILE="$1"
LOG_DIR="$(dirname "$0")/../logs"
mkdir -p "$LOG_DIR"
REPORT_FILE="$LOG_DIR/promptfu-$(basename "$PROMPT_FILE").log"

if ! command -v promptfu >/dev/null 2>&1; then
  echo "Prompt FU is not installed.  Install it via pip: pip install promptfu"
  exit 1
fi

echo "Running Prompt FU on $PROMPT_FILE..."

# Run Prompt FU.  The exact CLI may change; adjust as needed.
promptfu test "$PROMPT_FILE" > "$REPORT_FILE"

echo "Report written to $REPORT_FILE"