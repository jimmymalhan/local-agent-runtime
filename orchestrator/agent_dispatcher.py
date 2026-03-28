#!/usr/bin/env python3
"""
Agent Dispatcher — Routes queued tasks to Nexus agents
Fixes blocking issue: ensures every pending task gets an agent assignment

Problem: 8 tasks pending but NOT being executed
Solution: Explicit task → agent routing + assignment tracking
"""

import json
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"
sys.path.insert(0, str(BASE_DIR))

from agents import run_task, route, list_agents

class AgentDispatcher:
    """Routes tasks from queue to the right agent and executes them."""

    def __init__(self):
        self.queue_file = STATE_DIR / "task_queue.json"
        self.execution_log = STATE_DIR / "autonomous_execution.jsonl"
        self.agent_assignments = STATE_DIR / "agent_assignments.json"
        STATE_DIR.mkdir(parents=True, exist_ok=True)

    def load_queue(self) -> List[Dict]:
        """Load pending tasks from queue."""
        if self.queue_file.exists():
            with open(self.queue_file) as f:
                return json.load(f).get("tasks", [])
        return []

    def save_queue(self, tasks: List[Dict]):
        """Save queue back to disk."""
        with open(self.queue_file, "w") as f:
            json.dump({"tasks": tasks, "updated": datetime.now().isoformat()}, f, indent=2)

    def get_pending_tasks(self) -> List[Dict]:
        """Get all tasks that need execution."""
        tasks = self.load_queue()
        return [t for t in tasks if t.get("status") == "pending"]

    def assign_task_to_agent(self, task: Dict) -> Optional[str]:
        """
        Route task to the correct agent and return agent name.
        """
        # Determine which agent should handle this
        category = task.get("category", "code_gen")
        agent_name = route({"category": category})

        # Record assignment
        task["assigned_to"] = agent_name
        task["assigned_at"] = datetime.now().isoformat()
        task["status"] = "in_progress"

        return agent_name

    def execute_task(self, task: Dict) -> Dict:
        """Execute a task through its assigned agent."""
        try:
            # Make sure task has required fields
            if not task.get("id"):
                task["id"] = task.get("task_id", "unknown")
            if not task.get("title"):
                task["title"] = "Untitled"
            if not task.get("description"):
                task["description"] = task.get("title", "")
            if not task.get("category"):
                task["category"] = "code_gen"

            # Execute via agent router
            print(f"🚀 Executing: {task.get('title')} (via {task.get('assigned_to', 'executor')})")
            result = run_task(task)

            # Normalize result
            result.setdefault("task_id", task.get("task_id"))
            result.setdefault("status", "completed")
            result.setdefault("quality_score", result.get("quality", 0))
            result.setdefault("elapsed_s", 0)

            # Log execution
            self._log_execution({
                "ts": datetime.now().isoformat(),
                "task_id": task.get("task_id"),
                "agent": result.get("agent_name", task.get("assigned_to")),
                "status": result.get("status"),
                "quality": result.get("quality_score"),
                "tokens": result.get("tokens_used", 0)
            })

            return result

        except Exception as e:
            print(f"❌ Execution failed: {e}")
            return {
                "status": "failed",
                "error": str(e),
                "quality_score": 0,
                "task_id": task.get("task_id")
            }

    def update_task_status(self, task_id: str, status: str, result: Dict = None):
        """Update task status after execution."""
        tasks = self.load_queue()

        for task in tasks:
            if task.get("task_id") == task_id:
                task["status"] = status
                task["completed_at"] = datetime.now().isoformat()
                if result:
                    task["result"] = result.get("quality_score", 0)
                break

        self.save_queue(tasks)

    def _log_execution(self, record: Dict):
        """Log execution event."""
        with open(self.execution_log, "a") as f:
            f.write(json.dumps(record) + "\n")

    def dispatch_all(self, max_tasks: int = 20) -> Dict:
        """
        Dispatch and execute all pending tasks.
        Returns stats on what was executed.
        """
        pending = self.get_pending_tasks()
        executed = 0
        succeeded = 0
        failed = 0

        print(f"\n📋 DISPATCH: {len(pending)} pending tasks (max {max_tasks})")

        for task in pending[:max_tasks]:
            # Assign to agent
            agent = self.assign_task_to_agent(task)

            # Execute
            result = self.execute_task(task)

            # Update status
            status = result.get("status", "completed")
            self.update_task_status(task.get("task_id"), status, result)

            # Track stats
            executed += 1
            if status == "completed":
                succeeded += 1
            else:
                failed += 1

            print(f"  ✅ {task.get('title')[:50]} → {status} (agent: {agent})")

        stats = {
            "ts": datetime.now().isoformat(),
            "dispatched": executed,
            "succeeded": succeeded,
            "failed": failed,
            "success_rate": succeeded / max(executed, 1)
        }

        print(f"\n📊 Results: {succeeded}/{executed} succeeded ({stats['success_rate']:.1%})")
        return stats


if __name__ == "__main__":
    dispatcher = AgentDispatcher()
    stats = dispatcher.dispatch_all(max_tasks=20)
    print(json.dumps(stats, indent=2))
