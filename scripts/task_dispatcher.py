#!/usr/bin/env python3
"""
task_dispatcher.py — Emergency Task Dispatcher
==============================================
If the main orchestrator is stuck/spinning, this can manually dispatch
pending tasks to agents. Used as a workaround/backup if needed.

This is INFRASTRUCTURE support, not agent code modification.
"""
import json, sys, os
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
PROJECTS_FILE = BASE_DIR / "projects.json"
STATE_FILE = BASE_DIR / "dashboard" / "state.json"

def load_projects():
    """Load projects.json"""
    with open(PROJECTS_FILE) as f:
        return json.load(f)

def load_state():
    """Load state.json"""
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except:
        return {}

def save_state(state):
    """Save state.json"""
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)

def get_pending_tasks():
    """Get all pending tasks from projects.json"""
    projects = load_projects()
    tasks = []
    for project in projects.get("projects", []):
        for task in project.get("tasks", []):
            if task.get("status") == "pending":
                task["project_id"] = project["id"]
                tasks.append(task)
    return tasks

def dispatch_task(task, agent_name):
    """Mark task as in_progress and assign to agent"""
    projects = load_projects()

    for project in projects["projects"]:
        for t in project.get("tasks", []):
            if t.get("id") == task["id"]:
                t["status"] = "in_progress"
                t["agent"] = agent_name
                t["dispatched_at"] = datetime.now().isoformat()
                t["assigned_by"] = "task_dispatcher"

                # Save updated projects.json
                with open(PROJECTS_FILE, "w") as f:
                    json.dump(projects, f, indent=2)

                # Update state.json
                state = load_state()
                if "task_queue" not in state:
                    state["task_queue"] = {}
                state["task_queue"]["in_progress"] = state["task_queue"].get("in_progress", 0) + 1
                state["task_queue"]["pending"] = state["task_queue"].get("pending", 0) - 1
                save_state(state)

                return True
    return False

def show_pending():
    """List all pending tasks"""
    tasks = get_pending_tasks()
    if not tasks:
        print("✅ No pending tasks")
        return

    print(f"\n📋 {len(tasks)} Pending Tasks:")
    print("=" * 80)
    for i, task in enumerate(tasks[:10], 1):
        print(f"{i}. ID: {task['id']}")
        print(f"   Title: {task.get('title', 'N/A')}")
        print(f"   Agent: {task.get('agent', 'unassigned')}")
        print(f"   Priority: {task.get('priority', 'normal')}")
        print()

def dispatch_next(num_tasks=5):
    """Dispatch next N pending tasks to available agents"""
    tasks = get_pending_tasks()

    if not tasks:
        print("✅ No pending tasks to dispatch")
        return 0

    # Simple agent rotation (in real system, use more sophisticated routing)
    agents = ["architect", "executor", "frontend_agent", "qa_agent", "writer", "orchestrator"]
    agent_idx = 0
    dispatched = 0

    for task in tasks[:num_tasks]:
        agent = agents[agent_idx % len(agents)]
        if dispatch_task(task, agent):
            print(f"✅ Dispatched {task['id']} to {agent}")
            dispatched += 1
            agent_idx += 1
        else:
            print(f"❌ Failed to dispatch {task['id']}")

    print(f"\n📊 Dispatched {dispatched} tasks")
    return dispatched

def status():
    """Show dispatch status"""
    projects = load_projects()
    state = load_state()

    total = 0
    pending = 0
    in_progress = 0
    completed = 0

    for project in projects["projects"]:
        for task in project.get("tasks", []):
            total += 1
            status = task.get("status", "pending")
            if status == "pending":
                pending += 1
            elif status == "in_progress":
                in_progress += 1
            elif status == "completed":
                completed += 1

    print(f"\n📊 DISPATCH STATUS")
    print("=" * 50)
    print(f"Total Tasks:    {total}")
    print(f"Pending:        {pending}")
    print(f"In Progress:    {in_progress}")
    print(f"Completed:      {completed}")
    print(f"Progress:       {completed}/{total} ({100*completed//total if total else 0}%)")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        print("\nUsage:")
        print("  python3 task_dispatcher.py status          # Show task status")
        print("  python3 task_dispatcher.py list            # List pending tasks")
        print("  python3 task_dispatcher.py dispatch [N]    # Dispatch next N tasks (default 5)")
        sys.exit(0)

    cmd = sys.argv[1]

    if cmd == "status":
        status()
    elif cmd == "list":
        show_pending()
    elif cmd == "dispatch":
        num = int(sys.argv[2]) if len(sys.argv) > 2 else 5
        dispatch_next(num)
        status()
    else:
        print(f"Unknown command: {cmd}")
        sys.exit(1)
