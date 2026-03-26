"""ProjectManager: CRUD + task queue. Thread-safe JSON persistence via fcntl."""
import fcntl
import json
import os
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from projects.schema import Epic, Project, SubTask

PROJECTS_FILE = os.path.join(os.path.dirname(__file__), "projects.json")


def _now() -> str:
    return datetime.utcnow().isoformat()


class ProjectManager:
    def __init__(self, filepath: str = PROJECTS_FILE):
        self.filepath = filepath
        if not os.path.exists(self.filepath):
            self._write_raw({"projects": []})

    def _read_raw(self) -> dict:
        with open(self.filepath, "r") as fh:
            fcntl.flock(fh, fcntl.LOCK_SH)
            try:
                return json.load(fh)
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)

    def _write_raw(self, data: dict) -> None:
        tmp = self.filepath + ".tmp"
        with open(tmp, "w") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                json.dump(data, fh, indent=2)
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
        os.replace(tmp, self.filepath)

    def _load_projects(self) -> list:
        return self._read_raw().get("projects", [])

    def _save_projects(self, projects: list) -> None:
        self._write_raw({"projects": projects})

    def create_project(self, name: str, type: str = "unknown", description: str = "", path: str = "") -> dict:
        data = asdict(Project(name=name, type=type, description=description, path=path))
        projects = self._load_projects()
        projects.append(data)
        self._save_projects(projects)
        return data

    def get_project(self, project_id: str) -> Optional[dict]:
        for p in self._load_projects():
            if p["id"] == project_id:
                return p
        return None

    def list_projects(self) -> list:
        return self._load_projects()

    def update_project(self, project_id: str, **kwargs) -> Optional[dict]:
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

    def add_epic(self, project_id: str, epic: Epic) -> Optional[dict]:
        projects = self._load_projects()
        for p in projects:
            if p["id"] == project_id:
                epic_data = asdict(epic)
                p["epics"].append(epic_data)
                p["updated"] = _now()
                self._save_projects(projects)
                return epic_data
        return None

    def add_task(self, project_id: str, epic_id: str, task: SubTask) -> Optional[dict]:
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
        best = None
        best_priority = 999
        for p in self._load_projects():
            if p["status"] != "active":
                continue
            for e in p["epics"]:
                if e["status"] == "done":
                    continue
                for t in e["tasks"]:
                    if t["status"] == "pending" and e["priority"] < best_priority:
                        best_priority = e["priority"]
                        best = {"project_id": p["id"], "project_name": p["name"],
                                "epic_id": e["id"], "epic_title": e["title"], "task": t}
        return best

    def complete_task(self, project_id: str, epic_id: str, task_id: str, result: dict, quality: int) -> Optional[dict]:
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
                                done = [tk for ep in p["epics"] for tk in ep["tasks"] if tk["status"] == "done"]
                                if done:
                                    p["quality_avg"] = round(sum(tk["quality"] for tk in done) / len(done), 1)
                                self._save_projects(projects)
                                return t
        return None

    def get_all_tasks(self, status: Optional[str] = None) -> list:
        results = []
        for p in self._load_projects():
            for e in p["epics"]:
                for t in e["tasks"]:
                    if status is None or t["status"] == status:
                        results.append({"project_id": p["id"], "project_name": p["name"],
                                        "epic_id": e["id"], "epic_title": e["title"], "task": t})
        return results

    def project_stats(self, project_id: str) -> Optional[dict]:
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
        return {"total": total, "done": done, "in_progress": in_progress,
                "blocked": blocked, "pending": pending, "quality_avg": quality_avg}
