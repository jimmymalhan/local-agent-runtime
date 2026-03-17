#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
TARGET_DIR=${1:-${LOCAL_AGENT_TARGET_REPO:-$PWD}}
OUTPUT="$TARGET_DIR/AGENTS.md"

if [ -f "$OUTPUT" ]; then
  echo "AGENTS.md already exists at $OUTPUT. Edit in place or remove first." >&2
  exit 1
fi

mkdir -p "$TARGET_DIR"
cat > "$OUTPUT" <<'EOF'
# Agent Instructions

Persistent instructions for this repository. The local agent team will read this file when working in this directory.

## Project Overview

Describe what this project does and its main goals.

## Conventions

- Code style and formatting preferences
- Naming conventions
- Architecture patterns

## Do / Don't

- Things the agent should always do
- Things the agent should avoid

## Commands

- How to run tests
- How to build
- Key scripts

EOF

echo "Created $OUTPUT"
echo "Edit it to match your repository conventions."
