#!/usr/bin/env python3
"""persistence_layer.py — Persist task state across restarts + failure recovery"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"
PROJECTS_FILE = BASE_DIR / "projects.json"

class PersistenceLayer:
    def __init__(self):
        self.queue_file = STATE_DIR / "task_queue.json"
        self.agent_state_file = STATE_DIR / "agent_state.json"
        self.recovery_log = STATE_DIR / "recovery.jsonl"
        STATE_DIR.mkdir(parents=True, exist_ok=True)

    def load_queue(self):
        """Load persistent task queue with failure recovery."""
        if self.queue_file.exists():
            with open(self.queue_file) as f:
                return json.load(f)

        # Fallback: recover from projects.json
        return self._recover_from_projects()

    def _recover_from_projects(self) -> Dict[str, Any]:
        """Recover task queue from projects.json (failure recovery)."""
        tasks = []
        try:
            with open(PROJECTS_FILE) as f:
                data = json.load(f)

            # Extract all non-completed tasks from projects
            for project in data.get("projects", []):
                for task in project.get("tasks", []):
                    # Re-queue if: pending, failed, or low success rate
                    if task.get("status") in ["pending", "failed", "blocked"]:
                        tasks.append({
                            "project_id": project.get("id"),
                            "task_id": task.get("id"),
                            "title": task.get("title"),
                            "status": "pending",
                            "priority": task.get("priority", "P2"),
                            "retries": task.get("retries", 0)
                        })

            self._log_recovery(f"Recovered {len(tasks)} tasks from projects.json")
        except Exception as e:
            self._log_recovery(f"Recovery failed: {e}")

        return {"tasks": tasks, "last_updated": datetime.now().isoformat()}

    def save_queue(self, queue):
        """Save task queue to persistent storage."""
        self.queue_file.write_text(json.dumps(queue, indent=2))

    def load_agent_state(self):
        """Load persistent agent state."""
        if self.agent_state_file.exists():
            with open(self.agent_state_file) as f:
                return json.load(f)
        return {}

    def save_agent_state(self, state):
        """Save agent state to persistent storage."""
        self.agent_state_file.write_text(json.dumps(state, indent=2))

    def mark_task_failed(self, task_id: str, error: str, attempt: int = 1):
        """Mark task as failed and re-queue if retries remain."""
        queue = self.load_queue()
        tasks = queue.get("tasks", [])

        for task in tasks:
            if task.get("task_id") == task_id:
                task["status"] = "pending"
                task["retries"] = attempt
                task["last_error"] = error
                task["failed_at"] = datetime.now().isoformat()
                break

        self.save_queue(queue)
        self._log_recovery(f"Requeued task {task_id} (attempt {attempt})")

    def sync_from_dashboard(self, dashboard_state: Dict[str, Any]):
        """Sync task queue from dashboard state (handle out-of-sync scenarios)."""
        queue = self.load_queue()
        tasks = queue.get("tasks", [])

        # Add missing tasks from dashboard
        for task_data in dashboard_state.get("recent_tasks", []):
            if task_data.get("status") in ["todo", "blocked"]:
                task_id = task_data.get("task_id")
                if not any(t.get("task_id") == task_id for t in tasks):
                    tasks.append({
                        "task_id": task_id,
                        "title": task_data.get("title"),
                        "status": "pending",
                        "priority": "P1" if task_data.get("status") == "blocked" else "P2",
                        "retries": 0
                    })

        queue["tasks"] = tasks
        self.save_queue(queue)
        self._log_recovery(f"Synced {len(tasks)} tasks from dashboard")

    def _log_recovery(self, msg: str):
        """Log recovery events."""
        with open(self.recovery_log, "a") as f:
            f.write(json.dumps({
                "ts": datetime.now().isoformat(),
                "msg": msg
            }) + "\n")

if __name__ == "__main__":
    pl = PersistenceLayer()
    queue = pl.load_queue()
    print(f"Loaded {len(queue.get('tasks', []))} tasks from persistent storage")
    print(f"Recovery log: {pl.recovery_log}")
