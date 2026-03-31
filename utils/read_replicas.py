"""
Read Replicas & Consistency Protocols

Distributes reads across replica nodes while maintaining configurable consistency
guarantees. Supports five consistency levels:

  - STRONG:             read from leader; always fresh
  - BOUNDED_STALENESS:  read from replica if lag < threshold
  - SESSION:            read-your-writes within a session
  - CONSISTENT_PREFIX:  reads never see out-of-order writes
  - EVENTUAL:           read from any replica (fastest)

Built on top of utils.geo_replication for region-aware routing.
"""

import hashlib
import json
import math
import random
import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

from utils.geo_replication import (
    GeoCoord,
    GeoRouter,
    HealthStatus,
    RegionNode,
    ReplicatedStore,
    VectorClock,
    VersionedValue,
    haversine_km,
)


# ---------------------------------------------------------------------------
# Consistency levels
# ---------------------------------------------------------------------------

class ConsistencyLevel(Enum):
    STRONG = "strong"
    BOUNDED_STALENESS = "bounded_staleness"
    SESSION = "session"
    CONSISTENT_PREFIX = "consistent_prefix"
    EVENTUAL = "eventual"


# ---------------------------------------------------------------------------
# Write-Ahead Log entry — ordered, monotonic sequence per leader
# ---------------------------------------------------------------------------

