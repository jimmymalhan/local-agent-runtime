"""
Distributed Task Queue with Producer, Broker, Consumer Pool,
Dead Letter Queue, Worker Heartbeat, Retry on Timeout, and Poison Pill Handling.
"""

import threading
import time
import uuid
import queue
import enum
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional
from collections import defaultdict


class TaskState(enum.Enum):
    PENDING = "pending"
    DISPATCHED = "dispatched"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    DEAD = "dead"  # moved to DLQ


@dataclass
class Task:
    task_id: str
    func_name: str
    args: tuple = ()
    kwargs: dict = field(default_factory=dict)
    state: TaskState = TaskState.PENDING
    retries: int = 0
    max_retries: int = 3
    timeout: float = 5.0
    result: Any = None
    error: Optional[str] = None
    created_at: float = field(default_factory=time.time)
    started_at: Optional[float] = None
    completed_at: Optional[float] = None


@dataclass
class WorkerHeartbeat:
    worker_id: str
    last_seen: float
    current_task_id: Optional[str] = None
    alive: bool = True


class DeadLetterQueue:
    """Stores tasks that have exhausted all retries or are poison pills."""

    def __init__(self):
        self._lock = threading.Lock()
        self._tasks: List[Task] = []

    def put(self, task: Task, reason: str):
        with self._lock:
            task.state = TaskState.DEAD
            task.error = reason
            self._tasks.append(task)

    def get_all(self) -> List[Task]:
        with self._lock:
            return list(self._tasks)

    def size(self) -> int:
        with self._lock:
            return len(self._tasks)


class Broker:
    """
    In-memory message broker. Manages task queue, dispatching,
    timeout detection, retries, and dead-lettering.
    """

    def __init__(self, dlq: DeadLetterQueue, task_timeout: float = 5.0):
        self._pending: queue.Queue[Task] = queue.Queue()
        self._in_flight: Dict[str, Task] = {}
        self._completed: Dict[str, Task] = {}
        self._lock = threading.Lock()
        self._dlq = dlq
        self._task_timeout = task_timeout
        self._heartbeats: Dict[str, WorkerHeartbeat] = {}
        self._heartbeat_lock = threading.Lock()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._function_registry: Dict[str, Callable] = {}
        self._poison_funcs: set = set()

    def register_function(self, name: str, func: Callable):
        self._function_registry[name] = func

    def mark_poison(self, func_name: str):
        """Mark a function as a poison pill — always route to DLQ."""
        self._poison_funcs.add(func_name)

    def submit(self, task: Task):
        if task.func_name in self._poison_funcs:
            self._dlq.put(task, f"Poison pill: function '{task.func_name}' is blacklisted")
            return
        task.state = TaskState.PENDING
        self._pending.put(task)

    def dispatch(self, timeout: float = 1.0) -> Optional[Task]:
        """Blocking get from the pending queue. Returns None on timeout."""
        try:
            task = self._pending.get(timeout=timeout)
        except queue.Empty:
            return None
        with self._lock:
            task.state = TaskState.DISPATCHED
            task.started_at = time.time()
            self._in_flight[task.task_id] = task
        return task

    def complete(self, task_id: str, result: Any):
        with self._lock:
            task = self._in_flight.pop(task_id, None)
            if task:
                task.state = TaskState.COMPLETED
                task.result = result
                task.completed_at = time.time()
                self._completed[task_id] = task

    def fail(self, task_id: str, error: str):
        with self._lock:
            task = self._in_flight.pop(task_id, None)
        if task:
            self._retry_or_dlq(task, error)

    def _retry_or_dlq(self, task: Task, error: str):
        task.retries += 1
        if task.retries > task.max_retries:
            self._dlq.put(task, f"Max retries exceeded. Last error: {error}")
        else:
            task.state = TaskState.PENDING
            task.started_at = None
            task.error = error
            self._pending.put(task)

    def resolve_function(self, func_name: str) -> Optional[Callable]:
        return self._function_registry.get(func_name)

    # --- Heartbeat ---

    def register_worker(self, worker_id: str):
        with self._heartbeat_lock:
            self._heartbeats[worker_id] = WorkerHeartbeat(
                worker_id=worker_id, last_seen=time.time()
            )

    def heartbeat(self, worker_id: str, task_id: Optional[str] = None):
        with self._heartbeat_lock:
            hb = self._heartbeats.get(worker_id)
            if hb:
                hb.last_seen = time.time()
                hb.current_task_id = task_id

    def unregister_worker(self, worker_id: str):
        with self._heartbeat_lock:
            hb = self._heartbeats.pop(worker_id, None)
            if hb:
                hb.alive = False

    def get_worker_heartbeats(self) -> Dict[str, WorkerHeartbeat]:
        with self._heartbeat_lock:
            return dict(self._heartbeats)

    # --- Timeout Monitor ---

    def start_monitor(self, interval: float = 0.5):
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, args=(interval,), daemon=True
        )
        self._monitor_thread.start()

    def stop_monitor(self):
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=3)

    def _monitor_loop(self, interval: float):
        while self._running:
            self._check_timeouts()
            self._check_dead_workers()
            time.sleep(interval)

    def _check_timeouts(self):
        now = time.time()
        timed_out = []
        with self._lock:
            for task_id, task in list(self._in_flight.items()):
                if task.started_at and (now - task.started_at) > task.timeout:
                    timed_out.append(self._in_flight.pop(task_id))
        for task in timed_out:
            self._retry_or_dlq(task, f"Task timed out after {task.timeout}s")

    def _check_dead_workers(self):
        now = time.time()
        dead_threshold = self._task_timeout * 5
        with self._heartbeat_lock:
            for wid, hb in list(self._heartbeats.items()):
                if hb.alive and (now - hb.last_seen) > dead_threshold:
                    hb.alive = False

    # --- Stats ---

    def stats(self) -> dict:
        with self._lock:
            return {
                "pending": self._pending.qsize(),
                "in_flight": len(self._in_flight),
                "completed": len(self._completed),
                "dead": self._dlq.size(),
            }

    def get_completed(self) -> Dict[str, Task]:
        with self._lock:
            return dict(self._completed)


