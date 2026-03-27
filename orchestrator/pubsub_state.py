#!/usr/bin/env python3
"""
orchestrator/pubsub_state.py — Event-Driven State Updates (Publish-Subscribe)
==============================================================================
Replaces all polling loops with reactive, event-driven state propagation.

Components:
  - ReactiveStateStore: State container that auto-publishes on every mutation.
  - StateWatcher: Subscribe to key patterns; callbacks fire on change (no polling).
  - DashboardReactor: Reacts to state events and updates dashboard atomically.
  - AgentHealthReactor: Monitors agent heartbeats via events, detects stale agents.
  - TaskQueueReactor: Tracks task lifecycle via events, maintains queue metrics.
  - PollingEliminator: Drop-in replacement for while+sleep polling patterns.

Usage:
    store = ReactiveStateStore()
    store.watch("agent.*.status", lambda key, old, new: print(f"{key}: {old} -> {new}"))
    store.set("agent.executor.status", "running")  # triggers callback immediately
"""

import time
import json
import threading
import re
import os
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Tuple


# ── Topic Pattern Matcher ────────────────────────────────────────────────────

def _compile_pattern(pattern: str) -> re.Pattern:
    """Compile a dot-separated topic pattern with * and # wildcards into regex.
    '*' matches one segment, '#' matches zero or more segments.
    """
    if pattern == "#":
        return re.compile(r".*")
    segments = pattern.split(".")
    parts = []
    for seg in segments:
        if seg == "#":
            parts.append(r"(?:[^.]+(?:\.[^.]+)*)?")
        elif seg == "*":
            parts.append(r"[^.]+")
        else:
            parts.append(re.escape(seg))
    regex = r"\.".join(parts)
    # Trailing # should match zero or more trailing segments
    regex = regex.replace(r"\.(?:[^.]+(?:\.[^.]+)*)?", r"(?:\..+)?")
    return re.compile(f"^{regex}$")


def _topic_matches(pattern: str, topic: str) -> bool:
    """Check if a topic matches a pattern with wildcard support."""
    return bool(_compile_pattern(pattern).match(topic))


# ── Change Event ─────────────────────────────────────────────────────────────

@dataclass(frozen=True)
class StateChange:
    """Immutable record of a state mutation."""
    key: str
    old_value: Any
    new_value: Any
    timestamp: float
    source: str = "system"

    @property
    def changed(self) -> bool:
        return self.old_value != self.new_value

    def to_dict(self) -> dict:
        return {
            "key": self.key,
            "old_value": self.old_value,
            "new_value": self.new_value,
            "timestamp": self.timestamp,
            "source": self.source,
            "changed": self.changed,
        }


# ── Subscription ─────────────────────────────────────────────────────────────

@dataclass
class StateSubscription:
    """A watcher bound to a key pattern."""
    pattern: str
    callback: Callable[[StateChange], None]
    sub_id: str = ""
    priority: int = 0
    once: bool = False
    filter_unchanged: bool = True  # Skip if old == new

    def __post_init__(self):
        if not self.sub_id:
            self.sub_id = f"ssub-{id(self) & 0xFFFFFF:06x}"
        self._compiled = _compile_pattern(self.pattern)

    def matches(self, key: str) -> bool:
        return bool(self._compiled.match(key))


# ── ReactiveStateStore ───────────────────────────────────────────────────────

