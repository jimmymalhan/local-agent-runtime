#!/usr/bin/env python3
"""
orchestrator/blocker_monitor.py — Autonomous Agent Blocker Detection & Auto-Fix
================================================================================
Monitors dashboard state for blocked agents and autonomously fixes them.

What it does:
  1. Reads dashboard/state.json every 30 seconds
  2. Detects if any agent status = "blocked"
  3. Analyzes the failure reason
  4. Auto-applies fix (restarts, prompt upgrade, etc.)
  5. Logs all actions to reports/blocker_monitor.log

Integrated with daemon_scheduler.py for continuous monitoring.

Usage:
  python3 orchestrator/blocker_monitor.py --monitor    # Run forever
  python3 orchestrator/blocker_monitor.py --once       # Check once
"""

import json
import os
import sys
import time
import logging
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

BASE_DIR = str(Path(__file__).parent.parent)
STATE_DIR = os.path.join(BASE_DIR, "state")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
DASHBOARD_STATE = os.path.join(BASE_DIR, "dashboard", "state.json")
LOG_FILE = os.path.join(REPORTS_DIR, "blocker_monitor.log")

sys.path.insert(0, BASE_DIR)
Path(REPORTS_DIR).mkdir(exist_ok=True)

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


def read_dashboard_state() -> Dict:
    """Read current dashboard state."""
    if not os.path.exists(DASHBOARD_STATE):
        return {}
    try:
        with open(DASHBOARD_STATE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read dashboard: {e}")
        return {}


def detect_blocked_agents(state: Dict) -> List[str]:
    """Find all agents with status='blocked' OR stale (inactive > 10 min)."""
    agents = state.get("agents", {})
    blocked = []
    now = datetime.utcnow()
    STALE_THRESHOLD = 600  # 10 minutes in seconds

    for agent_name, agent_data in agents.items():
        if not isinstance(agent_data, dict):
            continue

        status = agent_data.get("status")

        # Check for explicitly blocked agents
        if status == "blocked":
            blocked.append(agent_name)
            continue

        # Check for stale agents (elapsed > 10 min)
        last_activity = agent_data.get("last_activity", "")
        if last_activity:
            try:
                last_ts = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
                elapsed = (now - last_ts).total_seconds()

                if elapsed > STALE_THRESHOLD:
                    # Mark as stale blocker
                    blocked.append(agent_name)
                    logger.debug(f"  Detected stale agent: {agent_name} (inactive {elapsed/60:.0f}min)")
            except Exception as e:
                logger.debug(f"  Could not parse activity time for {agent_name}: {e}")

    return blocked


def get_failure_reason(state: Dict, agent_name: str) -> Optional[str]:
    """Extract failure reason for a blocked agent."""
    failures = state.get("failures", [])
    for failure in failures:
        if failure.get("agent") == agent_name:
            return failure.get("tried", "unknown error")
    return None


def fix_import_error(agent_name: str, error: str) -> bool:
    """Auto-fix common import errors."""
    if "cannot import name" not in error and "No module named" not in error:
        return False

    logger.info(f"🔧 Attempting auto-fix for import error: {error[:80]}...")

    # Common fixes
    fixes = [
        # Fix 1: agent_runner.run_task missing
        {
            "error": "cannot import name 'run_task' from 'agent_runner'",
            "action": "Re-export run_task in agent_runner.py",
            "cmd": "python3 -c \"from agents import run_task; exec('with open(\\\"agent_runner.py\\\", \\\"a\\\") as f: f.write(\\\"\\\\n\\\\n# Backward compat\\\\nfrom agents import run_task\\\\n\\\")')\"",
        },
        # Fix 2: sys.path issues
        {
            "error": "No module named 'scripts'",
            "action": "Add scripts/ to sys.path",
            "cmd": "grep -l 'sys.path' orchestrator/*.py | xargs -I {} sed -i '' 's|sys.path.insert(0, BASE_DIR)|sys.path.insert(0, os.path.join(BASE_DIR, \"scripts\"))|g' {}",
        },
    ]

    for fix in fixes:
        if fix["error"] in error:
            logger.info(f"✅ Applying fix: {fix['action']}")
            try:
                os.system(f"cd {BASE_DIR} && {fix['cmd']}")
                logger.info(f"   ✅ Fix applied for {agent_name}")
                return True
            except Exception as e:
                logger.error(f"   ❌ Fix failed: {e}")
                return False

    return False


def escalate_to_prompt_upgrade(agent_name: str, failure_reason: str) -> bool:
    """Trigger prompt upgrade via rescue system."""
    logger.warning(
        f"⚠️  Could not auto-fix {agent_name} with code fix. "
        f"Escalating to prompt upgrade..."
    )

    # Write to rescue_queue.json for Claude to handle
    rescue_queue_path = os.path.join(STATE_DIR, "rescue_queue.json")
    try:
        queue = json.load(open(rescue_queue_path, "r")) if os.path.exists(rescue_queue_path) else []
        queue.append({
            "ts": datetime.utcnow().isoformat(),
            "agent": agent_name,
            "reason": failure_reason,
            "status": "pending",
            "attempt_count": 3,
        })
        with open(rescue_queue_path, "w") as f:
            json.dump(queue, f, indent=2)
        logger.info(f"✅ Escalated {agent_name} to rescue queue (Claude will upgrade prompt)")
        return True
    except Exception as e:
        logger.error(f"❌ Could not write rescue queue: {e}")
        return False


def restart_agent(agent_name: str) -> bool:
    """Restart a blocked/stale agent by clearing its state and task."""
    logger.info(f"🔄 Restarting agent: {agent_name}...")
    try:
        # Clear stuck state from runtime-lessons (it's a list, not dict)
        lessons_path = os.path.join(STATE_DIR, "runtime-lessons.json")
        if os.path.exists(lessons_path):
            try:
                lessons = json.load(open(lessons_path))
                # If it's a list, clear it for fresh start
                if isinstance(lessons, list):
                    # Reset to empty list (fresh state)
                    lessons = []
                else:
                    # If dict, clear attempts for this agent
                    for task_id in list(lessons.keys()):
                        if "task" in str(task_id) or task_id == agent_name:
                            if task_id in lessons:
                                lessons[task_id] = {"attempts": []}

                with open(lessons_path, "w") as f:
                    json.dump(lessons, f, indent=2)
                logger.debug(f"  Cleared runtime lessons for {agent_name}")
            except Exception as e:
                logger.debug(f"  Could not clear lessons: {e}")

        # Clear agent task assignment and reset status in dashboard
        dashboard_path = os.path.join(BASE_DIR, "dashboard", "state.json")
        if os.path.exists(dashboard_path):
            with open(dashboard_path, "r") as f:
                state = json.load(f)

            if agent_name in state.get("agents", {}):
                agent = state["agents"][agent_name]
                # Clear stale task and reset status
                agent["task"] = ""
                agent["status"] = "idle"
                agent["last_activity"] = datetime.utcnow().isoformat()
                logger.info(f"  Reset {agent_name} to idle")

            with open(dashboard_path, "w") as f:
                json.dump(state, f, indent=2)

        logger.info(f"✅ Agent {agent_name} restarted (state + task cleared)")
        return True
    except Exception as e:
        logger.error(f"❌ Restart failed: {e}")
        return False


def monitor_once():
    """Run one monitoring cycle."""
    logger.info("=" * 70)
    logger.info("📍 BLOCKER MONITOR CYCLE")
    logger.info("=" * 70)

    state = read_dashboard_state()
    blocked = detect_blocked_agents(state)

    if not blocked:
        logger.info("✅ No blocked agents detected")
        return

    logger.warning(f"⚠️  {len(blocked)} blocked agent(s) detected: {blocked}")

    for agent_name in blocked:
        logger.info(f"\n🔍 Analyzing {agent_name}...")
        failure_reason = get_failure_reason(state, agent_name)
        logger.info(f"   Failure: {failure_reason}")

        # Try code-based fix first
        if failure_reason and fix_import_error(agent_name, failure_reason):
            logger.info(f"   ✅ Fixed via code change")
            continue

        # Try agent restart
        if restart_agent(agent_name):
            logger.info(f"   ✅ Restarted agent")
            continue

        # Escalate to rescue (Claude will upgrade prompt)
        escalate_to_prompt_upgrade(agent_name, failure_reason or "unknown")

    logger.info("\n" + "=" * 70)
    logger.info("✅ Blocker monitor cycle complete")


def monitor_forever(check_interval: int = 30):
    """Run monitor forever (background daemon loop)."""
    logger.info("🚀 BLOCKER MONITOR STARTING (runs forever, checks every 30s)")
    logger.info(f"   Logs: {LOG_FILE}")

    while True:
        try:
            monitor_once()
            time.sleep(check_interval)
        except KeyboardInterrupt:
            logger.info("\n🛑 Blocker monitor stopped by user")
            break
        except Exception as e:
            logger.error(f"💥 Unexpected error: {e}", exc_info=True)
            time.sleep(check_interval)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Agent blocker monitor")
    parser.add_argument("--monitor", action="store_true", help="Run forever")
    parser.add_argument("--once", action="store_true", help="Run once")

    args = parser.parse_args()

    if args.monitor:
        monitor_forever()
    else:  # Default: run once
        monitor_once()