class Consumer(threading.Thread):
    """Worker thread that pulls tasks from the broker and executes them."""

    def __init__(self, worker_id: str, broker: Broker):
        super().__init__(daemon=True)
        self.worker_id = worker_id
        self.broker = broker
        self._stop_event = threading.Event()
        self.tasks_processed = 0
        broker.register_worker(worker_id)

    def run(self):
        while not self._stop_event.is_set():
            task = self.broker.dispatch(timeout=0.5)
            if task is None:
                self.broker.heartbeat(self.worker_id)
                continue

            self.broker.heartbeat(self.worker_id, task.task_id)
            func = self.broker.resolve_function(task.func_name)

            if func is None:
                self.broker.fail(
                    task.task_id, f"Unknown function: {task.func_name}"
                )
                continue

            try:
                task.state = TaskState.RUNNING
                result = func(*task.args, **task.kwargs)
                self.broker.complete(task.task_id, result)
                self.tasks_processed += 1
            except Exception as e:
                self.broker.fail(task.task_id, f"{type(e).__name__}: {e}")
            finally:
                self.broker.heartbeat(self.worker_id)

    def stop(self):
        self._stop_event.set()
        self.broker.unregister_worker(self.worker_id)


class ConsumerPool:
    """Manages a pool of consumer worker threads."""

    def __init__(self, broker: Broker, size: int = 4):
        self.broker = broker
        self.size = size
        self.workers: List[Consumer] = []

    def start(self):
        for i in range(self.size):
            worker = Consumer(f"worker-{i}", self.broker)
            self.workers.append(worker)
            worker.start()

    def stop(self):
        for w in self.workers:
            w.stop()
        for w in self.workers:
            w.join(timeout=3)

    def total_processed(self) -> int:
        return sum(w.tasks_processed for w in self.workers)


