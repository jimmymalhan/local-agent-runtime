#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

MODE=${LOCAL_AGENT_MODE:-$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("default_profile", "balanced"))' "$REPO_ROOT/config/runtime.json")}
TARGET_REPO=${LOCAL_AGENT_TARGET_REPO:-$PWD}
TASK=""

show_help() {
cat <<EOF
Local agent launcher (use local-codex or Local - does NOT shadow codex/claude)

Usage:
  local-codex
  local-codex "<task>"
  local-codex /path/to/repo
  local-codex /path/to/repo "<task>"
  local-codex --mode deep
  local-codex --mode exhaustive
  local-codex --mode fast "<task>"

Behavior:
  - no task: starts the interactive local session
  - with task: runs a one-shot local task
  - if the first non-flag argument is a directory, it becomes the target repo

Modes:
  fast
  balanced
  deep
  exhaustive
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)
      show_help
      exit 0
      ;;
    -m|--mode)
      shift
      [ $# -gt 0 ] || { echo "Missing value for --mode" >&2; exit 1; }
      MODE=$1
      ;;
    --mode=*)
      MODE=${1#--mode=}
      ;;
    *)
      if [ -d "$1" ] && [ -z "${TASK}" ] && [ "${TARGET_REPO}" = "${LOCAL_AGENT_TARGET_REPO:-$PWD}" ]; then
        TARGET_REPO=$(cd "$1" && pwd)
      elif [ -z "$TASK" ]; then
        TASK=$1
      else
        TASK="$TASK $1"
      fi
      ;;
  esac
  shift
done

export LOCAL_AGENT_MODE=$MODE
export LOCAL_AGENT_TARGET_REPO=$TARGET_REPO
export SESSION_PERSONA=${SESSION_PERSONA:-codex}

cd "$REPO_ROOT"

if [ -n "$TASK" ]; then
  python3 "$REPO_ROOT/scripts/local_team_run.py" "$TASK" "$TARGET_REPO"
  if [ "${LOCAL_AGENT_AUTO_REVIEW:-1}" = "1" ]; then
    echo
    echo "== auto review =="
    python3 "$REPO_ROOT/scripts/review_current_changes.py" "$TARGET_REPO" || true
  fi
  exit 0
fi

exec bash "$REPO_ROOT/Local"
