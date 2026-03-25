#!/bin/bash
set -euo pipefail

TARGET_REPO=${1:-${LOCAL_AGENT_TARGET_REPO:-$PWD}}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

echo "[merge-gate] shell syntax"
bash -n "$REPO_ROOT/Local"
for file in "$SCRIPT_DIR"/*.sh; do
  bash -n "$file"
done
for file in "$REPO_ROOT"/local-codex "$REPO_ROOT"/local-claude; do
  [ -f "$file" ] && bash -n "$file" || true
done

echo "[merge-gate] python compile"
PY_COMPILE_FILES=("$SCRIPT_DIR"/*.py)
[ -f "$REPO_ROOT/mcp-local-runtime/server.py" ] && PY_COMPILE_FILES+=("$REPO_ROOT/mcp-local-runtime/server.py")
python3 -m py_compile "${PY_COMPILE_FILES[@]}"

echo "[merge-gate] unit tests"
python3 -m unittest discover -s "$REPO_ROOT/tests"

echo "[merge-gate] session policy"
python3 "$SCRIPT_DIR/validate_session_policy.py"

echo "[merge-gate] todo progress"
python3 "$SCRIPT_DIR/todo_progress.py"

echo "[merge-gate] cli smoke"
LOCAL_AGENT_TARGET_REPO="$TARGET_REPO" LOCAL_AGENT_MODE=fast bash "$REPO_ROOT/Local" <<'EOF'
/todo-progress
/team
/exit
EOF

echo "[merge-gate] pass"