class Producer:
    """Submits tasks to the broker."""

    def __init__(self, broker: Broker):
        self.broker = broker

    def submit(
        self,
        func_name: str,
        args: tuple = (),
        kwargs: dict = None,
        max_retries: int = 3,
        timeout: float = 5.0,
    ) -> str:
        task_id = str(uuid.uuid4())
        task = Task(
            task_id=task_id,
            func_name=func_name,
            args=args,
            kwargs=kwargs or {},
            max_retries=max_retries,
            timeout=timeout,
        )
        self.broker.submit(task)
        return task_id

    def submit_batch(
        self, func_name: str, args_list: List[tuple], **kwargs
    ) -> List[str]:
        return [self.submit(func_name, args=a, **kwargs) for a in args_list]


# ---------------------------------------------------------------------------
# Sample task functions
# ---------------------------------------------------------------------------

def add(a, b):
    return a + b


def flaky_task(fail_count_holder: list):
    """Fails the first N times, then succeeds. fail_count_holder is [remaining_failures]."""
    if fail_count_holder[0] > 0:
        fail_count_holder[0] -= 1
        raise RuntimeError("Transient failure")
    return "recovered"


def slow_task(duration: float):
    """Simulates a task that takes too long."""
    time.sleep(duration)
    return "done"


def poison_task():
    """Should never actually run — marked as poison pill."""
    raise Exception("This should never execute")


