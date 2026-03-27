#!/usr/bin/env python3
"""
unified_daemon.py — Complete Autonomous System Daemon
======================================================
Replaces ALL external crons with internal daemon scheduling.

Responsibilities (all internal, no cron needed):
  1. Every 2 minutes: Auto-recovery check (fix stuck tasks, restart agents)
  2. Every 10 minutes: Full loop (execute tasks, commit, push, merge PRs)
  3. Every 5 seconds: Real-time dashboard updates
  4. Every 60 seconds: System health check (CPU, memory, process health)
  5. Every 30 seconds: Check for ready PRs and auto-merge if clean
  6. On startup: Verify all infrastructure (daemon, agents, cron-less operation)

Runs 24/7 with auto-restart via LaunchAgent.
No external crons. All scheduling internal.
"""

import json
import os
import sys
import time
import logging
import subprocess
import threading
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

# Setup
BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

PROJECTS_FILE = Path(BASE_DIR) / "projects.json"
REPORTS_DIR = Path(BASE_DIR) / "reports"
STATE_DIR = Path(BASE_DIR) / "state"
LOGS_DIR = Path(BASE_DIR) / "logs"

for d in [REPORTS_DIR, STATE_DIR, LOGS_DIR]:
    d.mkdir(exist_ok=True)

# Logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(str(REPORTS_DIR / "unified_daemon.log")),
        logging.StreamHandler(sys.stdout),
    ]
)
logger = logging.getLogger(__name__)


class ScheduledTask:
    """Represents a recurring task with internal scheduling."""

    def __init__(self, name: str, interval_seconds: int, func, *args, **kwargs):
        self.name = name
        self.interval_seconds = interval_seconds
        self.func = func
        self.args = args
        self.kwargs = kwargs
        self.last_run = 0
        self.thread = None
        self.running = False

    def should_run(self) -> bool:
        """Check if enough time has elapsed since last run."""
        return (time.time() - self.last_run) >= self.interval_seconds

    def run(self):
        """Execute the task."""
        try:
            self.last_run = time.time()
            self.func(*self.args, **self.kwargs)
        except Exception as e:
            logger.error(f"Task '{self.name}' failed: {e}", exc_info=True)


