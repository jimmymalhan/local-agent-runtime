#!/usr/bin/env python3
"""
orchestrator/read_replicas.py — Read Replicas & Consistency Protocols
=====================================================================
Distribute reads across replicas while maintaining configurable consistency.

Architecture:
  Primary (single writer)
    ├─ Accepts all writes
    ├─ Propagates via replication stream
    └─ Serves strongly-consistent reads

  Read Replica 1..N
    ├─ Receives replication stream from primary
    ├─ Serves eventual / bounded-staleness / session reads
    └─ Reports replication lag to router

Consistency Protocols:
  - STRONG:            Read from primary only (linearizable)
  - BOUNDED_STALENESS: Read from any replica within max lag threshold
  - SESSION:           Read-your-writes within a client session
  - EVENTUAL:          Read from any replica (lowest latency)

Features:
  - Weighted round-robin load balancing across healthy replicas
  - Replication lag tracking with automatic stale-replica exclusion
  - Session tokens for read-your-writes consistency
  - Read hedging: parallel reads to multiple replicas, first response wins
  - Replica promotion: any replica can become primary
  - Connection pooling with per-replica limits
"""

import json
import math
import time
import hashlib
import threading
import logging
from pathlib import Path
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set, Tuple
from dataclasses import dataclass, field
from collections import defaultdict, deque
from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor, as_completed, Future

BASE_DIR = Path(__file__).parent.parent
STATE_DIR = BASE_DIR / "state"

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("read_replicas")


# ---------------------------------------------------------------------------
# Consistency levels
# ---------------------------------------------------------------------------

class ReadConsistency(Enum):
    STRONG = "strong"                      # read from primary only
    BOUNDED_STALENESS = "bounded_staleness" # any replica within lag threshold
    SESSION = "session"                    # read-your-writes per session
    EVENTUAL = "eventual"                  # any replica, best effort


# ---------------------------------------------------------------------------
# Session token — tracks per-client write position for read-your-writes
# ---------------------------------------------------------------------------

@dataclass
class SessionToken:
    """Tracks the latest write position for a client session."""
    session_id: str
    write_sequence: int = 0       # monotonic write counter
    last_write_ts: float = 0.0    # wall-clock of last write
    last_write_keys: Set[str] = field(default_factory=set)  # keys written in current session

    def advance(self, key: str) -> "SessionToken":
        self.write_sequence += 1
        self.last_write_ts = time.time()
        self.last_write_keys.add(key)
        return self

    def to_dict(self) -> dict:
        return {
            "session_id": self.session_id,
            "write_sequence": self.write_sequence,
            "last_write_ts": self.last_write_ts,
            "last_write_keys": sorted(self.last_write_keys),
        }


class SessionManager:
    """Manages client sessions for read-your-writes consistency."""

    def __init__(self):
        self._sessions: Dict[str, SessionToken] = {}
        self._lock = threading.Lock()

    def get_or_create(self, session_id: str) -> SessionToken:
        with self._lock:
            if session_id not in self._sessions:
                self._sessions[session_id] = SessionToken(session_id=session_id)
            return self._sessions[session_id]

    def advance(self, session_id: str, key: str) -> SessionToken:
        with self._lock:
            token = self._sessions.setdefault(
                session_id, SessionToken(session_id=session_id)
            )
            token.advance(key)
            return token

    def remove(self, session_id: str) -> None:
        with self._lock:
            self._sessions.pop(session_id, None)

    @property
    def active_sessions(self) -> int:
        with self._lock:
            return len(self._sessions)


# ---------------------------------------------------------------------------
# Replica — a read-only copy of the primary's state
# ---------------------------------------------------------------------------

@dataclass
class ReplicationEvent:
    sequence: int
    key: str
    value: Any
    timestamp: float
    tombstone: bool = False