class ReactiveStateStore:
    """
    In-memory state store with publish-subscribe on every mutation.
    Eliminates polling: watchers are notified synchronously on set().

    Thread-safe. Supports key-pattern subscriptions with wildcards.
    Tracks change history for replay and auditing.
    """

    def __init__(self, history_size: int = 500):
        self._state: Dict[str, Any] = {}
        self._lock = threading.RLock()

        self._subscriptions: List[StateSubscription] = []
        self._sub_lock = threading.RLock()

        self._history: deque[StateChange] = deque(maxlen=history_size)
        self._history_lock = threading.Lock()

        # Metrics
        self._set_count = 0
        self._notify_count = 0
        self._error_count = 0
        self._dead_letters: deque[dict] = deque(maxlen=200)

    # ── Core API ──────────────────────────────────────────────────────────

    def set(self, key: str, value: Any, source: str = "system") -> StateChange:
        """Set a value and notify all matching subscribers. Returns the change."""
        with self._lock:
            old = self._state.get(key)
            self._state[key] = value
            self._set_count += 1

        change = StateChange(
            key=key,
            old_value=old,
            new_value=value,
            timestamp=time.time(),
            source=source,
        )

        with self._history_lock:
            self._history.append(change)

        self._notify(change)
        return change

    def get(self, key: str, default: Any = None) -> Any:
        """Read a value. O(1), no side effects."""
        with self._lock:
            return self._state.get(key, default)

    def get_many(self, keys: List[str]) -> Dict[str, Any]:
        """Batch read multiple keys atomically."""
        with self._lock:
            return {k: self._state.get(k) for k in keys}

    def get_prefix(self, prefix: str) -> Dict[str, Any]:
        """Get all keys starting with prefix."""
        with self._lock:
            return {k: v for k, v in self._state.items() if k.startswith(prefix)}

    def delete(self, key: str, source: str = "system") -> Optional[StateChange]:
        """Delete a key and notify subscribers."""
        with self._lock:
            if key not in self._state:
                return None
            old = self._state.pop(key)
            self._set_count += 1

        change = StateChange(
            key=key, old_value=old, new_value=None,
            timestamp=time.time(), source=source,
        )
        with self._history_lock:
            self._history.append(change)
        self._notify(change)
        return change

    def increment(self, key: str, delta: int = 1, source: str = "system") -> int:
        """Atomic increment, returns new value."""
        with self._lock:
            old = self._state.get(key, 0)
            new_val = int(old) + delta
            self._state[key] = new_val
            self._set_count += 1

        change = StateChange(
            key=key, old_value=old, new_value=new_val,
            timestamp=time.time(), source=source,
        )
        with self._history_lock:
            self._history.append(change)
        self._notify(change)
        return new_val

    def update_dict(self, key: str, updates: dict, source: str = "system") -> StateChange:
        """Merge updates into a dict-valued key."""
        with self._lock:
            old = self._state.get(key, {})
            if not isinstance(old, dict):
                old = {}
            new_val = {**old, **updates}
            self._state[key] = new_val
            self._set_count += 1

        change = StateChange(
            key=key, old_value=old, new_value=new_val,
            timestamp=time.time(), source=source,
        )
        with self._history_lock:
            self._history.append(change)
        self._notify(change)
        return change

    def snapshot(self) -> Dict[str, Any]:
        """Atomic snapshot of entire state."""
        with self._lock:
            return dict(self._state)

    def load(self, data: Dict[str, Any]) -> None:
        """Bulk load without triggering subscribers (for init)."""
        with self._lock:
            self._state.update(data)

    # ── Subscribe / Watch ─────────────────────────────────────────────────

    def watch(
        self,
        pattern: str,
        callback: Callable[[StateChange], None],
        priority: int = 0,
        filter_unchanged: bool = True,
    ) -> str:
        """Watch keys matching pattern. Returns subscription ID."""
        sub = StateSubscription(
            pattern=pattern,
            callback=callback,
            priority=priority,
            filter_unchanged=filter_unchanged,
        )
        with self._sub_lock:
            self._subscriptions.append(sub)
            self._subscriptions.sort(key=lambda s: -s.priority)
        return sub.sub_id

    def watch_once(
        self,
        pattern: str,
        callback: Callable[[StateChange], None],
    ) -> str:
        """Watch for a single change, then auto-unsubscribe."""
        sub = StateSubscription(
            pattern=pattern,
            callback=callback,
            once=True,
        )
        with self._sub_lock:
            self._subscriptions.append(sub)
        return sub.sub_id

    def unwatch(self, sub_id: str) -> bool:
        """Remove a subscription. Returns True if found."""
        with self._sub_lock:
            before = len(self._subscriptions)
            self._subscriptions = [s for s in self._subscriptions if s.sub_id != sub_id]
            return len(self._subscriptions) < before

    def wait_for(self, pattern: str, timeout: float = 30.0) -> Optional[StateChange]:
        """Block until a matching state change occurs. Returns change or None."""
        result = [None]
        event = threading.Event()

        def handler(change: StateChange):
            result[0] = change
            event.set()

        sub_id = self.watch(pattern, handler, priority=999, filter_unchanged=False)
        event.wait(timeout=timeout)
        self.unwatch(sub_id)
        return result[0]

    def wait_for_value(
        self, key: str, expected: Any, timeout: float = 30.0
    ) -> bool:
        """Block until key equals expected value. Returns True if matched."""
        current = self.get(key)
        if current == expected:
            return True

        matched = threading.Event()

        def handler(change: StateChange):
            if change.new_value == expected:
                matched.set()

        sub_id = self.watch(key, handler, filter_unchanged=True)
        matched.wait(timeout=timeout)
        self.unwatch(sub_id)
        return self.get(key) == expected

    # ── History / Replay ──────────────────────────────────────────────────

    def history(self, pattern: str = "#", limit: int = 50) -> List[StateChange]:
        """Get recent changes matching pattern."""
        with self._history_lock:
            changes = list(self._history)
        sub = StateSubscription(pattern=pattern, callback=lambda c: None)
        matching = [c for c in changes if sub.matches(c.key)]
        return matching[-limit:]

    def replay(
        self,
        pattern: str,
        callback: Callable[[StateChange], None],
        since: float = 0.0,
    ) -> int:
        """Replay historical changes matching pattern since timestamp."""
        with self._history_lock:
            changes = list(self._history)
        sub = StateSubscription(pattern=pattern, callback=lambda c: None)
        count = 0
        for change in changes:
            if change.timestamp >= since and sub.matches(change.key):
                callback(change)
                count += 1
        return count

    # ── Notification ──────────────────────────────────────────────────────

    def _notify(self, change: StateChange) -> None:
        """Deliver change to matching subscribers."""
        to_remove = []
        with self._sub_lock:
            subs = list(self._subscriptions)

        for sub in subs:
            if not sub.matches(change.key):
                continue
            if sub.filter_unchanged and not change.changed:
                continue
            try:
                sub.callback(change)
                self._notify_count += 1
            except Exception as e:
                self._error_count += 1
                self._dead_letters.append({
                    "sub_id": sub.sub_id,
                    "key": change.key,
                    "error": str(e),
                    "timestamp": time.time(),
                })
            if sub.once:
                to_remove.append(sub.sub_id)

        if to_remove:
            with self._sub_lock:
                self._subscriptions = [
                    s for s in self._subscriptions if s.sub_id not in to_remove
                ]

    # ── Metrics ───────────────────────────────────────────────────────────

    @property
    def metrics(self) -> dict:
        with self._sub_lock:
            sub_count = len(self._subscriptions)
        return {
            "sets": self._set_count,
            "notifications": self._notify_count,
            "errors": self._error_count,
            "subscribers": sub_count,
            "state_keys": len(self._state),
            "history_size": len(self._history),
            "dead_letters": len(self._dead_letters),
        }

    @property
    def dead_letters(self) -> List[dict]:
        return list(self._dead_letters)


