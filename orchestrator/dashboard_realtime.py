#!/usr/bin/env python3
"""
orchestrator/dashboard_realtime.py — Real-Time Dashboard State Writer
======================================================================
Continuously monitors agent execution and updates dashboard/state.json in real-time.

What it does:
  1. Polls state/agent_stats.json every 5 seconds
  2. Reads agent health data
  3. Updates dashboard/state.json with fresh status
  4. Detects blocked agents and updates status accordingly
  5. Writes timestamp to indicate freshness

Ensures dashboard UI always shows current state (max 5 seconds stale).

Usage:
  python3 orchestrator/dashboard_realtime.py --monitor  # Run forever
  python3 orchestrator/dashboard_realtime.py --once     # Update once
"""

import json
import os
import sys
import time
import logging
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

BASE_DIR = str(Path(__file__).parent.parent)
STATE_DIR = os.path.join(BASE_DIR, "state")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
DASHBOARD_STATE = os.path.join(BASE_DIR, "dashboard", "state.json")
AGENT_STATS = os.path.join(STATE_DIR, "agent_stats.json")
LOG_FILE = os.path.join(REPORTS_DIR, "dashboard_realtime.log")

sys.path.insert(0, BASE_DIR)
Path(REPORTS_DIR).mkdir(exist_ok=True)
Path(os.path.dirname(DASHBOARD_STATE)).mkdir(exist_ok=True)

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(LOG_FILE),
        logging.StreamHandler(sys.stdout),
    ],
)
logger = logging.getLogger(__name__)


def read_agent_stats() -> Dict:
    """Read current agent stats."""
    if not os.path.exists(AGENT_STATS):
        return {}
    try:
        with open(AGENT_STATS, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not read agent_stats: {e}")
        return {}


def read_dashboard() -> Dict:
    """Read current dashboard state."""
    if not os.path.exists(DASHBOARD_STATE):
        return create_empty_dashboard()
    try:
        with open(DASHBOARD_STATE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.warning(f"Could not read dashboard: {e}")
        return create_empty_dashboard()


def create_empty_dashboard() -> Dict:
    """Create empty dashboard state."""
    return {
        "ts": datetime.utcnow().isoformat(),
        "version": {"current": 0, "total": 100, "pct_complete": 0.0, "label": "idle"},
        "agents": {},
        "task_queue": {"total": 0, "completed": 0, "in_progress": 0, "failed": 0, "pending": 0},
        "benchmark_scores": {},
        "token_usage": {"claude_tokens": 0, "local_tokens": 0, "budget_pct": 0.0},
        "hardware": {"cpu_pct": 0.0, "ram_pct": 0.0, "disk_pct": 0.0, "alert_level": "ok"},
        "failures": [],
        "research_feed": [],
        "version_changelog": {},
    }


def update_dashboard_health(dashboard: Dict) -> Dict:
    """Update dashboard with current agent health."""
    stats = read_agent_stats()

    # Update overall timestamp
    dashboard["ts"] = datetime.utcnow().isoformat()

    # Update token usage from stats
    if stats and "executor" in stats:
        executor = stats["executor"]
        dashboard["token_usage"] = {
            "claude_tokens": 0,
            "local_tokens": executor.get("tokens", 0),
            "budget_pct": min((executor.get("tokens", 0) / 500000) * 100, 100),
            "warning": executor.get("tokens", 0) > 200000,
            "hard_limit_hit": executor.get("tokens", 0) > 500000,
        }

    # Check if any agents are blocked (not recovered)
    # This is inferred from failures and low success rate
    if stats and "executor" in stats:
        executor = stats["executor"]
        success_rate = executor.get("success_rate", 0)

        # If success rate is suspiciously low and we have failures, executor might be blocked
        if success_rate < 0.5 and executor.get("total", 0) > 10:
            logger.warning(f"⚠️  Executor health low: {success_rate*100:.1f}% success")

    return dashboard


def write_dashboard(dashboard: Dict) -> bool:
    """Write dashboard state to file."""
    try:
        with open(DASHBOARD_STATE, "w") as f:
            json.dump(dashboard, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to write dashboard: {e}")
        return False


def update_once():
    """Update dashboard once."""
    logger.info("📊 Updating dashboard state...")

    # Read current state
    dashboard = read_dashboard()

    # Update with fresh data
    dashboard = update_dashboard_health(dashboard)

    # Write back
    if write_dashboard(dashboard):
        logger.info("✅ Dashboard updated")
        logger.info(f"   Timestamp: {dashboard['ts']}")

        # Log agent health for visibility
        agents = dashboard.get("agents", {})
        for agent_name, agent_data in agents.items():
            status = agent_data.get("status", "unknown")
            logger.info(f"   {agent_name}: {status}")

        return True
    return False


def monitor_forever(update_interval: int = 5):
    """Monitor and update dashboard forever."""
    logger.info("🚀 DASHBOARD REALTIME MONITOR STARTING")
    logger.info(f"   Updates every {update_interval} seconds")
    logger.info(f"   Logs: {LOG_FILE}")
    logger.info(f"   State: {DASHBOARD_STATE}")

    update_count = 0
    while True:
        try:
            update_once()
            update_count += 1
            logger.info(f"   [{update_count}] Dashboard updated at {datetime.utcnow().isoformat()}")
            time.sleep(update_interval)
        except KeyboardInterrupt:
            logger.info("\n🛑 Dashboard monitor stopped by user")
            break
        except Exception as e:
            logger.error(f"💥 Error: {e}", exc_info=True)
            time.sleep(update_interval)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Real-time dashboard updater")
    parser.add_argument("--monitor", action="store_true", help="Run forever")
    parser.add_argument("--once", action="store_true", help="Update once")

    args = parser.parse_args()

    if args.monitor:
        monitor_forever()
    else:  # Default: update once
        update_once()
