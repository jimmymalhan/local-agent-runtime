#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)

export SESSION_PERSONA=claude
exec bash "$SCRIPT_DIR/start_codex_compatible.sh" "$@"
