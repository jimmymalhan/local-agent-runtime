#!/usr/bin/env python3
"""
orchestrator/event_bus.py — Event-Driven Pub-Sub for State Updates
===================================================================
Replaces polling loops with publish-subscribe pattern. Any component can
emit events on topics; subscribers receive only events matching their
topic filter (exact or wildcard).

Features:
  - Topic-based routing with wildcard support (e.g. "agent.*", "task.#")
  - Sync and async (threaded) delivery modes
  - Priority subscribers (execute first)
  - Event history ring buffer for replay / late subscribers
  - Dead-letter queue for failed deliveries
  - Thread-safe, zero external dependencies
  - Integrates with DistributedState for file-backed persistence

Topic patterns:
  "agent.executor.status"  — exact match
  "agent.*"                — single-level wildcard (matches agent.X but not agent.X.Y)
  "agent.#"                — multi-level wildcard (matches agent.X, agent.X.Y, etc.)
  "*"                      — matches all single-segment topics
  "#"                      — matches everything

Usage:
    from orchestrator.event_bus import EventBus, get_bus

    bus = get_bus()
    bus.subscribe("task.completed", lambda e: print(e))
    bus.publish("task.completed", {"task_id": "t-123", "quality": 95})
"""

import time
import threading
import fnmatch
import re
import json
import os
from collections import deque
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Set
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent


# ── Event ────────────────────────────────────────────────────────────────────

