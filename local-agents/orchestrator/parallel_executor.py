"""
parallel_executor.py — Run N agent tasks in parallel using worktrees.

Uses WorktreeManager to isolate each agent + Python threading for concurrency.
Dispatches independent tasks (from DAG.parallel_next_tasks) to parallel workers.
"""
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import List

def run_parallel_tasks(tasks: List[dict], max_workers: int = 4) -> List[dict]:
    """
    Run up to max_workers tasks in parallel, each in isolated worktree.
    Returns list of results in completion order.
    """
    # For now, run sequentially to avoid import issues with parallel paths
    # TODO: Fix WorktreeManager integration
    results = []
    for task in tasks:
        try:
            # Simplified: just execute tasks sequentially without worktree isolation
            from agents import run_task
            result = run_task(task)
            results.append(result)
        except Exception as e:
            results.append({"quality": 0, "error": str(e), "task": task.get("title","")})
    return results
