#!/usr/bin/env bash
# scripts/watchdog.sh — Never-down guardian for all local runtime processes
# Runs every minute via crontab. Restarts any dead process immediately.
# Part of the rescue protocol — if something dies, this brings it back.
#
# Crontab entry (already installed):
#   * * * * * /Users/jimmymalhan/Documents/local-agent-runtime/scripts/watchdog.sh >> /tmp/nexus-watchdog.log 2>&1

REPO="/Users/jimmymalhan/Documents/local-agent-runtime"
LOCAL_AGENTS="$REPO/local-agents"
LOG="/tmp/nexus-watchdog.log"
TS=$(date +"%Y-%m-%dT%H:%M:%S")

restart() {
  local name="$1"
  local cmd="$2"
  local logfile="$3"
  echo "[$TS] RESTART $name"
  eval "nohup $cmd >> $logfile 2>&1 &"
}

# ── 1. live_state_updater — dashboard data source ────────────────────────────
if ! pgrep -f "live_state_updater.py" > /dev/null; then
  restart "live_state_updater" \
    "python3 $LOCAL_AGENTS/dashboard/live_state_updater.py" \
    "/tmp/nexus-live-state.log"
fi

# ── 2. dashboard server — the UI itself ──────────────────────────────────────
if ! pgrep -f "dashboard/server.py" > /dev/null; then
  restart "dashboard_server" \
    "python3 $LOCAL_AGENTS/dashboard/server.py" \
    "/tmp/nexus-dashboard.log"
fi

# ── 3. continuous_loop orchestrator — main task engine ───────────────────────
if ! pgrep -f "continuous_loop" > /dev/null && \
   ! pgrep -f "orchestrator/main.py" > /dev/null; then
  # Only restart if a .restart-loop marker exists (set by user or auto-heal)
  if [ -f "$LOCAL_AGENTS/.restart-loop" ]; then
    rm -f "$LOCAL_AGENTS/.restart-loop"
    restart "continuous_loop" \
      "python3 -m orchestrator.continuous_loop --forever --project all" \
      "/tmp/nexus-loop.log"
  fi
fi

# ── 4. Heartbeat — write timestamp so dashboard can show watchdog status ─────
python3 - <<'EOF' 2>/dev/null
import json, os
from datetime import datetime, timezone
hb = {
  "ts": datetime.now(timezone.utc).isoformat(),
  "live_state_updater": bool(__import__('subprocess').run(['pgrep','-f','live_state_updater.py'], capture_output=True).returncode == 0),
  "dashboard_server":   bool(__import__('subprocess').run(['pgrep','-f','dashboard/server.py'],   capture_output=True).returncode == 0),
  "continuous_loop":    bool(__import__('subprocess').run(['pgrep','-f','continuous_loop'],        capture_output=True).returncode == 0),
}
path = "/Users/jimmymalhan/Documents/local-agent-runtime/local-agents/reports/watchdog_heartbeat.json"
os.makedirs(os.path.dirname(path), exist_ok=True)
open(path, "w").write(json.dumps(hb, indent=2))
all_ok = hb["live_state_updater"] and hb["dashboard_server"]
print(f'[{hb["ts"][:19]}] {"ALL OK" if all_ok else "RESTARTED"} | updater={hb["live_state_updater"]} server={hb["dashboard_server"]} loop={hb["continuous_loop"]}')
EOF