@dataclass
class Event:
    """Immutable event payload delivered to subscribers."""
    topic: str
    data: Any
    timestamp: float = field(default_factory=time.time)
    source: str = "system"
    event_id: str = ""

    def __post_init__(self):
        if not self.event_id:
            self.event_id = f"evt-{int(self.timestamp * 1000)}-{id(self) & 0xFFFF:04x}"

    def to_dict(self) -> dict:
        return {
            "event_id": self.event_id,
            "topic": self.topic,
            "data": self.data,
            "timestamp": self.timestamp,
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Event":
        return cls(
            topic=d["topic"],
            data=d["data"],
            timestamp=d.get("timestamp", time.time()),
            source=d.get("source", "system"),
            event_id=d.get("event_id", ""),
        )


# ── Subscription ─────────────────────────────────────────────────────────────

@dataclass
class Subscription:
    """A subscriber bound to a topic pattern."""
    pattern: str
    callback: Callable[[Event], None]
    priority: int = 0           # Higher = executes first
    async_delivery: bool = False  # True = deliver in separate thread
    sub_id: str = ""
    _matcher: Optional[re.Pattern] = field(default=None, repr=False)

    def __post_init__(self):
        if not self.sub_id:
            self.sub_id = f"sub-{id(self) & 0xFFFFFF:06x}"
        self._matcher = _compile_topic_pattern(self.pattern)

    def matches(self, topic: str) -> bool:
        """Check if a topic matches this subscription's pattern."""
        return bool(self._matcher.fullmatch(topic))


def _compile_topic_pattern(pattern: str) -> re.Pattern:
    """Convert topic pattern with wildcards to regex.

    '*' matches exactly one segment (no dots).
    '#' matches zero or more segments (including dots).
    """
    if pattern == "#":
        return re.compile(r".*")
    parts = []
    for segment in pattern.split("."):
        if segment == "#":
            parts.append(r"(?:[^.]+\.)*[^.]+")
        elif segment == "*":
            parts.append(r"[^.]+")
        else:
            parts.append(re.escape(segment))
    # Handle trailing '#' to also match zero additional segments
    regex = r"\.".join(parts)
    # '#' at end should match the rest including nothing extra
    regex = regex.replace(r"(?:[^.]+\.)*[^.]+", r".*")
    return re.compile(regex)


# ── Dead Letter ──────────────────────────────────────────────────────────────

@dataclass
class DeadLetter:
    """Record of a failed delivery attempt."""
    event: Event
    subscription_id: str
    error: str
    timestamp: float = field(default_factory=time.time)


# ── EventBus ─────────────────────────────────────────────────────────────────

class EventBus:
    """
    Thread-safe publish-subscribe event bus with topic-based routing.

    Replaces polling with push-based state updates. Components publish
    events when state changes; interested parties subscribe to topics.
    """

    def __init__(self, history_size: int = 1000, max_dead_letters: int = 500):
        self._subscriptions: List[Subscription] = []
        self._sub_lock = threading.RLock()

        # Event history for replay
        self._history: deque[Event] = deque(maxlen=history_size)
        self._history_lock = threading.Lock()

        # Dead letter queue
        self._dead_letters: deque[DeadLetter] = deque(maxlen=max_dead_letters)

        # Metrics
        self._publish_count = 0
        self._deliver_count = 0
        self._error_count = 0
        self._metrics_lock = threading.Lock()

        # Topic-specific listener counts for fast "has_subscribers" check
        self._topic_cache: Dict[str, List[Subscription]] = {}
        self._cache_valid = False

    # ── Subscribe ────────────────────────────────────────────────────────

    def subscribe(
        self,
        pattern: str,
        callback: Callable[[Event], None],
        priority: int = 0,
        async_delivery: bool = False,
    ) -> str:
        """Subscribe to events matching a topic pattern. Returns subscription ID."""
        sub = Subscription(
            pattern=pattern,
            callback=callback,
            priority=priority,
            async_delivery=async_delivery,
        )
        with self._sub_lock:
            self._subscriptions.append(sub)
            self._subscriptions.sort(key=lambda s: -s.priority)
            self._cache_valid = False
        return sub.sub_id

    def unsubscribe(self, sub_id: str) -> bool:
        """Remove a subscription by ID. Returns True if found."""
        with self._sub_lock:
            before = len(self._subscriptions)
            self._subscriptions = [s for s in self._subscriptions if s.sub_id != sub_id]
            self._cache_valid = False
            return len(self._subscriptions) < before

    def subscribe_once(
        self,
        pattern: str,
        callback: Callable[[Event], None],
        priority: int = 0,
    ) -> str:
        """Subscribe for a single event, then auto-unsubscribe."""
        sub_id_holder = [None]

        def wrapper(event: Event):
            callback(event)
            if sub_id_holder[0]:
                self.unsubscribe(sub_id_holder[0])

        sub_id = self.subscribe(pattern, wrapper, priority=priority)
        sub_id_holder[0] = sub_id
        return sub_id

    # ── Publish ──────────────────────────────────────────────────────────

    def publish(self, topic: str, data: Any = None, source: str = "system") -> Event:
        """Publish an event. Delivers to all matching subscribers. Returns the event."""
        event = Event(topic=topic, data=data, source=source)
        self._dispatch(event)
        return event

    def publish_event(self, event: Event) -> None:
        """Publish a pre-built Event object."""
        self._dispatch(event)

    def _dispatch(self, event: Event) -> None:
        """Route event to matching subscribers."""
        with self._history_lock:
            self._history.append(event)

        with self._metrics_lock:
            self._publish_count += 1

        with self._sub_lock:
            matching = [s for s in self._subscriptions if s.matches(event.topic)]

        for sub in matching:
            if sub.async_delivery:
                t = threading.Thread(
                    target=self._safe_deliver,
                    args=(sub, event),
                    daemon=True,
                    name=f"evt-{event.topic[:20]}",
                )
                t.start()
            else:
                self._safe_deliver(sub, event)

    def _safe_deliver(self, sub: Subscription, event: Event) -> None:
        """Deliver event to subscriber with error handling."""
        try:
            sub.callback(event)
            with self._metrics_lock:
                self._deliver_count += 1
        except Exception as e:
            with self._metrics_lock:
                self._error_count += 1
            self._dead_letters.append(
                DeadLetter(
                    event=event,
                    subscription_id=sub.sub_id,
                    error=str(e),
                )
            )

    # ── Replay / History ─────────────────────────────────────────────────

    def replay(
        self,
        pattern: str,
        callback: Callable[[Event], None],
        since: float = 0.0,
    ) -> int:
        """Replay historical events matching pattern since timestamp. Returns count."""
        matcher = Subscription(pattern=pattern, callback=lambda e: None)
        count = 0
        with self._history_lock:
            events = list(self._history)
        for event in events:
            if event.timestamp >= since and matcher.matches(event.topic):
                callback(event)
                count += 1
        return count

    def history(self, pattern: str = "#", limit: int = 50) -> List[Event]:
        """Get recent events matching pattern."""
        matcher = Subscription(pattern=pattern, callback=lambda e: None)
        with self._history_lock:
            events = list(self._history)
        matching = [e for e in events if matcher.matches(e.topic)]
        return matching[-limit:]

    # ── Query ────────────────────────────────────────────────────────────

    def has_subscribers(self, topic: str) -> bool:
        """Check if any subscriber would receive events on this topic."""
        with self._sub_lock:
            return any(s.matches(topic) for s in self._subscriptions)

    def subscriber_count(self, topic: str = "") -> int:
        """Count subscribers. If topic given, count only matching ones."""
        with self._sub_lock:
            if not topic:
                return len(self._subscriptions)
            return sum(1 for s in self._subscriptions if s.matches(topic))

    @property
    def dead_letters(self) -> List[DeadLetter]:
        return list(self._dead_letters)

    @property
    def metrics(self) -> dict:
        with self._metrics_lock:
            return {
                "published": self._publish_count,
                "delivered": self._deliver_count,
                "errors": self._error_count,
                "subscribers": len(self._subscriptions),
                "history_size": len(self._history),
                "dead_letters": len(self._dead_letters),
            }

    # ── Wait / Blocking helpers ──────────────────────────────────────────

    def wait_for(self, pattern: str, timeout: float = 30.0) -> Optional[Event]:
        """Block until an event matching pattern is published. Returns event or None on timeout."""
        result = [None]
        got_it = threading.Event()

        def handler(event: Event):
            result[0] = event
            got_it.set()

        sub_id = self.subscribe(pattern, handler, priority=999)
        got_it.wait(timeout=timeout)
        self.unsubscribe(sub_id)
        return result[0]

    # ── Cleanup ──────────────────────────────────────────────────────────

    def clear(self) -> None:
        """Remove all subscriptions and history."""
        with self._sub_lock:
            self._subscriptions.clear()
            self._cache_valid = False
        with self._history_lock:
            self._history.clear()
        self._dead_letters.clear()


# ── StateEventBridge ─────────────────────────────────────────────────────────

class StateEventBridge:
    """
    Bridges DistributedState writes to EventBus publishes.

    When state.set("agent.executor.status", "running") is called,
    the bridge auto-publishes: topic="state.agent.executor.status",
    data={"key": ..., "value": ..., "old_value": ...}.

    This eliminates polling — any component that cares about state changes
    subscribes to "state.#" or a specific "state.agent.executor.status" topic.
    """

    def __init__(self, bus: EventBus, state: Any = None):
        self.bus = bus
        self.state = state
        self._previous: Dict[str, Any] = {}

        if state is not None:
            self._attach(state)

    def _attach(self, state) -> None:
        """Hook into DistributedState's subscriber mechanism."""
        state.subscribe(self._on_state_change)
        # Snapshot current state for change detection
        try:
            snapshot = state.snapshot()
            self._previous.update(snapshot)
        except Exception:
            pass

    def _on_state_change(self, key: str, value: Any) -> None:
        """Called by DistributedState on every set(). Publishes to EventBus."""
        old_value = self._previous.get(key)
        self._previous[key] = value

        topic = f"state.{key}"
        data = {
            "key": key,
            "value": value,
            "old_value": old_value,
            "changed": old_value != value,
        }
        self.bus.publish(topic, data, source="distributed_state")


# ── FileWatcherPublisher ─────────────────────────────────────────────────────

class FileWatcherPublisher:
    """
    Watches a file for changes and publishes events.
    Replaces daemon.py's polling loop with event-driven file monitoring.

    Uses a single background thread with minimal overhead. Publishes
    "file.changed.<name>" when file content hash changes.
    """

    def __init__(self, bus: EventBus, watch_paths: Optional[Dict[str, Path]] = None):
        self.bus = bus
        self._watches: Dict[str, Path] = watch_paths or {}
        self._hashes: Dict[str, int] = {}
        self._running = False
        self._thread: Optional[threading.Thread] = None
        self._interval = 1.0  # Check interval in seconds

        # Initialize hashes
        for name, path in self._watches.items():
            self._hashes[name] = self._file_hash(path)

    def add_watch(self, name: str, path: Path) -> None:
        """Add a file to watch."""
        self._watches[name] = path
        self._hashes[name] = self._file_hash(path)

    def start(self) -> None:
        """Start watching in background thread."""
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._watch_loop, daemon=True, name="file-watcher")
        self._thread.start()

    def stop(self) -> None:
        """Stop watching."""
        self._running = False
        if self._thread:
            self._thread.join(timeout=5.0)

    def _watch_loop(self) -> None:
        while self._running:
            for name, path in list(self._watches.items()):
                new_hash = self._file_hash(path)
                if new_hash != self._hashes.get(name):
                    old_hash = self._hashes.get(name)
                    self._hashes[name] = new_hash
                    self.bus.publish(
                        f"file.changed.{name}",
                        {"path": str(path), "old_hash": old_hash, "new_hash": new_hash},
                        source="file_watcher",
                    )
            time.sleep(self._interval)

    @staticmethod
    def _file_hash(path: Path) -> Optional[int]:
        try:
            return hash(path.read_bytes())
        except Exception:
            return None