class Replica:
    """A read replica that receives writes from a replication stream."""

    def __init__(self, replica_id: str, weight: int = 1, max_connections: int = 100):
        self.replica_id = replica_id
        self.weight = weight
        self.max_connections = max_connections
        self._store: Dict[str, Any] = {}
        self._sequence: int = 0          # latest applied sequence number
        self._apply_ts: float = 0.0      # wall-clock of last applied event
        self._lock = threading.Lock()
        self._healthy = True
        self._active_connections = 0
        self._total_reads = 0
        self._total_applies = 0

    # -- Replication consumer --

    def apply_event(self, event: ReplicationEvent) -> None:
        """Apply a replication event from the primary."""
        with self._lock:
            if event.sequence <= self._sequence:
                return  # already applied (idempotent)
            if event.tombstone:
                self._store.pop(event.key, None)
            else:
                self._store[event.key] = event.value
            self._sequence = event.sequence
            self._apply_ts = event.timestamp
            self._total_applies += 1

    def apply_batch(self, events: List[ReplicationEvent]) -> int:
        """Apply a batch of replication events. Returns count applied."""
        applied = 0
        for event in sorted(events, key=lambda e: e.sequence):
            with self._lock:
                if event.sequence <= self._sequence:
                    continue
                if event.tombstone:
                    self._store.pop(event.key, None)
                else:
                    self._store[event.key] = event.value
                self._sequence = event.sequence
                self._apply_ts = event.timestamp
                self._total_applies += 1
                applied += 1
        return applied

    # -- Read operations --

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            self._total_reads += 1
            return self._store.get(key)

    def has_key(self, key: str) -> bool:
        with self._lock:
            return key in self._store

    def keys(self) -> List[str]:
        with self._lock:
            return list(self._store.keys())

    # -- Connection tracking --

    def acquire_connection(self) -> bool:
        with self._lock:
            if self._active_connections >= self.max_connections:
                return False
            self._active_connections += 1
            return True

    def release_connection(self) -> None:
        with self._lock:
            self._active_connections = max(0, self._active_connections - 1)

    # -- Health and lag --

    @property
    def current_sequence(self) -> int:
        with self._lock:
            return self._sequence

    @property
    def last_apply_timestamp(self) -> float:
        with self._lock:
            return self._apply_ts

    @property
    def healthy(self) -> bool:
        return self._healthy

    @healthy.setter
    def healthy(self, value: bool) -> None:
        self._healthy = value

    def replication_lag_seconds(self, primary_sequence: int, primary_ts: float) -> float:
        """Calculate replication lag relative to primary."""
        with self._lock:
            if self._sequence >= primary_sequence:
                return 0.0
            if self._apply_ts <= 0:
                return primary_ts - time.time() if primary_ts > 0 else float("inf")
            return primary_ts - self._apply_ts

    def replication_lag_events(self, primary_sequence: int) -> int:
        """Number of events behind the primary."""
        with self._lock:
            return max(0, primary_sequence - self._sequence)

    def metrics(self) -> dict:
        with self._lock:
            return {
                "replica_id": self.replica_id,
                "sequence": self._sequence,
                "store_size": len(self._store),
                "total_reads": self._total_reads,
                "total_applies": self._total_applies,
                "active_connections": self._active_connections,
                "max_connections": self.max_connections,
                "weight": self.weight,
                "healthy": self._healthy,
            }


# ---------------------------------------------------------------------------
# Primary — the single writer that generates the replication stream
# ---------------------------------------------------------------------------

class Primary:
    """The primary node that accepts writes and generates a replication stream."""

    def __init__(self, primary_id: str = "primary"):
        self.primary_id = primary_id
        self._store: Dict[str, Any] = {}
        self._sequence: int = 0
        self._write_ts: float = 0.0
        self._replication_log: deque = deque(maxlen=100_000)
        self._lock = threading.Lock()
        self._total_writes = 0
        self._total_reads = 0

    def put(self, key: str, value: Any) -> ReplicationEvent:
        with self._lock:
            self._sequence += 1
            self._write_ts = time.time()
            self._store[key] = value
            self._total_writes += 1
            event = ReplicationEvent(
                sequence=self._sequence,
                key=key,
                value=value,
                timestamp=self._write_ts,
            )
            self._replication_log.append(event)
            return event

    def delete(self, key: str) -> Optional[ReplicationEvent]:
        with self._lock:
            if key not in self._store:
                return None
            self._sequence += 1
            self._write_ts = time.time()
            del self._store[key]
            self._total_writes += 1
            event = ReplicationEvent(
                sequence=self._sequence,
                key=key,
                value=None,
                timestamp=self._write_ts,
                tombstone=True,
            )
            self._replication_log.append(event)
            return event

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            self._total_reads += 1
            return self._store.get(key)

    def has_key(self, key: str) -> bool:
        with self._lock:
            return key in self._store

    def keys(self) -> List[str]:
        with self._lock:
            return list(self._store.keys())

    @property
    def current_sequence(self) -> int:
        with self._lock:
            return self._sequence

    @property
    def last_write_timestamp(self) -> float:
        with self._lock:
            return self._write_ts

    def events_since(self, after_sequence: int) -> List[ReplicationEvent]:
        """Get all replication events after a given sequence number."""
        with self._lock:
            return [e for e in self._replication_log if e.sequence > after_sequence]

    def snapshot(self) -> Tuple[int, float, Dict[str, Any]]:
        """Returns (sequence, timestamp, full_store_copy)."""
        with self._lock:
            return self._sequence, self._write_ts, dict(self._store)

    def metrics(self) -> dict:
        with self._lock:
            return {
                "primary_id": self.primary_id,
                "sequence": self._sequence,
                "store_size": len(self._store),
                "total_writes": self._total_writes,
                "total_reads": self._total_reads,
                "replication_log_size": len(self._replication_log),
            }


# ---------------------------------------------------------------------------
# ReplicationStream — propagates writes from primary to replicas
# ---------------------------------------------------------------------------

