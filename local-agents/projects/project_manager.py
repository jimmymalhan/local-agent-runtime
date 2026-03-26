"""
ProjectManager — CRUD + task queue for projects/epics/tasks.

Backed by local-agents/projects/projects.json.
Thread-safe via fcntl file locking (POSIX) with portalocker fallback.
Auto-saves on every write.
"""
import json
import os
import fcntl
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from projects.schema import Project, Epic, SubTask

PROJECTS_FILE = os.path.join(os.path.dirname(__file__), "projects.json")


def _now() -> str:
    return datetime.utcnow().isoformat()


def _lock(fh):
    fcntl.flock(fh, fcntl.LOCK_EX)


def _unlock(fh):
    fcntl.flock(fh, fcntl.LOCK_UN)


class ProjectManager:
    """Thread-safe project/epic/task manager backed by a JSON file."""

    def __init__(self, filepath: str = PROJECTS_FILE):
        self.filepath = filepath
        if not os.path.exists(self.filepath):
            self._write_raw({"projects": []})

    # ------------------------------------------------------------------ #
    # Internal I/O
    # ------------------------------------------------------------------ #

    def _read_raw(self) -> dict:
        with open(self.filepath, "r") as fh:
            _lock(fh)
            try:
                return json.load(fh)
            finally:
                _unlock(fh)

    def _write_raw(self, data: dict) -> None:
        # Write to a temp file then rename for atomicity
        tmp = self.filepath + ".tmp"
        with open(tmp, "w") as fh:
            _lock(fh)
            try:
                json.dump(data, fh, indent=2)
            finally:
                _unlock(fh)
        os.replace(tmp, self.filepath)

    def _load_projects(self) -> list[dict]:
        return self._read_raw().get("projects", [])

    def _save_projects(self, projects: list[dict]) -> None:
        self._write_raw({"projects": projects})

    # ------------------------------------------------------------------ #
    # Project CRUD
    # ------------------------------------------------------------------ #

    def create_project(
        self,
        name: str,
        type: str = "unknown",
        description: str = "",
        path: str = "",
    ) -> dict:
        """Create a new project and persist it. Returns the project dict."""
        project = Project(name=name, type=type, description=description, path=path)
        data = asdict(project)
        projects = self._load_projects()
        projects.append(data)
        self._save_projects(projects)
        return data

    def get_project(self, project_id: str) -> Optional[dict]:
        """Return a project dict by id, or None."""
        for p in self._load_projects():
            if p["id"] == project_id:
                return p
        return None

    def list_projects(self) -> list[dict]:
        """Return all projects."""
        return self._load_projects()

    def update_project(self, project_id: str, **kwargs) -> Optional[dict]:
        """Update arbitrary fields on a project. Returns updated dict or None."""
        projects = self._load_projects()
        for p in projects:
            if p["id"] == project_id:
                for k, v in kwargs.items():
                    if k in p:
                        p[k] = v
                p["updated"] = _now()
                self._save_projects(projects)
                return p
        return None

    # ------------------------------------------------------------------ #
    # Epic management
    # ------------------------------------------------------------------ #

    def add_epic(self, project_id: str, epic: Epic) -> Optional[dict]:
        """Append an Epic to a project. Returns the epic dict or None."""
        projects = self._load_projects()
        for p in projects:
            if p["id"] == project_id:
                epic_data = asdict(epic)
                p["epics"].append(epic_data)
                p["updated"] = _now()
                self._save_projects(projects)
                return epic_data
        return None

    # ------------------------------------------------------------------ #
    # Task management
    # ------------------------------------------------------------------ #

    def add_task(
        self, project_id: str, epic_id: str, task: SubTask
    ) -> Optional[dict]:
        """Append a SubTask to an epic. Returns the task dict or None."""
        projects = self._load_projects()
        for p in projects:
            if p["id"] == project_id:
                for e in p["epics"]:
                    if e["id"] == epic_id:
                        task_data = asdict(task)
                        e["tasks"].append(task_data)
                        p["updated"] = _now()
                        self._save_projects(projects)
                        return task_data
        return None

    def next_task(self) -> Optional[dict]:
        """
        Return the highest-priority pending task across all active projects.

        Priority order:
          1. Project priority (epic.priority asc, 1=high)
          2. Epic order (insertion order)
          3. Task order (insertion order)

        Returns a dict with keys: project_id, epic_id, task (SubTask dict).
        """
        best = None
        best_priority = 999

        for p in self._load_projects():
            if p["status"] not in ("active",):
                continue
            for e in p["epics"]:
                if e["status"] in ("done",):
                    continue
                for t in e["tasks"]:
                    if t["status"] == "pending":
                        if e["priority"] < best_priority:
                            best_priority = e["priority"]
                            best = {
                                "project_id": p["id"],
                                "project_name": p["name"],
                                "epic_id": e["id"],
                                "epic_title": e["title"],
                                "task": t,
                            }
        return best

    def complete_task(
        self,
        project_id: str,
        epic_id: str,
        task_id: str,
        result: dict,
        quality: int,
    ) -> Optional[dict]:
        """Mark a task done, store result + quality. Returns updated task or None."""
        projects = self._load_projects()
        for p in projects:
            if p["id"] == project_id:
                for e in p["epics"]:
                    if e["id"] == epic_id:
                        for t in e["tasks"]:
                            if t["id"] == task_id:
                                t["status"] = "done"
                                t["result"] = result
                                t["quality"] = quality
                                t["updated"] = _now()
                                p["updated"] = _now()
                                # Recalculate project quality_avg
                                all_done = [
                                    tk
                                    for ep in p["epics"]
                                    for tk in ep["tasks"]
                                    if tk["status"] == "done"
                                ]
                                if all_done:
                                    p["quality_avg"] = round(
                                        sum(tk["quality"] for tk in all_done)
                                        / len(all_done),
                                        1,
                                    )
                                self._save_projects(projects)
                                return t
        return None

    def get_all_tasks(self, status: Optional[str] = None) -> list[dict]:
        """
        Return all tasks across all projects, optionally filtered by status.

        Each item includes project_id, project_name, epic_id, epic_title, and the task dict.
        """
        results = []
        for p in self._load_projects():
            for e in p["epics"]:
                for t in e["tasks"]:
                    if status is None or t["status"] == status:
                        results.append(
                            {
                                "project_id": p["id"],
                                "project_name": p["name"],
                                "epic_id": e["id"],
                                "epic_title": e["title"],
                                "task": t,
                            }
                        )
        return results

    def project_stats(self, project_id: str) -> Optional[dict]:
        """
        Return stats for a project.

        Returns: {total, done, in_progress, blocked, pending, quality_avg}
        """
        p = self.get_project(project_id)
        if p is None:
            return None

        total = done = in_progress = blocked = pending = 0
        qualities = []

        for e in p["epics"]:
            for t in e["tasks"]:
                total += 1
                s = t["status"]
                if s == "done":
                    done += 1
                    qualities.append(t["quality"])
                elif s == "in_progress":
                    in_progress += 1
                elif s == "blocked":
                    blocked += 1
                else:
                    pending += 1

        quality_avg = round(sum(qualities) / len(qualities), 1) if qualities else 0.0

        return {
            "total": total,
            "done": done,
            "in_progress": in_progress,
            "blocked": blocked,
            "pending": pending,
            "quality_avg": quality_avg,
        }