# ── TaskEventPublisher ───────────────────────────────────────────────────────

class TaskEventPublisher:
    """
    Publishes task lifecycle events to the bus.

    Topics:
      task.queued     — new task added to queue
      task.started    — task execution began
      task.completed  — task finished successfully
      task.failed     — task execution failed
      task.retrying   — task being retried
    """

    def __init__(self, bus: EventBus):
        self.bus = bus

    def task_queued(self, task_id: str, project_id: str = "", **extra) -> Event:
        return self.bus.publish("task.queued", {
            "task_id": task_id, "project_id": project_id, **extra
        }, source="task_publisher")

    def task_started(self, task_id: str, agent: str = "", **extra) -> Event:
        return self.bus.publish("task.started", {
            "task_id": task_id, "agent": agent, **extra
        }, source="task_publisher")

    def task_completed(self, task_id: str, quality: int = 0, elapsed: float = 0, **extra) -> Event:
        return self.bus.publish("task.completed", {
            "task_id": task_id, "quality": quality, "elapsed": elapsed, **extra
        }, source="task_publisher")

    def task_failed(self, task_id: str, error: str = "", attempt: int = 1, **extra) -> Event:
        return self.bus.publish("task.failed", {
            "task_id": task_id, "error": error, "attempt": attempt, **extra
        }, source="task_publisher")

    def task_retrying(self, task_id: str, attempt: int = 1, strategy: str = "", **extra) -> Event:
        return self.bus.publish("task.retrying", {
            "task_id": task_id, "attempt": attempt, "strategy": strategy, **extra
        }, source="task_publisher")


