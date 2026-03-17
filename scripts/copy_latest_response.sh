#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
LATEST="$REPO_ROOT/logs/latest-response.md"

if [ ! -f "$LATEST" ]; then
  echo "No latest response found. Run a pipeline first." >&2
  exit 1
fi

if command -v pbcopy >/dev/null 2>&1; then
  pbcopy < "$LATEST"
  echo "Copied latest response to clipboard."
elif command -v xclip >/dev/null 2>&1; then
  xclip -selection clipboard < "$LATEST"
  echo "Copied latest response to clipboard."
elif command -v xsel >/dev/null 2>&1; then
  xsel --clipboard < "$LATEST"
  echo "Copied latest response to clipboard."
else
  cat "$LATEST"
  echo "" >&2
  echo "No clipboard utility (pbcopy/xclip/xsel) found. Output above." >&2
  exit 1
fi
