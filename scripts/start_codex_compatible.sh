#!/bin/bash
set -euo pipefail

SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)

MODE=${LOCAL_AGENT_MODE:-$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1])).get("default_profile", "balanced"))' "$REPO_ROOT/config/runtime.json")}
TARGET_REPO=${LOCAL_AGENT_TARGET_REPO:-$PWD}
TASK=""

show_help() {
cat <<EOF
Local agent launcher (does NOT shadow codex/claude/cursor)

Usage:
  local-codex                              interactive session
  local-codex "<task>"                     one-shot task run
  local-codex /path/to/repo               set target repo
  local-codex /path/to/repo "<task>"      task in specific repo
  local-codex --mode deep "<task>"
  local-codex --persona claude "<task>"   run with claude persona
  local-codex --bench 3                   benchmark quick 3 tasks
  local-codex --bench-auto                full v1→v100 auto loop
  local-codex --dashboard                 open live dashboard

Modes:  fast | balanced | deep | exhaustive
EOF
}

while [ $# -gt 0 ]; do
  case "$1" in
    -h|--help)
      show_help; exit 0 ;;
    -m|--mode)
      shift; [ $# -gt 0 ] || { echo "Missing --mode value" >&2; exit 1; }
      MODE=$1 ;;
    --mode=*)
      MODE=${1#--mode=} ;;
    --persona)
      shift; SESSION_PERSONA=$1 ;;
    --persona=*)
      SESSION_PERSONA=${1#--persona=} ;;
    --bench)
      shift; BENCH_QUICK=${1:-3}
      python3 "$REPO_ROOT/local-agents/orchestrator/main.py" --version 1 --quick "$BENCH_QUICK" --local-only
      exit $? ;;
    --bench-auto)
      python3 "$REPO_ROOT/local-agents/orchestrator/main.py" --auto 1
      exit $? ;;
    --dashboard)
      bash "$REPO_ROOT/local-agents/dashboard/launch.sh" &
      echo "Dashboard starting — URL in DASHBOARD.txt"
      exit 0 ;;
    *)
      if [ -d "$1" ] && [ -z "${TASK}" ] && [ "${TARGET_REPO}" = "${LOCAL_AGENT_TARGET_REPO:-$PWD}" ]; then
        TARGET_REPO=$(cd "$1" && pwd)
      elif [ -z "$TASK" ]; then
        TASK=$1
      else
        TASK="$TASK $1"
      fi ;;
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
