#!/usr/bin/env python3
"""
watchdog_daemon.py — Self-healing daemon for the Nexus runtime.

Runs every 60s from a Terminal session (inherits user permissions).
Replaces cron/launchd which both fail on macOS 14+ without FDA grants.

Start: python3 scripts/watchdog_daemon.py &
Auto-start: added to ~/.zshrc (one instance only)
"""
import os
import sys
import json
import time
import signal
import subprocess
import logging
from pathlib import Path
from datetime import datetime, timezone

REPO = Path(__file__).parent.parent
LOCAL_AGENTS = REPO / "local-agents"
LOG_FILE = Path("/tmp/nexus-watchdog.log")
PID_FILE = Path("/tmp/nexus-watchdog.pid")
STOP_SCRIPT = REPO / "scripts" / "stop_loop.sh"
INTERVAL = 60
LOOP_STALE_S = 300  # 5 minutes without a completed task = stuck loop

logging.basicConfig(
    level=logging.INFO,
    format="[%(asctime)s] %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("watchdog")


def is_running(pattern: str) -> bool:
    r = subprocess.run(["pgrep", "-f", pattern], capture_output=True)
    return r.returncode == 0


def start(name: str, cmd: str, logfile: str):
    log.info(f"RESTART {name}")
    subprocess.Popen(
        f"nohup {cmd} >> {logfile} 2>&1 &",
        shell=True,
        close_fds=True,
    )


def is_loop_stuck(max_stale_s: int = LOOP_STALE_S) -> bool:
    """Return True if loop is running but no task completed in max_stale_s seconds."""
    try:
        from datetime import datetime, date, timezone
        today = date.today().strftime("%Y%m%d")
        loop_log = LOCAL_AGENTS / "reports" / f"loop_{today}.jsonl"
        if not loop_log.exists():
            return False  # no log yet, might be starting
        lines = loop_log.read_text().splitlines()
        if not lines:
            return False
        # find most recent task_done event
        for line in reversed(lines):
            try:
                record = json.loads(line)
                if record.get("event") == "task_done":
                    ts_str = record.get("ts", "")
                    if ts_str:
                        ts = datetime.fromisoformat(ts_str)
                        if ts.tzinfo is None:
                            ts = ts.replace(tzinfo=timezone.utc)
                        age = (datetime.now(timezone.utc) - ts).total_seconds()
                        return age > max_stale_s
            except Exception:
                continue
        return False
    except Exception:
        return False


def is_state_stale(max_age_s: int = 60) -> bool:
    """Return True if dashboard state.json ts is older than max_age_s seconds."""
    state_path = LOCAL_AGENTS / "dashboard" / "state.json"
    try:
        state = json.loads(state_path.read_text())
        ts_str = state.get("ts", "")
        if not ts_str:
            return True
        ts = datetime.fromisoformat(ts_str)
        if ts.tzinfo is None:
            ts = ts.replace(tzinfo=timezone.utc)
        age = (datetime.now(timezone.utc) - ts).total_seconds()
        return age > max_age_s
    except Exception:
        return True


def write_heartbeat(updater: bool, server: bool, loop: bool):
    hb = {
        "ts": datetime.now(timezone.utc).isoformat(),
        "live_state_updater": updater,
        "dashboard_server": server,
        "continuous_loop": loop,
    }
    hb_path = LOCAL_AGENTS / "reports" / "watchdog_heartbeat.json"
    hb_path.parent.mkdir(exist_ok=True)
    hb_path.write_text(json.dumps(hb, indent=2))
    status = "ALL OK" if updater and server else "RESTARTED"
    log.info(f"{status} | updater={updater} server={server} loop={loop}")


def tick():
    updater = is_running("live_state_updater.py")
    server = is_running("dashboard/server.py")
    loop = is_running("continuous_loop") or is_running("orchestrator/main.py")

    if not updater:
        start(
            "live_state_updater",
            f"python3 {LOCAL_AGENTS}/dashboard/live_state_updater.py",
            "/tmp/nexus-live-state.log",
        )
    elif is_state_stale(60):
        # Writer is running but state.json hasn't been updated in >60s — force restart
        log.warning("Dashboard state stale (>60s) — killing and restarting live_state_updater")
        subprocess.run(["pkill", "-f", "live_state_updater.py"], capture_output=True)
        time.sleep(1)
        start(
            "live_state_updater",
            f"python3 {LOCAL_AGENTS}/dashboard/live_state_updater.py",
            "/tmp/nexus-live-state.log",
        )

    if not server:
        start(
            "dashboard_server",
            f"python3 {LOCAL_AGENTS}/dashboard/server.py",
            "/tmp/nexus-dashboard.log",
        )
    if not loop:
        restart_marker = LOCAL_AGENTS / ".restart-loop"
        restart_marker.touch()
        start(
            "continuous_loop",
            f"python3 -m orchestrator.continuous_loop --forever --project all",
            "/tmp/nexus-loop.log",
        )
    elif is_loop_stuck(LOOP_STALE_S):
        # Loop is running but hasn't completed a task in 5+ minutes — stuck
        log.warning("Continuous loop stuck (no task in %ds) — restarting cleanly", LOOP_STALE_S)
        # Signal loop to exit gracefully via stop_loop.sh
        if STOP_SCRIPT.exists():
            subprocess.run(["bash", str(STOP_SCRIPT)], capture_output=True)
            time.sleep(5)
        # Kill if still running
        subprocess.run(["pkill", "-f", "continuous_loop"], capture_output=True)
        time.sleep(1)
        # Restart
        restart_marker = LOCAL_AGENTS / ".restart-loop"
        restart_marker.touch()
        start(
            "continuous_loop",
            f"python3 -m orchestrator.continuous_loop --forever --project all",
            "/tmp/nexus-loop.log",
        )

    write_heartbeat(
        is_running("live_state_updater.py"),
        is_running("dashboard/server.py"),
        is_running("continuous_loop"),
    )


def already_running() -> bool:
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            if pid != os.getpid():
                os.kill(pid, 0)  # raises if not running
                return True
        except (ProcessLookupError, ValueError):
            pass
    return False


def handle_signal(signum, frame):
    log.info("Watchdog daemon stopping.")
    PID_FILE.unlink(missing_ok=True)
    sys.exit(0)


def main():
    if already_running():
        print("Nexus watchdog already running — exiting.")
        sys.exit(0)

    PID_FILE.write_text(str(os.getpid()))
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    # Run from the repo root so `python3 -m orchestrator.*` resolves
    os.chdir(LOCAL_AGENTS)

    log.info(f"Nexus watchdog daemon started (pid={os.getpid()}, interval={INTERVAL}s)")
    try:
        while True:
            try:
                tick()
            except Exception as e:
                log.error(f"tick error: {e}")
            time.sleep(INTERVAL)
    finally:
        PID_FILE.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
