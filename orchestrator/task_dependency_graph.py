#!/usr/bin/env python3
"""
orchestrator/task_dependency_graph.py — Task Dependency Graph & Parallel Execution
==================================================================================
Builds a DAG (Directed Acyclic Graph) from tasks with dependency declarations,
performs topological sort, identifies parallelizable work at each level, and
executes tasks concurrently in waves respecting dependency order.

Integration: replaces naive batching in parallel_executor.get_parallel_batch
with true dependency-aware scheduling.
"""

import time
import threading
from collections import defaultdict, deque
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


class CycleError(Exception):
    """Raised when the dependency graph contains a cycle."""
    pass


class MissingDependencyError(Exception):
    """Raised when a task depends on a non-existent task."""
    pass


class TaskDAG:
    """
    Directed Acyclic Graph for task dependencies.

    Each task is identified by a string ID. Dependencies are edges:
    if task B depends on task A, there is an edge A -> B (A must finish before B).
    """

    def __init__(self):
        self._adj: Dict[str, Set[str]] = defaultdict(set)      # parent -> children
        self._reverse: Dict[str, Set[str]] = defaultdict(set)   # child -> parents
        self._tasks: Dict[str, Dict[str, Any]] = {}             # id -> task data
        self._lock = threading.Lock()

    @property
    def task_ids(self) -> Set[str]:
        return set(self._tasks.keys())

    @property
    def size(self) -> int:
        return len(self._tasks)

    def add_task(self, task: Dict[str, Any]) -> None:
        """
        Add a task to the graph.

        Task dict must have 'id' (str). Optional 'depends_on' (list of task IDs).
        """
        task_id = task["id"]
        with self._lock:
            self._tasks[task_id] = task
            if task_id not in self._adj:
                self._adj[task_id] = set()
            if task_id not in self._reverse:
                self._reverse[task_id] = set()

    def add_dependency(self, task_id: str, depends_on: str) -> None:
        """Declare that task_id depends on depends_on (depends_on must finish first)."""
        with self._lock:
            self._adj[depends_on].add(task_id)
            self._reverse[task_id].add(depends_on)

    def build_from_tasks(self, tasks: List[Dict[str, Any]]) -> None:
        """
        Build the full graph from a list of task dicts.

        Each task dict: { "id": str, "depends_on": [str, ...], ... }
        """
        for task in tasks:
            self.add_task(task)

        for task in tasks:
            for dep_id in task.get("depends_on", []):
                if dep_id not in self._tasks:
                    raise MissingDependencyError(
                        f"Task '{task['id']}' depends on '{dep_id}' which does not exist"
                    )
                self.add_dependency(task["id"], dep_id)

        self._detect_cycle()

    def _detect_cycle(self) -> None:
        """Detect cycles using Kahn's algorithm. Raise CycleError if found."""
        in_degree = {tid: len(self._reverse[tid]) for tid in self._tasks}
        queue = deque(tid for tid, deg in in_degree.items() if deg == 0)
        visited = 0

        while queue:
            node = queue.popleft()
            visited += 1
            for child in self._adj[node]:
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        if visited != len(self._tasks):
            remaining = [tid for tid, deg in in_degree.items() if deg > 0]
            raise CycleError(
                f"Dependency cycle detected involving tasks: {remaining}"
            )

    def in_degree(self, task_id: str) -> int:
        return len(self._reverse.get(task_id, set()))

    def get_parents(self, task_id: str) -> Set[str]:
        return set(self._reverse.get(task_id, set()))

    def get_children(self, task_id: str) -> Set[str]:
        return set(self._adj.get(task_id, set()))

    def get_task(self, task_id: str) -> Dict[str, Any]:
        return self._tasks[task_id]

    def topological_sort(self) -> List[str]:
        """
        Return task IDs in topological order (Kahn's algorithm).
        Tasks with no dependencies come first.
        """
        in_degree = {tid: len(self._reverse[tid]) for tid in self._tasks}
        queue = deque(sorted(tid for tid, deg in in_degree.items() if deg == 0))
        result = []

        while queue:
            node = queue.popleft()
            result.append(node)
            for child in sorted(self._adj[node]):
                in_degree[child] -= 1
                if in_degree[child] == 0:
                    queue.append(child)

        return result

    def get_execution_waves(self, done: Optional[Set[str]] = None) -> List[List[str]]:
        """
        Partition tasks into waves (levels) for parallel execution.

        Wave 0: all tasks with no dependencies (or whose deps are all done).
        Wave 1: tasks whose deps are all in wave 0.
        Wave N: tasks whose deps are all in waves 0..N-1.

        Args:
            done: Set of already-completed task IDs to skip.

        Returns:
            List of waves, each wave is a list of task IDs that can run in parallel.
        """
        if done is None:
            done = set()

        remaining = {tid for tid in self._tasks if tid not in done}
        satisfied = set(done)
        waves = []

        while remaining:
            wave = []
            for tid in sorted(remaining):
                parents = self._reverse[tid]
                if parents.issubset(satisfied):
                    wave.append(tid)

            if not wave:
                raise CycleError(
                    f"Cannot make progress; possible cycle in: {remaining}"
                )

            waves.append(wave)
            satisfied.update(wave)
            remaining -= set(wave)

        return waves

    def get_ready_tasks(self, done: Set[str]) -> List[str]:
        """
        Get all tasks that are ready to execute (all deps satisfied).

        Args:
            done: Set of completed task IDs.

        Returns:
            List of task IDs ready to run.
        """
        ready = []
        for tid in self._tasks:
            if tid in done:
                continue
            parents = self._reverse[tid]
            if parents.issubset(done):
                ready.append(tid)
        return sorted(ready)

    def critical_path(self) -> Tuple[List[str], float]:
        """
        Find the critical path (longest path through the DAG by task weight).

        Uses 'weight' field from task data (default 1.0).

        Returns:
            (path as list of task IDs, total weight)
        """
        topo = self.topological_sort()
        dist: Dict[str, float] = {}
        prev: Dict[str, Optional[str]] = {}

        for tid in topo:
            w = self._tasks[tid].get("weight", 1.0)
            parents = self._reverse[tid]
            if not parents:
                dist[tid] = w
                prev[tid] = None
            else:
                best_parent = max(parents, key=lambda p: dist.get(p, 0))
                dist[tid] = dist[best_parent] + w
                prev[tid] = best_parent

        if not dist:
            return [], 0.0

        end = max(dist, key=dist.get)
        path = []
        node = end
        while node is not None:
            path.append(node)
            node = prev[node]
        path.reverse()

        return path, dist[end]

    def subgraph(self, task_ids: Set[str]) -> "TaskDAG":
        """Return a new DAG containing only the specified tasks and their inter-edges."""
        sub = TaskDAG()
        for tid in task_ids:
            if tid in self._tasks:
                sub.add_task(self._tasks[tid])
        for tid in task_ids:
            for dep in self._reverse.get(tid, set()):
                if dep in task_ids:
                    sub.add_dependency(tid, dep)
        return sub


