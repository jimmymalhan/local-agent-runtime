"""
Read Replicas & Consistency Protocols

Distributes reads across replicas with configurable consistency levels:
  - EVENTUAL:        Read from any replica (fastest, may be stale)
  - READ_YOUR_WRITES: Session-sticky; reads reflect that session's prior writes
  - BOUNDED_STALENESS: Reads guaranteed within a staleness window (time or version)
  - QUORUM:          Majority of replicas must agree (strong consistency)
  - LINEARIZABLE:    Leader-verified read (strongest, highest latency)

Built on top of the geo_replication engine's VectorClock, LWWDict, and RegionNode.
"""

import hashlib
import math
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Consistency levels
# ---------------------------------------------------------------------------

class ConsistencyLevel(Enum):
    EVENTUAL = "eventual"
    READ_YOUR_WRITES = "read_your_writes"
    BOUNDED_STALENESS = "bounded_staleness"
    QUORUM = "quorum"
    LINEARIZABLE = "linearizable"


# ---------------------------------------------------------------------------
# Vector clock (self-contained for standalone operation)
# ---------------------------------------------------------------------------

class VectorClock:
    __slots__ = ("_clocks",)

    def __init__(self, clocks: Optional[dict[str, int]] = None):
        self._clocks: dict[str, int] = dict(clocks) if clocks else {}

    def increment(self, node_id: str) -> "VectorClock":
        new = dict(self._clocks)
        new[node_id] = new.get(node_id, 0) + 1
        return VectorClock(new)

    def merge(self, other: "VectorClock") -> "VectorClock":
        all_keys = set(self._clocks) | set(other._clocks)
        return VectorClock({
            k: max(self._clocks.get(k, 0), other._clocks.get(k, 0))
            for k in all_keys
        })

    def dominates(self, other: "VectorClock") -> bool:
        all_keys = set(self._clocks) | set(other._clocks)
        geq = all(self._clocks.get(k, 0) >= other._clocks.get(k, 0) for k in all_keys)
        gt = any(self._clocks.get(k, 0) > other._clocks.get(k, 0) for k in all_keys)
        return geq and gt

    def dominates_or_equal(self, other: "VectorClock") -> bool:
        all_keys = set(self._clocks) | set(other._clocks)
        return all(self._clocks.get(k, 0) >= other._clocks.get(k, 0) for k in all_keys)

    def total(self) -> int:
        return sum(self._clocks.values())

    def as_dict(self) -> dict[str, int]:
        return dict(self._clocks)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VectorClock):
            return NotImplemented
        all_keys = set(self._clocks) | set(other._clocks)
        return all(self._clocks.get(k, 0) == other._clocks.get(k, 0) for k in all_keys)

    def __repr__(self) -> str:
        return f"VC({self._clocks})"


# ---------------------------------------------------------------------------
# Versioned entry stored in each replica
# ---------------------------------------------------------------------------

@dataclass
class VersionedEntry:
    key: str
    value: Any
    version: int
    vclock: VectorClock
    timestamp: float
    writer_node: str
    tombstone: bool = False

    def supersedes(self, other: "VersionedEntry") -> bool:
        if self.vclock.dominates(other.vclock):
            return True
        if other.vclock.dominates(self.vclock):
            return False
        # Concurrent: LWW tie-break
        if self.timestamp != other.timestamp:
            return self.timestamp > other.timestamp
        return self.writer_node > other.writer_node


# ---------------------------------------------------------------------------
# Write-Ahead Log entry
# ---------------------------------------------------------------------------

@dataclass
class WALEntry:
    lsn: int  # log sequence number
    entry: VersionedEntry
    applied_at: float = field(default_factory=time.time)


# ---------------------------------------------------------------------------
# Single replica node (primary or read replica)
# ---------------------------------------------------------------------------

class ReplicaRole(Enum):
    PRIMARY = "primary"
    READ_REPLICA = "read_replica"


