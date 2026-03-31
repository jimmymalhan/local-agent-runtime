#!/usr/bin/env python3
"""
sync_projects_from_reports.py - Sync completed tasks from reports back to projects.json

This is the PERSISTENCE LAYER FIX:
- Reads v*_compare.jsonl files (orchestrator execution results)
- Updates projects.json with completion status for matching tasks
- Runs on a daemon loop to keep projects.json in sync with actual execution

Problem it solves:
- Orchestrator executes tasks but projects.json wasn't being updated
- Task ID mismatches between projects.json (task-1) and task_suite.py (1)
- Dashboard showing wrong task completion counts
"""

import json
import os
from pathlib import Path
from datetime import datetime
import time
import glob

BASE_DIR = Path(__file__).parent.parent
REPORTS_DIR = BASE_DIR / "reports"
PROJECTS_FILE = BASE_DIR / "projects.json"

def load_projects():
    """Load projects.json"""
    with open(PROJECTS_FILE) as f:
        return json.load(f)

def save_projects(data):
    """Save projects.json"""
    with open(PROJECTS_FILE, "w") as f:
        json.dump(data, f, indent=2)

def sync_from_compare_files():
    """
    Read all v*_compare.jsonl files and sync completions to projects.json.
    """
    projects = load_projects()

    # Build a map of task_id -> task for quick lookup
    task_map = {}
    for project in projects.get('projects', []):
        for task in project.get('tasks', []):
            task_id = str(task.get('id', ''))
            task_map[task_id] = (project, task)

    # Read all compare files
    updated_count = 0
    for compare_file in sorted(glob.glob(str(REPORTS_DIR / "v*_compare.jsonl"))):
        with open(compare_file) as f:
            for line in f:
                try:
                    result = json.loads(line)
                    task_id = str(result.get('task_id', ''))
                    local_quality = result.get('local_quality', 0)
                    timestamp = result.get('ts', datetime.now().isoformat())

                    # Try to find task in projects by ID
                    if task_id in task_map:
                        project, task = task_map[task_id]

                        # Only update if not already completed
                        if task.get('status') != 'completed':
                            task['status'] = 'completed'
                            task['quality_score'] = local_quality
                            task['completed_at'] = timestamp
                            updated_count += 1
                except Exception as e:
                    pass

    if updated_count > 0:
        print(f"[SYNC] Updated {updated_count} tasks in projects.json from compare files")
        save_projects(projects)

    return updated_count

def daemon_sync_loop(interval_seconds=60):
    """
    Run sync loop every N seconds to keep projects.json updated.
    """
    print(f"[SYNC_DAEMON] Starting sync daemon (every {interval_seconds}s)")

    while True:
        try:
            updated = sync_from_compare_files()
            if updated > 0:
                print(f"[SYNC_DAEMON] Synced {updated} tasks at {datetime.now().isoformat()}")
        except Exception as e:
            print(f"[SYNC_DAEMON] Error: {e}")

        time.sleep(interval_seconds)

if __name__ == '__main__':
    # Run once for immediate sync
    sync_from_compare_files()
    print("[SYNC] Initial sync complete")

    # Optionally start daemon mode (uncomment for production)
    # daemon_sync_loop(60)