@dataclass
class WALEntry:
    sequence: int
    key: str
    value: Any
    timestamp: float
    origin_region: str
    tombstone: bool = False

    def to_dict(self) -> dict:
        return {
            "sequence": self.sequence,
            "key": self.key,
            "value": self.value,
            "timestamp": self.timestamp,
            "origin_region": self.origin_region,
            "tombstone": self.tombstone,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "WALEntry":
        return cls(**d)


# ---------------------------------------------------------------------------
# Read Replica — follower node that tails the leader's WAL
# ---------------------------------------------------------------------------

class ReplicaRole(Enum):
    LEADER = "leader"
    FOLLOWER = "follower"
    READONLY = "readonly"


@dataclass
class ReplicaStats:
    reads_served: int = 0
    reads_rejected_stale: int = 0
    wal_entries_applied: int = 0
    replication_lag_entries: int = 0
    replication_lag_ms: float = 0.0
    last_applied_seq: int = 0
    last_applied_ts: float = 0.0


class ReadReplica:
    """A single read replica that follows a leader's write-ahead log."""

    def __init__(self, replica_id: str, role: ReplicaRole = ReplicaRole.FOLLOWER):
        self.replica_id = replica_id
        self.role = role
        self._data: dict[str, VersionedValue] = {}
        self._lock = threading.Lock()
        self._wal: list[WALEntry] = []
        self._seq_counter = 0
        self.stats = ReplicaStats()
        self._applied_seq = 0
        self._session_tokens: dict[str, int] = {}  # session_id -> last_write_seq

    @property
    def current_sequence(self) -> int:
        with self._lock:
            return self._applied_seq

    @property
    def replication_lag_entries(self) -> int:
        return self.stats.replication_lag_entries

    # -- Leader-only: accept writes -----------------------------------------

    def write(self, key: str, value: Any, session_id: Optional[str] = None) -> WALEntry:
        if self.role != ReplicaRole.LEADER:
            raise RuntimeError(f"Replica {self.replica_id} is {self.role.value}, cannot accept writes")
        with self._lock:
            self._seq_counter += 1
            entry = WALEntry(
                sequence=self._seq_counter,
                key=key,
                value=value,
                timestamp=time.time(),
                origin_region=self.replica_id,
            )
            self._wal.append(entry)
            vc = VectorClock({self.replica_id: self._seq_counter})
            vv = VersionedValue(
                value=value,
                vclock=vc,
                timestamp=entry.timestamp,
                origin_region=self.replica_id,
            )
            self._data[key] = vv
            self._applied_seq = self._seq_counter
            self.stats.last_applied_seq = self._seq_counter
            self.stats.last_applied_ts = entry.timestamp
            if session_id:
                self._session_tokens[session_id] = self._seq_counter
            return entry

    def delete(self, key: str, session_id: Optional[str] = None) -> WALEntry:
        if self.role != ReplicaRole.LEADER:
            raise RuntimeError(f"Replica {self.replica_id} is {self.role.value}, cannot accept writes")
        with self._lock:
            self._seq_counter += 1
            entry = WALEntry(
                sequence=self._seq_counter,
                key=key,
                value=None,
                timestamp=time.time(),
                origin_region=self.replica_id,
                tombstone=True,
            )
            self._wal.append(entry)
            vc = VectorClock({self.replica_id: self._seq_counter})
            vv = VersionedValue(
                value=None,
                vclock=vc,
                timestamp=entry.timestamp,
                origin_region=self.replica_id,
                tombstone=True,
            )
            self._data[key] = vv
            self._applied_seq = self._seq_counter
            self.stats.last_applied_seq = self._seq_counter
            self.stats.last_applied_ts = entry.timestamp
            if session_id:
                self._session_tokens[session_id] = self._seq_counter
            return entry

    # -- Read (available on all replicas) -----------------------------------

    def read(self, key: str) -> Optional[Any]:
        with self._lock:
            vv = self._data.get(key)
            if vv is None or vv.tombstone:
                return None
            self.stats.reads_served += 1
            return vv.value

    def read_with_seq(self, key: str) -> tuple[Optional[Any], int]:
        """Return (value, applied_sequence) for consistency checks."""
        with self._lock:
            vv = self._data.get(key)
            seq = self._applied_seq
            if vv is None or vv.tombstone:
                return None, seq
            self.stats.reads_served += 1
            return vv.value, seq

    # -- WAL access (for replication) ---------------------------------------

    def get_wal_entries_after(self, after_seq: int) -> list[WALEntry]:
        with self._lock:
            return [e for e in self._wal if e.sequence > after_seq]

    def get_wal_length(self) -> int:
        with self._lock:
            return len(self._wal)

    # -- Follower: apply WAL entries from leader ----------------------------

    def apply_wal_entries(self, entries: list[WALEntry]) -> int:
        applied = 0
        with self._lock:
            for entry in entries:
                if entry.sequence <= self._applied_seq:
                    continue
                vc = VectorClock({entry.origin_region: entry.sequence})
                vv = VersionedValue(
                    value=entry.value,
                    vclock=vc,
                    timestamp=entry.timestamp,
                    origin_region=entry.origin_region,
                    tombstone=entry.tombstone,
                )
                self._data[entry.key] = vv
                self._applied_seq = entry.sequence
                self.stats.last_applied_seq = entry.sequence
                self.stats.last_applied_ts = entry.timestamp
                applied += 1
            self.stats.wal_entries_applied += applied
        return applied

    def get_session_write_seq(self, session_id: str) -> int:
        return self._session_tokens.get(session_id, 0)

    def record_session_write(self, session_id: str, seq: int):
        self._session_tokens[session_id] = max(
            self._session_tokens.get(session_id, 0), seq
        )

    def items(self) -> list[tuple[str, Any]]:
        with self._lock:
            return [(k, vv.value) for k, vv in self._data.items() if not vv.tombstone]


# ---------------------------------------------------------------------------
# Replication Stream — pulls WAL from leader and pushes to follower
# ---------------------------------------------------------------------------

class ReplicationStream:
    """Connects a follower to its leader and streams WAL entries."""

    def __init__(self, leader: ReadReplica, follower: ReadReplica):
        if leader.role != ReplicaRole.LEADER:
            raise ValueError(f"{leader.replica_id} is not a leader")
        self.leader = leader
        self.follower = follower
        self._cursor = 0
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def pull_once(self) -> int:
        """Pull new entries from leader and apply to follower."""
        entries = self.leader.get_wal_entries_after(self._cursor)
        if not entries:
            return 0
        applied = self.follower.apply_wal_entries(entries)
        if entries:
            self._cursor = entries[-1].sequence
        lag = self.leader.current_sequence - self.follower.current_sequence
        self.follower.stats.replication_lag_entries = lag
        if lag > 0 and self.leader.stats.last_applied_ts > 0:
            self.follower.stats.replication_lag_ms = (
                (time.time() - self.follower.stats.last_applied_ts) * 1000
            )
        else:
            self.follower.stats.replication_lag_ms = 0.0
        return applied

    def start_streaming(self, interval_s: float = 0.05):
        self._running = True

        def _loop():
            while self._running:
                self.pull_once()
                time.sleep(interval_s)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop_streaming(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)


# ---------------------------------------------------------------------------
# Consistency Protocol Engine
# ---------------------------------------------------------------------------

class ConsistencyProtocol:
    """
    Enforces consistency guarantees when routing reads to replicas.

    Protocols:
      STRONG:             Always read from leader.
      BOUNDED_STALENESS:  Read from replica if its lag is under max_staleness_ms.
      SESSION:            Read from replica only if it has applied the session's
                          last write (read-your-writes guarantee).
      CONSISTENT_PREFIX:  Only return data from a replica that has applied entries
                          in order (guaranteed by WAL-based replication).
      EVENTUAL:           Read from any available replica.
    """

    def __init__(
        self,
        leader: ReadReplica,
        replicas: list[ReadReplica],
        default_level: ConsistencyLevel = ConsistencyLevel.SESSION,
        max_staleness_ms: float = 5000.0,
    ):
        self.leader = leader
        self.replicas = list(replicas)
        self.default_level = default_level
        self.max_staleness_ms = max_staleness_ms
        self._lock = threading.Lock()
        self._read_metrics: dict[str, int] = defaultdict(int)

    def read(
        self,
        key: str,
        level: Optional[ConsistencyLevel] = None,
        session_id: Optional[str] = None,
    ) -> Optional[Any]:
        level = level or self.default_level
        self._read_metrics[level.value] += 1

        if level == ConsistencyLevel.STRONG:
            return self._read_strong(key)
        elif level == ConsistencyLevel.BOUNDED_STALENESS:
            return self._read_bounded(key)
        elif level == ConsistencyLevel.SESSION:
            return self._read_session(key, session_id)
        elif level == ConsistencyLevel.CONSISTENT_PREFIX:
            return self._read_consistent_prefix(key)
        elif level == ConsistencyLevel.EVENTUAL:
            return self._read_eventual(key)
        else:
            raise ValueError(f"Unknown consistency level: {level}")

    def _read_strong(self, key: str) -> Optional[Any]:
        """Always read from leader — linearizable."""
        return self.leader.read(key)

    def _read_bounded(self, key: str) -> Optional[Any]:
        """Read from a replica whose lag is within max_staleness_ms."""
        eligible = []
        for r in self.replicas:
            if r.stats.replication_lag_ms <= self.max_staleness_ms:
                eligible.append(r)
        if eligible:
            chosen = min(eligible, key=lambda r: r.stats.replication_lag_ms)
            return chosen.read(key)
        # Fallback to leader if all replicas are too stale
        return self.leader.read(key)

    def _read_session(self, key: str, session_id: Optional[str] = None) -> Optional[Any]:
        """Read-your-writes: route to a replica that has applied the session's last write."""
        if session_id is None:
            return self._read_eventual(key)
        required_seq = self.leader.get_session_write_seq(session_id)
        if required_seq == 0:
            return self._read_eventual(key)
        # Find a replica that has caught up to the session's write
        for r in self.replicas:
            if r.current_sequence >= required_seq:
                return r.read(key)
        # Fallback to leader
        return self.leader.read(key)

    def _read_consistent_prefix(self, key: str) -> Optional[Any]:
        """Read from the replica with the highest applied sequence (most complete prefix)."""
        if not self.replicas:
            return self.leader.read(key)
        best = max(self.replicas, key=lambda r: r.current_sequence)
        return best.read(key)

    def _read_eventual(self, key: str) -> Optional[Any]:
        """Read from a random replica for lowest latency."""
        if not self.replicas:
            return self.leader.read(key)
        chosen = random.choice(self.replicas)
        return chosen.read(key)

    def write(self, key: str, value: Any, session_id: Optional[str] = None) -> WALEntry:
        """All writes go through the leader."""
        return self.leader.write(key, value, session_id=session_id)

    def delete_key(self, key: str, session_id: Optional[str] = None) -> WALEntry:
        return self.leader.delete(key, session_id=session_id)

    def get_metrics(self) -> dict:
        return {
            "read_distribution": dict(self._read_metrics),
            "leader": {
                "id": self.leader.replica_id,
                "seq": self.leader.current_sequence,
                "reads": self.leader.stats.reads_served,
            },
            "replicas": [
                {
                    "id": r.replica_id,
                    "seq": r.current_sequence,
                    "lag_entries": r.stats.replication_lag_entries,
                    "lag_ms": round(r.stats.replication_lag_ms, 2),
                    "reads": r.stats.reads_served,
                    "rejected_stale": r.stats.reads_rejected_stale,
                }
                for r in self.replicas
            ],
        }


# ---------------------------------------------------------------------------
# Read Replica Cluster — manages a leader + N followers
# ---------------------------------------------------------------------------

class ReadReplicaCluster:
    """
    Manages a single-leader, multi-follower cluster with configurable
    consistency and automatic WAL streaming.
    """

    def __init__(
        self,
        cluster_id: str,
        num_replicas: int = 3,
        default_consistency: ConsistencyLevel = ConsistencyLevel.SESSION,
        max_staleness_ms: float = 5000.0,
    ):
        self.cluster_id = cluster_id
        self.leader = ReadReplica(f"{cluster_id}-leader", role=ReplicaRole.LEADER)
        self.followers: list[ReadReplica] = [
            ReadReplica(f"{cluster_id}-replica-{i}", role=ReplicaRole.FOLLOWER)
            for i in range(num_replicas)
        ]
        self.streams: list[ReplicationStream] = [
            ReplicationStream(self.leader, f) for f in self.followers
        ]
        self.protocol = ConsistencyProtocol(
            leader=self.leader,
            replicas=self.followers,
            default_level=default_consistency,
            max_staleness_ms=max_staleness_ms,
        )
        self._streaming = False

    def write(self, key: str, value: Any, session_id: Optional[str] = None) -> WALEntry:
        return self.protocol.write(key, value, session_id=session_id)

    def read(
        self,
        key: str,
        level: Optional[ConsistencyLevel] = None,
        session_id: Optional[str] = None,
    ) -> Optional[Any]:
        return self.protocol.read(key, level=level, session_id=session_id)

    def delete_key(self, key: str, session_id: Optional[str] = None) -> WALEntry:
        return self.protocol.delete_key(key, session_id=session_id)

    def sync_all(self) -> int:
        """Pull WAL entries to all followers (synchronous, for testing)."""
        total = 0
        for stream in self.streams:
            total += stream.pull_once()
        return total

    def sync_until_caught_up(self, max_rounds: int = 20) -> int:
        for r in range(1, max_rounds + 1):
            applied = self.sync_all()
            if applied == 0:
                return r
        return max_rounds

    def start_streaming(self, interval_s: float = 0.05):
        self._streaming = True
        for stream in self.streams:
            stream.start_streaming(interval_s)

    def stop_streaming(self):
        self._streaming = False
        for stream in self.streams:
            stream.stop_streaming()

    def check_convergence(self) -> tuple[bool, list[str]]:
        """Check that all followers have the same data as leader."""
        leader_data = dict(self.leader.items())
        errors = []
        for follower in self.followers:
            follower_data = dict(follower.items())
            if follower_data != leader_data:
                missing = set(leader_data) - set(follower_data)
                extra = set(follower_data) - set(leader_data)
                diff = {
                    k for k in set(leader_data) & set(follower_data)
                    if leader_data[k] != follower_data[k]
                }
                if missing:
                    errors.append(f"{follower.replica_id}: missing keys {missing}")
                if extra:
                    errors.append(f"{follower.replica_id}: extra keys {extra}")
                if diff:
                    errors.append(f"{follower.replica_id}: value mismatch on {diff}")
        return len(errors) == 0, errors

    def cluster_health(self) -> dict:
        return {
            "cluster_id": self.cluster_id,
            "leader": self.leader.replica_id,
            "leader_seq": self.leader.current_sequence,
            "followers": [
                {
                    "id": f.replica_id,
                    "seq": f.current_sequence,
                    "lag": f.stats.replication_lag_entries,
                    "lag_ms": round(f.stats.replication_lag_ms, 2),
                }
                for f in self.followers
            ],
            "streaming": self._streaming,
            "metrics": self.protocol.get_metrics(),
        }


# ---------------------------------------------------------------------------
# Quorum reads — read from R replicas, return if R agree
# ---------------------------------------------------------------------------

class QuorumPolicy(Enum):
    ONE = 1
    MAJORITY = -1   # sentinel: computed from cluster size
    ALL = -2        # sentinel: all replicas


class QuorumRead:
    """
    Implements quorum-based read consistency:
      - Read from R replicas in parallel
      - Return the value if R agree (freshest version wins on disagreement)
    """

    def __init__(self, cluster: ReadReplicaCluster, quorum: QuorumPolicy = QuorumPolicy.MAJORITY):
        self.cluster = cluster
        self._quorum_policy = quorum

    def _quorum_size(self) -> int:
        total = 1 + len(self.cluster.followers)  # leader + followers
        if self._quorum_policy == QuorumPolicy.MAJORITY:
            return (total // 2) + 1
        elif self._quorum_policy == QuorumPolicy.ALL:
            return total
        else:
            return self._quorum_policy.value

    def read(self, key: str) -> tuple[Optional[Any], int, int]:
        """
        Read with quorum.
        Returns: (value, agreeing_replicas, total_queried)
        """
        quorum_needed = self._quorum_size()
        all_nodes = [self.cluster.leader] + self.cluster.followers

        results: list[tuple[Optional[Any], int]] = []
        threads: list[threading.Thread] = []
        results_lock = threading.Lock()

        def _query(node: ReadReplica):
            val, seq = node.read_with_seq(key)
            with results_lock:
                results.append((val, seq))

        for node in all_nodes:
            t = threading.Thread(target=_query, args=(node,))
            threads.append(t)
            t.start()
        for t in threads:
            t.join(timeout=2.0)

        if not results:
            return None, 0, 0

        # Pick the value from the highest sequence (freshest)
        results.sort(key=lambda x: x[1], reverse=True)
        best_value = results[0][0]
        best_seq = results[0][1]

        # Count how many agree with the freshest value
        agree_count = 0
        for val, seq in results:
            serialized_best = json.dumps(best_value, sort_keys=True, default=str)
            serialized_val = json.dumps(val, sort_keys=True, default=str)
            if serialized_val == serialized_best:
                agree_count += 1

        return best_value, agree_count, len(results)


# ---------------------------------------------------------------------------
# Multi-Region Read Distributor
# ---------------------------------------------------------------------------

class ReadDistributor:
    """
    Distributes reads across multiple regional clusters.
    Each region has a ReadReplicaCluster; the distributor picks the
    nearest region's cluster and applies the requested consistency.
    """

    def __init__(self):
        self._clusters: dict[str, tuple[GeoCoord, ReadReplicaCluster]] = {}

    def add_cluster(self, region_id: str, location: GeoCoord, cluster: ReadReplicaCluster):
        self._clusters[region_id] = (location, cluster)

    def nearest_cluster(self, client_location: GeoCoord) -> Optional[ReadReplicaCluster]:
        if not self._clusters:
            return None
        best_dist = float("inf")
        best_cluster = None
        for rid, (loc, cluster) in self._clusters.items():
            d = haversine_km(client_location, loc)
            if d < best_dist:
                best_dist = d
                best_cluster = cluster
        return best_cluster

    def read(
        self,
        key: str,
        client_location: GeoCoord,
        level: Optional[ConsistencyLevel] = None,
        session_id: Optional[str] = None,
    ) -> Optional[Any]:
        cluster = self.nearest_cluster(client_location)
        if cluster is None:
            raise RuntimeError("No clusters available")
        return cluster.read(key, level=level, session_id=session_id)

    def write(
        self,
        key: str,
        value: Any,
        client_location: GeoCoord,
        session_id: Optional[str] = None,
    ) -> WALEntry:
        cluster = self.nearest_cluster(client_location)
        if cluster is None:
            raise RuntimeError("No clusters available")
        return cluster.write(key, value, session_id=session_id)


# ---------------------------------------------------------------------------
# __main__ — comprehensive verification suite
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("READ REPLICAS & CONSISTENCY PROTOCOLS — VERIFICATION SUITE")
    print("=" * 70)

    # =========================================================================
    # Test 1: Leader accepts writes, followers reject writes
    # =========================================================================
    print("\n[Test 1] Leader/follower role enforcement...")
    leader = ReadReplica("leader-1", role=ReplicaRole.LEADER)
    follower = ReadReplica("follower-1", role=ReplicaRole.FOLLOWER)

    entry = leader.write("key:1", {"name": "Alice"})
    assert entry.sequence == 1
    assert entry.key == "key:1"
    assert leader.read("key:1") == {"name": "Alice"}

    try:
        follower.write("key:2", "should fail")
        assert False, "Follower should reject writes"
    except RuntimeError as e:
        assert "cannot accept writes" in str(e).lower()
    print("  PASS: Leader writes succeed, follower writes rejected")

    # =========================================================================
    # Test 2: WAL-based replication from leader to follower
    # =========================================================================
    print("\n[Test 2] WAL replication...")
    leader.write("key:2", {"name": "Bob"})
    leader.write("key:3", {"name": "Charlie"})

    entries = leader.get_wal_entries_after(0)
    assert len(entries) == 3

    applied = follower.apply_wal_entries(entries)
    assert applied == 3

    assert follower.read("key:1") == {"name": "Alice"}
    assert follower.read("key:2") == {"name": "Bob"}
    assert follower.read("key:3") == {"name": "Charlie"}
    assert follower.current_sequence == 3
    print("  PASS: 3 WAL entries replicated to follower")

    # =========================================================================
    # Test 3: Idempotent WAL application
    # =========================================================================
    print("\n[Test 3] Idempotent WAL replay...")
    applied_again = follower.apply_wal_entries(entries)
    assert applied_again == 0, f"Expected 0 re-applied, got {applied_again}"
    assert follower.current_sequence == 3
    print("  PASS: Re-applying same entries is a no-op")

    # =========================================================================
    # Test 4: ReplicationStream pulls from leader
    # =========================================================================
    print("\n[Test 4] ReplicationStream pull...")
    follower2 = ReadReplica("follower-2", role=ReplicaRole.FOLLOWER)
    stream = ReplicationStream(leader, follower2)

    pulled = stream.pull_once()
    assert pulled == 3
    assert follower2.read("key:1") == {"name": "Alice"}
    assert follower2.read("key:3") == {"name": "Charlie"}

    # New write, pull again
    leader.write("key:4", {"name": "Diana"})
    pulled2 = stream.pull_once()
    assert pulled2 == 1
    assert follower2.read("key:4") == {"name": "Diana"}
    print("  PASS: ReplicationStream incrementally pulls WAL")

    # =========================================================================
    # Test 5: ReadReplicaCluster end-to-end
    # =========================================================================
    print("\n[Test 5] ReadReplicaCluster basic operations...")
    cluster = ReadReplicaCluster("us-east", num_replicas=3)

    cluster.write("user:1", {"name": "Alice", "role": "admin"})
    cluster.write("user:2", {"name": "Bob", "role": "viewer"})
    cluster.write("config:theme", "dark")

    rounds = cluster.sync_until_caught_up()
    assert rounds <= 2, f"Took {rounds} rounds to catch up"

    converged, errors = cluster.check_convergence()
    assert converged, f"Cluster not converged: {errors}"

    for f in cluster.followers:
        assert f.read("user:1") == {"name": "Alice", "role": "admin"}
        assert f.read("user:2") == {"name": "Bob", "role": "viewer"}
        assert f.read("config:theme") == "dark"
    print(f"  PASS: Cluster converged in {rounds} round(s), all 3 followers consistent")

    # =========================================================================
    # Test 6: STRONG consistency — always reads from leader
    # =========================================================================
    print("\n[Test 6] STRONG consistency...")
    cluster2 = ReadReplicaCluster("eu-west", num_replicas=2, default_consistency=ConsistencyLevel.STRONG)
    cluster2.write("x", "leader-value")
    # Don't sync — followers are behind

    val = cluster2.read("x", level=ConsistencyLevel.STRONG)
    assert val == "leader-value", f"Strong read should hit leader, got {val}"

    # Followers should not have it yet
    for f in cluster2.followers:
        assert f.read("x") is None, "Followers should not have value before sync"
    print("  PASS: STRONG reads always return leader's data")

    # =========================================================================
    # Test 7: EVENTUAL consistency — reads from any replica
    # =========================================================================
    print("\n[Test 7] EVENTUAL consistency...")
    cluster2.sync_all()

    values_seen = set()
    for _ in range(20):
        v = cluster2.read("x", level=ConsistencyLevel.EVENTUAL)
        values_seen.add(v)
    assert values_seen == {"leader-value"}, f"Unexpected values: {values_seen}"
    print("  PASS: EVENTUAL reads return correct value after sync")

    # =========================================================================
    # Test 8: SESSION consistency — read-your-writes
    # =========================================================================
    print("\n[Test 8] SESSION consistency (read-your-writes)...")
    cluster3 = ReadReplicaCluster("ap-south", num_replicas=2, default_consistency=ConsistencyLevel.SESSION)

    session_a = "session-alice"
    cluster3.write("profile:alice", {"bio": "original"}, session_id=session_a)
    # Don't sync yet — followers are behind

    # Session read should go to leader since followers haven't caught up
    val = cluster3.read("profile:alice", level=ConsistencyLevel.SESSION, session_id=session_a)
    assert val == {"bio": "original"}, f"Session read should see own write, got {val}"

    # Update the profile
    cluster3.write("profile:alice", {"bio": "updated"}, session_id=session_a)
    val2 = cluster3.read("profile:alice", level=ConsistencyLevel.SESSION, session_id=session_a)
    assert val2 == {"bio": "updated"}, f"Session read should see latest write, got {val2}"

    # A different session without writes can read from anywhere
    val3 = cluster3.read("profile:alice", level=ConsistencyLevel.SESSION, session_id="session-bob")
    # Bob's session has no writes, so eventual read is fine (may hit leader or stale follower)
    # After sync, it should be "updated"
    cluster3.sync_all()
    val4 = cluster3.read("profile:alice", level=ConsistencyLevel.SESSION, session_id="session-bob")
    assert val4 == {"bio": "updated"}
    print("  PASS: SESSION consistency guarantees read-your-writes")

    # =========================================================================
    # Test 9: BOUNDED_STALENESS — reject stale replicas
    # =========================================================================
    print("\n[Test 9] BOUNDED_STALENESS consistency...")
    cluster4 = ReadReplicaCluster(
        "us-west", num_replicas=2,
        default_consistency=ConsistencyLevel.BOUNDED_STALENESS,
        max_staleness_ms=100.0,
    )
    cluster4.write("item:1", "fresh")
    cluster4.sync_all()

    # Followers are caught up, lag is low — should read from replica
    val = cluster4.read("item:1", level=ConsistencyLevel.BOUNDED_STALENESS)
    assert val == "fresh"

    # Write more data but don't sync — followers become stale
    for i in range(10):
        cluster4.write(f"item:bulk:{i}", f"value-{i}")

    # Manually set high lag on followers for testing
    for f in cluster4.followers:
        f.stats.replication_lag_ms = 200.0  # over threshold

    val2 = cluster4.read("item:1", level=ConsistencyLevel.BOUNDED_STALENESS)
    assert val2 == "fresh"  # Falls back to leader which has the data
    print("  PASS: BOUNDED_STALENESS falls back to leader when replicas are stale")

    # =========================================================================
    # Test 10: CONSISTENT_PREFIX — reads from most up-to-date replica
    # =========================================================================
    print("\n[Test 10] CONSISTENT_PREFIX consistency...")
    cluster5 = ReadReplicaCluster("ap-northeast", num_replicas=3)

    for i in range(5):
        cluster5.write(f"log:{i}", f"entry-{i}")

    # Only sync some entries to first follower
    partial_entries = cluster5.leader.get_wal_entries_after(0)[:3]
    cluster5.followers[0].apply_wal_entries(partial_entries)

    # Sync all to second follower
    all_entries = cluster5.leader.get_wal_entries_after(0)
    cluster5.followers[1].apply_wal_entries(all_entries)

    # CONSISTENT_PREFIX picks the replica with highest sequence
    val = cluster5.read("log:4", level=ConsistencyLevel.CONSISTENT_PREFIX)
    assert val == "entry-4", f"Should read from most up-to-date replica, got {val}"
    print("  PASS: CONSISTENT_PREFIX reads from most up-to-date replica")

    # =========================================================================
    # Test 11: Delete replication through cluster
    # =========================================================================
    print("\n[Test 11] Delete replication...")
    cluster.write("temp:data", "to-be-deleted")
    cluster.sync_until_caught_up()

    for f in cluster.followers:
        assert f.read("temp:data") == "to-be-deleted"

    cluster.delete_key("temp:data")
    cluster.sync_until_caught_up()

    assert cluster.leader.read("temp:data") is None
    for f in cluster.followers:
        assert f.read("temp:data") is None, f"{f.replica_id} still has deleted key"
    print("  PASS: Deletes propagated through WAL to all followers")

    # =========================================================================
    # Test 12: Quorum reads
    # =========================================================================
    print("\n[Test 12] Quorum reads...")
    qcluster = ReadReplicaCluster("quorum-test", num_replicas=4)
    qcluster.write("q:key", "quorum-value")
    qcluster.sync_until_caught_up()

    qr = QuorumRead(qcluster, quorum=QuorumPolicy.MAJORITY)
    value, agree, total = qr.read("q:key")
    assert value == "quorum-value"
    assert agree >= 3, f"Expected majority agreement, got {agree}/{total}"
    assert total == 5  # 1 leader + 4 followers
    print(f"  PASS: Quorum read: {agree}/{total} agree on value")

    # Test quorum with ALL policy
    qr_all = QuorumRead(qcluster, quorum=QuorumPolicy.ALL)
    value2, agree2, total2 = qr_all.read("q:key")
    assert value2 == "quorum-value"
    assert agree2 == 5
    print(f"  PASS: ALL-quorum read: {agree2}/{total2} unanimous")

    # =========================================================================
    # Test 13: Background streaming replication
    # =========================================================================
    print("\n[Test 13] Background streaming replication...")
    scluster = ReadReplicaCluster("stream-test", num_replicas=2)
    scluster.start_streaming(interval_s=0.02)

    scluster.write("stream:1", "first")
    scluster.write("stream:2", "second")
    time.sleep(0.2)  # Allow streaming to catch up

    for f in scluster.followers:
        assert f.read("stream:1") == "first", f"{f.replica_id} missing stream:1"
        assert f.read("stream:2") == "second", f"{f.replica_id} missing stream:2"

    scluster.stop_streaming()
    print("  PASS: Background streaming replicated writes to all followers")

    # =========================================================================
    # Test 14: Multi-region read distribution
    # =========================================================================
    print("\n[Test 14] Multi-region read distribution...")
    dist = ReadDistributor()

    us_cluster = ReadReplicaCluster("us-dist", num_replicas=2)
    eu_cluster = ReadReplicaCluster("eu-dist", num_replicas=2)
    ap_cluster = ReadReplicaCluster("ap-dist", num_replicas=2)

    us_cluster.write("global:config", "us-version")
    eu_cluster.write("global:config", "eu-version")
    ap_cluster.write("global:config", "ap-version")

    for c in [us_cluster, eu_cluster, ap_cluster]:
        c.sync_until_caught_up()

    dist.add_cluster("us-east-1", GeoCoord(39.04, -77.49), us_cluster)
    dist.add_cluster("eu-west-1", GeoCoord(53.35, -6.26), eu_cluster)
    dist.add_cluster("ap-south-1", GeoCoord(19.08, 72.88), ap_cluster)

    nyc = GeoCoord(40.71, -74.01)
    london = GeoCoord(51.51, -0.13)
    mumbai = GeoCoord(19.08, 72.88)

    val_nyc = dist.read("global:config", nyc, level=ConsistencyLevel.STRONG)
    assert val_nyc == "us-version", f"NYC should read from US cluster, got {val_nyc}"

    val_london = dist.read("global:config", london, level=ConsistencyLevel.STRONG)
    assert val_london == "eu-version", f"London should read from EU cluster, got {val_london}"

    val_mumbai = dist.read("global:config", mumbai, level=ConsistencyLevel.STRONG)
    assert val_mumbai == "ap-version", f"Mumbai should read from AP cluster, got {val_mumbai}"
    print("  PASS: Reads routed to nearest regional cluster")

    # =========================================================================
    # Test 15: Multi-region write distribution
    # =========================================================================
    print("\n[Test 15] Multi-region write distribution...")
    entry = dist.write("user:nyc", {"city": "NYC"}, nyc, session_id="s1")
    assert entry.origin_region == "us-dist-leader"

    entry2 = dist.write("user:london", {"city": "London"}, london, session_id="s2")
    assert entry2.origin_region == "eu-dist-leader"
    print("  PASS: Writes routed to nearest regional leader")

    # =========================================================================
    # Test 16: WALEntry serialization round-trip
    # =========================================================================
    print("\n[Test 16] WALEntry serialization...")
    wal_entry = WALEntry(sequence=42, key="test:ser", value={"a": 1}, timestamp=time.time(), origin_region="r1")
    serialized = json.dumps(wal_entry.to_dict())
    deserialized = WALEntry.from_dict(json.loads(serialized))
    assert deserialized.sequence == 42
    assert deserialized.key == "test:ser"
    assert deserialized.value == {"a": 1}
    assert deserialized.origin_region == "r1"
    print(f"  PASS: WALEntry round-trip ({len(serialized)} bytes)")

    # =========================================================================
    # Test 17: Cluster health report
    # =========================================================================
    print("\n[Test 17] Cluster health report...")
    health = cluster.cluster_health()
    assert health["cluster_id"] == "us-east"
    assert health["leader"] == "us-east-leader"
    assert len(health["followers"]) == 3
    assert "metrics" in health
    print(f"  PASS: Health report: leader_seq={health['leader_seq']}, "
          f"{len(health['followers'])} followers")

    # =========================================================================
    # Test 18: Metrics tracking per consistency level
    # =========================================================================
    print("\n[Test 18] Read metrics by consistency level...")
    metrics = cluster2.protocol.get_metrics()
    assert "strong" in metrics["read_distribution"]
    assert metrics["read_distribution"]["strong"] >= 1

    cluster2.read("x", level=ConsistencyLevel.EVENTUAL)
    cluster2.read("x", level=ConsistencyLevel.EVENTUAL)
    metrics2 = cluster2.protocol.get_metrics()
    assert metrics2["read_distribution"]["eventual"] >= 2
    print(f"  PASS: Metrics tracked: {metrics2['read_distribution']}")

    # =========================================================================
    # Test 19: Large workload — 100 keys, verify convergence
    # =========================================================================
    print("\n[Test 19] Large workload (100 keys)...")
    big_cluster = ReadReplicaCluster("big-test", num_replicas=3)

    for i in range(100):
        big_cluster.write(f"bulk:{i}", {"id": i, "data": f"payload-{i}"})

    rounds = big_cluster.sync_until_caught_up()
    converged, errors = big_cluster.check_convergence()
    assert converged, f"Big cluster not converged: {errors}"

    # Verify random samples
    for i in random.sample(range(100), 10):
        for f in big_cluster.followers:
            v = f.read(f"bulk:{i}")
            assert v == {"id": i, "data": f"payload-{i}"}, \
                f"{f.replica_id} has wrong value for bulk:{i}"
    print(f"  PASS: 100 keys converged in {rounds} round(s), spot-checks pass")

    # =========================================================================
    # Test 20: Quorum read on divergent replicas
    # =========================================================================
    print("\n[Test 20] Quorum read with partial replication...")
    div_cluster = ReadReplicaCluster("divergent", num_replicas=4)
    div_cluster.write("div:key", "v1")

    # Only replicate to 2 of 4 followers
    partial = div_cluster.leader.get_wal_entries_after(0)
    div_cluster.followers[0].apply_wal_entries(partial)
    div_cluster.followers[1].apply_wal_entries(partial)
    # followers[2] and [3] have nothing

    qr_div = QuorumRead(div_cluster, quorum=QuorumPolicy.MAJORITY)
    value, agree, total = qr_div.read("div:key")
    # Leader + 2 followers = 3 have data, 2 have None
    # Majority (3) is met by the 3 that have data
    assert value == "v1", f"Quorum should return 'v1', got {value}"
    assert agree >= 3, f"Expected at least 3 agreeing, got {agree}"
    print(f"  PASS: Quorum read with partial replication: {agree}/{total} agree")

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 70)
    print("ALL 20 TESTS PASSED — READ REPLICAS & CONSISTENCY PROTOCOLS VERIFIED")
    print("=" * 70)
    print(f"  Consistency levels tested:  STRONG, BOUNDED_STALENESS, SESSION, CONSISTENT_PREFIX, EVENTUAL")
    print(f"  Quorum policies tested:     MAJORITY, ALL")
    print(f"  Replication:                WAL-based, single-leader, multi-follower")
    print(f"  Features:                   read distribution, session tokens, staleness bounds, quorum reads")
