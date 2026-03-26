#!/usr/bin/env bash
# rescue_orchestrator.sh — Bulletproof orchestrator guardian
# Cron: * * * * * (every minute — never goes down)
# The only script that matters if everything else fails.

REPO="/Users/jimmymalhan/Documents/local-agent-runtime"
AGENTS="$REPO/local-agents"
LOGS="$AGENTS/logs"
STOP="$AGENTS/.stop"

mkdir -p "$LOGS"
TS=$(date -u +"%Y-%m-%dT%H:%M:%SZ")

[[ -f "$STOP" ]] && exit 0

# ── Orchestrator (main loop) ──────────────────────────────────────────────────
if ! pgrep -f "orchestrator/main.py" > /dev/null 2>&1; then
  echo "[$TS] orchestrator dead — restarting" >> "$LOGS/rescue_orchestrator.log"
  cd "$AGENTS"
  nohup python3 orchestrator/main.py --auto 1 >> "$LOGS/loop.log" 2>&1 &
  echo "[$TS] orchestrator started pid=$!" >> "$LOGS/rescue_orchestrator.log"
fi

# ── Researcher ────────────────────────────────────────────────────────────────
if ! pgrep -f "research_loop.py" > /dev/null 2>&1; then
  echo "[$TS] researcher dead — restarting" >> "$LOGS/rescue_orchestrator.log"
  cd "$AGENTS"
  nohup python3 scripts/research_loop.py >> "$LOGS/researcher.log" 2>&1 &
  echo "[$TS] researcher started pid=$!" >> "$LOGS/rescue_orchestrator.log"
fi
