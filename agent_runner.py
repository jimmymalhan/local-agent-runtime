#!/usr/bin/env python3
"""
agent_runner.py — Autonomous Agent Orchestrator
================================================
Main daemon that:
- Reads task queue from projects.json (persistence layer)
- Dispatches tasks to agents in parallel
- Monitors completion and retries
- Runs 24/7 without external cron
- Self-healing with automatic restarts

No external cron needed. All scheduling internal to daemon.
"""

import json
import os
import sys
import time
import logging
from pathlib import Path
from datetime import datetime

# ── RESEARCH PATCHES (v5) ─────────────────────────────────
# Applied from frustration research on 2026-03-27
  # [truncation] CRITICAL: NEVER truncate code. Write the COMPLETE file every time. If output would be too long, split into multiple WRITE_FILE directives. Never use '...' or '# rest of code here'.
  # [imports] Always verify import paths before writing them. Use relative imports for local modules. Test every import mentally.
  # [assertions] After writing code, mentally trace through it with example inputs. Verify assertions would pass.
# ── END RESEARCH PATCHES ──────────────────────────────────────────
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, List, Optional

# Add project root to path so agents can be imported
sys.path.insert(0, str(Path(__file__).parent))

# ── BACKWARD COMPATIBILITY: Re-export agents.run_task ────────────
# Some modules import 'from agent_runner import run_task'
# Re-export it here for backward compatibility
try:
    from agents import run_task
