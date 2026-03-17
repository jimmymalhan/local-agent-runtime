#!/bin/bash
# Summarize a file or directory using the OpenClaw CLI.
#
# OpenClaw is an open‑source personal AI framework that includes local
# summarization capabilities. This script wraps the `openclaw summarize`
# command to produce a concise summary of a directory or file, which can
# then be used by agents to reduce context and minimise hallucination.
#
# Usage:
#   ./openclaw_summarize.sh <path-to-file-or-directory> <output-file>
#
# Example:
#   ./openclaw_summarize.sh /path/to/project/src/ context/project_summary.md

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <path-to-file-or-directory> <output-file>"
  exit 1
fi

INPUT_PATH="$1"
OUTPUT_FILE="$2"

# Check that openclaw is installed.  If not, print a warning.
if ! command -v openclaw >/dev/null 2>&1; then
  echo "openclaw command not found.  Install it with:"
  echo "  curl -fsSL https://openclaw.ai/install.sh | bash"
  exit 1
fi

# Run openclaw summarization.  The `--max-tokens` option keeps the summary
# within a reasonable token budget.  Adjust as needed for your environment.
openclaw summarize --input "$INPUT_PATH" --output "$OUTPUT_FILE" --max-tokens 2048

echo "Summary written to $OUTPUT_FILE"