"""
Local Agents Kanban Tool for Open WebUI
Load: Open WebUI => Workspace => Tools => upload this file
"""
import httpx

API = "http://localhost:8000"


async def create_task(title: str, project_id: int = 1, task_type: str = "code",
                      priority: str = "medium", estimated_hours: float = 2.0) -> dict:
    """Create a new task on the Local Agents kanban board."""
    async with httpx.AsyncClient() as c:
        r = await c.post(f"{API}/tasks", json={
            "title": title, "project_id": project_id,
            "task_type": task_type, "priority": priority,
            "estimated_hours": estimated_hours, "assignee": "local-agent",
        })
        return r.json()


async def get_blocked_tasks() -> list:
    """Return all blocked tasks that need attention."""
    async with httpx.AsyncClient() as c:
        return (await c.get(f"{API}/tasks?status=blocked")).json()


async def get_global_eta() -> dict:
    """Get real-time global ETA across all projects and tasks."""
    async with httpx.AsyncClient() as c:
        return (await c.get(f"{API}/metrics/global-eta")).json()


async def complete_task(task_id: int) -> dict:
    """Mark a task as done."""
    async with httpx.AsyncClient() as c:
        return (await c.patch(f"{API}/tasks/{task_id}/status",
                              json={"status": "done"})).json()


async def get_agent_status() -> dict:
    """Get current agent worker status — which model is doing which task."""
    async with httpx.AsyncClient() as c:
        return (await c.get(f"{API}/agent/status")).json()


async def list_tasks(project_id: int = 1, status: str = None) -> list:
    """List tasks, optionally filtered by status."""
    async with httpx.AsyncClient() as c:
        params = f"?project_id={project_id}"
        if status:
            params += f"&status={status}"
        return (await c.get(f"{API}/tasks{params}")).json()


async def get_metrics() -> dict:
    """Get project metrics — velocity, burndown, ETA accuracy, costs."""
    async with httpx.AsyncClient() as c:
        return (await c.get(f"{API}/metrics")).json()
