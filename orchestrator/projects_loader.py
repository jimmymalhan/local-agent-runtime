#!/usr/bin/env python3
"""
projects_loader.py — Load tasks from projects.json

Converts projects.json format to the format expected by orchestrator/main.py
"""
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List, Dict, Any

BASE_DIR = Path(__file__).parent.parent
PROJECTS_FILE = BASE_DIR / "projects.json"


def load_projects_tasks() -> List[Dict[str, Any]]:
    """
    Load all pending tasks from projects.json and convert to orchestrator task format.

    Returns:
        list of tasks in format: {
            "id": task_id,
            "title": str,
            "description": str,
            "category": str,  # derived from epic/project type
            "agent": str,      # from task.agent field
            "priority": str,   # from task.priority field
            "project_id": str, # from containing project
        }
    """
    tasks = []

    try:
        with open(PROJECTS_FILE) as f:
            projects_data = json.load(f)
    except Exception as e:
        print(f"[PROJECTS_LOADER] Warning: Could not load projects.json: {e}")
        return []

    # Iterate through projects
    for project in projects_data.get("projects", []):
        project_id = project.get("id", "unknown")
        project_name = project.get("name", "")

        # Extract category from project name/type
        project_category = "project"  # default
        if "infrastructure" in project.get("description", "").lower():
            project_category = "infrastructure"
        elif "agent" in project.get("description", "").lower():
            project_category = "agent-setup"
        elif "dashboard" in project.get("description", "").lower():
            project_category = "dashboard"

        # Iterate through tasks in this project
        for task in project.get("tasks", []):
            status = task.get("status", "pending")
            task_id = task.get("id", "unknown")

            # TASK-FIX-2: Check for stuck in_progress tasks (timeout > 5 min) and retry
            if status == "in_progress":
                started_at_str = task.get("started_at", None)
                if started_at_str:
                    try:
                        # Parse ISO format timestamp
                        started_at = datetime.fromisoformat(started_at_str.replace("Z", "+00:00"))
                        elapsed = datetime.utcnow() - started_at.replace(tzinfo=None)

                        # If stuck longer than 300 seconds, reset to pending and retry
                        if elapsed.total_seconds() > 300:
                            print(f"[PROJECTS_LOADER] Task {task_id} stuck (in_progress for {int(elapsed.total_seconds())}s) — resetting to pending")
                            task["status"] = "pending"
                            status = "pending"
                            # The projects.json will be saved below
                        else:
                            print(f"[PROJECTS_LOADER] Skipping {task_id} (status=in_progress, elapsed={int(elapsed.total_seconds())}s)")
                            continue
                    except Exception as e:
                        print(f"[PROJECTS_LOADER] Warning parsing timestamp for {task_id}: {e}")
                        print(f"[PROJECTS_LOADER] Skipping {task_id} (status=in_progress)")
                        continue
                else:
                    print(f"[PROJECTS_LOADER] Skipping {task_id} (status=in_progress, no started_at)")
                    continue

            # Skip completed tasks
            if status == "completed":
                print(f"[PROJECTS_LOADER] Skipping {task_id} (status=completed)")
                continue

            # Only process pending tasks
            if status != "pending":
                print(f"[PROJECTS_LOADER] Skipping {task_id} (status={status})")
                continue

            # Convert to orchestrator task format
            orch_task = {
                "id": task.get("id", f"task-{len(tasks)}"),
                "title": task.get("title", ""),
                "description": task.get("description", ""),
                "category": task.get("category", project_category),
                "agent": task.get("agent", "executor"),  # default to executor
                "priority": task.get("priority", "P2"),
                "project_id": project_id,
                "project_name": project_name,
                "files": task.get("files", []),
                "success_criteria": task.get("success_criteria", ""),
            }

            tasks.append(orch_task)

    print(f"[PROJECTS_LOADER] Loaded {len(tasks)} pending tasks from projects.json")
    return tasks


def mark_task_complete(task_id: str, project_id: str = None):
    """Mark a task as completed in projects.json"""
    try:
        with open(PROJECTS_FILE) as f:
            projects_data = json.load(f)
    except:
        return False

    # Find and update task
    for project in projects_data.get("projects", []):
        if project_id and project["id"] != project_id:
            continue

        for task in project.get("tasks", []):
            if task.get("id") == task_id:
                task["status"] = "completed"
                task["completed_at"] = Path(__file__).stem  # Mark with loader name

                # Save
                with open(PROJECTS_FILE, "w") as f:
                    json.dump(projects_data, f, indent=2)
                print(f"[PROJECTS_LOADER] Marked {task_id} as completed")
                return True

    return False


def mark_task_in_progress(task_id: str, agent: str = ""):
    """Mark a task as in_progress in projects.json"""
    try:
        with open(PROJECTS_FILE) as f:
            projects_data = json.load(f)
    except:
        return False

    for project in projects_data.get("projects", []):
        for task in project.get("tasks", []):
            if task.get("id") == task_id:
                task["status"] = "in_progress"
                if agent:
                    task["agent"] = agent

                with open(PROJECTS_FILE, "w") as f:
                    json.dump(projects_data, f, indent=2)
                print(f"[PROJECTS_LOADER] Marked {task_id} as in_progress (agent={agent})")
                return True

    return False


if __name__ == "__main__":
    tasks = load_projects_tasks()
    print(f"\nLoaded {len(tasks)} tasks:")
    for task in tasks:
        print(f"  - {task['id']}: {task['title'][:50]}")
