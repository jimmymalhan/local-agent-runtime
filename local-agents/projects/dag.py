"""
dag.py — Directed Acyclic Graph for task dependencies + critical path analysis.

Enables parallel agent dispatch: tasks with no blockers run simultaneously.
Critical path highlights which tasks determine total project duration.
"""
from collections import defaultdict, deque
from typing import List


class TaskDAG:
    def __init__(self):
        self.tasks = {}                    # id -> task dict
        self.edges = defaultdict(set)      # id -> set of ids it blocks
        self.reverse = defaultdict(set)    # id -> set of ids that block it

    def add_task(self, task_id: str, task: dict):
        self.tasks[task_id] = task

    def add_dependency(self, blocker_id: str, blocked_id: str):
        """blocker must complete before blocked can start"""
        self.edges[blocker_id].add(blocked_id)
        self.reverse[blocked_id].add(blocker_id)

    def topological_sort(self) -> List[str]:
        """Kahn's algorithm — returns execution order"""
        in_degree = {t: len(self.reverse[t]) for t in self.tasks}
        queue = deque([t for t in self.tasks if in_degree[t] == 0])
        order = []
        while queue:
            node = queue.popleft()
            order.append(node)
            for neighbor in self.edges[node]:
                in_degree[neighbor] -= 1
                if in_degree[neighbor] == 0:
                    queue.append(neighbor)
        if len(order) != len(self.tasks):
            raise ValueError("Cycle detected in task dependencies")
        return order

    def critical_path(self) -> List[str]:
        """Longest path through DAG — determines minimum project duration"""
        order = self.topological_sort()
        dist = {t: self.tasks[t].get("effort_hours", 1) for t in self.tasks}
        prev = {t: None for t in self.tasks}
        for node in order:
            for neighbor in self.edges[node]:
                new_dist = dist[node] + self.tasks[neighbor].get("effort_hours", 1)
                if new_dist > dist[neighbor]:
                    dist[neighbor] = new_dist
                    prev[neighbor] = node
        end = max(dist, key=dist.get)
        path = []
        while end:
            path.append(end)
            end = prev[end]
        return list(reversed(path))

    def available_tasks(self) -> List[str]:
        """Tasks with no incomplete blockers — can start now"""
        return [
            t for t in self.tasks
            if self.tasks[t].get("status", "pending") == "pending"
            and all(self.tasks.get(b, {}).get("status") == "done" for b in self.reverse[t])
        ]

    def parallel_groups(self) -> List[List[str]]:
        """Group tasks that can run in parallel (no deps between them)"""
        order = self.topological_sort()
        groups = []
        levels = {}
        for t in order:
            level = 0
            for blocker in self.reverse[t]:
                level = max(level, levels.get(blocker, 0) + 1)
            levels[t] = level
            if level >= len(groups):
                groups.append([])
            groups[level].append(t)
        return groups

    def blocking_score(self, task_id: str) -> int:
        """How many tasks are transitively blocked by this task"""
        visited = set()
        stack = list(self.edges[task_id])
        while stack:
            t = stack.pop()
            if t not in visited:
                visited.add(t)
                stack.extend(self.edges[t])
        return len(visited)
