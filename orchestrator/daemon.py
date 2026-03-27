#!/usr/bin/env python3
"""
daemon.py — Event-Driven Orchestrator Daemon
=============================================
Replaces cron-based execution with persistent daemon that watches projects.json
for state changes and automatically triggers task execution.

No cron. No external scheduling. Pure event-driven internal scheduling.
"""

import os
import sys
import json
import time
import subprocess
import threading
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

PROJECTS_FILE = BASE_DIR / "projects.json"
DAEMON_PID_FILE = BASE_DIR / ".daemon_pid"
LAST_HASH_FILE = BASE_DIR / ".last_projects_hash"


def file_hash(path):
    """Quick hash to detect projects.json changes."""
    try:
        with open(path, 'rb') as f:
            return hash(f.read())
    except:
        return None


def load_projects():
    """Load current projects.json state."""
    try:
        with open(PROJECTS_FILE) as f:
            return json.load(f)
    except:
        return None


def get_next_pending_task():
    """Find first pending task that hasn't been attempted recently."""
    data = load_projects()
    if not data:
        return None

    for project in data.get('projects', []):
        for task in project.get('tasks', []):
            if task.get('status') == 'pending':
                return task.get('id'), project.get('id')
    return None


def check_token_budget():
    """Check if rescue budget is available."""
    try:
        enforcer_file = BASE_DIR / 'orchestrator' / '.token_budget'
        if enforcer_file.exists():
            with open(enforcer_file) as f:
                budget = json.load(f)
                return budget.get('rescues_used', 0) < 1
    except:
        return True  # Default: allow if can't check
    return True


def execute_next_task():
    """Execute one pending task."""
    task_id, project_id = get_next_pending_task() or (None, None)

    if not task_id:
        return False  # No pending tasks

    print(f"\n[DAEMON] Executing pending task: {task_id} from {project_id}")
    print(f"[DAEMON] Timestamp: {datetime.now().isoformat()}")

    try:
        result = subprocess.run(
            [
                sys.executable,
                str(BASE_DIR / 'orchestrator' / 'main.py'),
                '--version', '1',
                '--quick', '1'
            ],
            cwd=str(BASE_DIR),
            capture_output=True,
            timeout=120,
            text=True
        )

        print(f"[DAEMON] Execution completed (exit code: {result.returncode})")

        # Log output
        log_file = BASE_DIR / 'reports' / f'daemon_{datetime.now().timestamp()}.log'
        log_file.parent.mkdir(exist_ok=True)
        with open(log_file, 'w') as f:
            f.write(result.stdout)
            if result.stderr:
                f.write("\n[STDERR]\n" + result.stderr)

        return True
    except subprocess.TimeoutExpired:
        print(f"[DAEMON] ERROR: Task execution timed out")
        return False
    except Exception as e:
        print(f"[DAEMON] ERROR: {e}")
        return False


def watch_and_execute():
    """Main daemon loop: watch projects.json and execute on changes."""
    print("\n" + "="*70)
    print("EVENT-DRIVEN ORCHESTRATOR DAEMON STARTED")
    print("="*70)
    print(f"[DAEMON] Watching: {PROJECTS_FILE}")
    print(f"[DAEMON] No cron. Event-driven execution.")
    print(f"[DAEMON] PID: {os.getpid()}")
    print("="*70 + "\n")

    last_hash = None
    last_execution_time = 0
    min_interval = 10  # Minimum 10 seconds between executions

    try:
        while True:
            # Check if projects.json changed
            current_hash = file_hash(PROJECTS_FILE)

            if current_hash and current_hash != last_hash:
                # File changed - check for pending tasks
                time_since_last = time.time() - last_execution_time

                if time_since_last >= min_interval:
                    task_info = get_next_pending_task()

                    if task_info:
                        print(f"\n[DAEMON] File change detected at {datetime.now().isoformat()}")
                        print(f"[DAEMON] Pending task found: {task_info[0]}")

                        if check_token_budget():
                            execute_next_task()
                            last_execution_time = time.time()
                        else:
                            print(f"[DAEMON] Token budget exhausted, pausing execution")

                    last_hash = current_hash
                else:
                    print(f"[DAEMON] Throttling (executed {time_since_last:.1f}s ago)")

            # Sleep briefly before checking again
            time.sleep(2)

    except KeyboardInterrupt:
        print("\n[DAEMON] Shutdown requested")
    except Exception as e:
        print(f"[DAEMON] FATAL: {e}")
    finally:
        # Clean up
        try:
            DAEMON_PID_FILE.unlink()
        except:
            pass
        print("[DAEMON] Daemon stopped")


def start_daemon():
    """Start the daemon in background."""
    # Check if already running
    if DAEMON_PID_FILE.exists():
        try:
            with open(DAEMON_PID_FILE) as f:
                old_pid = int(f.read().strip())
            # Check if process still exists
            os.kill(old_pid, 0)
            print(f"[DAEMON] Already running (PID: {old_pid})")
            return
        except:
            pass

    # Start daemon in background
    pid = os.fork() if hasattr(os, 'fork') else None

    if pid is None:
        # Windows or single-process mode
        print("[DAEMON] Starting in foreground (no fork available)")
        with open(DAEMON_PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        watch_and_execute()
    elif pid == 0:
        # Child process
        with open(DAEMON_PID_FILE, 'w') as f:
            f.write(str(os.getpid()))
        watch_and_execute()
        sys.exit(0)
    else:
        # Parent process
        print(f"[DAEMON] Started in background (PID: {pid})")


if __name__ == '__main__':
    if len(sys.argv) > 1 and sys.argv[1] == 'start':
        start_daemon()
    elif len(sys.argv) > 1 and sys.argv[1] == 'stop':
        if DAEMON_PID_FILE.exists():
            with open(DAEMON_PID_FILE) as f:
                pid = int(f.read().strip())
            try:
                os.kill(pid, 15)
                print(f"[DAEMON] Stopped (PID: {pid})")
            except:
                print("[DAEMON] Process not running")
        else:
            print("[DAEMON] Not running")
    else:
        watch_and_execute()