# ── StateWatcher (convenience class) ─────────────────────────────────────────

class StateWatcher:
    """
    High-level watcher that aggregates multiple pattern subscriptions
    on a ReactiveStateStore. Useful for components that care about
    several key families.
    """

    def __init__(self, store: ReactiveStateStore):
        self._store = store
        self._sub_ids: List[str] = []

    def on(
        self,
        pattern: str,
        callback: Callable[[StateChange], None],
        priority: int = 0,
    ) -> "StateWatcher":
        """Fluent API: watch a pattern. Returns self for chaining."""
        sid = self._store.watch(pattern, callback, priority=priority)
        self._sub_ids.append(sid)
        return self

    def stop(self) -> None:
        """Unsubscribe from all watched patterns."""
        for sid in self._sub_ids:
            self._store.unwatch(sid)
        self._sub_ids.clear()


# ── DashboardReactor ─────────────────────────────────────────────────────────

class DashboardReactor:
    """
    Reacts to state changes and updates a dashboard dict atomically.
    Replaces dashboard_realtime.py polling loop.

    Instead of:
        while True:
            stats = read_json("agent_stats.json")
            update_dashboard(stats)
            time.sleep(5)

    Now:
        reactor = DashboardReactor(store)
        store.set("agent.executor.status", "running")  # dashboard updates instantly
    """

    def __init__(self, store: ReactiveStateStore):
        self._store = store
        self._dashboard: Dict[str, Any] = {
            "agents": {},
            "tasks": {"queued": 0, "running": 0, "completed": 0, "failed": 0},
            "last_updated": 0.0,
        }
        self._lock = threading.Lock()

        # Subscribe to relevant state changes
        store.watch("agent.*.status", self._on_agent_status)
        store.watch("agent.*.health", self._on_agent_health)
        store.watch("task.queue.*", self._on_task_queue)
        store.watch("system.*", self._on_system)

    def _on_agent_status(self, change: StateChange) -> None:
        parts = change.key.split(".")
        if len(parts) >= 3:
            agent_name = parts[1]
            with self._lock:
                if agent_name not in self._dashboard["agents"]:
                    self._dashboard["agents"][agent_name] = {}
                self._dashboard["agents"][agent_name]["status"] = change.new_value
                self._dashboard["agents"][agent_name]["last_update"] = change.timestamp
                self._dashboard["last_updated"] = change.timestamp

    def _on_agent_health(self, change: StateChange) -> None:
        parts = change.key.split(".")
        if len(parts) >= 3:
            agent_name = parts[1]
            with self._lock:
                if agent_name not in self._dashboard["agents"]:
                    self._dashboard["agents"][agent_name] = {}
                self._dashboard["agents"][agent_name]["health"] = change.new_value
                self._dashboard["last_updated"] = change.timestamp

    def _on_task_queue(self, change: StateChange) -> None:
        metric = change.key.split(".")[-1]
        with self._lock:
            if metric in self._dashboard["tasks"]:
                self._dashboard["tasks"][metric] = change.new_value
            self._dashboard["last_updated"] = change.timestamp

    def _on_system(self, change: StateChange) -> None:
        metric = change.key.split(".", 1)[-1]
        with self._lock:
            self._dashboard[f"system.{metric}"] = change.new_value
            self._dashboard["last_updated"] = change.timestamp

    @property
    def state(self) -> dict:
        with self._lock:
            return json.loads(json.dumps(self._dashboard, default=str))