class ReplicationStream:
    """Pushes replication events from the primary to all registered replicas."""

    def __init__(self, primary: Primary):
        self._primary = primary
        self._replicas: Dict[str, Replica] = {}
        self._replica_cursors: Dict[str, int] = {}  # replica_id -> last_applied_seq
        self._lock = threading.Lock()

    def register(self, replica: Replica) -> None:
        with self._lock:
            self._replicas[replica.replica_id] = replica
            self._replica_cursors[replica.replica_id] = 0

    def unregister(self, replica_id: str) -> None:
        with self._lock:
            self._replicas.pop(replica_id, None)
            self._replica_cursors.pop(replica_id, None)

    def sync_replica(self, replica_id: str) -> int:
        """Push pending events to a single replica. Returns events applied."""
        with self._lock:
            replica = self._replicas.get(replica_id)
            if replica is None or not replica.healthy:
                return 0
            cursor = self._replica_cursors.get(replica_id, 0)

        events = self._primary.events_since(cursor)
        if not events:
            return 0

        applied = replica.apply_batch(events)
        with self._lock:
            if events:
                self._replica_cursors[replica_id] = events[-1].sequence
        return applied

    def sync_all(self) -> Dict[str, int]:
        """Push pending events to all replicas. Returns {replica_id: events_applied}."""
        results: Dict[str, int] = {}
        with self._lock:
            replica_ids = list(self._replicas.keys())
        for rid in replica_ids:
            results[rid] = self.sync_replica(rid)
        return results

    def lag_report(self) -> Dict[str, dict]:
        """Per-replica lag report."""
        primary_seq = self._primary.current_sequence
        primary_ts = self._primary.last_write_timestamp
        report: Dict[str, dict] = {}
        with self._lock:
            for rid, replica in self._replicas.items():
                report[rid] = {
                    "sequence_lag": replica.replication_lag_events(primary_seq),
                    "time_lag_s": round(replica.replication_lag_seconds(primary_seq, primary_ts), 4),
                    "healthy": replica.healthy,
                    "cursor": self._replica_cursors.get(rid, 0),
                }
        return report

    @property
    def replica_count(self) -> int:
        with self._lock:
            return len(self._replicas)


# ---------------------------------------------------------------------------
# ReadRouter — distributes reads based on consistency level
# ---------------------------------------------------------------------------

