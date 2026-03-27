#!/usr/bin/env python3
"""
quick_dispatcher.py — Simple task dispatcher bypassing orchestrator hang

Loads pending tasks from projects.json and executes them directly via agents.run_task()
WITHOUT the overhead/hang of orchestrator/main.py.

Usage:
  python3 orchestrator/quick_dispatcher.py [--tasks N] [--project PROJECT_ID]
"""

import json
import sys
import time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any

BASE_DIR = Path(__file__).parent.parent
sys.path.insert(0, str(BASE_DIR))

PROJECTS_FILE = BASE_DIR / "projects.json"
REPORTS_DIR = BASE_DIR / "reports"
REPORTS_DIR.mkdir(exist_ok=True)

# Import agent task runner
from agents import run_task
from orchestrator.projects_loader import load_projects_tasks, mark_task_in_progress, mark_task_complete


def dispatch_and_execute(max_tasks: int = 1, project_id: str = None) -> Dict[str, Any]:
    """Load pending tasks and execute them directly via agents."""

    print(f"\n{'='*70}")
    print(f"🚀 QUICK DISPATCHER — Task Execution (bypass orchestrator)")
    print(f"{'='*70}")

    # Load pending tasks
    print(f"\n[1] Loading pending tasks from projects.json...")
    all_tasks = load_projects_tasks()

    # Filter by project if specified
    if project_id:
        filtered = [t for t in all_tasks if t.get("project_id") == project_id]
        print(f"    Filtered to project '{project_id}': {len(filtered)} tasks")
        all_tasks = filtered

    if not all_tasks:
        print(f"    ✅ No pending tasks")
        return {"tasks_run": 0, "completed": 0, "failed": 0}

    # Limit to max_tasks
    tasks_to_run = all_tasks[:max_tasks]
    print(f"    ✅ Loaded {len(all_tasks)} pending tasks, will run {len(tasks_to_run)}")

    # Execute tasks
    print(f"\n[2] Executing {len(tasks_to_run)} task(s)...")
    results = {
        "tasks_run": 0,
        "completed": 0,
        "failed": 0,
        "tasks": []
    }

    for i, task in enumerate(tasks_to_run, 1):
        task_id = task.get("id", f"task-{i}")
        title = task.get("title", "")[:60]
        agent = task.get("agent", "executor")

        print(f"\n  [{i}/{len(tasks_to_run)}] Executing: {task_id}")
        print(f"      Title: {title}")
        print(f"      Agent: {agent}")

        # Mark as in_progress
        mark_task_in_progress(task_id, agent)

        start_time = time.time()
        try:
            # Execute via agents.run_task()
            result = run_task(task)
            elapsed = time.time() - start_time

            status = result.get("status", "pending")
            quality = result.get("quality", result.get("quality_score", 0))

            print(f"      Status: {status}")
            print(f"      Quality: {quality:.0f}")
            print(f"      Elapsed: {elapsed:.2f}s")

            # Mark as completed in projects.json
            mark_task_complete(task_id)

            results["tasks_run"] += 1
            if status == "completed":
                results["completed"] += 1
            else:
                results["failed"] += 1

            results["tasks"].append({
                "id": task_id,
                "status": status,
                "quality": quality,
                "elapsed_s": elapsed
            })

        except Exception as e:
            elapsed = time.time() - start_time
            print(f"      ❌ Error: {str(e)[:100]}")
            results["failed"] += 1
            results["tasks_run"] += 1

            # Still mark as in our records
            results["tasks"].append({
                "id": task_id,
                "status": "failed",
                "error": str(e)[:100],
                "elapsed_s": elapsed
            })

    # Write summary
    print(f"\n[3] Updating state files...")
    try:
        summary_path = REPORTS_DIR / f"dispatch_{datetime.utcnow().isoformat()}.json"
        with open(summary_path, "w") as f:
            json.dump(results, f, indent=2)
        print(f"    ✅ Summary written to {summary_path.name}")
    except Exception as e:
        print(f"    ⚠️  Could not write summary: {e}")

    # Print summary
    print(f"\n{'='*70}")
    print(f"📊 RESULTS")
    print(f"{'='*70}")
    print(f"  Tasks run: {results['tasks_run']}")
    print(f"  Completed: {results['completed']}")
    print(f"  Failed: {results['failed']}")
    print(f"  Success rate: {(results['completed']/results['tasks_run']*100 if results['tasks_run'] else 0):.0f}%")
    print(f"{'='*70}\n")

    return results


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser(description="Quick task dispatcher")
    ap.add_argument("--tasks", type=int, default=1, help="Number of tasks to run")
    ap.add_argument("--project", type=str, default=None, help="Project ID to filter by")
    args = ap.parse_args()

    results = dispatch_and_execute(max_tasks=args.tasks, project_id=args.project)
    sys.exit(0 if results["failed"] == 0 else 1)
