#!/bin/bash
set -euo pipefail

TARGET_REPO=${1:-${LOCAL_AGENT_TARGET_REPO:-$PWD}}
SCRIPT_DIR=$(cd "$(dirname "$0")" && pwd)
REPO_ROOT=$(cd "$SCRIPT_DIR/.." && pwd)
LOG_DIR="$REPO_ROOT/logs"
REPORT_PATH="$LOG_DIR/uat-suite-report.md"

mkdir -p "$LOG_DIR"

STATUS="pass"
FAILURES=()
NOTES=()

record_failure() {
  STATUS="fail"
  FAILURES+=("$1")
}

record_note() {
  NOTES+=("$1")
}

record_note "Target repo: $TARGET_REPO"

if ! python3 "$SCRIPT_DIR/repair_runtime_state.py" "$TARGET_REPO" >/dev/null; then
  record_note "runtime heal reported warnings; continuing with user acceptance prompts"
else
  record_note "runtime heal completed before user acceptance suite"
fi

PROMPT_1="$LOG_DIR/uat-prompt-1.md"
PROMPT_2="$LOG_DIR/uat-prompt-2.md"
PROMPT_3="$LOG_DIR/uat-prompt-3.md"

if ! LOCAL_AGENT_MODE=fast LOCAL_AGENT_ONLY_ROLES=researcher,retriever,planner,user_acceptance,summarizer \
  python3 "$SCRIPT_DIR/local_team_run.py" \
  "I am new here. Tell me the first local command to run and the five most useful slash commands in this repo." \
  "$TARGET_REPO" >"$PROMPT_1" 2>&1; then
  record_failure "prompt 1 user acceptance run failed"
else
  record_note "prompt 1 user acceptance run passed"
fi

if ! LOCAL_AGENT_MODE=fast LOCAL_AGENT_ONLY_ROLES=researcher,retriever,planner,user_acceptance,summarizer \
  python3 "$SCRIPT_DIR/local_team_run.py" \
  "I am non-technical. Explain in a few steps how I use this local assistant for another project, and what I should expect to see." \
  "$TARGET_REPO" >"$PROMPT_2" 2>&1; then
  record_failure "prompt 2 user acceptance run failed"
else
  record_note "prompt 2 user acceptance run passed"
fi

if ! LOCAL_AGENT_MODE=fast LOCAL_AGENT_ONLY_ROLES=researcher,retriever,planner,user_acceptance,summarizer \
  python3 "$SCRIPT_DIR/local_team_run.py" \
  "Explain how I check progress, review work at the end, and recover safely if something goes wrong." \
  "$TARGET_REPO" >"$PROMPT_3" 2>&1; then
  record_failure "prompt 3 user acceptance run failed"
else
  record_note "prompt 3 user acceptance run passed"
fi

if ! python3 - "$PROMPT_1" "$PROMPT_2" "$PROMPT_3" <<'PY'
import pathlib
import sys

paths = [pathlib.Path(item) for item in sys.argv[1:]]
texts = []
for path in paths:
    text = path.read_text(errors="ignore") if path.exists() else ""
    if len(text.strip()) < 200:
        raise SystemExit(1)
    texts.append(text.lower())

joined = "\n".join(texts)
required_markers = [
    "bash ./local",
    "/progress",
    "/review",
    "/checkpoint",
    "local",
]
if not all(marker in joined for marker in required_markers):
    raise SystemExit(1)

generic_markers = [
    "not enough context",
    "more context would help",
    "based on the information provided",
]
if any(marker in joined for marker in generic_markers):
    raise SystemExit(1)
PY
then
  record_failure "user acceptance answers did not meet the non-technical readiness rubric"
else
  record_note "user acceptance answers matched the non-technical readiness rubric"
fi

{
  echo "# User Acceptance Suite Report"
  echo
  echo "- generated_at: $(date '+%Y-%m-%d %H:%M:%S')"
  echo "- target_repo: $TARGET_REPO"
  echo "- release_status: $STATUS"
  echo
  echo "## Notes"
  if [ ${#NOTES[@]} -eq 0 ]; then
    echo "- none"
  else
    for item in "${NOTES[@]}"; do
      echo "- $item"
    done
  fi
  echo
  echo "## Failures"
  if [ ${#FAILURES[@]} -eq 0 ]; then
    echo "- none"
  else
    for item in "${FAILURES[@]}"; do
      echo "- $item"
    done
  fi
  echo
  echo "## Artifacts"
  echo "- prompt_1: $PROMPT_1"
  echo "- prompt_2: $PROMPT_2"
  echo "- prompt_3: $PROMPT_3"
} >"$REPORT_PATH"

cat "$REPORT_PATH"

if [ "$STATUS" != "pass" ]; then
  exit 1
fi