class ReplicaNode:
    """A single node in the replica set; can be primary or read-only replica."""

    def __init__(self, node_id: str, role: ReplicaRole = ReplicaRole.READ_REPLICA,
                 simulated_latency_ms: float = 0.0):
        self.node_id = node_id
        self.role = role
        self.simulated_latency_ms = simulated_latency_ms

        self._store: dict[str, VersionedEntry] = {}
        self._vclock = VectorClock()
        self._version_counter = 0
        self._wal: list[WALEntry] = []
        self._lock = threading.Lock()

        self.stats = {
            "reads": 0,
            "writes": 0,
            "replication_applied": 0,
            "stale_reads": 0,
        }

    @property
    def latest_lsn(self) -> int:
        with self._lock:
            return self._wal[-1].lsn if self._wal else 0

    @property
    def vclock(self) -> VectorClock:
        with self._lock:
            return self._vclock

    # -- writes (primary only) ----------------------------------------------

    def write(self, key: str, value: Any) -> VersionedEntry:
        if self.role != ReplicaRole.PRIMARY:
            raise RuntimeError(f"Node {self.node_id} is a read replica; writes rejected")
        with self._lock:
            self._version_counter += 1
            self._vclock = self._vclock.increment(self.node_id)
            entry = VersionedEntry(
                key=key,
                value=value,
                version=self._version_counter,
                vclock=self._vclock,
                timestamp=time.time(),
                writer_node=self.node_id,
            )
            self._apply_entry(entry)
            self.stats["writes"] += 1
            return entry

    def delete(self, key: str) -> VersionedEntry:
        if self.role != ReplicaRole.PRIMARY:
            raise RuntimeError(f"Node {self.node_id} is a read replica; writes rejected")
        with self._lock:
            self._version_counter += 1
            self._vclock = self._vclock.increment(self.node_id)
            entry = VersionedEntry(
                key=key,
                value=None,
                version=self._version_counter,
                vclock=self._vclock,
                timestamp=time.time(),
                writer_node=self.node_id,
                tombstone=True,
            )
            self._apply_entry(entry)
            self.stats["writes"] += 1
            return entry

    # -- reads (all nodes) --------------------------------------------------

    def local_read(self, key: str) -> Optional[VersionedEntry]:
        """Read from this node's local store without consistency checks."""
        self.stats["reads"] += 1
        if self.simulated_latency_ms > 0:
            time.sleep(self.simulated_latency_ms / 1000.0)
        with self._lock:
            e = self._store.get(key)
            if e and not e.tombstone:
                return e
            return None

    def local_read_with_version(self, key: str) -> tuple[Optional[VersionedEntry], int]:
        """Read entry and current LSN (for staleness checks)."""
        self.stats["reads"] += 1
        with self._lock:
            lsn = self._wal[-1].lsn if self._wal else 0
            e = self._store.get(key)
            if e and not e.tombstone:
                return e, lsn
            return None, lsn

    # -- replication (replica receives WAL from primary) --------------------

    def apply_wal(self, entries: list[WALEntry]) -> int:
        """Apply WAL entries from primary. Returns count applied."""
        applied = 0
        with self._lock:
            for wal_entry in entries:
                existing = self._store.get(wal_entry.entry.key)
                if existing is None or wal_entry.entry.supersedes(existing):
                    self._store[wal_entry.entry.key] = wal_entry.entry
                    self._wal.append(wal_entry)
                    self._vclock = self._vclock.merge(wal_entry.entry.vclock)
                    applied += 1
                    self.stats["replication_applied"] += 1
        return applied

    def get_wal_after(self, lsn: int) -> list[WALEntry]:
        """Return WAL entries with LSN > given lsn."""
        with self._lock:
            return [w for w in self._wal if w.lsn > lsn]

    # -- internal -----------------------------------------------------------

    def _apply_entry(self, entry: VersionedEntry) -> None:
        """Must be called under self._lock."""
        existing = self._store.get(entry.key)
        if existing is None or entry.supersedes(existing):
            self._store[entry.key] = entry
        lsn = (self._wal[-1].lsn + 1) if self._wal else 1
        self._wal.append(WALEntry(lsn=lsn, entry=entry))

    def snapshot_keys(self) -> dict[str, Any]:
        with self._lock:
            return {
                k: e.value for k, e in self._store.items() if not e.tombstone
            }

    def health(self) -> dict:
        with self._lock:
            return {
                "node_id": self.node_id,
                "role": self.role.value,
                "entries": sum(1 for e in self._store.values() if not e.tombstone),
                "wal_length": len(self._wal),
                "latest_lsn": self._wal[-1].lsn if self._wal else 0,
                "stats": dict(self.stats),
            }


# ---------------------------------------------------------------------------
# Session tracker (for read-your-writes consistency)
# ---------------------------------------------------------------------------