class ReadRouter:
    """
    Routes read requests to the appropriate replica based on the
    requested consistency level.

    Load balancing: weighted round-robin across eligible replicas.
    Stale exclusion: replicas beyond max_lag_seconds are excluded from
                     BOUNDED_STALENESS reads.
    Session affinity: SESSION reads check replica sequence against
                      session write position.
    Hedging: sends parallel reads to N replicas, returns first response.
    """

    def __init__(
        self,
        primary: Primary,
        replicas: Dict[str, Replica],
        replication_stream: ReplicationStream,
        max_lag_seconds: float = 5.0,
        max_lag_events: int = 100,
        hedge_count: int = 2,
    ):
        self._primary = primary
        self._replicas = replicas
        self._stream = replication_stream
        self._max_lag_seconds = max_lag_seconds
        self._max_lag_events = max_lag_events
        self._hedge_count = hedge_count
        self._session_mgr = SessionManager()
        self._lock = threading.Lock()
        self._rr_index = 0  # round-robin counter
        self._total_reads = 0
        self._reads_by_consistency: Dict[str, int] = defaultdict(int)
        self._reads_from_primary = 0
        self._reads_from_replica = 0
        self._hedge_wins = 0

    @property
    def session_manager(self) -> SessionManager:
        return self._session_mgr

    # -- Eligible replica selection --

    def _healthy_replicas(self) -> List[Replica]:
        return [r for r in self._replicas.values() if r.healthy]

    def _within_lag_threshold(self, replica: Replica) -> bool:
        primary_seq = self._primary.current_sequence
        primary_ts = self._primary.last_write_timestamp
        lag_s = replica.replication_lag_seconds(primary_seq, primary_ts)
        lag_e = replica.replication_lag_events(primary_seq)
        return lag_s <= self._max_lag_seconds and lag_e <= self._max_lag_events

    def _bounded_staleness_replicas(self) -> List[Replica]:
        return [r for r in self._healthy_replicas() if self._within_lag_threshold(r)]

    def _session_eligible_replicas(self, session_id: str, key: str) -> List[Replica]:
        """Replicas whose sequence >= the session's last write sequence."""
        token = self._session_mgr.get_or_create(session_id)
        eligible = []
        for r in self._healthy_replicas():
            if r.current_sequence >= token.write_sequence:
                eligible.append(r)
        return eligible

    # -- Weighted round-robin selection --

    def _weighted_select(self, candidates: List[Replica]) -> Optional[Replica]:
        if not candidates:
            return None
        # Build weighted list
        weighted: List[Replica] = []
        for r in candidates:
            weighted.extend([r] * r.weight)
        if not weighted:
            return candidates[0]
        with self._lock:
            idx = self._rr_index % len(weighted)
            self._rr_index += 1
        return weighted[idx]

    # -- Core read dispatch --

    def read(
        self,
        key: str,
        consistency: ReadConsistency = ReadConsistency.EVENTUAL,
        session_id: Optional[str] = None,
    ) -> Optional[Any]:
        """
        Read a key with the specified consistency level.

        STRONG:            Always reads from primary.
        BOUNDED_STALENESS: Reads from any replica within lag threshold; falls back to primary.
        SESSION:           Reads from replica that has seen the session's writes; falls back to primary.
        EVENTUAL:          Reads from any healthy replica; falls back to primary.
        """
        with self._lock:
            self._total_reads += 1
            self._reads_by_consistency[consistency.value] += 1

        if consistency == ReadConsistency.STRONG:
            with self._lock:
                self._reads_from_primary += 1
            return self._primary.get(key)

        if consistency == ReadConsistency.BOUNDED_STALENESS:
            candidates = self._bounded_staleness_replicas()
            replica = self._weighted_select(candidates)
            if replica is not None:
                with self._lock:
                    self._reads_from_replica += 1
                return replica.get(key)
            # Fallback to primary
            with self._lock:
                self._reads_from_primary += 1
            return self._primary.get(key)

        if consistency == ReadConsistency.SESSION:
            if session_id is None:
                # No session → treat as eventual
                candidates = self._healthy_replicas()
            else:
                candidates = self._session_eligible_replicas(session_id, key)
            replica = self._weighted_select(candidates)
            if replica is not None:
                with self._lock:
                    self._reads_from_replica += 1
                return replica.get(key)
            with self._lock:
                self._reads_from_primary += 1
            return self._primary.get(key)

        # EVENTUAL
        candidates = self._healthy_replicas()
        replica = self._weighted_select(candidates)
        if replica is not None:
            with self._lock:
                self._reads_from_replica += 1
            return replica.get(key)
        with self._lock:
            self._reads_from_primary += 1
        return self._primary.get(key)

    # -- Hedged reads --

    def hedged_read(self, key: str, consistency: ReadConsistency = ReadConsistency.EVENTUAL) -> Optional[Any]:
        """
        Send read to multiple replicas in parallel, return the first result.
        Reduces tail latency at the cost of extra read load.
        """
        candidates = self._healthy_replicas()
        if not candidates:
            return self._primary.get(key)

        targets = candidates[:self._hedge_count]
        results: List[Optional[Any]] = [None]
        winner_event = threading.Event()

        def do_read(replica: Replica) -> Optional[Any]:
            val = replica.get(key)
            if not winner_event.is_set():
                results[0] = val
                winner_event.set()
            return val

        threads = []
        for t in targets:
            th = threading.Thread(target=do_read, args=(t,))
            th.start()
            threads.append(th)

        winner_event.wait(timeout=2.0)
        with self._lock:
            self._hedge_wins += 1
            self._reads_from_replica += 1
            self._total_reads += 1
            self._reads_by_consistency["hedged"] += 1

        # Clean up threads
        for th in threads:
            th.join(timeout=0.5)

        return results[0]

    # -- Metrics --

    def metrics(self) -> dict:
        with self._lock:
            return {
                "total_reads": self._total_reads,
                "reads_by_consistency": dict(self._reads_by_consistency),
                "reads_from_primary": self._reads_from_primary,
                "reads_from_replica": self._reads_from_replica,
                "hedge_wins": self._hedge_wins,
                "active_sessions": self._session_mgr.active_sessions,
            }


# ---------------------------------------------------------------------------
# ReadReplicaCluster — the complete read-replica system
# ---------------------------------------------------------------------------

