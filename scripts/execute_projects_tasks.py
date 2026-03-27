#!/usr/bin/env python3
"""
execute_projects_tasks.py — Direct executor for projects.json tasks

Bypasses full orchestrator loop. Directly loads and executes pending tasks
from projects.json using the agent routing system.

Usage:
  python3 scripts/execute_projects_tasks.py 6        # Execute first 6 tasks
  python3 scripts/execute_projects_tasks.py all      # Execute all pending tasks
"""
import sys
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

from orchestrator.projects_loader import load_projects_tasks, mark_task_in_progress, mark_task_complete
from agents import run_task
from dashboard.state_writer import update_task_queue, update_agent


def execute_projects_tasks(max_tasks: int = None):
    """
    Load and execute tasks from projects.json.

    Args:
        max_tasks: Maximum number of tasks to execute (None = all pending)
    """
    print("=" * 70)
    print("PROJECTS.JSON TASK EXECUTOR")
    print("=" * 70)
    print()

    # Load pending tasks
    tasks = load_projects_tasks()

    if not tasks:
        print("✅ No pending tasks in projects.json")
        return 0

    # Limit to max_tasks if specified
    if max_tasks and max_tasks != "all":
        try:
            max_tasks = int(max_tasks)
            tasks = tasks[:max_tasks]
        except ValueError:
            pass

    print(f"📋 {len(tasks)} pending tasks to execute")
    print()

    executed = 0
    failed = 0

    for i, task in enumerate(tasks, 1):
        task_id = task.get("id", f"task-{i}")
        title = task.get("title", "")
        agent_name = task.get("agent", "executor")
        project_id = task.get("project_id", "")

        print(f"[{i}/{len(tasks)}] {title[:60]}")
        print(f"         Agent: {agent_name} | ID: {task_id}")

        try:
            # Mark as in_progress
            mark_task_in_progress(task_id, agent_name)
            update_agent(agent_name, "running", title[:60], task_id)

            # Execute task via agent router
            print(f"         Executing...")
            result = run_task(task)

            # Check if successful
            success = result and result.get("status") in ["done", "completed"] and result.get("quality", 0) >= 30

            if success:
                print(f"         ✅ Success (quality: {result.get('quality', 0)}/100)")
                mark_task_complete(task_id, project_id)
                executed += 1
            else:
                print(f"         ❌ Failed (status: {result.get('status') if result else 'None'})")
                failed += 1

        except Exception as e:
            print(f"         ❌ Exception: {e}")
            failed += 1

        print()

    print("=" * 70)
    print(f"SUMMARY: {executed} executed, {failed} failed (out of {len(tasks)})")
    print("=" * 70)

    # Update state.json with final counts
    remaining_pending = len(tasks) - executed - failed
    print(f"\nUpdating state.json...")
    try:
        update_task_queue(
            total=executed + failed + remaining_pending,
            completed=executed,
            in_progress=0,
            failed=failed,
            pending=remaining_pending
        )
        print(f"✅ State updated: {executed} complete, {failed} failed, {remaining_pending} pending")
    except Exception as e:
        print(f"⚠️  Could not update state: {e}")

    return executed


if __name__ == "__main__":
    max_tasks = sys.argv[1] if len(sys.argv) > 1 else 6
    executed = execute_projects_tasks(max_tasks)
    sys.exit(0 if executed > 0 else 1)