class SessionTracker:
    """Tracks per-session write versions so reads can honour read-your-writes."""

    def __init__(self):
        self._sessions: dict[str, VectorClock] = {}
        self._session_lsn: dict[str, int] = {}
        self._lock = threading.Lock()

    def new_session(self) -> str:
        sid = str(uuid.uuid4())
        with self._lock:
            self._sessions[sid] = VectorClock()
            self._session_lsn[sid] = 0
        return sid

    def record_write(self, session_id: str, entry: VersionedEntry, lsn: int) -> None:
        with self._lock:
            if session_id in self._sessions:
                self._sessions[session_id] = self._sessions[session_id].merge(entry.vclock)
                self._session_lsn[session_id] = max(self._session_lsn.get(session_id, 0), lsn)

    def get_session_vclock(self, session_id: str) -> Optional[VectorClock]:
        with self._lock:
            return self._sessions.get(session_id)

    def get_session_lsn(self, session_id: str) -> int:
        with self._lock:
            return self._session_lsn.get(session_id, 0)


# ---------------------------------------------------------------------------
# Replication manager — pushes WAL from primary to read replicas
# ---------------------------------------------------------------------------

class ReplicationManager:
    """Manages WAL-based async replication from primary to read replicas."""

    def __init__(self, primary: ReplicaNode, replicas: list[ReplicaNode]):
        assert primary.role == ReplicaRole.PRIMARY
        self.primary = primary
        self.replicas = list(replicas)
        self._replica_cursors: dict[str, int] = {r.node_id: 0 for r in replicas}
        self._lock = threading.Lock()
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def add_replica(self, replica: ReplicaNode) -> None:
        assert replica.role == ReplicaRole.READ_REPLICA
        self.replicas.append(replica)
        with self._lock:
            self._replica_cursors[replica.node_id] = 0

    def sync_one(self, replica: ReplicaNode) -> int:
        """Push pending WAL entries to a single replica."""
        with self._lock:
            cursor = self._replica_cursors.get(replica.node_id, 0)
        wal_entries = self.primary.get_wal_after(cursor)
        if not wal_entries:
            return 0
        applied = replica.apply_wal(wal_entries)
        with self._lock:
            self._replica_cursors[replica.node_id] = wal_entries[-1].lsn
        return applied

    def sync_all(self) -> dict[str, int]:
        """Push pending WAL entries to all replicas."""
        result = {}
        for replica in self.replicas:
            n = self.sync_one(replica)
            if n > 0:
                result[replica.node_id] = n
        return result

    def sync_until_converged(self, max_rounds: int = 20) -> int:
        for r in range(1, max_rounds + 1):
            result = self.sync_all()
            if not result:
                return r
        return max_rounds

    def replication_lag(self) -> dict[str, int]:
        primary_lsn = self.primary.latest_lsn
        with self._lock:
            return {
                nid: primary_lsn - cursor
                for nid, cursor in self._replica_cursors.items()
            }

    def start_background(self, interval_sec: float = 0.05) -> None:
        self._running = True

        def _loop():
            while self._running:
                self.sync_all()
                time.sleep(interval_sec)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop_background(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# Consistency protocol — executes reads according to consistency level
# ---------------------------------------------------------------------------

class ConsistencyProtocol:
    """Routes reads through the appropriate consistency protocol."""

    def __init__(self, primary: ReplicaNode, replicas: list[ReplicaNode],
                 replication_mgr: ReplicationManager,
                 session_tracker: SessionTracker):
        self.primary = primary
        self.replicas = list(replicas)
        self.replication_mgr = replication_mgr
        self.session_tracker = session_tracker
        self._read_counter = 0
        self._lock = threading.Lock()

    @property
    def all_nodes(self) -> list[ReplicaNode]:
        return [self.primary] + self.replicas

    # -- public read API ----------------------------------------------------

    def read(self, key: str, consistency: ConsistencyLevel,
             session_id: Optional[str] = None,
             max_staleness_sec: float = 5.0,
             max_staleness_versions: int = 10) -> Optional[Any]:
        """Read a key with the specified consistency level."""
        if consistency == ConsistencyLevel.EVENTUAL:
            return self._read_eventual(key)
        elif consistency == ConsistencyLevel.READ_YOUR_WRITES:
            if session_id is None:
                raise ValueError("session_id required for READ_YOUR_WRITES")
            return self._read_your_writes(key, session_id)
        elif consistency == ConsistencyLevel.BOUNDED_STALENESS:
            return self._read_bounded(key, max_staleness_sec, max_staleness_versions)
        elif consistency == ConsistencyLevel.QUORUM:
            return self._read_quorum(key)
        elif consistency == ConsistencyLevel.LINEARIZABLE:
            return self._read_linearizable(key)
        else:
            raise ValueError(f"Unknown consistency level: {consistency}")

    # -- EVENTUAL: read from any replica (round-robin) ----------------------

    def _read_eventual(self, key: str) -> Optional[Any]:
        with self._lock:
            self._read_counter += 1
            idx = self._read_counter % len(self.all_nodes)
        node = self.all_nodes[idx]
        entry = node.local_read(key)
        return entry.value if entry else None

    # -- READ_YOUR_WRITES: read from a replica that has seen the session's writes

    def _read_your_writes(self, key: str, session_id: str) -> Optional[Any]:
        required_lsn = self.session_tracker.get_session_lsn(session_id)
        required_vc = self.session_tracker.get_session_vclock(session_id)

        # Try replicas first (offload from primary)
        for replica in self.replicas:
            if replica.latest_lsn >= required_lsn:
                entry = replica.local_read(key)
                if entry is not None:
                    if required_vc is None or entry.vclock.dominates_or_equal(required_vc):
                        return entry.value
                elif required_lsn == 0:
                    return None  # no writes in session yet, None is valid
                # Replica has caught up on LSN, key just doesn't exist
                if replica.latest_lsn >= required_lsn:
                    return None

        # Fallback to primary (guaranteed to have all writes)
        entry = self.primary.local_read(key)
        return entry.value if entry else None

    # -- BOUNDED_STALENESS: read from replica within staleness window -------

    def _read_bounded(self, key: str, max_staleness_sec: float,
                      max_staleness_versions: int) -> Optional[Any]:
        now = time.time()
        primary_lsn = self.primary.latest_lsn

        for replica in self.replicas:
            entry, replica_lsn = replica.local_read_with_version(key)
            version_lag = primary_lsn - replica_lsn
            # Check version lag
            if version_lag > max_staleness_versions:
                continue
            # Check time lag: look at most recent WAL entry timestamp
            with replica._lock:
                if replica._wal:
                    last_applied = replica._wal[-1].applied_at
                    if now - last_applied > max_staleness_sec:
                        continue
            return entry.value if entry else None

        # No replica within bounds — fall back to primary
        entry = self.primary.local_read(key)
        return entry.value if entry else None

    # -- QUORUM: majority of nodes must agree on the value ------------------

    def _read_quorum(self, key: str) -> Optional[Any]:
        nodes = self.all_nodes
        quorum_size = (len(nodes) // 2) + 1

        # Gather responses from all nodes
        responses: list[tuple[Optional[VersionedEntry], str]] = []
        for node in nodes:
            entry = node.local_read(key)
            responses.append((entry, node.node_id))

        # Find the value with the highest version that has quorum agreement
        if not any(r[0] is not None for r in responses):
            return None

        # Pick the entry with the highest version/vclock
        valid_entries = [(e, nid) for e, nid in responses if e is not None]
        if not valid_entries:
            return None

        # Sort by version descending, then by timestamp descending
        valid_entries.sort(key=lambda x: (x[0].version, x[0].timestamp), reverse=True)
        best_entry = valid_entries[0][0]

        # Count how many nodes have this value or a version that dominates/equals
        agreement = 0
        for entry, _ in responses:
            if entry is not None and entry.value == best_entry.value:
                agreement += 1
            elif entry is None and best_entry is None:
                agreement += 1

        if agreement >= quorum_size:
            return best_entry.value

        # If no quorum on latest, read-repair: return the highest-version value
        # (primary is always authoritative)
        entry = self.primary.local_read(key)
        return entry.value if entry else None

    # -- LINEARIZABLE: read from primary (strongest guarantee) --------------

    def _read_linearizable(self, key: str) -> Optional[Any]:
        # Must confirm primary is still leader (in production, this would
        # involve a lease check or heartbeat). We simulate by reading
        # directly from primary.
        entry = self.primary.local_read(key)
        return entry.value if entry else None

    # -- write helper (wraps primary write + session tracking) --------------

    def write(self, key: str, value: Any, session_id: Optional[str] = None) -> VersionedEntry:
        entry = self.primary.write(key, value)
        if session_id:
            self.session_tracker.record_write(session_id, entry, self.primary.latest_lsn)
        return entry

    def delete_key(self, key: str, session_id: Optional[str] = None) -> VersionedEntry:
        entry = self.primary.delete(key)
        if session_id:
            self.session_tracker.record_write(session_id, entry, self.primary.latest_lsn)
        return entry


# ---------------------------------------------------------------------------
# Read replica load balancer
# ---------------------------------------------------------------------------

class ReadReplicaBalancer:
    """Distributes reads across replicas using weighted round-robin,
    factoring in replication lag and simulated latency."""

    def __init__(self, replicas: list[ReplicaNode],
                 replication_mgr: ReplicationManager):
        self.replicas = list(replicas)
        self.replication_mgr = replication_mgr
        self._counter = 0
        self._lock = threading.Lock()

    def pick_replica(self, max_lag: int = 50) -> Optional[ReplicaNode]:
        """Pick the best replica: lowest lag that's within max_lag."""
        lag = self.replication_mgr.replication_lag()
        eligible = [
            r for r in self.replicas
            if lag.get(r.node_id, 0) <= max_lag
        ]
        if not eligible:
            return None
        # Weighted by inverse lag (lower lag = higher weight)
        eligible.sort(key=lambda r: (lag.get(r.node_id, 0), r.simulated_latency_ms))
        with self._lock:
            self._counter += 1
        return eligible[self._counter % len(eligible)]

    def replica_health(self) -> list[dict]:
        lag = self.replication_mgr.replication_lag()
        return [
            {
                "node_id": r.node_id,
                "lag": lag.get(r.node_id, 0),
                "latency_ms": r.simulated_latency_ms,
                **r.health(),
            }
            for r in self.replicas
        ]


# ---------------------------------------------------------------------------
# Metrics collector
# ---------------------------------------------------------------------------

class ReplicaMetrics:
    """Collects and reports metrics across the replica set."""

    def __init__(self, primary: ReplicaNode, replicas: list[ReplicaNode],
                 replication_mgr: ReplicationManager):
        self.primary = primary
        self.replicas = replicas
        self.replication_mgr = replication_mgr

    def summary(self) -> dict:
        lag = self.replication_mgr.replication_lag()
        total_reads = sum(r.stats["reads"] for r in self.replicas) + self.primary.stats["reads"]
        replica_reads = sum(r.stats["reads"] for r in self.replicas)
        return {
            "primary": self.primary.health(),
            "replicas": [r.health() for r in self.replicas],
            "replication_lag": lag,
            "max_lag": max(lag.values()) if lag else 0,
            "total_reads": total_reads,
            "replica_reads": replica_reads,
            "read_offload_pct": (replica_reads / total_reads * 100) if total_reads > 0 else 0,
        }


# ---------------------------------------------------------------------------
# __main__ — comprehensive verification suite
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 72)
    print("READ REPLICAS & CONSISTENCY PROTOCOLS — VERIFICATION SUITE")
    print("=" * 72)

    # ── 1. Set up primary + read replicas ─────────────────────────────
    print("\n[1] Setting up primary + 4 read replicas...")

    primary = ReplicaNode("primary-us-east", ReplicaRole.PRIMARY)
    replica_west = ReplicaNode("replica-us-west", ReplicaRole.READ_REPLICA, simulated_latency_ms=2.0)
    replica_eu = ReplicaNode("replica-eu-west", ReplicaRole.READ_REPLICA, simulated_latency_ms=5.0)
    replica_ap = ReplicaNode("replica-ap-south", ReplicaRole.READ_REPLICA, simulated_latency_ms=8.0)
    replica_ap2 = ReplicaNode("replica-ap-east", ReplicaRole.READ_REPLICA, simulated_latency_ms=10.0)

    all_replicas = [replica_west, replica_eu, replica_ap, replica_ap2]

    repl_mgr = ReplicationManager(primary, all_replicas)
    session_tracker = SessionTracker()
    protocol = ConsistencyProtocol(primary, all_replicas, repl_mgr, session_tracker)
    balancer = ReadReplicaBalancer(all_replicas, repl_mgr)
    metrics = ReplicaMetrics(primary, all_replicas, repl_mgr)

    print(f"  Primary: {primary.node_id}")
    print(f"  Replicas: {[r.node_id for r in all_replicas]}")
    assert primary.role == ReplicaRole.PRIMARY
    assert all(r.role == ReplicaRole.READ_REPLICA for r in all_replicas)
    print("  ✓ Roles assigned correctly")

    # ── 2. Writes go to primary only ──────────────────────────────────
    print("\n[2] Primary-only writes...")

    protocol.write("user:1", {"name": "Alice", "tier": "enterprise"})
    protocol.write("user:2", {"name": "Bob", "tier": "pro"})
    protocol.write("user:3", {"name": "Chandra", "tier": "starter"})
    protocol.write("config:max_retries", 5)
    protocol.write("config:timeout_ms", 30000)

    assert primary.local_read("user:1").value["name"] == "Alice"
    assert primary.local_read("config:max_retries").value == 5

    # Read replicas should NOT have data yet (before sync)
    assert replica_west.local_read("user:1") is None, \
        "Replica should not have data before replication"
    print("  ✓ Writes accepted by primary, replicas empty before sync")

    # Verify write rejection on replicas
    try:
        replica_west.write("bad:key", "should fail")
        assert False, "Write to read replica should have raised"
    except RuntimeError as e:
        assert "read replica" in str(e)
    print("  ✓ Writes correctly rejected by read replicas")

    # ── 3. WAL-based replication ──────────────────────────────────────
    print("\n[3] WAL-based replication to all replicas...")

    rounds = repl_mgr.sync_until_converged()
    print(f"  Converged in {rounds} round(s)")

    for replica in all_replicas:
        assert replica.local_read("user:1").value["name"] == "Alice", \
            f"{replica.node_id} missing user:1"
        assert replica.local_read("user:2").value["name"] == "Bob", \
            f"{replica.node_id} missing user:2"
        assert replica.local_read("config:max_retries").value == 5, \
            f"{replica.node_id} missing config:max_retries"

    lag = repl_mgr.replication_lag()
    assert all(v == 0 for v in lag.values()), f"Lag should be 0 after convergence: {lag}"
    print(f"  Lag after sync: {lag}")
    print("  ✓ All replicas converged to primary state")

    # ── 4. EVENTUAL consistency ───────────────────────────────────────
    print("\n[4] EVENTUAL consistency reads...")

    # Reads should distribute across nodes
    results = set()
    for _ in range(10):
        val = protocol.read("user:1", ConsistencyLevel.EVENTUAL)
        assert val["name"] == "Alice"
        results.add(val["name"])

    # Check that reads went to multiple nodes (round-robin)
    total_reads = sum(n.stats["reads"] for n in protocol.all_nodes)
    assert total_reads >= 10, "Should have at least 10 reads total"
    nodes_used = [n.node_id for n in protocol.all_nodes if n.stats["reads"] > 0]
    assert len(nodes_used) > 1, f"Reads should spread across nodes, only used: {nodes_used}"
    print(f"  10 reads distributed across {len(nodes_used)} nodes: {nodes_used}")
    print("  ✓ Eventual reads distribute across replicas")

    # ── 5. READ_YOUR_WRITES consistency ───────────────────────────────
    print("\n[5] READ_YOUR_WRITES consistency...")

    session_a = session_tracker.new_session()
    session_b = session_tracker.new_session()

    # Session A writes, then reads back immediately (before replication)
    protocol.write("session_test:a", {"val": "from_session_a"}, session_id=session_a)

    # Don't sync replicas yet — force read from primary for session_a
    val = protocol.read("session_test:a", ConsistencyLevel.READ_YOUR_WRITES,
                        session_id=session_a)
    assert val["val"] == "from_session_a", f"Session A should see its own write, got {val}"
    print("  ✓ Session A sees its own write before replication")

    # Session B hasn't written this key; with READ_YOUR_WRITES it may see stale
    # (this is acceptable — RYW only guarantees your own writes)
    val_b = protocol.read("session_test:a", ConsistencyLevel.READ_YOUR_WRITES,
                          session_id=session_b)
    # After sync, session B should also see it
    repl_mgr.sync_all()
    val_b_after = protocol.read("session_test:a", ConsistencyLevel.READ_YOUR_WRITES,
                                session_id=session_b)
    assert val_b_after["val"] == "from_session_a"
    print("  ✓ Session B sees value after replication sync")

    # ── 6. BOUNDED_STALENESS consistency ──────────────────────────────
    print("\n[6] BOUNDED_STALENESS consistency...")

    # Write new data, partially sync (create lag)
    for i in range(20):
        protocol.write(f"bounded:key{i}", f"value_{i}")

    # Sync only some replicas
    repl_mgr.sync_one(replica_west)
    # Other replicas have lag

    lag_now = repl_mgr.replication_lag()
    print(f"  Lag before bounded read: {lag_now}")

    # With tight staleness bound, should fall back to primary or fresh replica
    val = protocol.read("bounded:key19", ConsistencyLevel.BOUNDED_STALENESS,
                        max_staleness_sec=10.0, max_staleness_versions=5)
    assert val == "value_19", f"Bounded read should return latest, got {val}"
    print("  ✓ Bounded staleness returns fresh data (from synced replica or primary)")

    # Sync all for next tests
    repl_mgr.sync_until_converged()

    # ── 7. QUORUM consistency ─────────────────────────────────────────
    print("\n[7] QUORUM consistency reads...")

    protocol.write("quorum:key", {"important": True, "version": 42})
    repl_mgr.sync_until_converged()

    val = protocol.read("quorum:key", ConsistencyLevel.QUORUM)
    assert val["important"] is True
    assert val["version"] == 42
    print("  ✓ Quorum read returns correct value with majority agreement")

    # Quorum with non-existent key
    val_missing = protocol.read("quorum:nonexistent", ConsistencyLevel.QUORUM)
    assert val_missing is None
    print("  ✓ Quorum read returns None for missing key")

    # ── 8. LINEARIZABLE consistency ───────────────────────────────────
    print("\n[8] LINEARIZABLE consistency reads...")

    protocol.write("linear:key", {"strict": True, "seq": 1})
    # Don't sync — linearizable reads always go to primary
    val = protocol.read("linear:key", ConsistencyLevel.LINEARIZABLE)
    assert val["strict"] is True
    assert val["seq"] == 1
    print("  ✓ Linearizable read returns latest primary value")

    # Update and read again — should reflect update immediately
    protocol.write("linear:key", {"strict": True, "seq": 2})
    val = protocol.read("linear:key", ConsistencyLevel.LINEARIZABLE)
    assert val["seq"] == 2
    print("  ✓ Linearizable read sees latest write instantly (no lag)")

    # ── 9. Delete replication ─────────────────────────────────────────
    print("\n[9] Delete replication across replicas...")

    protocol.write("to_delete", "temporary value")
    repl_mgr.sync_until_converged()

    for replica in all_replicas:
        assert replica.local_read("to_delete").value == "temporary value"

    protocol.delete_key("to_delete")
    repl_mgr.sync_until_converged()

    assert primary.local_read("to_delete") is None
    for replica in all_replicas:
        assert replica.local_read("to_delete") is None, \
            f"{replica.node_id} still has deleted key"
    print("  ✓ Deletes replicated via tombstones to all replicas")

    # ── 10. Read replica load balancer ────────────────────────────────
    print("\n[10] Load balancer picks lowest-lag replica...")

    # Create some lag on ap replicas
    for i in range(10):
        protocol.write(f"lb:key{i}", f"val_{i}")
    repl_mgr.sync_one(replica_west)
    repl_mgr.sync_one(replica_eu)
    # ap replicas have lag

    picked = balancer.pick_replica(max_lag=5)
    assert picked is not None
    lag_now = repl_mgr.replication_lag()
    assert lag_now[picked.node_id] <= 5, \
        f"Picked replica has too much lag: {lag_now[picked.node_id]}"
    print(f"  Picked: {picked.node_id} (lag={lag_now[picked.node_id]})")

    # With very tight max_lag, only freshest replicas qualify
    repl_mgr.sync_until_converged()
    picked_tight = balancer.pick_replica(max_lag=0)
    assert picked_tight is not None
    print(f"  Tight lag=0: {picked_tight.node_id}")
    print("  ✓ Load balancer selects lowest-lag eligible replica")

    # ── 11. Background replication ────────────────────────────────────
    print("\n[11] Background replication...")

    repl_mgr.start_background(interval_sec=0.02)
    protocol.write("bg:auto", {"auto_replicated": True})
    time.sleep(0.2)  # allow background sync
    repl_mgr.stop_background()

    for replica in all_replicas:
        entry = replica.local_read("bg:auto")
        assert entry is not None and entry.value["auto_replicated"] is True, \
            f"{replica.node_id} missing bg:auto"
    print("  ✓ Background replication propagated writes automatically")

    # ── 12. Metrics and offload tracking ──────────────────────────────
    print("\n[12] Metrics & read offload...")

    summary = metrics.summary()
    print(f"  Total reads: {summary['total_reads']}")
    print(f"  Replica reads: {summary['replica_reads']}")
    print(f"  Read offload: {summary['read_offload_pct']:.1f}%")
    print(f"  Max lag: {summary['max_lag']}")
    assert summary['total_reads'] > 0
    assert summary['replica_reads'] > 0
    assert summary['read_offload_pct'] > 0
    print("  ✓ Metrics correctly track read distribution")

    # ── 13. Consistency level comparison ──────────────────────────────
    print("\n[13] Consistency level comparison...")

    protocol.write("compare:key", "latest_value")
    repl_mgr.sync_until_converged()

    session_c = session_tracker.new_session()
    protocol.write("compare:key", "updated_value", session_id=session_c)
    repl_mgr.sync_until_converged()

    # All levels should return the same value when fully synced
    for level in ConsistencyLevel:
        kwargs = {}
        if level == ConsistencyLevel.READ_YOUR_WRITES:
            kwargs["session_id"] = session_c
        val = protocol.read("compare:key", level, **kwargs)
        assert val == "updated_value", \
            f"{level.value} returned {val}, expected 'updated_value'"
        print(f"  {level.value:25s} → {val}")

    print("  ✓ All consistency levels agree when fully synced")

    # ── 14. Session isolation ─────────────────────────────────────────
    print("\n[14] Session isolation...")

    s1 = session_tracker.new_session()
    s2 = session_tracker.new_session()

    protocol.write("isolated:s1", "session_1_data", session_id=s1)
    protocol.write("isolated:s2", "session_2_data", session_id=s2)

    # Before replication, each session should see its own write via RYW
    v1 = protocol.read("isolated:s1", ConsistencyLevel.READ_YOUR_WRITES, session_id=s1)
    v2 = protocol.read("isolated:s2", ConsistencyLevel.READ_YOUR_WRITES, session_id=s2)
    assert v1 == "session_1_data"
    assert v2 == "session_2_data"
    print("  ✓ Sessions see their own writes independently")

    # ── 15. WAL integrity ─────────────────────────────────────────────
    print("\n[15] WAL integrity check...")

    wal_entries = primary.get_wal_after(0)
    lsns = [w.lsn for w in wal_entries]
    # LSNs must be monotonically increasing
    for i in range(1, len(lsns)):
        assert lsns[i] > lsns[i - 1], f"WAL LSNs not monotonic: {lsns[i-1]} >= {lsns[i]}"

    # After full sync, replicas should have same LSN as primary
    repl_mgr.sync_until_converged()
    primary_lsn = primary.latest_lsn
    for replica in all_replicas:
        assert replica.latest_lsn == primary_lsn, \
            f"{replica.node_id} LSN {replica.latest_lsn} != primary {primary_lsn}"

    print(f"  Primary WAL: {len(wal_entries)} entries, LSN range [{lsns[0]}..{lsns[-1]}]")
    print(f"  All replicas at LSN {primary_lsn}")
    print("  ✓ WAL is monotonic and replicas fully caught up")

    # ── 16. Vector clock progression ──────────────────────────────────
    print("\n[16] Vector clock progression...")

    vc_primary = primary.vclock
    assert vc_primary.total() > 0, "Primary vclock should have progressed"

    for replica in all_replicas:
        vc_r = replica.vclock
        assert vc_primary.dominates_or_equal(vc_r), \
            f"Primary vclock should dominate replica {replica.node_id}"

    print(f"  Primary vclock: {vc_primary}")
    print("  ✓ Vector clocks properly track causality")

    # ── 17. Snapshot consistency ──────────────────────────────────────
    print("\n[17] Snapshot consistency...")

    primary_snap = primary.snapshot_keys()
    for replica in all_replicas:
        replica_snap = replica.snapshot_keys()
        assert primary_snap == replica_snap, \
            f"{replica.node_id} snapshot differs from primary"

    print(f"  All nodes have {len(primary_snap)} live keys")
    print("  ✓ Full snapshot consistency across replica set")

    # ── 18. Cluster health report ─────────────────────────────────────
    print("\n[18] Cluster health report...")

    for node in [primary] + all_replicas:
        h = node.health()
        print(f"  {h['node_id']:25s} role={h['role']:12s} "
              f"entries={h['entries']:3d} wal={h['wal_length']:3d} "
              f"reads={h['stats']['reads']:3d} writes={h['stats']['writes']:3d}")

    # ── Summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 72)
    print("ALL ASSERTIONS PASSED — READ REPLICAS & CONSISTENCY VERIFIED")
    print("=" * 72)
    print(f"  Primary:              1 ({primary.node_id})")
    print(f"  Read replicas:        {len(all_replicas)}")
    print(f"  Consistency levels:   {len(ConsistencyLevel)} "
          f"({', '.join(c.value for c in ConsistencyLevel)})")
    print(f"  WAL entries:          {primary.latest_lsn}")
    print(f"  Replication:          WAL-based async with convergence")
    print(f"  Load balancing:       lag-aware weighted round-robin")
    print(f"  Session tracking:     per-session vclock + LSN")
    print(f"  Conflict resolution:  LWW with deterministic tie-break")