except ImportError:
    def run_task(task: dict) -> dict:
        """Fallback if agents module not available."""
        raise ImportError('agents module not found — cannot dispatch tasks')

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[
        logging.FileHandler('reports/agent_runner.log'),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

BASE_DIR = Path(__file__).parent
PROJECTS_FILE = BASE_DIR / "projects.json"
STATE_DIR = BASE_DIR / "state"
REPORTS_DIR = BASE_DIR / "reports"

# Ensure directories exist
REPORTS_DIR.mkdir(exist_ok=True)
STATE_DIR.mkdir(exist_ok=True)


class AgentOrchestrator:
    """Orchestrates agent execution from persistent task queue."""

    def __init__(self, max_workers: int = 5, poll_interval: int = 10):
        """
        Initialize orchestrator.

        Args:
            max_workers: Max parallel agents
            poll_interval: Seconds between polling for new tasks
        """
        self.max_workers = max_workers
        self.poll_interval = poll_interval
        self.executor = ThreadPoolExecutor(max_workers=max_workers)
        self.running_tasks = {}
        self.health_check_interval = 60  # Health check every 60 seconds
        self.last_health_check = 0
        self.iteration_count = 0

    def health_check(self):
        """Internal health check (replaces external cron auto_recover.sh)."""
        try:
            # Verify projects.json is valid
            with open(PROJECTS_FILE, 'r') as f:
                json.load(f)

            # Check state directory
            STATE_DIR.mkdir(exist_ok=True)
            REPORTS_DIR.mkdir(exist_ok=True)

            logger.info(f"[HEALTH] Iteration {self.iteration_count} - all systems nominal")
            return True

        except json.JSONDecodeError:
            logger.error("[HEALTH] projects.json corrupted - recovery needed")
            try:
                # Attempt restore from git if available
                import subprocess
                subprocess.run(['git', 'checkout', 'HEAD', '--', str(PROJECTS_FILE)],
                             cwd=str(BASE_DIR), timeout=5)
                logger.info("[HEALTH] Restored projects.json from git")
            except Exception as e:
                logger.error(f"[HEALTH] Recovery failed: {e}")
            return False
        except Exception as e:
            logger.error(f"[HEALTH] Check failed: {e}")
            return False

    def load_tasks(self) -> List[Dict]:
        """Load pending tasks from projects.json."""
        try:
            with open(PROJECTS_FILE, 'r') as f:
                data = json.load(f)

            pending = []
            for project in data.get('projects', []):
                for task in project.get('tasks', []):
                    # Pick up pending or failed tasks (retry logic)
                    if task.get('status') in ['pending', 'failed', 'in_progress']:
                        # Check retry limit
                        attempts = task.get('attempts', 0)
                        max_attempts = task.get('max_attempts', 3)

                        if attempts < max_attempts:
                            pending.append(task)

            return pending
        except Exception as e:
            logger.error(f"Error loading tasks: {e}")
            return []

    def dispatch_task(self, task: Dict) -> bool:
        """
        Dispatch task to appropriate agent.

        Returns:
            bool: True if dispatch successful
        """
        task_id = task.get('id', 'unknown')

        try:
            logger.info(f"Dispatching task {task_id}")

            # Import agent interface
            from agents import run_task
            from agents.persistence import update_task_result, mark_task_attempted

            # Mark attempt before running
            mark_task_attempted(task_id)

            # Run agent (handles routing internally)
            start_time = time.time()
            result = run_task(task)
            elapsed = time.time() - start_time

            logger.info(f"Task {task_id} result: {result}")

            # Update persistence layer
            status = result.get('status', 'failed')
            quality = float(result.get('quality', result.get('quality_score', 0)))

            # Normalize status
            if status in ['completed', 'done', 'is_done']:
                status = 'completed'
            elif status in ['failed', 'error']:
                status = 'failed'
            else:
                status = 'pending'

            success = status == 'completed'
            error_msg = result.get('error', '')

            update_task_result(
                task_id=task_id,
                status=status,
                quality_score=quality,
                elapsed_time=elapsed,
                error_msg=error_msg
            )

            logger.info(f"Task {task_id} completed: status={status}, quality={quality}, elapsed={elapsed:.1f}s")
            return success

        except ImportError as e:
            logger.error(f"Import error for task {task_id}: {e}")
            return False
        except Exception as e:
            logger.error(f"Error dispatching task {task_id}: {e}", exc_info=True)
            return False

    def run_loop(self, duration_seconds: Optional[int] = None):
        """
        Main orchestration loop.
        Runs continuously until killed or duration expires.

        Args:
            duration_seconds: Max runtime (None = infinite)
        """
        start_time = time.time()
        iteration = 0

        logger.info(f"Starting agent orchestrator (workers={self.max_workers}, poll={self.poll_interval}s)")

        try:
            while True:
                # Check duration limit
                if duration_seconds and (time.time() - start_time) > duration_seconds:
                    logger.info(f"Duration limit reached ({duration_seconds}s)")
                    break

                iteration += 1
                self.iteration_count = iteration
                logger.info(f"=== Iteration {iteration} ===")

                # Run health check every 60 seconds (internal, no cron)
                if (time.time() - self.last_health_check) > self.health_check_interval:
                    self.health_check()
                    self.last_health_check = time.time()

                # Load pending tasks
                tasks = self.load_tasks()
                if not tasks:
                    logger.debug(f"No pending tasks, waiting {self.poll_interval}s...")
                    time.sleep(self.poll_interval)
                    continue

                logger.info(f"Found {len(tasks)} pending tasks")

                # Dispatch tasks in parallel
                futures = {}
                for task in tasks:
                    task_id = task.get('id')
                    future = self.executor.submit(self.dispatch_task, task)
                    futures[future] = task_id

                # Wait for results
                completed = 0
                failed = 0
                for future in as_completed(futures):
                    task_id = futures[future]
                    try:
                        success = future.result()
                        if success:
                            completed += 1
                        else:
                            failed += 1
                    except Exception as e:
                        logger.error(f"Task {task_id} raised exception: {e}")
                        failed += 1

                logger.info(f"Iteration {iteration} complete: {completed} succeeded, {failed} failed")

                # Wait before next poll
                time.sleep(self.poll_interval)

        except KeyboardInterrupt:
            logger.info("Orchestrator stopped by user")
        except Exception as e:
            logger.error(f"Orchestrator error: {e}", exc_info=True)
        finally:
            logger.info("Shutting down agent orchestrator")
            self.executor.shutdown(wait=True)


class DaemonManager:
    """Manages daemon state and auto-restart."""

    STATE_FILE = STATE_DIR / "orchestrator_state.json"

    @classmethod
    def record_start(cls):
        """Record daemon start time."""
        state = {
            'started_at': datetime.now().isoformat(),
            'iterations': 0,
            'status': 'running'
        }
        try:
            with open(cls.STATE_FILE, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            logger.error(f"Error recording daemon state: {e}")

    @classmethod
    def record_stop(cls, status: str = 'stopped'):
        """Record daemon stop."""
        try:
            with open(cls.STATE_FILE, 'r') as f:
                state = json.load(f)
        except:
            state = {}

        state['stopped_at'] = datetime.now().isoformat()
        state['status'] = status

        try:
            with open(cls.STATE_FILE, 'w') as f:
                json.dump(state, f)
        except Exception as e:
            logger.error(f"Error recording daemon state: {e}")

    @classmethod
    def should_restart(cls) -> bool:
        """Check if daemon should restart on crash."""
        try:
            with open(cls.STATE_FILE, 'r') as f:
                state = json.load(f)

            # Auto-restart if crashed
            return state.get('status') != 'stopped_by_user'
        except:
            return True


def main():
    """Entry point for agent runner daemon."""
    import argparse

    parser = argparse.ArgumentParser(description='Autonomous agent orchestrator')
    parser.add_argument('--workers', type=int, default=5, help='Max parallel agents')
    parser.add_argument('--poll', type=int, default=10, help='Poll interval (seconds)')
    parser.add_argument('--duration', type=int, help='Max runtime (seconds)')

    args = parser.parse_args()

    logger.info(f"Agent Runner v1.0 starting (workers={args.workers}, poll={args.poll}s)")

    # Record daemon start
    DaemonManager.record_start()

    try:
        orchestrator = AgentOrchestrator(
            max_workers=args.workers,
            poll_interval=args.poll
        )
        orchestrator.run_loop(duration_seconds=args.duration)
    finally:
        DaemonManager.record_stop('stopped')


if __name__ == '__main__':
    main()