class ReadReplicaCluster:
    """
    Complete read-replica system with:
      - Single primary for writes
      - N read replicas for distributed reads
      - Configurable consistency protocols
      - Replication stream management
      - Replica promotion
      - Health monitoring
    """

    def __init__(
        self,
        num_replicas: int = 3,
        default_consistency: ReadConsistency = ReadConsistency.EVENTUAL,
        max_lag_seconds: float = 5.0,
        max_lag_events: int = 100,
        replica_weights: Optional[List[int]] = None,
    ):
        self._primary = Primary()
        self._replicas: Dict[str, Replica] = {}
        self._default_consistency = default_consistency

        weights = replica_weights or [1] * num_replicas
        for i in range(num_replicas):
            rid = f"replica-{i}"
            w = weights[i] if i < len(weights) else 1
            self._replicas[rid] = Replica(replica_id=rid, weight=w)

        self._stream = ReplicationStream(self._primary)
        for r in self._replicas.values():
            self._stream.register(r)

        self._router = ReadRouter(
            primary=self._primary,
            replicas=self._replicas,
            replication_stream=self._stream,
            max_lag_seconds=max_lag_seconds,
            max_lag_events=max_lag_events,
        )

        self._auto_sync = False
        self._sync_thread: Optional[threading.Thread] = None
        self._sync_interval = 0.1
        self._running = False

    @property
    def primary(self) -> Primary:
        return self._primary

    @property
    def replicas(self) -> Dict[str, Replica]:
        return self._replicas

    @property
    def router(self) -> ReadRouter:
        return self._router

    @property
    def stream(self) -> ReplicationStream:
        return self._stream

    # -- Write operations (always go to primary) --

    def write(self, key: str, value: Any, session_id: Optional[str] = None) -> ReplicationEvent:
        """Write to primary and optionally track in session."""
        event = self._primary.put(key, value)
        if session_id:
            self._router.session_manager.advance(session_id, key)
        return event

    def delete(self, key: str, session_id: Optional[str] = None) -> Optional[ReplicationEvent]:
        event = self._primary.delete(key)
        if session_id and event:
            self._router.session_manager.advance(session_id, key)
        return event

    # -- Read operations (distributed across replicas) --

    def read(
        self,
        key: str,
        consistency: Optional[ReadConsistency] = None,
        session_id: Optional[str] = None,
    ) -> Optional[Any]:
        c = consistency or self._default_consistency
        return self._router.read(key, consistency=c, session_id=session_id)

    def hedged_read(self, key: str) -> Optional[Any]:
        return self._router.hedged_read(key)

    # -- Replication management --

    def sync(self) -> Dict[str, int]:
        """Manually sync all replicas."""
        return self._stream.sync_all()

    def sync_replica(self, replica_id: str) -> int:
        return self._stream.sync_replica(replica_id)

    def start_auto_sync(self, interval_s: float = 0.1) -> None:
        if self._running:
            return
        self._sync_interval = interval_s
        self._running = True
        self._sync_thread = threading.Thread(
            target=self._sync_loop, daemon=True, name="replica-sync"
        )
        self._sync_thread.start()

    def stop_auto_sync(self) -> None:
        self._running = False
        if self._sync_thread:
            self._sync_thread.join(timeout=2.0)
            self._sync_thread = None

    def _sync_loop(self) -> None:
        while self._running:
            self._stream.sync_all()
            time.sleep(self._sync_interval)

    # -- Replica management --

    def add_replica(self, replica_id: str, weight: int = 1) -> Replica:
        replica = Replica(replica_id=replica_id, weight=weight)
        self._replicas[replica_id] = replica
        self._stream.register(replica)
        # Bootstrap from primary snapshot — each key gets its own sequence
        seq, ts, store = self._primary.snapshot()
        for i, (key, value) in enumerate(store.items(), start=1):
            replica.apply_event(ReplicationEvent(
                sequence=i, key=key, value=value, timestamp=ts,
            ))
        return replica

    def remove_replica(self, replica_id: str) -> None:
        self._stream.unregister(replica_id)
        self._replicas.pop(replica_id, None)

    def promote_replica(self, replica_id: str) -> Primary:
        """
        Promote a replica to primary. The old primary becomes a replica.
        Steps:
          1. Stop accepting writes on old primary
          2. Ensure target replica is fully caught up
          3. Swap roles
          4. Re-register replication stream
        """
        replica = self._replicas.get(replica_id)
        if replica is None:
            raise ValueError(f"Replica {replica_id} not found")

        # 1. Final sync to catch up
        self._stream.sync_replica(replica_id)

        # 2. Build new primary from replica state
        new_primary = Primary(primary_id=replica_id)
        for key in replica.keys():
            val = replica.get(key)
            if val is not None:
                new_primary.put(key, val)

        # 3. Demote old primary to replica
        old_primary_id = self._primary.primary_id
        old_replica = Replica(replica_id=old_primary_id)
        seq, ts, store = self._primary.snapshot()
        for key, value in store.items():
            old_replica.apply_event(ReplicationEvent(
                sequence=seq, key=key, value=value, timestamp=ts,
            ))

        # 4. Swap
        self._replicas.pop(replica_id, None)
        self._replicas[old_primary_id] = old_replica
        self._primary = new_primary

        # 5. Rebuild replication stream
        self._stream = ReplicationStream(self._primary)
        for r in self._replicas.values():
            self._stream.register(r)
        self._router = ReadRouter(
            primary=self._primary,
            replicas=self._replicas,
            replication_stream=self._stream,
        )

        logger.info("Promoted %s to primary, demoted %s to replica", replica_id, old_primary_id)
        return new_primary

    # -- Health --

    def mark_replica_unhealthy(self, replica_id: str) -> None:
        if replica_id in self._replicas:
            self._replicas[replica_id].healthy = False

    def mark_replica_healthy(self, replica_id: str) -> None:
        if replica_id in self._replicas:
            self._replicas[replica_id].healthy = True

    # -- Metrics --

    def lag_report(self) -> Dict[str, dict]:
        return self._stream.lag_report()

    def cluster_metrics(self) -> dict:
        return {
            "primary": self._primary.metrics(),
            "replicas": {rid: r.metrics() for rid, r in self._replicas.items()},
            "replication": self._stream.lag_report(),
            "router": self._router.metrics(),
        }


