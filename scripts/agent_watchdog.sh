#!/usr/bin/env bash
# =============================================================================
# agent_watchdog.sh — Always-On Agent Runtime Guardian
# =============================================================================
# Cron: */5 * * * * /Users/jimmymalhan/Documents/local-agent-runtime/scripts/agent_watchdog.sh
#
# What it does:
#   1. Checks if the agent loop is running → auto-restarts if dead
#   2. Checks if the researcher is running → auto-restarts if dead
#   3. Triggers auto-upgrade if a new version report appears
#   4. Writes health.json for the dashboard
#
# Controls:
#   touch local-agents/.stop     → pause everything
#   rm local-agents/.stop        → resume
#   tail -f local-agents/logs/watchdog.log  → live status
# =============================================================================

REPO="/Users/jimmymalhan/Documents/local-agent-runtime"
LOGS="$REPO/local-agents/logs"
REPORTS="$REPO/local-agents/reports"
STOP_FILE="$REPO/local-agents/.stop"
HEALTH="$REPORTS/health.json"

mkdir -p "$LOGS" "$REPORTS"

TS=$(python3 -c "from datetime import datetime,timezone; print(datetime.now(timezone.utc).isoformat())" 2>/dev/null || date -u +"%Y-%m-%dT%H:%M:%SZ")

log()   { echo "[$TS] $*" >> "$LOGS/watchdog.log"; }
event() { echo "{\"ts\":\"$TS\",\"event\":\"$1\",\"detail\":\"${2:-}\"}" >> "$LOGS/watchdog.jsonl"; }

# ── Bail if manually paused ───────────────────────────────────────────────────
if [[ -f "$STOP_FILE" ]]; then
  log "PAUSED (.stop file present — remove to resume)"
  exit 0
fi

# ── 1. Continuous Agent Loop ──────────────────────────────────────────────────
LOOP_PID=$(pgrep -f "orchestrator/main.py" 2>/dev/null | head -1 || true)
LOOP_STATUS="running"

if [[ -z "$LOOP_PID" ]]; then
  LOOP_STATUS="restarted"
  log "loop dead — restarting"
  event "loop_restart" "watchdog auto-restart"
  cd "$REPO/local-agents"
  nohup python3 orchestrator/main.py --continuous >> "$LOGS/loop.log" 2>&1 &
  LOOP_PID=$!
  log "loop started pid=$LOOP_PID"
fi

# ── 2. Research Loop ──────────────────────────────────────────────────────────
RESEARCHER_PID=$(pgrep -f "research_loop.py" 2>/dev/null | head -1 || true)
RESEARCHER_STATUS="running"

if [[ -z "$RESEARCHER_PID" ]]; then
  RESEARCHER_STATUS="restarted"
  log "researcher dead — restarting"
  event "researcher_restart" "watchdog auto-restart"
  cd "$REPO/local-agents"
  nohup python3 scripts/research_loop.py >> "$LOGS/researcher.log" 2>&1 &
  RESEARCHER_PID=$!
  log "researcher started pid=$RESEARCHER_PID"
fi

# ── 3. Auto-Upgrade Trigger ───────────────────────────────────────────────────
SENTINEL="$REPORTS/last_upgrade_check"
touch -a "$SENTINEL" 2>/dev/null || true
LATEST=$(find "$REPORTS" -name "v*_compare.jsonl" -newer "$SENTINEL" 2>/dev/null | head -1 || true)
touch "$SENTINEL" 2>/dev/null || true

if [[ -n "$LATEST" ]]; then
  log "new version report — running gap analysis"
  event "upgrade_trigger" "$LATEST"
  cd "$REPO/local-agents"
  python3 agents/benchmarker.py --gap-only >> "$LOGS/upgrade.log" 2>&1 &
fi

# ── 4. Health Snapshot ────────────────────────────────────────────────────────
python3 - <<PYEOF
import json, os
health = {
    "ts": "$TS",
    "loop":       {"pid": ${LOOP_PID:-0},       "status": "$LOOP_STATUS"},
    "researcher": {"pid": ${RESEARCHER_PID:-0}, "status": "$RESEARCHER_STATUS"},
    "paused":     False,
    "watchdog":   "ok"
}
os.makedirs(os.path.dirname("$HEALTH"), exist_ok=True)
open("$HEALTH","w").write(json.dumps(health, indent=2))
PYEOF

log "ok — loop=$LOOP_STATUS(${LOOP_PID:-0}) researcher=$RESEARCHER_STATUS(${RESEARCHER_PID:-0})"
event "health_ok" "loop=$LOOP_STATUS researcher=$RESEARCHER_STATUS"
