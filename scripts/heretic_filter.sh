#!/bin/bash
# Wrapper for the Heretic censorship removal tool (use with caution).
#
# Heretic applies the obliteration technique to remove model
# censorship.  This script reads an input prompt file and writes the
# uncensored prompt to an output file.  It warns the user if Heretic
# is not installed.  Only use this in controlled experiments.
#
# Usage: ./heretic_filter.sh <input-prompt-file> <output-prompt-file>

if [ "$#" -ne 2 ]; then
  echo "Usage: $0 <input-prompt-file> <output-prompt-file>"
  exit 1
fi

INPUT_PROMPT="$1"
OUTPUT_PROMPT="$2"

if ! command -v heretic >/dev/null 2>&1; then
  echo "Heretic CLI not installed.  Install heretic from its repository and ensure the 'heretic' command is in your PATH."
  # Copy input to output as a fallback.
  cp "$INPUT_PROMPT" "$OUTPUT_PROMPT"
  exit 0
fi

echo "Applying Heretic censorship removal to $INPUT_PROMPT..."

heretic "$INPUT_PROMPT" > "$OUTPUT_PROMPT"

echo "Uncensored prompt written to $OUTPUT_PROMPT"