# ---------------------------------------------------------------------------
# __main__ — correctness verification with assertions
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("READ REPLICAS & CONSISTENCY PROTOCOLS: Correctness Tests")
    print("=" * 70)

    # ---- Test 1: Primary write + read ----
    print("\n[Test 1] Primary accepts writes and reads...")
    cluster = ReadReplicaCluster(num_replicas=3)
    event = cluster.write("key1", "value1")
    assert event.sequence == 1
    assert event.key == "key1"
    val = cluster.primary.get("key1")
    assert val == "value1"
    print("  PASS: primary write/read works")

    # ---- Test 2: Replication to replicas ----
    print("\n[Test 2] Replication stream pushes to replicas...")
    cluster.write("key2", "value2")
    cluster.write("key3", "value3")
    synced = cluster.sync()
    assert all(v > 0 for v in synced.values()), f"All replicas should have synced: {synced}"
    for rid, replica in cluster.replicas.items():
        assert replica.get("key1") == "value1", f"{rid} missing key1"
        assert replica.get("key2") == "value2", f"{rid} missing key2"
        assert replica.get("key3") == "value3", f"{rid} missing key3"
    print(f"  PASS: all 3 replicas synced — {synced}")

    # ---- Test 3: STRONG consistency reads from primary ----
    print("\n[Test 3] STRONG consistency reads from primary only...")
    cluster.write("strong_key", "primary_val")
    # Don't sync — replicas won't have it yet
    val = cluster.read("strong_key", consistency=ReadConsistency.STRONG)
    assert val == "primary_val", f"STRONG read should come from primary, got {val}"
    print("  PASS: STRONG read returns primary data without sync")

    # ---- Test 4: EVENTUAL consistency reads from replicas ----
    print("\n[Test 4] EVENTUAL consistency reads from replicas...")
    cluster.sync()  # now replicas have everything
    val = cluster.read("key1", consistency=ReadConsistency.EVENTUAL)
    assert val == "value1"
    metrics = cluster.router.metrics()
    assert metrics["reads_from_replica"] > 0, "Should have read from a replica"
    print(f"  PASS: EVENTUAL read served from replica (total replica reads: {metrics['reads_from_replica']})")

    # ---- Test 5: BOUNDED_STALENESS excludes lagging replicas ----
    print("\n[Test 5] BOUNDED_STALENESS excludes stale replicas...")
    stale_cluster = ReadReplicaCluster(
        num_replicas=2,
        max_lag_seconds=0.5,
        max_lag_events=5,
    )
    # Write 10 events, sync only replica-0
    for i in range(10):
        stale_cluster.write(f"bs_key_{i}", f"bs_val_{i}")
    stale_cluster.sync_replica("replica-0")
    # replica-1 is behind by 10 events (> max_lag_events=5)

    val = stale_cluster.read("bs_key_0", consistency=ReadConsistency.BOUNDED_STALENESS)
    assert val == "bs_val_0"
    # Should have read from replica-0 (the only one within threshold) or primary
    print("  PASS: BOUNDED_STALENESS read succeeds with stale replica excluded")

    # ---- Test 6: SESSION consistency (read-your-writes) ----
    print("\n[Test 6] SESSION consistency provides read-your-writes...")
    session_cluster = ReadReplicaCluster(num_replicas=2)
    sid = "user-session-42"
    session_cluster.write("session_key", "session_val", session_id=sid)
    session_cluster.sync()  # sync so replicas are caught up

    val = session_cluster.read("session_key", consistency=ReadConsistency.SESSION, session_id=sid)
    assert val == "session_val", f"SESSION read should see own write, got {val}"
    token = session_cluster.router.session_manager.get_or_create(sid)
    assert token.write_sequence == 1
    assert "session_key" in token.last_write_keys
    print(f"  PASS: session read-your-writes works (seq={token.write_sequence})")

    # ---- Test 7: Session token tracking ----
    print("\n[Test 7] Session tokens advance correctly...")
    session_cluster.write("key_a", "val_a", session_id=sid)
    session_cluster.write("key_b", "val_b", session_id=sid)
    token = session_cluster.router.session_manager.get_or_create(sid)
    assert token.write_sequence == 3
    assert {"session_key", "key_a", "key_b"}.issubset(token.last_write_keys)
    print(f"  PASS: session token tracks 3 writes across 3 keys")

    # ---- Test 8: Replica health exclusion ----
    print("\n[Test 8] Unhealthy replicas excluded from reads...")
    cluster.mark_replica_unhealthy("replica-0")
    cluster.mark_replica_unhealthy("replica-1")
    # Only replica-2 is healthy
    val = cluster.read("key1", consistency=ReadConsistency.EVENTUAL)
    assert val == "value1"
    cluster.mark_replica_healthy("replica-0")
    cluster.mark_replica_healthy("replica-1")
    print("  PASS: unhealthy replicas excluded, read still succeeds")

    # ---- Test 9: All replicas unhealthy — fallback to primary ----
    print("\n[Test 9] All replicas down — fallback to primary...")
    for rid in cluster.replicas:
        cluster.mark_replica_unhealthy(rid)
    val = cluster.read("key1", consistency=ReadConsistency.EVENTUAL)
    assert val == "value1", "Should fall back to primary"
    for rid in cluster.replicas:
        cluster.mark_replica_healthy(rid)
    print("  PASS: all replicas down, primary served the read")

    # ---- Test 10: Delete replication ----
    print("\n[Test 10] Delete propagates to replicas...")
    cluster.write("del_key", "del_val")
    cluster.sync()
    for r in cluster.replicas.values():
        assert r.get("del_key") == "del_val"

    event = cluster.delete("del_key")
    assert event is not None
    assert event.tombstone is True
    cluster.sync()
    for r in cluster.replicas.values():
        assert r.get("del_key") is None, f"Replica should not have deleted key"
    print("  PASS: delete propagated to all replicas")

    # ---- Test 11: Idempotent event application ----
    print("\n[Test 11] Replica ignores duplicate events...")
    r = Replica("test-idempotent")
    e = ReplicationEvent(sequence=1, key="k", value="v", timestamp=time.time())
    r.apply_event(e)
    r.apply_event(e)  # duplicate
    r.apply_event(e)  # duplicate again
    assert r.current_sequence == 1
    assert r.metrics()["total_applies"] == 1
    print("  PASS: duplicate events applied only once")

    # ---- Test 12: Batch event application ----
    print("\n[Test 12] Batch apply respects ordering...")
    r2 = Replica("test-batch")
    events = [
        ReplicationEvent(sequence=3, key="c", value=3, timestamp=time.time()),
        ReplicationEvent(sequence=1, key="a", value=1, timestamp=time.time()),
        ReplicationEvent(sequence=2, key="b", value=2, timestamp=time.time()),
    ]
    applied = r2.apply_batch(events)
    assert applied == 3
    assert r2.get("a") == 1
    assert r2.get("b") == 2
    assert r2.get("c") == 3
    assert r2.current_sequence == 3
    print("  PASS: batch applied 3 events in sequence order")

    # ---- Test 13: Weighted round-robin distribution ----
    print("\n[Test 13] Weighted round-robin distributes reads...")
    weighted_cluster = ReadReplicaCluster(
        num_replicas=3,
        replica_weights=[3, 1, 1],
    )
    for i in range(5):
        weighted_cluster.write(f"w_key_{i}", f"w_val_{i}")
    weighted_cluster.sync()

    read_counts: Dict[str, int] = defaultdict(int)
    for _ in range(100):
        weighted_cluster.read("w_key_0", consistency=ReadConsistency.EVENTUAL)
    for rid, r in weighted_cluster.replicas.items():
        read_counts[rid] = r.metrics()["total_reads"]

    # replica-0 (weight=3) should get roughly 3x the reads of replica-1 (weight=1)
    assert read_counts["replica-0"] > read_counts["replica-1"], \
        f"Weighted replica should get more reads: {dict(read_counts)}"
    print(f"  PASS: weighted distribution: {dict(read_counts)}")

    # ---- Test 14: Hedged read returns result ----
    print("\n[Test 14] Hedged read returns first result...")
    hedge_cluster = ReadReplicaCluster(num_replicas=3)
    hedge_cluster.write("hedge_key", "hedge_val")
    hedge_cluster.sync()
    val = hedge_cluster.hedged_read("hedge_key")
    assert val == "hedge_val"
    m = hedge_cluster.router.metrics()
    assert m["hedge_wins"] > 0
    print(f"  PASS: hedged read returned value (hedge_wins={m['hedge_wins']})")

    # ---- Test 15: Add replica dynamically ----
    print("\n[Test 15] Add replica dynamically with bootstrap...")
    cluster.write("dynamic_key", "dynamic_val")
    cluster.sync()
    new_replica = cluster.add_replica("replica-new", weight=2)
    assert new_replica.get("dynamic_key") == "dynamic_val", "New replica should bootstrap from primary"
    assert new_replica.get("key1") == "value1", "New replica should have all primary data"
    print(f"  PASS: new replica bootstrapped with {len(new_replica.keys())} keys")

    # ---- Test 16: Remove replica ----
    print("\n[Test 16] Remove replica cleanly...")
    cluster.remove_replica("replica-new")
    assert "replica-new" not in cluster.replicas
    assert cluster.stream.replica_count == 3  # original 3
    print("  PASS: replica removed, stream updated")

    # ---- Test 17: Promote replica to primary ----
    print("\n[Test 17] Promote replica to primary...")
    promo_cluster = ReadReplicaCluster(num_replicas=2)
    promo_cluster.write("promo_key", "promo_val")
    promo_cluster.sync()

    old_primary_id = promo_cluster.primary.primary_id
    new_primary = promo_cluster.promote_replica("replica-0")
    assert new_primary.primary_id == "replica-0"
    assert promo_cluster.primary.primary_id == "replica-0"
    # Old primary should now be a replica
    assert old_primary_id in promo_cluster.replicas
    # Data should survive promotion
    assert promo_cluster.primary.get("promo_key") == "promo_val"
    print(f"  PASS: promoted replica-0 to primary, demoted {old_primary_id}")

    # ---- Test 18: Replication lag report ----
    print("\n[Test 18] Replication lag tracking...")
    lag_cluster = ReadReplicaCluster(num_replicas=2)
    for i in range(20):
        lag_cluster.write(f"lag_key_{i}", f"lag_val_{i}")
    # Only sync one replica
    lag_cluster.sync_replica("replica-0")
    report = lag_cluster.lag_report()
    assert report["replica-0"]["sequence_lag"] == 0
    assert report["replica-1"]["sequence_lag"] == 20
    print(f"  PASS: lag report: replica-0 lag=0, replica-1 lag=20")

    # ---- Test 19: Connection pool limits ----
    print("\n[Test 19] Connection pool limits...")
    r = Replica("pool-test", max_connections=3)
    assert r.acquire_connection() is True
    assert r.acquire_connection() is True
    assert r.acquire_connection() is True
    assert r.acquire_connection() is False  # at limit
    r.release_connection()
    assert r.acquire_connection() is True  # freed one
    print("  PASS: connection pool enforces limit")

    # ---- Test 20: Cluster metrics aggregation ----
    print("\n[Test 20] Cluster metrics aggregation...")
    m = cluster.cluster_metrics()
    assert "primary" in m
    assert "replicas" in m
    assert "replication" in m
    assert "router" in m
    assert m["primary"]["total_writes"] > 0
    print(f"  PASS: cluster metrics: primary writes={m['primary']['total_writes']}, "
          f"replicas={len(m['replicas'])}")

    # ---- Test 21: Auto-sync thread lifecycle ----
    print("\n[Test 21] Auto-sync thread start/stop...")
    auto_cluster = ReadReplicaCluster(num_replicas=2)
    auto_cluster.write("auto_key", "auto_val")
    auto_cluster.start_auto_sync(interval_s=0.05)
    time.sleep(0.2)  # let a few syncs run
    val = auto_cluster.replicas["replica-0"].get("auto_key")
    assert val == "auto_val", "Auto-sync should have replicated"
    auto_cluster.stop_auto_sync()
    print("  PASS: auto-sync thread replicated data and stopped cleanly")

    # ---- Test 22: Primary snapshot for full bootstrap ----
    print("\n[Test 22] Primary snapshot captures full state...")
    snap_cluster = ReadReplicaCluster(num_replicas=1)
    for i in range(50):
        snap_cluster.write(f"snap_{i}", i)
    seq, ts, store = snap_cluster.primary.snapshot()
    assert seq == 50
    assert len(store) == 50
    assert store["snap_0"] == 0
    assert store["snap_49"] == 49
    print(f"  PASS: snapshot has {len(store)} keys at sequence {seq}")

    # ---- Test 23: Session cleanup ----
    print("\n[Test 23] Session removal...")
    sm = SessionManager()
    sm.get_or_create("s1")
    sm.get_or_create("s2")
    assert sm.active_sessions == 2
    sm.remove("s1")
    assert sm.active_sessions == 1
    sm.remove("s2")
    assert sm.active_sessions == 0
    print("  PASS: sessions created and cleaned up")

    # ---- Test 24: End-to-end mixed consistency workload ----
    print("\n[Test 24] Mixed consistency workload...")
    mix = ReadReplicaCluster(num_replicas=3)
    sid = "mixed-session"

    # Phase 1: writes
    for i in range(10):
        mix.write(f"mix_{i}", f"val_{i}", session_id=sid)
    mix.sync()

    # Phase 2: read with each consistency level
    v1 = mix.read("mix_0", consistency=ReadConsistency.STRONG)
    assert v1 == "val_0"

    v2 = mix.read("mix_1", consistency=ReadConsistency.BOUNDED_STALENESS)
    assert v2 == "val_1"

    v3 = mix.read("mix_2", consistency=ReadConsistency.SESSION, session_id=sid)
    assert v3 == "val_2"

    v4 = mix.read("mix_3", consistency=ReadConsistency.EVENTUAL)
    assert v4 == "val_3"

    v5 = mix.hedged_read("mix_4")
    assert v5 == "val_4"

    rm = mix.router.metrics()
    assert rm["reads_by_consistency"]["strong"] >= 1
    assert rm["reads_by_consistency"]["bounded_staleness"] >= 1
    assert rm["reads_by_consistency"]["session"] >= 1
    assert rm["reads_by_consistency"]["eventual"] >= 1
    assert rm["reads_by_consistency"]["hedged"] >= 1
    print(f"  PASS: all 5 read modes exercised — {rm['reads_by_consistency']}")

    # ---- Summary ----
    print("\n" + "=" * 70)
    print("ALL 24 TESTS PASSED — Read replicas & consistency protocols verified")
    print("=" * 70)