# ── Singleton ────────────────────────────────────────────────────────────────

_bus_instance: Optional[EventBus] = None
_bus_lock = threading.Lock()


def get_bus() -> EventBus:
    """Get or create the singleton EventBus."""
    global _bus_instance
    with _bus_lock:
        if _bus_instance is None:
            _bus_instance = EventBus()
        return _bus_instance


def reset_bus() -> None:
    """Reset the singleton (for testing)."""
    global _bus_instance
    with _bus_lock:
        if _bus_instance:
            _bus_instance.clear()
        _bus_instance = None


# ── Main: verify correctness ────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    print("=" * 70)
    print("EventBus Pub-Sub System — Verification Suite")
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

    # ── Test 1: Basic publish/subscribe ──────────────────────────────────
    print("\n[Test 1] Basic publish/subscribe")
    bus = EventBus()
    received = []
    bus.subscribe("test.hello", lambda e: received.append(e))
    bus.publish("test.hello", {"msg": "world"})
    check("subscriber receives event", len(received) == 1)
    check("event has correct topic", received[0].topic == "test.hello")
    check("event has correct data", received[0].data == {"msg": "world"})
    check("event has event_id", received[0].event_id.startswith("evt-"))
    check("event has timestamp", received[0].timestamp > 0)

    # ── Test 2: Wildcard matching (* = single level) ─────────────────────
    print("\n[Test 2] Single-level wildcard (*)")
    bus2 = EventBus()
    star_received = []
    bus2.subscribe("agent.*", lambda e: star_received.append(e))
    bus2.publish("agent.executor", {"status": "running"})
    bus2.publish("agent.planner", {"status": "idle"})
    bus2.publish("agent.executor.health", {"ok": True})  # Should NOT match
    bus2.publish("other.thing", {"x": 1})  # Should NOT match
    check("* matches single segment (2 events)", len(star_received) == 2)
    check("first match is executor", star_received[0].data["status"] == "running")
    check("second match is planner", star_received[1].data["status"] == "idle")

    # ── Test 3: Wildcard matching (# = multi level) ──────────────────────
    print("\n[Test 3] Multi-level wildcard (#)")
    bus3 = EventBus()
    hash_received = []
    bus3.subscribe("agent.#", lambda e: hash_received.append(e))
    bus3.publish("agent.executor", {"a": 1})
    bus3.publish("agent.executor.health", {"b": 2})
    bus3.publish("agent.planner.deep.nested", {"c": 3})
    bus3.publish("task.completed", {"d": 4})  # Should NOT match
    check("# matches multi-level (3 events)", len(hash_received) == 3)

    # ── Test 4: Catch-all subscriber ─────────────────────────────────────
    print("\n[Test 4] Catch-all (#) subscriber")
    bus4 = EventBus()
    all_events = []
    bus4.subscribe("#", lambda e: all_events.append(e))
    bus4.publish("a", 1)
    bus4.publish("a.b", 2)
    bus4.publish("a.b.c.d.e", 3)
    check("catch-all receives everything (3)", len(all_events) == 3)

    # ── Test 5: Priority ordering ────────────────────────────────────────
    print("\n[Test 5] Priority ordering")
    bus5 = EventBus()
    order = []
    bus5.subscribe("pri.test", lambda e: order.append("low"), priority=0)
    bus5.subscribe("pri.test", lambda e: order.append("high"), priority=10)
    bus5.subscribe("pri.test", lambda e: order.append("mid"), priority=5)
    bus5.publish("pri.test")
    check("high priority first", order[0] == "high")
    check("mid priority second", order[1] == "mid")
    check("low priority third", order[2] == "low")

    # ── Test 6: Unsubscribe ──────────────────────────────────────────────
    print("\n[Test 6] Unsubscribe")
    bus6 = EventBus()
    unsub_count = [0]
    sid = bus6.subscribe("unsub.test", lambda e: unsub_count.__setitem__(0, unsub_count[0] + 1))
    bus6.publish("unsub.test")
    check("received before unsub", unsub_count[0] == 1)
    result = bus6.unsubscribe(sid)
    check("unsubscribe returns True", result is True)
    bus6.publish("unsub.test")
    check("not received after unsub", unsub_count[0] == 1)
    check("unsub non-existent returns False", bus6.unsubscribe("fake-id") is False)

    # ── Test 7: Subscribe once ───────────────────────────────────────────
    print("\n[Test 7] Subscribe once")
    bus7 = EventBus()
    once_count = [0]
    bus7.subscribe_once("once.test", lambda e: once_count.__setitem__(0, once_count[0] + 1))
    bus7.publish("once.test")
    bus7.publish("once.test")
    bus7.publish("once.test")
    check("subscribe_once fires only once", once_count[0] == 1)

    # ── Test 8: Event history and replay ─────────────────────────────────
    print("\n[Test 8] Event history and replay")
    bus8 = EventBus(history_size=100)
    for i in range(5):
        bus8.publish("hist.event", {"i": i})
    bus8.publish("other.event", {"x": 1})

    history = bus8.history("hist.event")
    check("history returns matching events (5)", len(history) == 5)
    check("history preserves order", history[0].data["i"] == 0)

    all_history = bus8.history("#")
    check("all history has 6 events", len(all_history) == 6)

    replayed = []
    count = bus8.replay("hist.event", lambda e: replayed.append(e))
    check("replay returns correct count", count == 5)
    check("replay delivers events", len(replayed) == 5)

    # Replay with time filter
    cutoff = history[2].timestamp
    recent = []
    bus8.replay("hist.event", lambda e: recent.append(e), since=cutoff)
    check("replay with since filters old events", len(recent) >= 3)

    # ── Test 9: Dead letter queue ────────────────────────────────────────
    print("\n[Test 9] Dead letter queue (error handling)")
    bus9 = EventBus()

    def bad_handler(e):
        raise ValueError("subscriber exploded")

    good_count = [0]
    bus9.subscribe("err.test", bad_handler)
    bus9.subscribe("err.test", lambda e: good_count.__setitem__(0, good_count[0] + 1))
    bus9.publish("err.test", {"payload": "data"})

    check("good subscriber still called after bad one", good_count[0] == 1)
    check("dead letter recorded", len(bus9.dead_letters) == 1)
    check("dead letter has error message", "exploded" in bus9.dead_letters[0].error)

    # ── Test 10: Metrics ─────────────────────────────────────────────────
    print("\n[Test 10] Metrics tracking")
    bus10 = EventBus()
    bus10.subscribe("m.test", lambda e: None)
    bus10.subscribe("m.test", lambda e: None)
    bus10.publish("m.test")
    bus10.publish("m.test")
    m = bus10.metrics
    check("published count", m["published"] == 2)
    check("delivered count", m["delivered"] == 4)  # 2 subscribers x 2 events
    check("subscriber count", m["subscribers"] == 2)
    check("history size", m["history_size"] == 2)

    # ── Test 11: has_subscribers / subscriber_count ───────────────────────
    print("\n[Test 11] Query helpers")
    bus11 = EventBus()
    bus11.subscribe("q.specific", lambda e: None)
    bus11.subscribe("q.*", lambda e: None)
    check("has_subscribers (exact)", bus11.has_subscribers("q.specific"))
    check("has_subscribers (wildcard match)", bus11.has_subscribers("q.other"))
    check("no subscribers for unrelated", not bus11.has_subscribers("zzz.nope"))
    check("subscriber_count for q.specific is 2", bus11.subscriber_count("q.specific") == 2)
    check("total subscriber count is 2", bus11.subscriber_count() == 2)

    # ── Test 12: wait_for (blocking) ─────────────────────────────────────
    print("\n[Test 12] wait_for (blocking helper)")
    bus12 = EventBus()

    def delayed_publish():
        time.sleep(0.1)
        bus12.publish("wait.done", {"result": 42})

    threading.Thread(target=delayed_publish, daemon=True).start()
    evt = bus12.wait_for("wait.done", timeout=2.0)
    check("wait_for receives event", evt is not None)
    check("wait_for event has correct data", evt.data["result"] == 42)

    # Timeout case
    bus12b = EventBus()
    evt2 = bus12b.wait_for("never.happens", timeout=0.2)
    check("wait_for returns None on timeout", evt2 is None)

    # ── Test 13: Async delivery ──────────────────────────────────────────
    print("\n[Test 13] Async (threaded) delivery")
    bus13 = EventBus()
    async_results = []
    async_event = threading.Event()

    def async_handler(e):
        async_results.append(threading.current_thread().name)
        async_event.set()

    bus13.subscribe("async.test", async_handler, async_delivery=True)
    bus13.publish("async.test", {"val": 1})
    async_event.wait(timeout=2.0)
    check("async handler executed", len(async_results) == 1)
    check("async handler ran in different thread", async_results[0] != threading.current_thread().name)

    # ── Test 14: Event serialization ─────────────────────────────────────
    print("\n[Test 14] Event to_dict / from_dict")
    evt14 = Event(topic="ser.test", data={"key": "value"}, source="test")
    d = evt14.to_dict()
    check("to_dict has topic", d["topic"] == "ser.test")
    check("to_dict has data", d["data"] == {"key": "value"})
    evt14b = Event.from_dict(d)
    check("from_dict roundtrip topic", evt14b.topic == evt14.topic)
    check("from_dict roundtrip data", evt14b.data == evt14.data)
    check("from_dict roundtrip source", evt14b.source == evt14.source)

    # ── Test 15: StateEventBridge ────────────────────────────────────────
    print("\n[Test 15] StateEventBridge (mock DistributedState)")

    class MockState:
        """Minimal mock of DistributedState for bridge testing."""
        def __init__(self):
            self._subscribers = []
            self._cache = {}

        def subscribe(self, cb):
            self._subscribers.append(cb)

        def snapshot(self):
            return dict(self._cache)

        def set(self, key, value):
            self._cache[key] = value
            for cb in self._subscribers:
                cb(key, value)

    mock_state = MockState()
    bus15 = EventBus()
    bridge = StateEventBridge(bus15, mock_state)

    bridge_events = []
    bus15.subscribe("state.#", lambda e: bridge_events.append(e))

    mock_state.set("agent.executor.status", "running")
    check("bridge publishes state change", len(bridge_events) == 1)
    check("bridge topic correct", bridge_events[0].topic == "state.agent.executor.status")
    check("bridge data has key", bridge_events[0].data["key"] == "agent.executor.status")
    check("bridge data has value", bridge_events[0].data["value"] == "running")
    check("bridge data has old_value None", bridge_events[0].data["old_value"] is None)

    mock_state.set("agent.executor.status", "idle")
    check("bridge detects second change", len(bridge_events) == 2)
    check("bridge tracks old_value", bridge_events[1].data["old_value"] == "running")
    check("bridge changed flag true", bridge_events[1].data["changed"] is True)

    # Same value → changed=False
    mock_state.set("agent.executor.status", "idle")
    check("bridge changed flag false for same value", bridge_events[2].data["changed"] is False)

    # ── Test 16: TaskEventPublisher ──────────────────────────────────────
    print("\n[Test 16] TaskEventPublisher")
    bus16 = EventBus()
    task_pub = TaskEventPublisher(bus16)
    task_events = []
    bus16.subscribe("task.#", lambda e: task_events.append(e))

    task_pub.task_queued("t-001", project_id="p-1")
    task_pub.task_started("t-001", agent="executor")
    task_pub.task_completed("t-001", quality=95, elapsed=1.5)
    task_pub.task_failed("t-002", error="timeout", attempt=2)
    task_pub.task_retrying("t-002", attempt=3, strategy="different_agent")

    check("5 task lifecycle events", len(task_events) == 5)
    check("queued topic", task_events[0].topic == "task.queued")
    check("started topic", task_events[1].topic == "task.started")
    check("completed has quality", task_events[2].data["quality"] == 95)
    check("failed has error", task_events[3].data["error"] == "timeout")
    check("retrying has strategy", task_events[4].data["strategy"] == "different_agent")

    # ── Test 17: FileWatcherPublisher ────────────────────────────────────
    print("\n[Test 17] FileWatcherPublisher")
    import tempfile

    bus17 = EventBus()
    tmpdir = Path(tempfile.mkdtemp())
    test_file = tmpdir / "test_watch.json"
    test_file.write_text('{"version": 1}')

    watcher = FileWatcherPublisher(bus17, {"test_config": test_file})
    watcher._interval = 0.2  # Speed up for test

    file_events = []
    bus17.subscribe("file.changed.#", lambda e: file_events.append(e))

    watcher.start()
    time.sleep(0.3)

    # Modify file
    test_file.write_text('{"version": 2}')
    time.sleep(0.5)

    watcher.stop()

    check("file change detected", len(file_events) >= 1)
    if file_events:
        check("file event has path", str(test_file) in file_events[0].data["path"])

    # Cleanup
    test_file.unlink()
    tmpdir.rmdir()

    # ── Test 18: Singleton get_bus / reset_bus ───────────────────────────
    print("\n[Test 18] Singleton management")
    reset_bus()
    b1 = get_bus()
    b2 = get_bus()
    check("get_bus returns same instance", b1 is b2)
    reset_bus()
    b3 = get_bus()
    check("reset_bus creates new instance", b1 is not b3)
    reset_bus()

    # ── Test 19: Multiple patterns on same bus ───────────────────────────
    print("\n[Test 19] Multiple patterns, selective delivery")
    bus19 = EventBus()
    agent_events = []
    task_events19 = []
    all_events19 = []

    bus19.subscribe("agent.*", lambda e: agent_events.append(e))
    bus19.subscribe("task.*", lambda e: task_events19.append(e))
    bus19.subscribe("#", lambda e: all_events19.append(e))

    bus19.publish("agent.started", {"id": "a1"})
    bus19.publish("task.completed", {"id": "t1"})
    bus19.publish("system.health", {"ok": True})

    check("agent subscriber got 1", len(agent_events) == 1)
    check("task subscriber got 1", len(task_events19) == 1)
    check("catch-all got 3", len(all_events19) == 3)

    # ── Test 20: Thread safety stress test ───────────────────────────────
    print("\n[Test 20] Thread safety (concurrent pub/sub)")
    bus20 = EventBus()
    counter = {"n": 0}
    counter_lock = threading.Lock()

    def counting_handler(e):
        with counter_lock:
            counter["n"] += 1

    bus20.subscribe("stress.#", counting_handler)

    threads = []
    num_threads = 10
    events_per_thread = 100

    def publisher(thread_id):
        for i in range(events_per_thread):
            bus20.publish(f"stress.t{thread_id}", {"i": i})

    for t in range(num_threads):
        th = threading.Thread(target=publisher, args=(t,))
        threads.append(th)
        th.start()

    for th in threads:
        th.join(timeout=10.0)

    expected = num_threads * events_per_thread
    check(f"all {expected} events delivered under concurrency", counter["n"] == expected)

    # ── Test 21: clear() ─────────────────────────────────────────────────
    print("\n[Test 21] clear()")
    bus21 = EventBus()
    bus21.subscribe("x", lambda e: None)
    bus21.publish("x")
    bus21.clear()
    check("subscriptions cleared", bus21.subscriber_count() == 0)
    check("history cleared", len(bus21.history()) == 0)

    # ── Summary ──────────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    total = passed + failed
    print(f"Results: {passed}/{total} passed, {failed} failed")
    if failed == 0:
        print("ALL TESTS PASSED")
    else:
        print("SOME TESTS FAILED")
    print("=" * 70)
    sys.exit(0 if failed == 0 else 1)
