#!/bin/bash
# agent-loop.sh — LOCAL ONLY. No git. No commits. No branches. No browser.
set -euo pipefail
source ~/.zshrc 2>/dev/null || true

export BOS_HOME="${BOS_HOME:-$HOME/stacky-os}"
export NEXUS_API="${NEXUS_API:-}"
PORT_API="${PORT_API:-8000}"
WORKER_ID="${WORKER_ID:-1}"
PROJECT_SLUG="${PROJECT_SLUG:-stacky}"
PROJECT_NAME="${PROJECT_NAME:-Stacky}"
LOCAL_LIGHT="${LOCAL_LIGHT:-nexus-local}"
LOCAL_STANDARD="${LOCAL_STANDARD:-nexus-local}"

log() { echo "[$(date '+%H:%M:%S')] [W$WORKER_ID] $*" | tee -a "$BOS_HOME/logs/agent.log"; }
task_log() {
  ESCAPED=$(echo "$2" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo '""')
  [ "$ESCAPED" != '""' ] && curl -s -X POST "localhost:$PORT_API/tasks/$1/logs" \
    -H "Content-Type: application/json" \
    -d "{\"message\":$ESCAPED,\"source\":\"${3:-agent}\"}" >/dev/null &
}

# Wait for supervisor gate clearance before every task
wait_for_gate() {
  local ATTEMPTS=0
  while true; do
    PASSED=$(python3 -c "
import json
try:
  d=json.load(open('$BOS_HOME/logs/gate.json'))
  print(str(d.get('passed',False)))
except: print('False')
" 2>/dev/null)
    [ "$PASSED" = "True" ] && return 0
    ATTEMPTS=$((ATTEMPTS+1))
    log "gate blocked — waiting 15s ($ATTEMPTS/10)"
    [ $ATTEMPTS -ge 10 ] && {
      curl -sX POST "localhost:$PORT_API/notifications/webhook" \
        -d "{\"message\":\"Worker $WORKER_ID gate blocked 10x\",\"type\":\"critical\"}" \
        -H "Content-Type: application/json" 2>/dev/null || true
      return 1
    }
    sleep 15
  done
}

log "Agent worker $WORKER_ID starting"

while true; do
  # Gate check before every task
  wait_for_gate || { sleep 30; continue; }

  # Fetch next task
  TASK=$(curl -sf "localhost:$PORT_API/agent/queue" 2>/dev/null) || { sleep 10; continue; }
  TASK_ID=$(echo "$TASK" | python3 -c "import sys,json; print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
  [ -z "$TASK_ID" ] && { sleep 15; continue; }

  MODEL=$(echo "$TASK"  | python3 -c "import sys,json; print(json.load(sys.stdin).get('resolved_model','$LOCAL_STANDARD'))")
  TITLE=$(echo "$TASK"  | python3 -c "import sys,json; print(json.load(sys.stdin).get('title','')[:80])")
  TYPE=$(echo "$TASK"   | python3 -c "import sys,json; print(json.load(sys.stdin).get('task_type','code'))")
  DESC=$(echo "$TASK"   | python3 -c "import sys,json; print(json.load(sys.stdin).get('description','') or '')")
  CPATH=$(echo "$TASK"  | python3 -c "import sys,json; print(json.load(sys.stdin).get('codebase_path','') or '')")
  PRIORITY=$(echo "$TASK" | python3 -c "import sys,json; print(json.load(sys.stdin).get('priority','medium'))")

  WORK_DIR="$CPATH"
  [ ! -d "$WORK_DIR" ] && WORK_DIR="$BOS_HOME"

  log "Task #$TASK_ID [$PRIORITY/$TYPE]: $TITLE"
  log "Model: $MODEL | Dir: $WORK_DIR"

  # Register worker slot in settings (dashboard shows this)
  TITLE_ESC=$(echo "$TITLE" | python3 -c 'import sys,json; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo '""')
  curl -sX PATCH "localhost:$PORT_API/settings" \
    -H "Content-Type: application/json" \
    -d "{\"worker_${WORKER_ID}_task\":\"$TASK_ID\",\"agent${WORKER_ID}_model\":\"$MODEL\",\"agent${WORKER_ID}_task\":$TITLE_ESC}" \
    >/dev/null 2>&1 || true

  # Mark in_progress
  curl -sf -X PATCH "localhost:$PORT_API/tasks/$TASK_ID/status" \
    -H "Content-Type: application/json" \
    -d '{"status":"in_progress"}' >/dev/null
  curl -sf -X POST "localhost:$PORT_API/tasks/$TASK_ID/time/start" >/dev/null 2>&1 || true
  START=$(date +%s)

  # Send heartbeat — marks worker as active on dashboard
  curl -sf -X PATCH "localhost:$PORT_API/agent/heartbeat" \
    -H "Content-Type: application/json" \
    -d "{\"task_id\":$TASK_ID,\"model\":\"$MODEL\",\"worker_id\":\"worker-$WORKER_ID\",\"task_title\":$TITLE_ESC}" \
    >/dev/null 2>&1 || true

  # Background heartbeat loop — keeps worker showing active during aider execution
  ( while kill -0 $$ 2>/dev/null; do
      sleep 30
      curl -sf -X PATCH "localhost:$PORT_API/agent/heartbeat" \
        -H "Content-Type: application/json" \
        -d "{\"task_id\":$TASK_ID,\"model\":\"$MODEL\",\"worker_id\":\"worker-$WORKER_ID\",\"task_title\":$TITLE_ESC}" \
        >/dev/null 2>&1 || true
    done ) &
  HB_PID=$!

  task_log "$TASK_ID" "[W$WORKER_ID] Starting: $TITLE (model=$MODEL)" "system"

  # Write task JSON for agent_runner.py
  # Use PID-based name (always unique — eliminates mktemp collision bug)
  TASK_FILE="/tmp/stacky_task_w${WORKER_ID}_$$.json"
  rm -f "$TASK_FILE"  # clean any prior crash remnant with same PID (rare)
  echo "$TASK" | python3 -c "
import sys, json
t = json.load(sys.stdin)
t['resolved_model'] = '$MODEL'
t['codebase_path']  = '$WORK_DIR'
print(json.dumps(t))" > "$TASK_FILE"

  # Execute with autonomous agent_runner.py (self-heals internally via run_with_retry)
  set +e
  python3 "$BOS_HOME/agent_runner.py" "$TASK_FILE" 2>&1 \
    | tee -a "$BOS_HOME/logs/agent.log" \
    | while IFS= read -r LINE; do
        ESCAPED=$(echo "$LINE" | python3 -c \
          'import sys,json; print(json.dumps(sys.stdin.read().strip()))' 2>/dev/null || echo '""')
        [ "$ESCAPED" != '""' ] && \
          curl -s -X POST "localhost:$PORT_API/tasks/$TASK_ID/logs" \
            -H "Content-Type: application/json" \
            -d "{\"message\":$ESCAPED,\"source\":\"agent\"}" >/dev/null 2>&1 &
      done
  EXIT_CODE=${PIPESTATUS[0]}
  set -e

  rm -f "$TASK_FILE"
  [ $EXIT_CODE -eq 0 ] && log "Task #$TASK_ID succeeded" || log "Task #$TASK_ID failed (exit=$EXIT_CODE)"

  END=$(date +%s)
  HOURS=$(python3 -c "print(round(($END-$START)/3600,4))")

  if [ $EXIT_CODE -eq 0 ]; then
    curl -sf -X PATCH "localhost:$PORT_API/tasks/$TASK_ID" \
      -H "Content-Type: application/json" \
      -d "{\"status\":\"review\",\"actual_hours\":$HOURS}" >/dev/null
    task_log "$TASK_ID" "[W$WORKER_ID] DONE in ${HOURS}h" "system"
    log "Task #$TASK_ID DONE in ${HOURS}h"
  else
    RETRY_COUNT=$(curl -sf "localhost:$PORT_API/tasks/$TASK_ID" 2>/dev/null \
      | python3 -c "import sys,json; print(json.load(sys.stdin).get('retry_count',0))" 2>/dev/null || echo "0")
    NEW_RETRY=$((RETRY_COUNT + 1))
    curl -sf -X PATCH "localhost:$PORT_API/tasks/$TASK_ID" \
      -H "Content-Type: application/json" \
      -d "{\"status\":\"blocked\",\"actual_hours\":$HOURS,\"retry_count\":$NEW_RETRY}" >/dev/null
    task_log "$TASK_ID" "[W$WORKER_ID] BLOCKED after 3 attempts (retry_count=$NEW_RETRY)" "error"
    log "Task #$TASK_ID BLOCKED (retry_count=$NEW_RETRY)"
  fi

  curl -sf -X POST "localhost:$PORT_API/tasks/$TASK_ID/time/stop" \
    -H "Content-Type: application/json" \
    -d "{\"actual_hours\":$HOURS}" >/dev/null 2>&1 || true

  # Stop heartbeat background loop and send idle heartbeat
  kill $HB_PID 2>/dev/null || true
  curl -sf -X PATCH "localhost:$PORT_API/agent/heartbeat" \
    -H "Content-Type: application/json" \
    -d "{\"task_id\":null,\"model\":\"idle\",\"worker_id\":\"worker-$WORKER_ID\",\"task_title\":null}" \
    >/dev/null 2>&1 || true

  # Clear worker slot
  curl -sX PATCH "localhost:$PORT_API/settings" \
    -H "Content-Type: application/json" \
    -d "{\"worker_${WORKER_ID}_task\":\"\",\"agent${WORKER_ID}_task\":\"waiting\"}" \
    >/dev/null 2>&1 || true

  osascript -e "display notification \"$TITLE\" with title \"$PROJECT_NAME OS\"" 2>/dev/null || true

  sleep 5
done
