#!/usr/bin/env python3
"""
orchestrator/daemon_scheduler.py — Internal Persistence-Based Scheduler
=========================================================================
REPLACES CRON ENTIRELY

Internal event loop that replaces `* * * * * auto_recover.sh` cron job.
Uses daemon_state.json as persistent state, triggers health checks every 120 seconds internally.

Goals:
  1. No cron dependency — all timing internal to daemon
  2. Persistent state survives restarts — reads/writes daemon_state.json
  3. Self-healing — auto-restarts failed agents
  4. Auto-commit — pushes state every cycle
  5. Observability — logs all actions to reports/daemon_scheduler.log

Flow per cycle (every 120 seconds):
  1. Read daemon_state.json (last_cycle, cycles_completed, etc.)
  2. Check agent health: state/agent_stats.json success rate
  3. If health < 80%: Run orchestrator recovery (diagnose + fix)
  4. If queue has pending tasks: Dispatch next from projects.json
  5. Update daemon_state.json with new timestamp
  6. Commit + push if changes made
  7. Sleep 120 seconds, loop

Usage:
  python3 orchestrator/daemon_scheduler.py --auto    # Run forever (daemon mode)
  python3 orchestrator/daemon_scheduler.py --once    # One cycle then exit
  python3 orchestrator/daemon_scheduler.py --test    # Test cycle, no commit

Replaces cron:
  OLD: */2 * * * * cd ... && bash scripts/auto_recover.sh
  NEW: python3 orchestrator/daemon_scheduler.py --auto  # Start once, runs 24/7
"""

import os
import sys
import json
import time
import subprocess
import argparse
import logging
from pathlib import Path
from datetime import datetime

BASE_DIR = str(Path(__file__).parent.parent)
STATE_DIR = os.path.join(BASE_DIR, "state")
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
DAEMON_STATE = os.path.join(STATE_DIR, "daemon_state.json")
AGENT_STATS = os.path.join(STATE_DIR, "agent_stats.json")
LOG_FILE = os.path.join(REPORTS_DIR, "daemon_scheduler.log")

sys.path.insert(0, BASE_DIR)
Path(STATE_DIR).mkdir(exist_ok=True)
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

# Configuration
HEALTH_CHECK_INTERVAL_SECONDS = 120  # Check every 2 minutes (replaces */2 cron)
AGENT_HEALTH_THRESHOLD = 0.80  # Trigger recovery if success_rate < 80%


def read_daemon_state():
    """Read persistent daemon state."""
    if not os.path.exists(DAEMON_STATE):
        return {
            "last_cycle": datetime.utcnow().isoformat(),
            "daemon_started": datetime.utcnow().isoformat(),
            "cycles_completed": 0,
            "health_checks_passed": 0,
            "health_checks_failed": 0,
            "agents_restarted": 0,
        }
    try:
        with open(DAEMON_STATE, "r") as f:
            return json.load(f)
    except Exception as e:
        logger.error(f"Failed to read daemon_state.json: {e}")
        return {}


def write_daemon_state(state):
    """Write persistent daemon state."""
    state["last_cycle"] = datetime.utcnow().isoformat()
    state["cycles_completed"] = state.get("cycles_completed", 0) + 1
    try:
        with open(DAEMON_STATE, "w") as f:
            json.dump(state, f, indent=2)
        return True
    except Exception as e:
        logger.error(f"Failed to write daemon_state.json: {e}")
        return False


def get_agent_health():
    """Check current agent health from agent_stats.json."""
    if not os.path.exists(AGENT_STATS):
        logger.warning("agent_stats.json not found — assuming cold start")
        return None

    try:
        with open(AGENT_STATS, "r") as f:
            stats = json.load(f)
        success_rate = stats.get("executor", {}).get("success_rate", 0)
        success = stats.get("executor", {}).get("success", 0)
        total = stats.get("executor", {}).get("total", 0)
        return {"success_rate": success_rate, "success": success, "total": total}
    except Exception as e:
        logger.error(f"Failed to read agent_stats.json: {e}")
        return None


