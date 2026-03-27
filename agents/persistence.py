#!/usr/bin/env python3
"""
persistence.py — Agent Direct Persistence Layer
================================================
Allows agents to write their own task results to projects.json
WITHOUT Claude involvement. Full agent autonomy.

Agents call: update_task_result(task_id, status, quality_score, elapsed_time)
Result: projects.json updated immediately, next task triggered by daemon
"""

import json
import os
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
PROJECTS_FILE = BASE_DIR / "projects.json"


def update_task_result(task_id: str, status: str, quality_score: float = 0.0,
                      elapsed_time: float = 0.0, error_msg: str = ""):
    """
    Agent directly updates task result in projects.json.

    Args:
        task_id: Task ID (e.g., "task-1")
        status: "completed", "failed", "pending"
        quality_score: 0-100 quality metric
        elapsed_time: Seconds elapsed
        error_msg: Error message if failed

    Returns:
        bool: True if successful

    This is how agents update state AUTONOMOUSLY without Claude.
    The daemon watches projects.json and triggers next task on completion.
    """

    try:
        # Load current state
        with open(PROJECTS_FILE, 'r') as f:
            data = json.load(f)
    except Exception as e:
        print(f"[AGENT_PERSISTENCE] ERROR reading projects.json: {e}")
        return False

    # Find and update task
    task_found = False
    for project in data.get('projects', []):
        for task in project.get('tasks', []):
            if task.get('id') == task_id:
                task['status'] = status
                task['quality_score'] = quality_score
                task['elapsed_seconds'] = elapsed_time
                task['completed_at'] = datetime.now().isoformat()

                if error_msg:
                    task['error'] = error_msg

                task_found = True
                break
        if task_found:
            break

    if not task_found:
        print(f"[AGENT_PERSISTENCE] WARNING: Task {task_id} not found in projects.json")
        return False

    # Write back atomically
    try:
        tmp_file = PROJECTS_FILE.with_suffix('.tmp')
        with open(tmp_file, 'w') as f:
            json.dump(data, f, indent=2)

        # Atomic replace
        tmp_file.replace(PROJECTS_FILE)

        print(f"[AGENT_PERSISTENCE] ✅ Updated {task_id}: status={status}, quality={quality_score}")
        return True

    except Exception as e:
        print(f"[AGENT_PERSISTENCE] ERROR writing projects.json: {e}")
        return False


def mark_task_attempted(task_id: str):
    """Mark a task as attempted (increment attempt counter)."""
    try:
        with open(PROJECTS_FILE, 'r') as f:
            data = json.load(f)
    except:
        return False

    for project in data.get('projects', []):
        for task in project.get('tasks', []):
            if task.get('id') == task_id:
                attempts = task.get('attempts', 0)
                task['attempts'] = attempts + 1
                task['last_attempt'] = datetime.now().isoformat()

                try:
                    tmp_file = PROJECTS_FILE.with_suffix('.tmp')
                    with open(tmp_file, 'w') as f:
                        json.dump(data, f, indent=2)
                    tmp_file.replace(PROJECTS_FILE)
                    return True
                except:
                    return False

    return False


if __name__ == "__main__":
    # Test: Agent updating its own result
    print("Testing agent persistence layer...")

    # Simulate agent completing task-1
    result = update_task_result(
        task_id="task-1",
        status="completed",
        quality_score=85.0,
        elapsed_time=42.5,
        error_msg=""
    )

    print(f"Test result: {result}")

    # Verify
    with open(PROJECTS_FILE) as f:
        data = json.load(f)
        for p in data['projects']:
            for t in p['tasks']:
                if t['id'] == 'task-1':
                    print(f"\nVerified: {t['id']}")
                    print(f"  Status: {t['status']}")
                    print(f"  Quality: {t.get('quality_score')}")