# ── AgentHealthReactor ───────────────────────────────────────────────────────

class AgentHealthReactor:
    """
    Monitors agent heartbeats via events, not polling.
    Detects stale agents when no heartbeat arrives within threshold.

    Replaces blocker_monitor.py's 30-second polling loop.
    """

    def __init__(
        self,
        store: ReactiveStateStore,
        stale_threshold: float = 60.0,
        check_interval: float = 10.0,
        on_stale: Optional[Callable[[str, float], None]] = None,
    ):
        self._store = store
        self._stale_threshold = stale_threshold
        self._on_stale = on_stale or (lambda name, age: None)
        self._last_heartbeat: Dict[str, float] = {}
        self._lock = threading.Lock()
        self._running = False
        self._check_interval = check_interval
        self._stale_detected: List[Tuple[str, float]] = []

        store.watch("heartbeat.*", self._on_heartbeat, filter_unchanged=False)

    def _on_heartbeat(self, change: StateChange) -> None:
        agent_name = change.key.split(".", 1)[-1]
        with self._lock:
            self._last_heartbeat[agent_name] = change.timestamp

    def start(self) -> None:
        """Start background stale-agent checker."""
        self._running = True
        self._thread = threading.Thread(
            target=self._check_loop, daemon=True, name="health-reactor"
        )
        self._thread.start()

    def stop(self) -> None:
        self._running = False

    def _check_loop(self) -> None:
        while self._running:
            now = time.time()
            with self._lock:
                for agent, last_ts in list(self._last_heartbeat.items()):
                    age = now - last_ts
                    if age > self._stale_threshold:
                        self._stale_detected.append((agent, age))
                        self._on_stale(agent, age)
            time.sleep(self._check_interval)

    @property
    def stale_agents(self) -> List[Tuple[str, float]]:
        return list(self._stale_detected)

    @property
    def last_heartbeats(self) -> Dict[str, float]:
        with self._lock:
            return dict(self._last_heartbeat)


# ── TaskQueueReactor ─────────────────────────────────────────────────────────

class TaskQueueReactor:
    """
    Tracks task lifecycle purely through events.
    Replaces polling-based task queue monitoring.

    Subscribe to task.* events → maintain real-time counters and history.
    """

    def __init__(self, store: ReactiveStateStore):
        self._store = store
        self._tasks: Dict[str, dict] = {}
        self._counters = {"queued": 0, "started": 0, "completed": 0, "failed": 0}
        self._lock = threading.Lock()
        self._completion_callbacks: List[Callable[[str, dict], None]] = []

        store.watch("task.*.state", self._on_task_state_change, filter_unchanged=True)

    def _on_task_state_change(self, change: StateChange) -> None:
        parts = change.key.split(".")
        if len(parts) < 3:
            return
        task_id = parts[1]
        new_state = change.new_value

        with self._lock:
            if task_id not in self._tasks:
                self._tasks[task_id] = {"created": change.timestamp}
            self._tasks[task_id]["state"] = new_state
            self._tasks[task_id]["updated"] = change.timestamp

            if new_state in self._counters:
                self._counters[new_state] += 1

            if new_state == "completed":
                task_info = dict(self._tasks[task_id])

        if new_state == "completed":
            for cb in self._completion_callbacks:
                try:
                    cb(task_id, task_info)
                except Exception:
                    pass

    def on_complete(self, callback: Callable[[str, dict], None]) -> None:
        """Register callback for task completion."""
        self._completion_callbacks.append(callback)

    @property
    def counters(self) -> dict:
        with self._lock:
            return dict(self._counters)

    @property
    def tasks(self) -> Dict[str, dict]:
        with self._lock:
            return dict(self._tasks)


# ── PollingEliminator ────────────────────────────────────────────────────────

class PollingEliminator:
    """
    Drop-in replacement for while+sleep polling patterns.

    Before (polling):
        while True:
            data = read_file("state.json")
            if data != last_data:
                process(data)
                last_data = data
            time.sleep(5)

    After (event-driven):
        eliminator = PollingEliminator(store)
        eliminator.replace_poll("agent.executor.status", process_status)
        # process_status called immediately on change, no polling
    """

    def __init__(self, store: ReactiveStateStore):
        self._store = store
        self._replacements: Dict[str, str] = {}

    def replace_poll(
        self,
        pattern: str,
        handler: Callable[[StateChange], None],
        priority: int = 0,
    ) -> str:
        """Replace a polling loop with an event subscription. Returns sub_id."""
        sub_id = self._store.watch(pattern, handler, priority=priority)
        self._replacements[pattern] = sub_id
        return sub_id

    def restore_poll(self, pattern: str) -> bool:
        """Remove a replacement (for rollback)."""
        sub_id = self._replacements.pop(pattern, None)
        if sub_id:
            return self._store.unwatch(sub_id)
        return False

    @property
    def active_replacements(self) -> Dict[str, str]:
        return dict(self._replacements)