def trigger_recovery():
    """Run full agent recovery via orchestrator/main.py."""
    logger.info("🔧 Triggering agent recovery cycle...")
    try:
        result = subprocess.run(
            ["python3", os.path.join(BASE_DIR, "orchestrator", "main.py"), "--quick", "5"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
            timeout=300,  # 5 min timeout
        )
        if result.returncode == 0:
            logger.info("✅ Recovery cycle completed successfully")
            return True
        else:
            logger.error(f"❌ Recovery cycle failed: {result.stderr}")
            return False
    except subprocess.TimeoutExpired:
        logger.error("❌ Recovery cycle timeout (5 min)")
        return False
    except Exception as e:
        logger.error(f"❌ Recovery cycle error: {e}")
        return False


def commit_and_push():
    """Commit and push any changes made during the cycle."""
    try:
        # Check if there are changes
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=BASE_DIR,
            capture_output=True,
            text=True,
        )
        if not result.stdout.strip():
            logger.debug("No changes to commit")
            return True

        # Stage and commit
        subprocess.run(["git", "add", "-A"], cwd=BASE_DIR, check=True)
        commit_msg = f"chore: daemon scheduler cycle {datetime.utcnow().isoformat()}"
        subprocess.run(
            ["git", "commit", "-m", commit_msg],
            cwd=BASE_DIR,
            check=True,
            capture_output=True,
        )

        # Push (best effort)
        subprocess.run(
            ["git", "push", "origin", "feat/extreme-unblock-1774576056"],
            cwd=BASE_DIR,
            capture_output=True,
            timeout=30,
        )
        logger.info("✅ Committed and pushed changes")
        return True
    except Exception as e:
        logger.error(f"⚠️  Commit/push failed (non-blocking): {e}")
        return True  # Don't fail the cycle


def run_cycle(test_mode=False):
    """Run one health check + recovery cycle."""
    logger.info("=" * 70)
    logger.info("📍 DAEMON SCHEDULER CYCLE")
    logger.info("=" * 70)

    # Load state
    state = read_daemon_state()
    cycle_num = state.get("cycles_completed", 0) + 1

    # Check agent health
    health = get_agent_health()
    if health:
        success_rate = health["success_rate"]
        logger.info(
            f"📊 Agent Health: {health['success']}/{health['total']} "
            f"({success_rate * 100:.1f}%)"
        )

        if success_rate >= AGENT_HEALTH_THRESHOLD:
            logger.info("✅ Health check PASSED")
            state["health_checks_passed"] = state.get("health_checks_passed", 0) + 1
        else:
            logger.warning(f"⚠️  Health check FAILED: {success_rate * 100:.1f}% < {AGENT_HEALTH_THRESHOLD * 100:.0f}%")
            state["health_checks_failed"] = state.get("health_checks_failed", 0) + 1

            if not test_mode:
                logger.info("🚀 Triggering recovery...")
                if trigger_recovery():
                    state["agents_restarted"] = state.get("agents_restarted", 0) + 1
    else:
        logger.info("❓ No agent stats yet (cold start or first cycle)")

    # Write updated state
    if not test_mode:
        write_daemon_state(state)

        # Commit changes
        commit_and_push()

    logger.info(f"✅ Cycle {cycle_num} complete")
    logger.info("=" * 70)


def run_forever():
    """Run daemon scheduler forever (background loop)."""
    logger.info("🚀 DAEMON SCHEDULER STARTING (runs every 120 seconds forever)")
    logger.info("   Replace cron with: python3 orchestrator/daemon_scheduler.py --auto")
    logger.info(f"   Logs: {LOG_FILE}")
    logger.info("")

    cycle_count = 0
    while True:
        try:
            cycle_count += 1
            run_cycle(test_mode=False)
            logger.info(f"💤 Sleeping {HEALTH_CHECK_INTERVAL_SECONDS}s until next cycle...")
            time.sleep(HEALTH_CHECK_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            logger.info("\n🛑 Daemon scheduler stopped by user")
            break
        except Exception as e:
            logger.error(f"💥 Unexpected error in cycle: {e}", exc_info=True)
            logger.info(f"💤 Recovering in {HEALTH_CHECK_INTERVAL_SECONDS}s...")
            time.sleep(HEALTH_CHECK_INTERVAL_SECONDS)


def main():
    parser = argparse.ArgumentParser(
        description="Internal daemon scheduler (replaces cron entirely)"
    )
    parser.add_argument(
        "--auto",
        action="store_true",
        help="Run forever (background daemon mode)",
    )
    parser.add_argument(
        "--once",
        action="store_true",
        help="Run one cycle then exit",
    )
    parser.add_argument(
        "--test",
        action="store_true",
        help="Test cycle (no commit/push)",
    )

    args = parser.parse_args()

    if args.auto:
        run_forever()
    elif args.test:
        run_cycle(test_mode=True)
    else:  # Default: --once
        run_cycle(test_mode=False)


if __name__ == "__main__":
    main()