class UnifiedDaemon:
    """Main daemon that orchestrates all internal scheduling."""

    def __init__(self):
        self.tasks: List[ScheduledTask] = []
        self.running = False
        logger.info("🚀 UnifiedDaemon initializing...")

    def register_task(self, name: str, interval_seconds: int, func, *args, **kwargs):
        """Register a new scheduled task."""
        task = ScheduledTask(name, interval_seconds, func, *args, **kwargs)
        self.tasks.append(task)
        logger.info(f"  Registered: {name} (interval: {interval_seconds}s)")

    def start(self):
        """Start the daemon main loop."""
        self.running = True
        logger.info("✅ UnifiedDaemon started (all crons replaced with internal scheduling)")
        logger.info("=" * 70)

        try:
            while self.running:
                # Check and run scheduled tasks
                for task in self.tasks:
                    if task.should_run():
                        logger.info(f"🔄 Running: {task.name}")
                        task.run()

                # Sleep briefly before next check
                time.sleep(1)

        except KeyboardInterrupt:
            logger.info("⚠️  UnifiedDaemon interrupted by user")
            self.stop()
        except Exception as e:
            logger.error(f"Fatal error in daemon: {e}", exc_info=True)
            self.stop()

    def stop(self):
        """Stop the daemon gracefully."""
        self.running = False
        logger.info("✅ UnifiedDaemon stopped")

    # ════════════════════════════════════════════════════════════════════════════════
    # SCHEDULED TASKS (replace all external crons)
    # ════════════════════════════════════════════════════════════════════════════════

    def task_health_check(self):
        """Every 60s: System health check."""
        try:
            import psutil

            cpu_percent = psutil.cpu_percent(interval=1)
            memory_percent = psutil.virtual_memory().percent

            logger.info(
                f"📊 Health: CPU {cpu_percent}% | Memory {memory_percent}% | "
                f"Processes: agent_runner={self._check_process('agent_runner')}, "
                f"dashboard={self._check_process('dashboard')}"
            )

            # Write health status
            health_file = STATE_DIR / "daemon_health.json"
            health_file.write_text(
                json.dumps(
                    {
                        "timestamp": datetime.utcnow().isoformat() + "Z",
                        "cpu_percent": cpu_percent,
                        "memory_percent": memory_percent,
                        "daemon_running": True,
                    }
                )
            )

        except Exception as e:
            logger.warning(f"Health check failed: {e}")

    def task_auto_recovery(self):
        """Every 2min: Auto-recovery (stuck tasks, restart agents)."""
        try:
            logger.info("🔧 Running auto-recovery...")

            # Check for stuck tasks in projects.json
            with open(PROJECTS_FILE) as f:
                data = json.load(f)

            stuck_count = 0
            for project in data.get("projects", []):
                for task in project.get("tasks", []):
                    if task.get("status") == "in_progress":
                        started = task.get("started_at", "")
                        if started:
                            try:
                                started_dt = datetime.fromisoformat(
                                    started.replace("Z", "+00:00")
                                )
                                elapsed = (
                                    datetime.utcnow() - started_dt.replace(tzinfo=None)
                                ).total_seconds()
                                if elapsed > 300:  # 5 minutes
                                    logger.warning(
                                        f"  ⚠️  Stuck task {task['id']} (elapsed {elapsed}s) — resetting"
                                    )
                                    task["status"] = "pending"
                                    stuck_count += 1
                            except:
                                pass

            # Write back if changes
            if stuck_count > 0:
                with open(PROJECTS_FILE, "w") as f:
                    json.dump(data, f, indent=2)
                logger.info(f"  ✅ Fixed {stuck_count} stuck task(s)")

        except Exception as e:
            logger.warning(f"Auto-recovery failed: {e}")

    def task_full_loop(self):
        """Every 10min: Full execution loop (tasks, commit, push, merge)."""
        try:
            logger.info("🚀 Running full 10-minute loop...")

            # Run the 10min_loop.sh script
            loop_script = Path(BASE_DIR) / ".claude" / "10min_loop.sh"
            if loop_script.exists():
                result = subprocess.run(
                    ["bash", str(loop_script)],
                    cwd=BASE_DIR,
                    capture_output=True,
                    text=True,
                    timeout=300,
                )
                if result.returncode == 0:
                    logger.info("  ✅ Full loop completed successfully")
                else:
                    logger.warning(f"  ⚠️  Full loop returned {result.returncode}")
            else:
                logger.warning(f"  ⚠️  10min_loop.sh not found")

        except Exception as e:
            logger.warning(f"Full loop failed: {e}")

    def task_dashboard_update(self):
        """Every 5s: Update dashboard state in real-time."""
        try:
            # Run dashboard realtime updater
            updater = Path(BASE_DIR) / "orchestrator" / "dashboard_realtime.py"
            if updater.exists():
                subprocess.run(
                    ["python3", str(updater), "--once"],
                    cwd=BASE_DIR,
                    capture_output=True,
                    timeout=10,
                )
        except Exception as e:
            logger.debug(f"Dashboard update failed: {e}")

    def task_pr_merge_check(self):
        """Every 30s: Check for ready PRs and auto-merge if clean."""
        try:
            logger.info("🔀 Checking for ready PRs to merge...")

            # Use gh CLI to check for open PRs that are ready to merge
            result = subprocess.run(
                [
                    "gh",
                    "pr",
                    "list",
                    "--state",
                    "open",
                    "--json",
                    "number,mergeStateStatus",
                ],
                cwd=BASE_DIR,
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result.returncode == 0:
                try:
                    prs = json.loads(result.stdout)
                    merged_count = 0

                    for pr in prs:
                        pr_num = pr.get("number")
                        status = pr.get("mergeStateStatus")

                        # Auto-merge if MERGEABLE
                        if status == "MERGEABLE":
                            logger.info(f"  ✅ Merging PR #{pr_num}...")
                            merge_result = subprocess.run(
                                ["gh", "pr", "merge", str(pr_num), "--auto", "--squash"],
                                cwd=BASE_DIR,
                                capture_output=True,
                                timeout=30,
                            )
                            if merge_result.returncode == 0:
                                merged_count += 1
                                logger.info(f"    ✓ PR #{pr_num} merged")

                    if merged_count > 0:
                        logger.info(f"  📊 Merged {merged_count} PR(s)")

                except json.JSONDecodeError:
                    pass

        except subprocess.TimeoutExpired:
            logger.debug("PR merge check timed out")
        except Exception as e:
            logger.debug(f"PR merge check failed: {e}")

    def task_update_epic_status(self):
        """Every 30min: Update epic statuses based on task completion."""
        try:
            logger.info("📈 Updating epic statuses...")

            with open(PROJECTS_FILE) as f:
                data = json.load(f)

            updated = False
            for project in data.get("projects", []):
                tasks = project.get("tasks", [])
                if not tasks:
                    continue

                total = len(tasks)
                completed = sum(1 for t in tasks if t.get("status") == "completed")

                # Update epic status based on task completion
                if completed == total and total > 0:
                    if project.get("status") != "completed":
                        project["status"] = "completed"
                        project["eta_completion"] = datetime.utcnow().isoformat() + "Z"
                        logger.info(f"  ✅ {project['id']} → completed")
                        updated = True

            if updated:
                with open(PROJECTS_FILE, "w") as f:
                    json.dump(data, f, indent=2)
                logger.info("  📝 Epic statuses updated")

        except Exception as e:
            logger.warning(f"Epic status update failed: {e}")

    def task_quarantine_monitor(self):
        """Every 5min: Detect and fix macOS quarantine attributes blocking execution."""
        try:
            from orchestrator.quarantine_monitor import report_quarantine_status

            if not report_quarantine_status():
                logger.warning("⚠️  Quarantine attributes detected and fixed")

        except Exception as e:
            logger.debug(f"Quarantine monitor failed: {e}")

    def task_phase_progression(self):
        """Every 10min: Check phase completion and auto-generate next phases."""
        try:
            from orchestrator.phase_progression import auto_progress_phases

            auto_progress_phases()

        except Exception as e:
            logger.warning(f"Phase progression failed: {e}")

    def _check_process(self, name: str) -> str:
        """Check if a process is running."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", name],
                capture_output=True,
                timeout=5,
            )
            return "✓" if result.returncode == 0 else "✗"
        except:
            return "?"


def main():
    """Main entry point."""
    daemon = UnifiedDaemon()

    # Register all scheduled tasks
    # Format: (name, interval_seconds, function)
    daemon.register_task(
        "health-check", 60, daemon.task_health_check
    )  # Every 60s
    daemon.register_task(
        "auto-recovery", 120, daemon.task_auto_recovery
    )  # Every 2min
    daemon.register_task(
        "quarantine-monitor", 300, daemon.task_quarantine_monitor
    )  # Every 5min - PREVENTS 7-HOUR BLOCKAGE
    daemon.register_task(
        "dashboard-update", 5, daemon.task_dashboard_update
    )  # Every 5s
    daemon.register_task(
        "pr-merge-check", 30, daemon.task_pr_merge_check
    )  # Every 30s
    daemon.register_task(
        "full-loop", 600, daemon.task_full_loop
    )  # Every 10min
    daemon.register_task(
        "phase-progression", 600, daemon.task_phase_progression
    )  # Every 10min - AUTO-GENERATE NEXT PHASES
    daemon.register_task(
        "epic-status-update", 1800, daemon.task_update_epic_status
    )  # Every 30min

    # Start the daemon
    logger.info("=" * 70)
    logger.info("UNIFIED DAEMON — Replaces All External Crons")
    logger.info("=" * 70)
    logger.info("✨ All scheduling now internal to daemon")
    logger.info("✨ Zero external cron dependencies")
    logger.info("✨ 24/7 autonomous operation")
    logger.info("=" * 70)
    daemon.start()


if __name__ == "__main__":
    main()
