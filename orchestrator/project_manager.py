#!/usr/bin/env python3
"""
orchestrator/project_manager.py — Task dispatch from projects.json
====================================================================
Reads projects.json and provides task queue for orchestrator loop.
"""
import json
import os
from pathlib import Path
from typing import List, Dict, Optional

class ProjectManager:
    """Manages project tasks from projects.json"""

    def __init__(self, projects_file: str = None):
        if projects_file is None:
            projects_file = str(Path(__file__).parent.parent / "projects.json")
        self.projects_file = projects_file
        self.projects = {}
        self._load_projects()

    def _load_projects(self):
        """Load projects from projects.json"""
        try:
            if os.path.exists(self.projects_file):
                with open(self.projects_file) as f:
                    data = json.load(f)
                    self.projects = {p["id"]: p for p in data.get("projects", [])}
                    print(f"[ProjectManager] Loaded {len(self.projects)} projects")
            else:
                print(f"[ProjectManager] {self.projects_file} not found")
        except Exception as e:
            print(f"[ProjectManager] Error loading projects: {e}")

    def get_pending_tasks(self) -> List[Dict]:
        """Get all pending tasks across all projects"""
        tasks = []
        for project in self.projects.values():
            for task in project.get("tasks", []):
                if task.get("status") == "pending":
                    task["project_id"] = project["id"]
                    task["project_name"] = project.get("name", "")
                    tasks.append(task)
        return tasks

    def get_task(self, task_id: str) -> Optional[Dict]:
        """Get a specific task by ID"""
        for project in self.projects.values():
            for task in project.get("tasks", []):
                if task.get("id") == task_id:
                    task["project_id"] = project["id"]
                    return task
        return None

    def update_task_status(self, task_id: str, status: str):
        """Update task status in projects.json"""
        for project in self.projects.values():
            for task in project.get("tasks", []):
                if task.get("id") == task_id:
                    task["status"] = status
                    self._save_projects()
                    return True
        return False

    def _save_projects(self):
        """Save projects back to projects.json"""
        try:
            data = {"projects": list(self.projects.values())}
            with open(self.projects_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            print(f"[ProjectManager] Error saving projects: {e}")

    def get_task_count(self) -> Dict[str, int]:
        """Get count of tasks by status"""
        counts = {"pending": 0, "in_progress": 0, "completed": 0, "blocked": 0}
        for project in self.projects.values():
            for task in project.get("tasks", []):
                status = task.get("status", "pending")
                if status in counts:
                    counts[status] += 1
        return counts


def get_project_manager() -> ProjectManager:
    """Get or create ProjectManager instance"""
    return ProjectManager()