# ── Computed / Derived State ─────────────────────────────────────────────────

class ComputedState:
    """
    Derived state that auto-recomputes when dependencies change.

    Example:
        computed = ComputedState(
            store, "dashboard.success_rate",
            dependencies=["stats.completed", "stats.total"],
            compute=lambda s: s.get("stats.completed", 0) / max(s.get("stats.total", 1), 1)
        )
    """

    def __init__(
        self,
        store: ReactiveStateStore,
        output_key: str,
        dependencies: List[str],
        compute: Callable[[ReactiveStateStore], Any],
    ):
        self._store = store
        self._output_key = output_key
        self._compute = compute
        self._sub_ids: List[str] = []

        for dep in dependencies:
            sid = store.watch(dep, self._recompute, filter_unchanged=True)
            self._sub_ids.append(sid)

        # Initial computation
        self._recompute(None)

    def _recompute(self, _change: Optional[StateChange]) -> None:
        try:
            value = self._compute(self._store)
            self._store.set(self._output_key, value, source="computed")
        except Exception:
            pass

    @property
    def value(self) -> Any:
        return self._store.get(self._output_key)

    def stop(self) -> None:
        for sid in self._sub_ids:
            self._store.unwatch(sid)
        self._sub_ids.clear()


# ═══════════════════════════════════════════════════════════════════════════════
# Verification
# ═══════════════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import sys

    print("=" * 70)
    print("Pub-Sub State Updates — Verification Suite")
    print("=" * 70)

    passed = 0
    failed = 0

    def check(name, condition):
        global passed, failed
        if condition:
            passed += 1
            print(f"  PASS: {name}")
        else:
            failed += 1
            print(f"  FAIL: {name}")

    # ── Test 1: Basic set/get ─────────────────────────────────────────────
    print("\n[Test 1] Basic set/get")
    store = ReactiveStateStore()
    store.set("x", 42)
    check("get returns set value", store.get("x") == 42)
    check("get default for missing", store.get("missing", -1) == -1)
    store.set("x", 100)
    check("overwrite works", store.get("x") == 100)

    # ── Test 2: Watch fires on change ─────────────────────────────────────
    print("\n[Test 2] Watch fires on state change")
    store2 = ReactiveStateStore()
    changes = []
    store2.watch("color", lambda c: changes.append(c))
    store2.set("color", "red")
    store2.set("color", "blue")
    check("received 2 changes", len(changes) == 2)
    check("first change old=None", changes[0].old_value is None)
    check("first change new=red", changes[0].new_value == "red")
    check("second change old=red", changes[1].old_value == "red")
    check("second change new=blue", changes[1].new_value == "blue")

    # ── Test 3: Wildcard pattern matching ─────────────────────────────────
    print("\n[Test 3] Wildcard pattern matching")
    store3 = ReactiveStateStore()
    star_changes = []
    hash_changes = []
    store3.watch("agent.*.status", lambda c: star_changes.append(c))
    store3.watch("agent.#", lambda c: hash_changes.append(c))

    store3.set("agent.executor.status", "running")
    store3.set("agent.planner.status", "idle")
    store3.set("agent.executor.health", "ok")  # matches # but not *
    store3.set("unrelated.key", "val")  # matches neither

    check("* matched 2 (agent.X.status)", len(star_changes) == 2)
    check("# matched 3 (all agent.*)", len(hash_changes) == 3)

    # ── Test 4: filter_unchanged skips same-value sets ────────────────────
    print("\n[Test 4] filter_unchanged")
    store4 = ReactiveStateStore()
    filtered = []
    unfiltered = []
    store4.watch("f.key", lambda c: filtered.append(c), filter_unchanged=True)
    store4.watch("f.key", lambda c: unfiltered.append(c), filter_unchanged=False)

    store4.set("f.key", "a")
    store4.set("f.key", "a")  # same value
    store4.set("f.key", "b")  # different

    check("filtered got 2 (skip unchanged)", len(filtered) == 2)
    check("unfiltered got 3 (all sets)", len(unfiltered) == 3)

    # ── Test 5: watch_once auto-unsubscribes ──────────────────────────────
    print("\n[Test 5] watch_once")
    store5 = ReactiveStateStore()
    once_vals = []
    store5.watch_once("once.key", lambda c: once_vals.append(c.new_value))
    store5.set("once.key", "first")
    store5.set("once.key", "second")
    store5.set("once.key", "third")
    check("watch_once fires exactly once", len(once_vals) == 1)
    check("watch_once got first value", once_vals[0] == "first")

    # ── Test 6: Unwatch ───────────────────────────────────────────────────
    print("\n[Test 6] Unwatch")
    store6 = ReactiveStateStore()
    count6 = [0]
    sid = store6.watch("u.key", lambda c: count6.__setitem__(0, count6[0] + 1))
    store6.set("u.key", 1)
    check("received before unwatch", count6[0] == 1)
    ok = store6.unwatch(sid)
    check("unwatch returns True", ok is True)
    store6.set("u.key", 2)
    check("not received after unwatch", count6[0] == 1)
    check("unwatch nonexistent returns False", store6.unwatch("fake") is False)

    # ── Test 7: Priority ordering ─────────────────────────────────────────
    print("\n[Test 7] Priority ordering")
    store7 = ReactiveStateStore()
    order = []
    store7.watch("pri", lambda c: order.append("low"), priority=0, filter_unchanged=False)
    store7.watch("pri", lambda c: order.append("high"), priority=10, filter_unchanged=False)
    store7.watch("pri", lambda c: order.append("mid"), priority=5, filter_unchanged=False)
    store7.set("pri", "go")
    check("high first", order[0] == "high")
    check("mid second", order[1] == "mid")
    check("low third", order[2] == "low")

    # ── Test 8: Increment ─────────────────────────────────────────────────
    print("\n[Test 8] Atomic increment")
    store8 = ReactiveStateStore()
    inc_changes = []
    store8.watch("counter", lambda c: inc_changes.append(c), filter_unchanged=False)
    v1 = store8.increment("counter")
    v2 = store8.increment("counter", 5)
    v3 = store8.increment("counter", -2)
    check("first increment = 1", v1 == 1)
    check("second increment = 6", v2 == 6)
    check("third increment = 4", v3 == 4)
    check("3 change events", len(inc_changes) == 3)
    check("change tracks values", inc_changes[1].old_value == 1 and inc_changes[1].new_value == 6)

    # ── Test 9: Delete ────────────────────────────────────────────────────
    print("\n[Test 9] Delete")
    store9 = ReactiveStateStore()
    del_events = []
    store9.watch("del.key", lambda c: del_events.append(c), filter_unchanged=False)
    store9.set("del.key", "exists")
    change = store9.delete("del.key")
    check("delete returns change", change is not None)
    check("delete old_value", change.old_value == "exists")
    check("delete new_value is None", change.new_value is None)
    check("delete fires subscriber", len(del_events) == 2)
    check("key gone after delete", store9.get("del.key") is None)
    check("delete nonexistent returns None", store9.delete("nope") is None)

    # ── Test 10: update_dict (merge) ──────────────────────────────────────
    print("\n[Test 10] update_dict")
    store10 = ReactiveStateStore()
    store10.set("config", {"a": 1, "b": 2})
    store10.update_dict("config", {"b": 3, "c": 4})
    val = store10.get("config")
    check("merge preserves a", val["a"] == 1)
    check("merge updates b", val["b"] == 3)
    check("merge adds c", val["c"] == 4)

    # ── Test 11: get_many and get_prefix ──────────────────────────────────
    print("\n[Test 11] Batch reads")
    store11 = ReactiveStateStore()
    store11.set("ns.a", 1)
    store11.set("ns.b", 2)
    store11.set("other.c", 3)
    many = store11.get_many(["ns.a", "ns.b", "missing"])
    check("get_many returns dict", many == {"ns.a": 1, "ns.b": 2, "missing": None})
    prefix = store11.get_prefix("ns.")
    check("get_prefix filters", prefix == {"ns.a": 1, "ns.b": 2})

    # ── Test 12: History and replay ───────────────────────────────────────
    print("\n[Test 12] History and replay")
    store12 = ReactiveStateStore(history_size=100)
    for i in range(5):
        store12.set(f"h.item{i}", i)
    store12.set("other", "x")

    hist = store12.history("h.*")
    check("history filters by pattern (5)", len(hist) == 5)
    check("history order correct", hist[0].new_value == 0)

    replayed = []
    n = store12.replay("h.*", lambda c: replayed.append(c))
    check("replay count", n == 5)

    # ── Test 13: wait_for (blocking) ──────────────────────────────────────
    print("\n[Test 13] wait_for")
    store13 = ReactiveStateStore()

    def delayed_set():
        time.sleep(0.1)
        store13.set("ready", True)

    threading.Thread(target=delayed_set, daemon=True).start()
    result = store13.wait_for("ready", timeout=2.0)
    check("wait_for got change", result is not None)
    check("wait_for value correct", result.new_value is True)

    # Timeout case
    store13b = ReactiveStateStore()
    result2 = store13b.wait_for("never", timeout=0.15)
    check("wait_for returns None on timeout", result2 is None)

    # ── Test 14: wait_for_value ───────────────────────────────────────────
    print("\n[Test 14] wait_for_value")
    store14 = ReactiveStateStore()
    store14.set("status", "pending")

    def transition():
        time.sleep(0.05)
        store14.set("status", "processing")
        time.sleep(0.05)
        store14.set("status", "done")

    threading.Thread(target=transition, daemon=True).start()
    matched = store14.wait_for_value("status", "done", timeout=2.0)
    check("wait_for_value matched", matched is True)

    # Already matching
    store14.set("already", "ok")
    check("wait_for_value immediate match", store14.wait_for_value("already", "ok", timeout=0.1))

    # ── Test 15: Dead letter queue ────────────────────────────────────────
    print("\n[Test 15] Dead letter queue")
    store15 = ReactiveStateStore()
    good = [0]

    def bad(c):
        raise RuntimeError("boom")

    store15.watch("err", bad, filter_unchanged=False)
    store15.watch("err", lambda c: good.__setitem__(0, good[0] + 1), filter_unchanged=False)
    store15.set("err", "val")
    check("good subscriber still runs", good[0] == 1)
    check("dead letter recorded", len(store15.dead_letters) == 1)
    check("dead letter has error", "boom" in store15.dead_letters[0]["error"])

    # ── Test 16: StateWatcher (fluent API) ────────────────────────────────
    print("\n[Test 16] StateWatcher fluent API")
    store16 = ReactiveStateStore()
    events_a = []
    events_b = []
    watcher = StateWatcher(store16)
    watcher.on("a.*", lambda c: events_a.append(c)).on("b.*", lambda c: events_b.append(c))
    store16.set("a.x", 1)
    store16.set("b.y", 2)
    store16.set("c.z", 3)
    check("watcher a got 1", len(events_a) == 1)
    check("watcher b got 1", len(events_b) == 1)
    watcher.stop()
    store16.set("a.x", 99)
    check("watcher stopped, no more events", len(events_a) == 1)

    # ── Test 17: DashboardReactor ─────────────────────────────────────────
    print("\n[Test 17] DashboardReactor")
    store17 = ReactiveStateStore()
    reactor = DashboardReactor(store17)

    store17.set("agent.executor.status", "running")
    store17.set("agent.planner.status", "idle")
    store17.set("agent.executor.health", "healthy")
    store17.set("task.queue.completed", 42)
    store17.set("system.cpu", 0.65)

    dash = reactor.state
    check("dashboard has executor", "executor" in dash["agents"])
    check("executor status", dash["agents"]["executor"]["status"] == "running")
    check("executor health", dash["agents"]["executor"]["health"] == "healthy")
    check("planner status", dash["agents"]["planner"]["status"] == "idle")
    check("task completed count", dash["tasks"]["completed"] == 42)
    check("system cpu", dash["system.cpu"] == 0.65)
    check("last_updated set", dash["last_updated"] > 0)

    # ── Test 18: AgentHealthReactor ───────────────────────────────────────
    print("\n[Test 18] AgentHealthReactor")
    store18 = ReactiveStateStore()
    stale_alerts = []
    health = AgentHealthReactor(
        store18,
        stale_threshold=0.2,
        check_interval=0.1,
        on_stale=lambda name, age: stale_alerts.append((name, age)),
    )
    store18.set("heartbeat.executor", {"ts": time.time(), "alive": True})
    health.start()
    time.sleep(0.05)
    check("executor not stale yet", len(stale_alerts) == 0)
    check("heartbeat tracked", "executor" in health.last_heartbeats)

    # Wait for staleness
    time.sleep(0.4)
    health.stop()
    check("stale agent detected", len(stale_alerts) >= 1)
    check("stale agent is executor", stale_alerts[0][0] == "executor")

    # ── Test 19: TaskQueueReactor ─────────────────────────────────────────
    print("\n[Test 19] TaskQueueReactor")
    store19 = ReactiveStateStore()
    tq = TaskQueueReactor(store19)
    completed_tasks = []
    tq.on_complete(lambda tid, info: completed_tasks.append(tid))

    store19.set("task.t001.state", "queued")
    store19.set("task.t001.state", "started")
    store19.set("task.t001.state", "completed")
    store19.set("task.t002.state", "queued")
    store19.set("task.t002.state", "failed")

    counters = tq.counters
    check("queued count", counters["queued"] == 2)
    check("started count", counters["started"] == 1)
    check("completed count", counters["completed"] == 1)
    check("failed count", counters["failed"] == 1)
    check("completion callback fired", completed_tasks == ["t001"])
    check("task tracked", "t001" in tq.tasks and tq.tasks["t001"]["state"] == "completed")

    # ── Test 20: PollingEliminator ────────────────────────────────────────
    print("\n[Test 20] PollingEliminator")
    store20 = ReactiveStateStore()
    pe = PollingEliminator(store20)
    poll_events = []

    sid = pe.replace_poll("sensor.*", lambda c: poll_events.append(c))
    store20.set("sensor.temp", 72)
    store20.set("sensor.humidity", 45)
    store20.set("other.thing", "ignored")

    check("polling replacement works", len(poll_events) == 2)
    check("replacement tracked", "sensor.*" in pe.active_replacements)

    pe.restore_poll("sensor.*")
    store20.set("sensor.temp", 80)
    check("restored: no more events", len(poll_events) == 2)
    check("replacement removed", "sensor.*" not in pe.active_replacements)

    # ── Test 21: ComputedState ────────────────────────────────────────────
    print("\n[Test 21] ComputedState (derived values)")
    store21 = ReactiveStateStore()
    store21.set("stats.completed", 0)
    store21.set("stats.total", 0)

    computed = ComputedState(
        store21,
        output_key="dashboard.success_rate",
        dependencies=["stats.completed", "stats.total"],
        compute=lambda s: round(s.get("stats.completed", 0) / max(s.get("stats.total", 1), 1), 2),
    )

    check("initial computed value", store21.get("dashboard.success_rate") == 0)

    store21.set("stats.total", 10)
    store21.set("stats.completed", 7)
    check("computed auto-updates", store21.get("dashboard.success_rate") == 0.7)

    store21.set("stats.completed", 9)
    check("computed updates again", store21.get("dashboard.success_rate") == 0.9)
    check("computed.value property", computed.value == 0.9)

    computed.stop()
    store21.set("stats.completed", 5)
    check("computed stopped, no update", store21.get("dashboard.success_rate") == 0.9)

    # ── Test 22: Thread safety ────────────────────────────────────────────
    print("\n[Test 22] Thread safety (concurrent set + watch)")
    store22 = ReactiveStateStore()
    counter22 = {"n": 0}
    lock22 = threading.Lock()

    def counting(c):
        with lock22:
            counter22["n"] += 1

    store22.watch("stress.#", counting, filter_unchanged=False)

    threads = []
    N_THREADS = 8
    N_OPS = 200

    def writer(tid):
        for i in range(N_OPS):
            store22.set(f"stress.t{tid}.v{i}", i, source=f"thread-{tid}")

    for t in range(N_THREADS):
        th = threading.Thread(target=writer, args=(t,))
        threads.append(th)
        th.start()

    for th in threads:
        th.join(timeout=15.0)

    expected = N_THREADS * N_OPS
    check(f"all {expected} events delivered concurrently", counter22["n"] == expected)

    # ── Test 23: Snapshot ─────────────────────────────────────────────────
    print("\n[Test 23] Snapshot")
    store23 = ReactiveStateStore()
    store23.set("a", 1)
    store23.set("b", 2)
    snap = store23.snapshot()
    check("snapshot has all keys", snap == {"a": 1, "b": 2})
    snap["a"] = 999
    check("snapshot is a copy", store23.get("a") == 1)

    # ── Test 24: Load (bulk init) ─────────────────────────────────────────
    print("\n[Test 24] Bulk load (no events)")
    store24 = ReactiveStateStore()
    load_events = []
    store24.watch("#", lambda c: load_events.append(c), filter_unchanged=False)
    store24.load({"x": 1, "y": 2, "z": 3})
    check("load does not fire events", len(load_events) == 0)
    check("loaded values accessible", store24.get("x") == 1 and store24.get("z") == 3)

    # ── Test 25: Metrics ──────────────────────────────────────────────────
    print("\n[Test 25] Metrics")
    store25 = ReactiveStateStore()
    store25.watch("m.*", lambda c: None, filter_unchanged=False)
    store25.set("m.a", 1)
    store25.set("m.b", 2)
    m = store25.metrics
    check("sets counted", m["sets"] == 2)
    check("notifications counted", m["notifications"] == 2)
    check("subscriber counted", m["subscribers"] == 1)
    check("state keys counted", m["state_keys"] == 2)
    check("history tracked", m["history_size"] == 2)

    # ── Test 26: Pattern compilation edge cases ───────────────────────────
    print("\n[Test 26] Pattern edge cases")
    check("exact match", _topic_matches("a.b.c", "a.b.c"))
    check("exact no match", not _topic_matches("a.b.c", "a.b.d"))
    check("star matches one", _topic_matches("a.*", "a.b"))
    check("star no deep match", not _topic_matches("a.*", "a.b.c"))
    check("hash matches deep", _topic_matches("a.#", "a.b.c.d"))
    check("hash matches one", _topic_matches("a.#", "a.b"))
    check("catch-all matches anything", _topic_matches("#", "x.y.z"))
    check("mid wildcard", _topic_matches("a.*.c", "a.b.c"))
    check("mid wildcard no match", not _topic_matches("a.*.c", "a.b.d"))

    # ── Test 27: StateChange properties ───────────────────────────────────
    print("\n[Test 27] StateChange dataclass")
    c1 = StateChange(key="k", old_value=1, new_value=2, timestamp=1.0)
    c2 = StateChange(key="k", old_value=1, new_value=1, timestamp=2.0)
    check("changed=True when different", c1.changed is True)
    check("changed=False when same", c2.changed is False)
    d = c1.to_dict()
    check("to_dict has all fields", d["key"] == "k" and d["changed"] is True)

    # ── Summary ───────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    total = passed + failed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if failed == 0:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
    print("=" * 70)

    assert failed == 0, f"{failed} tests failed"
    sys.exit(0)
