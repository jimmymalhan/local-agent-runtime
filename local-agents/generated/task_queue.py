import threading
import queue
import time


class TaskQueue:
    def __init__(self):
        self._queue = queue.Queue()
        self._results = []
        self._results_lock = threading.Lock()
        self._workers = []
        self._stop_event = threading.Event()

    def enqueue(self, func, *args):
        self._queue.put((func, args))

    def _worker(self):
        while not self._stop_event.is_set():
            try:
                func, args = self._queue.get(timeout=0.1)
            except queue.Empty:
                continue
            try:
                result = func(*args)
            except Exception as e:
                result = e
            with self._results_lock:
                self._results.append(result)
            self._queue.task_done()

    def start_workers(self, n):
        for _ in range(n):
            t = threading.Thread(target=self._worker, daemon=True)
            t.start()
            self._workers.append(t)

    def stop(self):
        self._queue.join()
        self._stop_event.set()
        for t in self._workers:
            t.join()

    def get_results(self):
        with self._results_lock:
            return list(self._results)


if __name__ == "__main__":
    def square(x):
        time.sleep(0.01)
        return x * x

    def failing_task(x):
        raise ValueError(f"bad value: {x}")

    tq = TaskQueue()

    # Enqueue 50 normal tasks
    for i in range(50):
        tq.enqueue(square, i)

    # Enqueue 5 failing tasks
    for i in range(5):
        tq.enqueue(failing_task, i)

    tq.start_workers(4)
    tq.stop()

    results = tq.get_results()

    assert len(results) == 55, f"Expected 55 results, got {len(results)}"

    exceptions = [r for r in results if isinstance(r, Exception)]
    successes = [r for r in results if not isinstance(r, Exception)]

    assert len(exceptions) == 5, f"Expected 5 exceptions, got {len(exceptions)}"
    assert len(successes) == 50, f"Expected 50 successes, got {len(successes)}"
    assert sorted(successes) == [i * i for i in range(50)], "Square results mismatch"

    for e in exceptions:
        assert isinstance(e, ValueError)

    print(f"All assertions passed: {len(successes)} successes, {len(exceptions)} exceptions handled.")