class ParallelDAGExecutor:
    """
    Executes tasks from a TaskDAG in dependency order, running independent
    tasks concurrently within each wave.
    """

    def __init__(
        self,
        dag: TaskDAG,
        worker_fn: Callable[[Dict[str, Any]], Dict[str, Any]],
        max_workers: int = 4,
        timeout_per_task: int = 120,
    ):
        self.dag = dag
        self.worker_fn = worker_fn
        self.max_workers = max_workers
        self.timeout_per_task = timeout_per_task
        self.results: Dict[str, Dict[str, Any]] = {}
        self.done: Set[str] = set()
        self.failed: Set[str] = set()
        self._lock = threading.Lock()

    def execute_all(self) -> Dict[str, Dict[str, Any]]:
        """
        Execute all tasks in dependency order with maximum parallelism.

        Returns:
            Dict mapping task_id -> result dict.
        """
        waves = self.dag.get_execution_waves()
        total = self.dag.size
        completed = 0

        print(f"[DAG-EXEC] {total} tasks in {len(waves)} waves, max_workers={self.max_workers}")

        for wave_idx, wave in enumerate(waves):
            # Filter out tasks whose parents failed (cascade skip)
            runnable = []
            for tid in wave:
                parents = self.dag.get_parents(tid)
                if parents & self.failed:
                    print(f"  [SKIP] {tid} — parent failed")
                    with self._lock:
                        self.failed.add(tid)
                        self.results[tid] = {
                            "task_id": tid,
                            "status": "skipped",
                            "reason": "parent_failed",
                        }
                    completed += 1
                    continue
                runnable.append(tid)

            if not runnable:
                continue

            print(f"  [WAVE {wave_idx}] Running {len(runnable)} tasks: {runnable}")
            wave_results = self._execute_wave(runnable)

            for tid, result in wave_results.items():
                with self._lock:
                    self.results[tid] = result
                    if result.get("status") == "success":
                        self.done.add(tid)
                    else:
                        self.failed.add(tid)
                completed += 1

            print(f"  [WAVE {wave_idx}] Done. Progress: {completed}/{total}")

        return self.results

    def _execute_wave(self, task_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Execute a single wave of independent tasks in parallel."""
        wave_results = {}
        workers = min(self.max_workers, len(task_ids))

        with ThreadPoolExecutor(max_workers=workers) as pool:
            future_map = {}
            for tid in task_ids:
                task_data = self.dag.get_task(tid)
                future = pool.submit(self._run_one, task_data)
                future_map[future] = tid

            for future in as_completed(future_map, timeout=self.timeout_per_task * len(task_ids)):
                tid = future_map[future]
                try:
                    result = future.result(timeout=self.timeout_per_task)
                    wave_results[tid] = result
                except Exception as e:
                    wave_results[tid] = {
                        "task_id": tid,
                        "status": "failed",
                        "error": str(e),
                    }

        return wave_results

    def _run_one(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Run a single task through the worker function."""
        task_id = task["id"]
        start = time.time()
        try:
            result = self.worker_fn(task)
            elapsed = time.time() - start
            result.setdefault("task_id", task_id)
            result.setdefault("status", "success")
            result["elapsed_s"] = round(elapsed, 3)
            return result
        except Exception as e:
            elapsed = time.time() - start
            return {
                "task_id": task_id,
                "status": "failed",
                "error": str(e),
                "elapsed_s": round(elapsed, 3),
            }

    def execute_streaming(self) -> Dict[str, Dict[str, Any]]:
        """
        Execute tasks as soon as dependencies are met (streaming/dynamic scheduling).
        More efficient than wave-based when task durations vary widely.

        Returns:
            Dict mapping task_id -> result dict.
        """
        total = self.dag.size
        in_flight: Set[str] = set()
        completed = 0

        print(f"[DAG-STREAM] {total} tasks, max_workers={self.max_workers}")

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            future_map: Dict[Any, str] = {}

            def submit_ready():
                ready = self.dag.get_ready_tasks(self.done | self.failed)
                for tid in ready:
                    if tid in in_flight or tid in self.done or tid in self.failed:
                        continue
                    # Skip if parent failed
                    parents = self.dag.get_parents(tid)
                    if parents & self.failed:
                        with self._lock:
                            self.failed.add(tid)
                            self.results[tid] = {
                                "task_id": tid,
                                "status": "skipped",
                                "reason": "parent_failed",
                            }
                        continue
                    task_data = self.dag.get_task(tid)
                    future = pool.submit(self._run_one, task_data)
                    future_map[future] = tid
                    in_flight.add(tid)

            submit_ready()

            while len(self.done) + len(self.failed) < total:
                if not future_map:
                    break

                done_futures = []
                for future in as_completed(list(future_map.keys()), timeout=self.timeout_per_task):
                    tid = future_map.pop(future)
                    in_flight.discard(tid)
                    try:
                        result = future.result(timeout=1)
                    except Exception as e:
                        result = {"task_id": tid, "status": "failed", "error": str(e)}

                    with self._lock:
                        self.results[tid] = result
                        if result.get("status") == "success":
                            self.done.add(tid)
                        else:
                            self.failed.add(tid)

                    completed += 1
                    print(f"  [STREAM] {completed}/{total} — {tid}: {result.get('status')}")

                    # After each completion, submit newly-ready tasks
                    submit_ready()
                    break  # re-check as_completed with new futures

        return self.results


def get_dag_parallel_batch(
    dag: TaskDAG,
    done: Set[str],
    max_batch: int = 4,
) -> List[Dict[str, Any]]:
    """
    Drop-in replacement for parallel_executor.get_parallel_batch.
    Returns the next batch of tasks whose dependencies are all satisfied.

    Args:
        dag: The task dependency graph.
        done: Set of completed task IDs.
        max_batch: Maximum batch size.

    Returns:
        List of task dicts ready for parallel execution.
    """
    ready = dag.get_ready_tasks(done)
    batch = [dag.get_task(tid) for tid in ready[:max_batch]]
    return batch


# ---------------------------------------------------------------------------
# Main: assertions that verify correctness
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=" * 60)
    print("TEST 1: Basic DAG construction and topological sort")
    print("=" * 60)

    tasks = [
        {"id": "parse_input", "depends_on": []},
        {"id": "validate", "depends_on": ["parse_input"]},
        {"id": "fetch_data", "depends_on": ["parse_input"]},
        {"id": "transform", "depends_on": ["validate", "fetch_data"]},
        {"id": "write_output", "depends_on": ["transform"]},
    ]

    dag = TaskDAG()
    dag.build_from_tasks(tasks)

    topo = dag.topological_sort()
    print(f"  Topological order: {topo}")

    # parse_input must come before everything
    assert topo.index("parse_input") < topo.index("validate")
    assert topo.index("parse_input") < topo.index("fetch_data")
    assert topo.index("validate") < topo.index("transform")
    assert topo.index("fetch_data") < topo.index("transform")
    assert topo.index("transform") < topo.index("write_output")
    print("  ✓ Topological order correct")

    print()
    print("=" * 60)
    print("TEST 2: Execution waves")
    print("=" * 60)

    waves = dag.get_execution_waves()
    print(f"  Waves: {waves}")

    assert waves[0] == ["parse_input"]
    assert set(waves[1]) == {"fetch_data", "validate"}
    assert waves[2] == ["transform"]
    assert waves[3] == ["write_output"]
    print("  ✓ Waves correct (4 waves, wave 1 has 2 parallel tasks)")

    print()
    print("=" * 60)
    print("TEST 3: Ready tasks with partial completion")
    print("=" * 60)

    ready = dag.get_ready_tasks(done=set())
    assert ready == ["parse_input"]
    print(f"  Ready (nothing done): {ready} ✓")

    ready = dag.get_ready_tasks(done={"parse_input"})
    assert set(ready) == {"fetch_data", "validate"}
    print(f"  Ready (parse_input done): {ready} ✓")

    ready = dag.get_ready_tasks(done={"parse_input", "validate"})
    assert ready == ["fetch_data"]  # transform needs fetch_data too
    print(f"  Ready (parse_input+validate done): {ready} ✓")

    ready = dag.get_ready_tasks(done={"parse_input", "validate", "fetch_data"})
    assert ready == ["transform"]
    print(f"  Ready (3 done): {ready} ✓")

    print()
    print("=" * 60)
    print("TEST 4: Critical path")
    print("=" * 60)

    weighted_tasks = [
        {"id": "A", "depends_on": [], "weight": 1.0},
        {"id": "B", "depends_on": ["A"], "weight": 5.0},
        {"id": "C", "depends_on": ["A"], "weight": 2.0},
        {"id": "D", "depends_on": ["B", "C"], "weight": 1.0},
    ]

    dag2 = TaskDAG()
    dag2.build_from_tasks(weighted_tasks)
    path, total_weight = dag2.critical_path()
    print(f"  Critical path: {path}, weight: {total_weight}")
    assert path == ["A", "B", "D"]
    assert total_weight == 7.0
    print("  ✓ Critical path correct (A→B→D = 7.0)")

    print()
    print("=" * 60)
    print("TEST 5: Cycle detection")
    print("=" * 60)

    cyclic_tasks = [
        {"id": "X", "depends_on": ["Z"]},
        {"id": "Y", "depends_on": ["X"]},
        {"id": "Z", "depends_on": ["Y"]},
    ]

    try:
        dag3 = TaskDAG()
        dag3.build_from_tasks(cyclic_tasks)
        assert False, "Should have raised CycleError"
    except CycleError as e:
        print(f"  Caught CycleError: {e}")
        print("  ✓ Cycle detection works")

    print()
    print("=" * 60)
    print("TEST 6: Missing dependency detection")
    print("=" * 60)

    bad_tasks = [
        {"id": "A", "depends_on": ["GHOST"]},
    ]

    try:
        dag4 = TaskDAG()
        dag4.build_from_tasks(bad_tasks)
        assert False, "Should have raised MissingDependencyError"
    except MissingDependencyError as e:
        print(f"  Caught MissingDependencyError: {e}")
        print("  ✓ Missing dependency detection works")

    print()
    print("=" * 60)
    print("TEST 7: Parallel DAG execution (wave-based)")
    print("=" * 60)

    execution_log = []
    log_lock = threading.Lock()

    def mock_worker(task: Dict[str, Any]) -> Dict[str, Any]:
        tid = task["id"]
        duration = task.get("weight", 0.05)
        time.sleep(duration)
        with log_lock:
            execution_log.append(tid)
        return {"task_id": tid, "status": "success", "output": f"done-{tid}"}

    dag5 = TaskDAG()
    dag5.build_from_tasks([
        {"id": "a", "depends_on": [], "weight": 0.05},
        {"id": "b", "depends_on": [], "weight": 0.05},
        {"id": "c", "depends_on": [], "weight": 0.05},
        {"id": "d", "depends_on": ["a", "b"], "weight": 0.05},
        {"id": "e", "depends_on": ["c"], "weight": 0.05},
        {"id": "f", "depends_on": ["d", "e"], "weight": 0.05},
    ])

    executor = ParallelDAGExecutor(dag5, mock_worker, max_workers=3)
    results = executor.execute_all()

    print(f"  Execution order: {execution_log}")
    print(f"  Results: {list(results.keys())}")

    assert len(results) == 6
    for tid in ["a", "b", "c", "d", "e", "f"]:
        assert results[tid]["status"] == "success", f"Task {tid} should succeed"

    # Verify dependency ordering in execution log
    assert execution_log.index("a") < execution_log.index("d")
    assert execution_log.index("b") < execution_log.index("d")
    assert execution_log.index("c") < execution_log.index("e")
    assert execution_log.index("d") < execution_log.index("f")
    assert execution_log.index("e") < execution_log.index("f")
    print("  ✓ All 6 tasks completed in correct dependency order")

    print()
    print("=" * 60)
    print("TEST 8: Failure cascading (skip children of failed tasks)")
    print("=" * 60)

    def failing_worker(task: Dict[str, Any]) -> Dict[str, Any]:
        tid = task["id"]
        if tid == "fail_me":
            raise RuntimeError("Intentional failure")
        return {"task_id": tid, "status": "success"}

    dag6 = TaskDAG()
    dag6.build_from_tasks([
        {"id": "root", "depends_on": []},
        {"id": "fail_me", "depends_on": ["root"]},
        {"id": "child_of_fail", "depends_on": ["fail_me"]},
        {"id": "independent", "depends_on": ["root"]},
    ])

    executor2 = ParallelDAGExecutor(dag6, failing_worker, max_workers=2)
    results2 = executor2.execute_all()

    assert results2["root"]["status"] == "success"
    assert results2["fail_me"]["status"] == "failed"
    assert results2["child_of_fail"]["status"] == "skipped"
    assert results2["child_of_fail"]["reason"] == "parent_failed"
    assert results2["independent"]["status"] == "success"
    print("  ✓ Failed task cascades to children, independent tasks still run")

    print()
    print("=" * 60)
    print("TEST 9: Streaming execution")
    print("=" * 60)

    stream_log = []
    stream_lock = threading.Lock()

    def stream_worker(task: Dict[str, Any]) -> Dict[str, Any]:
        tid = task["id"]
        time.sleep(task.get("weight", 0.02))
        with stream_lock:
            stream_log.append(tid)
        return {"task_id": tid, "status": "success"}

    dag7 = TaskDAG()
    dag7.build_from_tasks([
        {"id": "s1", "depends_on": [], "weight": 0.02},
        {"id": "s2", "depends_on": [], "weight": 0.02},
        {"id": "s3", "depends_on": ["s1"], "weight": 0.02},
        {"id": "s4", "depends_on": ["s2", "s3"], "weight": 0.02},
    ])

    executor3 = ParallelDAGExecutor(dag7, stream_worker, max_workers=2)
    results3 = executor3.execute_streaming()

    assert len(results3) == 4
    for tid in ["s1", "s2", "s3", "s4"]:
        assert results3[tid]["status"] == "success"
    assert stream_log.index("s1") < stream_log.index("s3")
    assert stream_log.index("s3") < stream_log.index("s4")
    assert stream_log.index("s2") < stream_log.index("s4")
    print(f"  Stream order: {stream_log}")
    print("  ✓ Streaming execution respects dependencies")

    print()
    print("=" * 60)
    print("TEST 10: get_dag_parallel_batch (drop-in replacement)")
    print("=" * 60)

    batch = get_dag_parallel_batch(dag5, done=set(), max_batch=4)
    batch_ids = [t["id"] for t in batch]
    assert set(batch_ids) == {"a", "b", "c"}
    print(f"  Batch (none done): {batch_ids} ✓")

    batch = get_dag_parallel_batch(dag5, done={"a", "b", "c"}, max_batch=4)
    batch_ids = [t["id"] for t in batch]
    assert set(batch_ids) == {"d", "e"}
    print(f"  Batch (a,b,c done): {batch_ids} ✓")

    print()
    print("=" * 60)
    print("TEST 11: Subgraph extraction")
    print("=" * 60)

    sub = dag5.subgraph({"a", "b", "d"})
    assert sub.size == 3
    assert sub.get_parents("d") == {"a", "b"}
    assert sub.get_children("a") == {"d"}
    print(f"  Subgraph size: {sub.size}, parents of d: {sub.get_parents('d')} ✓")

    print()
    print("=" * 60)
    print("TEST 12: Empty DAG")
    print("=" * 60)

    dag_empty = TaskDAG()
    dag_empty.build_from_tasks([])
    assert dag_empty.topological_sort() == []
    assert dag_empty.get_execution_waves() == []
    assert dag_empty.get_ready_tasks(set()) == []
    path, w = dag_empty.critical_path()
    assert path == [] and w == 0.0
    print("  ✓ Empty DAG handles all operations gracefully")

    print()
    print("=" * 60)
    print("TEST 13: Single task DAG")
    print("=" * 60)

    dag_single = TaskDAG()
    dag_single.build_from_tasks([{"id": "solo", "depends_on": []}])
    assert dag_single.topological_sort() == ["solo"]
    assert dag_single.get_execution_waves() == [["solo"]]
    path, w = dag_single.critical_path()
    assert path == ["solo"] and w == 1.0
    print("  ✓ Single task DAG works")

    print()
    print("=" * 60)
    print("TEST 14: Wide DAG (all independent)")
    print("=" * 60)

    wide_tasks = [{"id": f"t{i}", "depends_on": []} for i in range(10)]
    dag_wide = TaskDAG()
    dag_wide.build_from_tasks(wide_tasks)
    waves = dag_wide.get_execution_waves()
    assert len(waves) == 1
    assert len(waves[0]) == 10
    print(f"  1 wave with {len(waves[0])} parallel tasks ✓")

    print()
    print("=" * 60)
    print("TEST 15: Deep chain (fully sequential)")
    print("=" * 60)

    chain_tasks = [{"id": f"c{i}", "depends_on": [f"c{i-1}"] if i > 0 else []} for i in range(5)]
    dag_chain = TaskDAG()
    dag_chain.build_from_tasks(chain_tasks)
    waves = dag_chain.get_execution_waves()
    assert len(waves) == 5
    for i, wave in enumerate(waves):
        assert wave == [f"c{i}"]
    print(f"  5 sequential waves ✓")

    print()
    print("=" * 60)
    print("ALL 15 TESTS PASSED")
    print("=" * 60)
