"""
ProjectManager -- CRUD + task queue for projects/epics/tasks.

Backed by local-agents/projects/projects.json.
Thread-safe via fcntl file locking. Auto-saves on every write.

Integrates:
  - TaskDAG  for dependency tracking, cycle detection, and critical path
  - RICEScorer for auto-scoring and MoSCoW classification
  - next_task()            highest-priority DAG-available task
  - parallel_next_tasks(n) N independent tasks for multi-agent dispatch
"""
import fcntl
import json
import os
from dataclasses import asdict
from datetime import datetime
from typing import Optional

from projects.schema import Epic, Project, SubTask
from projects.dag import TaskDAG
from projects.prioritizer import RICEScorer

PROJECTS_FILE = os.path.join(os.path.dirname(__file__), "projects.json")


def _now() -> str:
    return datetime.utcnow().isoformat()


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

    # ------------------------------------------------------------------ #
    # DAG helpers
    # ------------------------------------------------------------------ #

    @staticmethod
    def _build_dag_from(project: dict) -> TaskDAG:
        """Build a TaskDAG from all tasks in the given project dict."""
        dag = TaskDAG()
        for epic in project.get("epics", []):
            for task in epic.get("tasks", []):
                dag.add_task(task["id"], task)
                for dep_id in task.get("depends_on", []):
                    dag.add_dependency(dep_id, task["id"])
        return dag

    def _refresh_blocking_scores(self, project: dict) -> None:
        """Recompute blocking_score + RICE/MoSCoW for every task in a project dict."""
        dag = self._build_dag_from(project)
        for epic in project.get("epics", []):
            for task in epic.get("tasks", []):
                task["blocking_score"] = dag.blocking_score(task["id"])
                RICEScorer.auto_score_task(task)

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

    def list_projects(self) -> list:
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
        self, project_id: str, epic_id: str, task: SubTask, depends_on: list = None
    ) -> Optional[dict]:
        """
        Append a SubTask to an epic. Returns the task dict or None.

        depends_on: optional list of task IDs that must complete before this task.
        Validates no dependency cycle is introduced (raises ValueError on cycle).
        Auto-scores the task with RICE/MoSCoW before saving.
        """
        projects = self._load_projects()
        for p in projects:
            if p["id"] == project_id:
                for e in p["epics"]:
                    if e["id"] == epic_id:
                        task_data = asdict(task)
                        task_data.setdefault("depends_on", depends_on or [])
                        task_data.setdefault("effort_hours", 1)
                        task_data.setdefault("blocking_score", 0)
                        task_data.setdefault("rice_score", 0.0)
                        task_data.setdefault("moscow", "could")

                        # Validate no cycle before appending
                        if task_data["depends_on"]:
                            dag = self._build_dag_from(p)
                            dag.add_task(task_data["id"], task_data)
                            for dep_id in task_data["depends_on"]:
                                dag.add_dependency(dep_id, task_data["id"])
                            try:
                                dag.topological_sort()
                            except ValueError as exc:
                                raise ValueError(
                                    f"Cannot add task {task_data['title']!r}: {exc}"
                                ) from exc

                        e["tasks"].append(task_data)
                        p["updated"] = _now()

                        # Auto-score after appending (blocking_score needs full DAG)
                        dag = self._build_dag_from(p)
                        task_data["blocking_score"] = dag.blocking_score(task_data["id"])
                        RICEScorer.auto_score_task(task_data)

                        self._save_projects(projects)
                        return task_data
        return None

    def add_task_dependency(self, project_id: str, blocker_id: str, blocked_id: str) -> bool:
        """
        Add a dependency edge: blocker must finish before blocked starts.
        Validates no cycle is introduced. Returns True on success, False on failure.
        """
        projects = self._load_projects()
        for p in projects:
            if p["id"] != project_id:
                continue
            for epic in p["epics"]:
                for task in epic["tasks"]:
                    if task["id"] == blocked_id:
                        deps = task.setdefault("depends_on", [])
                        if blocker_id in deps:
                            return True  # already exists
                        deps.append(blocker_id)

                        dag = self._build_dag_from(p)
                        try:
                            dag.topological_sort()
                        except ValueError:
                            deps.remove(blocker_id)
                            return False

                        self._refresh_blocking_scores(p)
                        self._save_projects(projects)
                        return True
        return False

    def next_task(self) -> Optional[dict]:
        """
        Return the highest-priority available task across all active projects.

        Available means: status=pending AND all blocker tasks are done.
        Sorted by RICE/MoSCoW via RICEScorer.sort_backlog().

        Returns dict: {project_id, project_name, epic_id, epic_title, task}
        """
        candidates = self._collect_candidates()
        if not candidates:
            return None
        sorted_candidates = RICEScorer.sort_backlog(candidates)
        return sorted_candidates[0]["_item"]

    def parallel_next_tasks(self, n: int = 3) -> list:
        """
        Returns up to N independent available tasks for parallel multi-agent dispatch.

        Tasks in the result are mutually independent -- none blocks another in
        the returned set. Sorted by RICE/MoSCoW priority before selection.
        """
        candidates = self._collect_candidates()
        if not candidates:
            return []
        sorted_candidates = RICEScorer.sort_backlog(candidates)

        selected = []
        selected_ids = set()
        for c in sorted_candidates:
            task = c["_item"]["task"]
            task_id = task["id"]
            # Skip if this task depends on any already-selected task
            deps = set(task.get("depends_on", []))
            if deps & selected_ids:
                continue
            selected.append(c["_item"])
            selected_ids.add(task_id)
            if len(selected) >= n:
                break
        return selected

    def _collect_candidates(self) -> list:
        """
        Collect all DAG-available tasks across active projects.
        Returns flat list of scoring dicts with embedded _item for final return.
        """
        candidates = []
        for project in self._load_projects():
            if project.get("status") != "active":
                continue
            dag = self._build_dag_from(project)
            available_ids = set(dag.available_tasks())

            for epic in project.get("epics", []):
                for task in epic.get("tasks", []):
                    if task["id"] not in available_ids:
                        continue
                    item = {
                        "project_id": project["id"],
                        "project_name": project["name"],
                        "epic_id": epic["id"],
                        "epic_title": epic["title"],
                        "task": task,
                    }
                    scoring = dict(task)
                    scoring["_item"] = item
                    candidates.append(scoring)
        return candidates

    # ------------------------------------------------------------------ #
    # DAG analysis (public surface)
    # ------------------------------------------------------------------ #

    def critical_path(self, project_id: str) -> list:
        """Return the critical path task IDs for a project."""
        project = self.get_project(project_id)
        if not project:
            return []
        dag = self._build_dag_from(project)
        if not dag.tasks:
            return []
        try:
            return dag.critical_path()
        except ValueError:
            return []

    def parallel_groups(self, project_id: str) -> list:
        """Return lists of task IDs that can execute in parallel per level."""
        project = self.get_project(project_id)
        if not project:
            return []
        dag = self._build_dag_from(project)
        if not dag.tasks:
            return []
        try:
            return dag.parallel_groups()
        except ValueError:
            return []

    # ------------------------------------------------------------------ #
    # Completion + flat task listing
    # ------------------------------------------------------------------ #

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

    def get_all_tasks(self, status: Optional[str] = None) -> list:
        """
        Return all tasks across all projects, optionally filtered by status.

        Each item includes: project_id, project_name, epic_id, epic_title, task dict.
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
        """Return stats for a project: {total, done, in_progress, blocked, pending, quality_avg}"""
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
