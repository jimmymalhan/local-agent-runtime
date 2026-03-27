#!/usr/bin/env python3
"""
persistent_executor.py - PERSISTENT TASK EXECUTOR (v2 - Real Orchestrator Integration)

Ensures orchestrator NEVER goes idle. Integrated with real orchestrator.py:

1. Continuously loads pending tasks from projects.json
2. Spawns orchestrator main.py in --auto mode to execute pending tasks
3. Waits for orchestrator to complete that version
4. Orchestrator updates projects.json with completions
5. Persistent executor checks for remaining tasks and loops
6. If no tasks, waits and retries (never exits)

This ensures:
- Real agent execution (not just simulated completions)
- Full orchestrator features (routing, Opus fallback, self-heal, etc.)
- Persistent execution without manual intervention
- Graceful handling of failures via orchestrator's built-in retry logic
"""

import json
import os
import sys
import time
import subprocess
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
PROJECTS_FILE = BASE_DIR / "projects.json"

def count_pending_tasks():
    """Count pending tasks in projects.json"""
    try:
        with open(PROJECTS_FILE) as f:
            data = json.load(f)

        pending = sum(
            1 for p in data.get('projects', [])
            for t in p.get('tasks', [])
            if t.get('status') == 'pending'
        )
        total = sum(
            1 for p in data.get('projects', [])
            for t in p.get('tasks', [])
        )
        return pending, total
    except Exception as e:
        print(f"[EXECUTOR] Error counting tasks: {e}")
        return 0, 0

def run_orchestrator_version(version: int):
    """
    Spawn orchestrator in --auto mode to execute one version.
    Orchestrator will:
    - Load all pending tasks from projects.json
    - Route each to appropriate agent
    - Compare with Opus 4.6
    - Update projects.json with results
    - Exit after version complete
    """
    try:
        print(f"[EXECUTOR] ═════════════════════════════════════════════════")
        print(f"[EXECUTOR] 🚀 Spawning orchestrator v{version}")
        print(f"[EXECUTOR] ═════════════════════════════════════════════════")

        result = subprocess.run(
            [
                "python3",
                str(BASE_DIR / "orchestrator" / "main.py"),
                "--auto", str(version)
            ],
            timeout=3600,  # 1 hour max per version
            text=True
        )

        if result.returncode == 0:
            print(f"[EXECUTOR] ✅ Orchestrator v{version} completed successfully")
            return True
        else:
            print(f"[EXECUTOR] ⚠️  Orchestrator v{version} exited with code {result.returncode}")
            return True  # Still continue to next version

    except subprocess.TimeoutExpired:
        print(f"[EXECUTOR] ⚠️  Orchestrator v{version} timeout (>1h)")
        return True
    except Exception as e:
        print(f"[EXECUTOR] ❌ Failed to spawn orchestrator v{version}: {e}")
        return True

def persistent_loop():
    """
    Main persistent executor loop.

    NEVER exits. Continuously:
    1. Checks for pending tasks
    2. Spawns orchestrator to execute them
    3. Waits for orchestrator to finish and update projects.json
    4. Loops to check for more tasks

    This ensures complete task execution at persistence layer.
    """
    print("[EXECUTOR] 🚀 PERSISTENT EXECUTOR STARTED (v2 - Real Orchestrator)")
    print("[EXECUTOR] ════════════════════════════════════════════════════════")
    print("[EXECUTOR] • Continuously checks for pending tasks every 30 seconds")
    print("[EXECUTOR] • Spawns orchestrator in --auto mode for each version")
    print("[EXECUTOR] • Orchestrator updates projects.json with completions")
    print("[EXECUTOR] • NEVER exits until ALL tasks complete")
    print("[EXECUTOR] • NEVER goes idle (waits for new tasks if needed)")
    print("[EXECUTOR] ════════════════════════════════════════════════════════")

    version = 1
    check_interval = 5  # Check every 5 seconds (was 30s - 6x faster)
    last_check = 0
    version = 1

    while True:
        try:
            now = time.time()

            # Check for pending tasks more frequently (5s = rapid response)
            if now - last_check > check_interval:
                pending, total = count_pending_tasks()
                progress = 100 * (total - pending) / total if total > 0 else 0

                print(f"[EXECUTOR] Status check: {pending} pending, {total} total ({progress:.1f}% complete)")
                last_check = now

                if pending > 0:
                    print(f"[EXECUTOR] 📊 Running orchestrator v{version} to process {pending} pending tasks")
                    run_orchestrator_version(version)
                    version += 1

                    # After orchestrator runs, immediately recheck (don't wait interval)
                    pending_new, _ = count_pending_tasks()
                    if pending_new < pending:
                        print(f"[EXECUTOR] ✅ Progress: {pending} → {pending_new} pending tasks")
                    else:
                        print(f"[EXECUTOR] ⚠️  No progress on version {version-1}")

                else:
                    print(f"[EXECUTOR] ⏳ ALL {total} TASKS COMPLETED! 🎉")
                    print(f"[EXECUTOR] Waiting for new tasks... (checking every {check_interval}s)")

            time.sleep(1)  # Brief sleep to avoid busy-waiting

        except KeyboardInterrupt:
            print("[EXECUTOR] Interrupted by user")
            break
        except Exception as e:
            print(f"[EXECUTOR] Error in main loop: {e}")
            time.sleep(5)

if __name__ == '__main__':
    try:
        persistent_loop()
    except Exception as e:
        print(f"[EXECUTOR] FATAL ERROR: {e}")
        sys.exit(1)
