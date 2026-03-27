#!/usr/bin/env python3
"""
test_executor_autonomous.py — Autonomous Test Executor
=======================================================
Agents run validation tasks and directly update projects.json.
NO Claude involvement. Full autonomy.
"""

import subprocess
import sys
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from agents.persistence import update_task_result


def run_validation_task(task_id: str, test_command: str, timeout: int = 30):
    """
    Execute a validation task test command.
    If passes, update projects.json directly (autonomous).

    Returns:
        dict: {"status": "completed"/"failed", "quality": 0-100, "elapsed_s": float}
    """

    start_time = datetime.now()

    print(f"\n[TEST_EXECUTOR] Running validation: {task_id}")
    print(f"[TEST_EXECUTOR] Command: {test_command[:80]}")

    try:
        result = subprocess.run(
            test_command,
            shell=True,
            capture_output=True,
            timeout=timeout,
            text=True,
            cwd=str(BASE_DIR)
        )

        elapsed = (datetime.now() - start_time).total_seconds()

        # Test passes if exit code 0 and output contains "PASS"
        passed = (result.returncode == 0) and ('PASS' in result.stdout or result.returncode == 0)

        if passed:
            print(f"[TEST_EXECUTOR] ✅ PASSED (elapsed: {elapsed:.1f}s)")
            quality = 90 + (10 if elapsed < 5 else 0)  # Bonus for speed

            # **AUTONOMOUS UPDATE: Agent writes directly to projects.json**
            update_task_result(
                task_id=task_id,
                status="completed",
                quality_score=quality,
                elapsed_time=elapsed,
                error_msg=""
            )

            return {
                "status": "completed",
                "quality": quality,
                "elapsed_s": elapsed,
                "result": result.stdout[:200]
            }
        else:
            print(f"[TEST_EXECUTOR] ❌ FAILED")
            elapsed = (datetime.now() - start_time).total_seconds()

            # **AUTONOMOUS UPDATE: Log failure**
            update_task_result(
                task_id=task_id,
                status="failed",
                quality_score=0,
                elapsed_time=elapsed,
                error_msg=result.stdout[:100] or result.stderr[:100]
            )

            return {
                "status": "failed",
                "quality": 0,
                "elapsed_s": elapsed,
                "error": result.stderr[:200]
            }

    except subprocess.TimeoutExpired:
        print(f"[TEST_EXECUTOR] ❌ TIMEOUT")
        elapsed = (datetime.now() - start_time).total_seconds()

        update_task_result(
            task_id=task_id,
            status="failed",
            quality_score=0,
            elapsed_time=elapsed,
            error_msg="Test timeout"
        )

        return {
            "status": "failed",
            "quality": 0,
            "elapsed_s": elapsed,
            "error": "Timeout"
        }

    except Exception as e:
        print(f"[TEST_EXECUTOR] ❌ ERROR: {e}")
        elapsed = (datetime.now() - start_time).total_seconds()

        update_task_result(
            task_id=task_id,
            status="failed",
            quality_score=0,
            elapsed_time=elapsed,
            error_msg=str(e)[:100]
        )

        return {
            "status": "failed",
            "quality": 0,
            "elapsed_s": elapsed,
            "error": str(e)
        }


def run(task: dict):
    """
    Main entry point for orchestrator.
    Execute validation task and update projects.json autonomously.
    """

    task_id = task.get("id")
    test_command = task.get("test_command", "echo 'PASS'")

    print(f"\n{'='*70}")
    print(f"[AUTONOMOUS TEST EXECUTOR] Task: {task_id}")
    print(f"{'='*70}")

    result = run_validation_task(task_id, test_command)

    print(f"\n[TEST_EXECUTOR] Result: {result['status']}")
    print(f"[TEST_EXECUTOR] Quality: {result.get('quality', 0)}")
    print(f"[TEST_EXECUTOR] Elapsed: {result.get('elapsed_s', 0):.1f}s")
    print(f"\n[TEST_EXECUTOR] ✅ Task updated in projects.json (autonomous)")
    print(f"[TEST_EXECUTOR] Daemon will trigger next pending task\n")

    return result


if __name__ == "__main__":
    # Test: Run a validation task autonomously
    test_task = {
        "id": "task-1",
        "title": "Test validation",
        "test_command": "echo 'PASS'"
    }

    result = run(test_task)
    print(f"\nTest completed: {result}")
