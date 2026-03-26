"""
parallel_executor.py — Run N agent tasks in parallel using worktrees.

Uses WorktreeManager to isolate each agent + Python threading for concurrency.
Dispatches independent tasks (from DAG.parallel_next_tasks) to parallel workers.
"""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List
from .worktree_manager import WorktreeManager

def run_parallel_tasks(tasks: List[dict], max_workers: int = 4) -> List[dict]:
    """
    Run up to max_workers tasks in parallel, each in isolated worktree.
    Returns list of results in completion order.
    """
    import sys; sys.path.insert(0, '.')
    from local_agents.agents import run_task as _run_task

    mgr = WorktreeManager()
    results = []

    def execute_one(task: dict) -> dict:
        agent_id = f"parallel-{task.get('id','x')[:8]}"
        try:
            path = mgr.allocate(agent_id, task_id=task.get("id",""))
            result = _run_task(task)
            quality = result.get("quality", 0)
            mgr.merge_or_discard(agent_id, quality, commit_message=task.get("title",""))
            return result
        except Exception as e:
            mgr.release(agent_id)
            return {"quality": 0, "error": str(e), "task": task.get("title","")}

    with ThreadPoolExecutor(max_workers=min(max_workers, len(tasks))) as pool:
        futures = {pool.submit(execute_one, task): task for task in tasks}
        for future in as_completed(futures):
            results.append(future.result())

    return results