# ---------------------------------------------------------------------------
# Main: end-to-end verification
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 60)
    print("Distributed Task Queue — Integration Test")
    print("=" * 60)

    dlq = DeadLetterQueue()
    broker = Broker(dlq, task_timeout=2.0)

    # Register functions
    broker.register_function("add", add)
    broker.register_function("flaky_task", flaky_task)
    broker.register_function("slow_task", slow_task)
    broker.register_function("poison_task", poison_task)
    broker.mark_poison("poison_task")

    broker.start_monitor(interval=0.3)

    pool = ConsumerPool(broker, size=3)
    pool.start()

    producer = Producer(broker)

    # ---------------------------------------------------------------
    # Test 1: Normal tasks complete successfully
    # ---------------------------------------------------------------
    print("\n[Test 1] Normal tasks (add)...")
    task_ids = []
    for i in range(10):
        tid = producer.submit("add", args=(i, i * 2))
        task_ids.append(tid)

    time.sleep(2)
    completed = broker.get_completed()
    completed_count = sum(1 for tid in task_ids if tid in completed)
    assert completed_count == 10, f"Expected 10 completed, got {completed_count}"

    # Verify results
    for i, tid in enumerate(task_ids):
        assert completed[tid].result == i + i * 2, (
            f"Task {tid} wrong result: {completed[tid].result}"
        )
    print(f"  PASS: {completed_count}/10 tasks completed with correct results")

    # ---------------------------------------------------------------
    # Test 2: Flaky task retries and eventually succeeds
    # ---------------------------------------------------------------
    print("\n[Test 2] Flaky task (retry logic)...")
    fail_holder = [2]  # fail twice, succeed on 3rd attempt
    tid_flaky = producer.submit("flaky_task", args=(fail_holder,), max_retries=3)

    time.sleep(3)
    completed = broker.get_completed()
    assert tid_flaky in completed, "Flaky task should have eventually completed"
    assert completed[tid_flaky].result == "recovered"
    print(f"  PASS: Flaky task recovered after retries, result='{completed[tid_flaky].result}'")

    # ---------------------------------------------------------------
    # Test 3: Task that always fails goes to DLQ
    # ---------------------------------------------------------------
    print("\n[Test 3] Permanent failure -> DLQ...")
    always_fail_holder = [999]  # will always fail
    tid_fail = producer.submit(
        "flaky_task", args=(always_fail_holder,), max_retries=2
    )

    time.sleep(4)
    dlq_tasks = dlq.get_all()
    dlq_ids = [t.task_id for t in dlq_tasks]
    assert tid_fail in dlq_ids, "Permanently failing task should be in DLQ"
    dead_task = next(t for t in dlq_tasks if t.task_id == tid_fail)
    assert "Max retries exceeded" in dead_task.error
    print(f"  PASS: Task in DLQ with error: '{dead_task.error[:60]}...'")

    # ---------------------------------------------------------------
    # Test 4: Timeout -> retry -> DLQ
    # ---------------------------------------------------------------
    print("\n[Test 4] Timeout detection -> retry -> DLQ...")
    tid_slow = producer.submit(
        "slow_task", args=(10.0,), max_retries=1, timeout=1.0
    )

    time.sleep(6)
    dlq_tasks = dlq.get_all()
    dlq_ids = [t.task_id for t in dlq_tasks]
    assert tid_slow in dlq_ids, "Timed-out task should end up in DLQ"
    dead_slow = next(t for t in dlq_tasks if t.task_id == tid_slow)
    assert "timed out" in dead_slow.error.lower()
    print(f"  PASS: Timed-out task in DLQ: '{dead_slow.error[:60]}...'")

    # ---------------------------------------------------------------
    # Test 5: Poison pill goes directly to DLQ
    # ---------------------------------------------------------------
    print("\n[Test 5] Poison pill handling...")
    dlq_before = dlq.size()
    tid_poison = producer.submit("poison_task")
    time.sleep(0.5)
    dlq_after = dlq.size()
    assert dlq_after == dlq_before + 1, "Poison pill should go straight to DLQ"
    poison_tasks = [t for t in dlq.get_all() if t.task_id == tid_poison]
    assert len(poison_tasks) == 1
    assert "Poison pill" in poison_tasks[0].error
    print(f"  PASS: Poison pill routed to DLQ: '{poison_tasks[0].error}'")

    # ---------------------------------------------------------------
    # Test 6: Worker heartbeats
    # ---------------------------------------------------------------
    print("\n[Test 6] Worker heartbeats...")
    heartbeats = broker.get_worker_heartbeats()
    registered_workers = [wid for wid in heartbeats]
    assert len(registered_workers) == 3, f"Expected 3 registered workers, got {len(registered_workers)}"
    # At least some workers should be alive (one may be stuck on slow_task)
    alive_workers = [wid for wid, hb in heartbeats.items() if hb.alive]
    assert len(alive_workers) >= 1, f"Expected at least 1 alive worker, got {len(alive_workers)}"
    # Submit a quick task and wait — proves heartbeat loop is working
    tid_hb = producer.submit("add", args=(100, 200))
    time.sleep(1)
    assert tid_hb in broker.get_completed(), "Heartbeat probe task should complete"
    print(f"  PASS: {len(registered_workers)} workers registered, {len(alive_workers)} alive, heartbeat probe OK")

    # ---------------------------------------------------------------
    # Test 7: Unknown function -> fail + retry -> DLQ
    # ---------------------------------------------------------------
    print("\n[Test 7] Unknown function handling...")
    tid_unknown = producer.submit("nonexistent_func", max_retries=1)
    time.sleep(3)
    dlq_tasks = dlq.get_all()
    dlq_ids = [t.task_id for t in dlq_tasks]
    assert tid_unknown in dlq_ids, "Unknown function task should be in DLQ"
    print("  PASS: Unknown function task routed to DLQ after retries")

    # ---------------------------------------------------------------
    # Test 8: Batch submission
    # ---------------------------------------------------------------
    print("\n[Test 8] Batch submission...")
    batch_ids = producer.submit_batch("add", [(1, 2), (3, 4), (5, 6), (7, 8)])
    time.sleep(2)
    completed = broker.get_completed()
    batch_results = [completed[tid].result for tid in batch_ids if tid in completed]
    assert batch_results == [3, 7, 11, 15], f"Batch results wrong: {batch_results}"
    print(f"  PASS: Batch of 4 tasks returned {batch_results}")

    # ---------------------------------------------------------------
    # Stats & Cleanup
    # ---------------------------------------------------------------
    print("\n[Stats]")
    stats = broker.stats()
    print(f"  Pending: {stats['pending']}")
    print(f"  In-flight: {stats['in_flight']}")
    print(f"  Completed: {stats['completed']}")
    print(f"  Dead (DLQ): {stats['dead']}")
    print(f"  Total processed by pool: {pool.total_processed()}")

    pool.stop()
    broker.stop_monitor()

    print("\n" + "=" * 60)
    print("ALL TESTS PASSED")
    print("=" * 60)
