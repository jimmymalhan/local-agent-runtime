"""
Active-Active Geo-Replication Engine

Serves customers from the nearest region with conflict-free replicated data.
Uses vector clocks for causality tracking and CRDTs for automatic conflict resolution.
"""

import hashlib
import heapq
import json
import math
import threading
import time
import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional


# ---------------------------------------------------------------------------
# Geography helpers
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class GeoCoord:
    lat: float
    lon: float


def haversine_km(a: GeoCoord, b: GeoCoord) -> float:
    """Great-circle distance between two points on Earth in kilometres."""
    R = 6371.0
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = math.radians(b.lat - a.lat)
    dlon = math.radians(b.lon - a.lon)
    h = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


# ---------------------------------------------------------------------------
# Vector clock – tracks causal ordering across regions
# ---------------------------------------------------------------------------

class VectorClock:
    __slots__ = ("_clocks",)

    def __init__(self, clocks: Optional[dict[str, int]] = None):
        self._clocks: dict[str, int] = dict(clocks) if clocks else {}

    def increment(self, region_id: str) -> "VectorClock":
        new = dict(self._clocks)
        new[region_id] = new.get(region_id, 0) + 1
        return VectorClock(new)

    def merge(self, other: "VectorClock") -> "VectorClock":
        all_keys = set(self._clocks) | set(other._clocks)
        merged = {k: max(self._clocks.get(k, 0), other._clocks.get(k, 0))
                  for k in all_keys}
        return VectorClock(merged)

    def dominates(self, other: "VectorClock") -> bool:
        """True if self >= other on every component and > on at least one."""
        all_keys = set(self._clocks) | set(other._clocks)
        dominated = all(
            self._clocks.get(k, 0) >= other._clocks.get(k, 0) for k in all_keys
        )
        strictly = any(
            self._clocks.get(k, 0) > other._clocks.get(k, 0) for k in all_keys
        )
        return dominated and strictly

    def concurrent_with(self, other: "VectorClock") -> bool:
        return not self.dominates(other) and not other.dominates(self) and self != other

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, VectorClock):
            return NotImplemented
        all_keys = set(self._clocks) | set(other._clocks)
        return all(self._clocks.get(k, 0) == other._clocks.get(k, 0) for k in all_keys)

    def __repr__(self) -> str:
        return f"VC({self._clocks})"

    def as_dict(self) -> dict[str, int]:
        return dict(self._clocks)

    def total(self) -> int:
        return sum(self._clocks.values())


# ---------------------------------------------------------------------------
# CRDT – Last-Writer-Wins Element Dict (LWW-Element-Dict)
# Deterministic conflict resolution: highest wall-clock wins; ties broken by
# region-id lexicographic order.
# ---------------------------------------------------------------------------

@dataclass
class LWWEntry:
    value: Any
    timestamp: float
    region_id: str
    vclock: VectorClock
    tombstone: bool = False

    def wins_over(self, other: "LWWEntry") -> bool:
        if self.timestamp != other.timestamp:
            return self.timestamp > other.timestamp
        return self.region_id > other.region_id  # deterministic tie-break


class LWWDict:
    """A conflict-free replicated dict using Last-Writer-Wins semantics."""

    def __init__(self):
        self._entries: dict[str, LWWEntry] = {}
        self._lock = threading.Lock()

    def set(self, key: str, value: Any, timestamp: float,
            region_id: str, vclock: VectorClock) -> bool:
        entry = LWWEntry(value=value, timestamp=timestamp,
                         region_id=region_id, vclock=vclock)
        with self._lock:
            existing = self._entries.get(key)
            if existing is None or entry.wins_over(existing):
                self._entries[key] = entry
                return True
            return False

    def delete(self, key: str, timestamp: float,
               region_id: str, vclock: VectorClock) -> bool:
        entry = LWWEntry(value=None, timestamp=timestamp,
                         region_id=region_id, vclock=vclock, tombstone=True)
        with self._lock:
            existing = self._entries.get(key)
            if existing is None or entry.wins_over(existing):
                self._entries[key] = entry
                return True
            return False

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            e = self._entries.get(key)
            if e and not e.tombstone:
                return e.value
            return None

    def items(self) -> list[tuple[str, Any]]:
        with self._lock:
            return [(k, e.value) for k, e in self._entries.items()
                    if not e.tombstone]

    def all_entries(self) -> dict[str, LWWEntry]:
        with self._lock:
            return dict(self._entries)


# ---------------------------------------------------------------------------
# Replication log – ordered stream of mutations
# ---------------------------------------------------------------------------

class OpType(Enum):
    SET = "SET"
    DELETE = "DELETE"


@dataclass
class ReplicationOp:
    op_id: str
    op_type: OpType
    key: str
    value: Any
    timestamp: float
    region_id: str
    vclock: VectorClock

    def to_dict(self) -> dict:
        return {
            "op_id": self.op_id,
            "op_type": self.op_type.value,
            "key": self.key,
            "value": self.value,
            "timestamp": self.timestamp,
            "region_id": self.region_id,
            "vclock": self.vclock.as_dict(),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ReplicationOp":
        return cls(
            op_id=d["op_id"],
            op_type=OpType(d["op_type"]),
            key=d["key"],
            value=d["value"],
            timestamp=d["timestamp"],
            region_id=d["region_id"],
            vclock=VectorClock(d["vclock"]),
        )


# ---------------------------------------------------------------------------
# Region node – one active replica
# ---------------------------------------------------------------------------

class RegionNode:
    def __init__(self, region_id: str, coord: GeoCoord,
                 capacity: int = 10000):
        self.region_id = region_id
        self.coord = coord
        self.capacity = capacity
        self.data = LWWDict()
        self.vclock = VectorClock()
        self.oplog: list[ReplicationOp] = []
        self.oplog_cursor: dict[str, int] = {}   # peer -> last-acked offset
        self.peers: dict[str, "RegionNode"] = {}
        self._lock = threading.Lock()
        self.stats = {
            "reads": 0,
            "writes": 0,
            "replicated_in": 0,
            "replicated_out": 0,
            "conflicts_resolved": 0,
        }

    # -- local writes -------------------------------------------------------

    def put(self, key: str, value: Any) -> ReplicationOp:
        ts = time.time()
        with self._lock:
            self.vclock = self.vclock.increment(self.region_id)
            vc = self.vclock
        op = ReplicationOp(
            op_id=str(uuid.uuid4()),
            op_type=OpType.SET,
            key=key,
            value=value,
            timestamp=ts,
            region_id=self.region_id,
            vclock=vc,
        )
        self._apply(op)
        with self._lock:
            self.oplog.append(op)
            self.stats["writes"] += 1
        return op

    def remove(self, key: str) -> ReplicationOp:
        ts = time.time()
        with self._lock:
            self.vclock = self.vclock.increment(self.region_id)
            vc = self.vclock
        op = ReplicationOp(
            op_id=str(uuid.uuid4()),
            op_type=OpType.DELETE,
            key=key,
            value=None,
            timestamp=ts,
            region_id=self.region_id,
            vclock=vc,
        )
        self._apply(op)
        with self._lock:
            self.oplog.append(op)
            self.stats["writes"] += 1
        return op

    def read(self, key: str) -> Optional[Any]:
        self.stats["reads"] += 1
        return self.data.get(key)

    # -- replication --------------------------------------------------------

    def _apply(self, op: ReplicationOp) -> None:
        if op.op_type == OpType.SET:
            applied = self.data.set(op.key, op.value, op.timestamp,
                                    op.region_id, op.vclock)
        else:
            applied = self.data.delete(op.key, op.timestamp,
                                       op.region_id, op.vclock)
        if not applied:
            self.stats["conflicts_resolved"] += 1

    def receive_ops(self, ops: list[ReplicationOp], from_region: str) -> int:
        applied = 0
        for op in ops:
            with self._lock:
                self.vclock = self.vclock.merge(op.vclock)
            self._apply(op)
            applied += 1
            self.stats["replicated_in"] += 1
        return applied

    def get_pending_ops(self, peer_id: str) -> list[ReplicationOp]:
        with self._lock:
            cursor = self.oplog_cursor.get(peer_id, 0)
            pending = self.oplog[cursor:]
            return pending

    def ack_ops(self, peer_id: str, count: int) -> None:
        with self._lock:
            cur = self.oplog_cursor.get(peer_id, 0)
            self.oplog_cursor[peer_id] = cur + count
            self.stats["replicated_out"] += count

    def add_peer(self, peer: "RegionNode") -> None:
        self.peers[peer.region_id] = peer
        with self._lock:
            self.oplog_cursor[peer.region_id] = 0

    def sync_to_peers(self) -> dict[str, int]:
        """Push pending ops to all peers. Returns {peer: ops_sent}."""
        result = {}
        for pid, peer in self.peers.items():
            ops = self.get_pending_ops(pid)
            if ops:
                n = peer.receive_ops(ops, self.region_id)
                self.ack_ops(pid, len(ops))
                result[pid] = n
        return result

    def health(self) -> dict:
        with self._lock:
            lag = {pid: len(self.oplog) - self.oplog_cursor.get(pid, 0)
                   for pid in self.peers}
        return {
            "region_id": self.region_id,
            "coord": (self.coord.lat, self.coord.lon),
            "items": len(self.data.items()),
            "oplog_len": len(self.oplog),
            "replication_lag": lag,
            "stats": dict(self.stats),
        }


# ---------------------------------------------------------------------------
# Geo-Router – directs customers to the nearest healthy region
# ---------------------------------------------------------------------------

class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass
class RegionHealth:
    region_id: str
    status: HealthStatus = HealthStatus.HEALTHY
    latency_ms: float = 0.0
    error_rate: float = 0.0
    last_check: float = field(default_factory=time.time)


class GeoRouter:
    """Routes requests to the nearest healthy region using haversine distance."""

    def __init__(self):
        self.regions: dict[str, RegionNode] = {}
        self.health_status: dict[str, RegionHealth] = {}
        self._lock = threading.Lock()

    def register_region(self, node: RegionNode) -> None:
        with self._lock:
            self.regions[node.region_id] = node
            self.health_status[node.region_id] = RegionHealth(
                region_id=node.region_id
            )

    def update_health(self, region_id: str, status: HealthStatus,
                      latency_ms: float = 0.0,
                      error_rate: float = 0.0) -> None:
        with self._lock:
            self.health_status[region_id] = RegionHealth(
                region_id=region_id,
                status=status,
                latency_ms=latency_ms,
                error_rate=error_rate,
                last_check=time.time(),
            )

    def nearest_region(self, client_coord: GeoCoord,
                       max_results: int = 3) -> list[tuple[str, float]]:
        """Return up to max_results (region_id, distance_km) sorted by distance,
        filtering out DOWN regions."""
        candidates = []
        with self._lock:
            for rid, node in self.regions.items():
                h = self.health_status.get(rid)
                if h and h.status == HealthStatus.DOWN:
                    continue
                dist = haversine_km(client_coord, node.coord)
                candidates.append((rid, dist))
        candidates.sort(key=lambda x: x[1])
        return candidates[:max_results]

    def route(self, client_coord: GeoCoord) -> Optional[RegionNode]:
        """Route a customer to the nearest healthy region."""
        ranked = self.nearest_region(client_coord)
        with self._lock:
            for rid, _dist in ranked:
                h = self.health_status.get(rid)
                if h and h.status == HealthStatus.HEALTHY:
                    return self.regions[rid]
            # fallback to degraded
            for rid, _dist in ranked:
                h = self.health_status.get(rid)
                if h and h.status == HealthStatus.DEGRADED:
                    return self.regions[rid]
        return None


# ---------------------------------------------------------------------------
# Replication coordinator – manages sync across all regions
# ---------------------------------------------------------------------------

class ReplicationCoordinator:
    """Coordinates active-active replication across all region nodes."""

    def __init__(self, router: GeoRouter):
        self.router = router
        self.conflict_log: list[dict] = []
        self._running = False
        self._thread: Optional[threading.Thread] = None

    def full_mesh(self) -> None:
        """Connect every region to every other region (full mesh topology)."""
        nodes = list(self.router.regions.values())
        for i, a in enumerate(nodes):
            for j, b in enumerate(nodes):
                if i != j:
                    a.add_peer(b)

    def sync_all(self) -> dict[str, dict[str, int]]:
        """One round of replication across all regions."""
        results = {}
        for rid, node in self.router.regions.items():
            sent = node.sync_to_peers()
            if sent:
                results[rid] = sent
        return results

    def sync_until_converged(self, max_rounds: int = 20) -> int:
        """Keep syncing until no ops are pending. Returns rounds taken."""
        for r in range(1, max_rounds + 1):
            result = self.sync_all()
            if not result:
                return r
        return max_rounds

    def start_background_sync(self, interval_sec: float = 0.1) -> None:
        """Start a background thread that syncs periodically."""
        self._running = True

        def _loop():
            while self._running:
                self.sync_all()
                time.sleep(interval_sec)

        self._thread = threading.Thread(target=_loop, daemon=True)
        self._thread.start()

    def stop_background_sync(self) -> None:
        self._running = False
        if self._thread:
            self._thread.join(timeout=2.0)

    def cluster_health(self) -> dict:
        return {rid: node.health() for rid, node in self.router.regions.items()}


# ---------------------------------------------------------------------------
# Consistency checker – validates convergence across replicas
# ---------------------------------------------------------------------------

class ConsistencyChecker:
    """Verifies that all regions have converged to the same state."""

    @staticmethod
    def check_convergence(regions: list[RegionNode]) -> tuple[bool, list[str]]:
        if len(regions) < 2:
            return True, []
        reference = dict(regions[0].data.items())
        errors = []
        for node in regions[1:]:
            current = dict(node.data.items())
            if current != reference:
                missing_in_current = set(reference) - set(current)
                missing_in_ref = set(current) - set(reference)
                value_diffs = {
                    k for k in set(reference) & set(current)
                    if reference[k] != current[k]
                }
                if missing_in_current:
                    errors.append(
                        f"{node.region_id}: missing keys {missing_in_current}")
                if missing_in_ref:
                    errors.append(
                        f"{node.region_id}: extra keys {missing_in_ref}")
                if value_diffs:
                    errors.append(
                        f"{node.region_id}: value mismatch on {value_diffs}")
        return len(errors) == 0, errors

    @staticmethod
    def snapshot(regions: list[RegionNode]) -> dict[str, dict]:
        return {
            node.region_id: dict(node.data.items())
            for node in regions
        }


# ---------------------------------------------------------------------------
# Consistent hashing ring – for shard-aware routing (optional layer)
# ---------------------------------------------------------------------------

class ConsistentHashRing:
    """Maps keys to regions using consistent hashing with virtual nodes."""

    def __init__(self, vnodes: int = 150):
        self.vnodes = vnodes
        self._ring: list[tuple[int, str]] = []
        self._sorted = False

    def add_region(self, region_id: str) -> None:
        for i in range(self.vnodes):
            h = self._hash(f"{region_id}:{i}")
            self._ring.append((h, region_id))
        self._sorted = False

    def remove_region(self, region_id: str) -> None:
        self._ring = [(h, r) for h, r in self._ring if r != region_id]
        self._sorted = False

    def get_region(self, key: str) -> Optional[str]:
        if not self._ring:
            return None
        if not self._sorted:
            self._ring.sort()
            self._sorted = True
        h = self._hash(key)
        idx = self._bisect(h)
        return self._ring[idx % len(self._ring)][1]

    def get_regions(self, key: str, n: int = 3) -> list[str]:
        """Get n distinct regions for a key (for replication factor)."""
        if not self._ring:
            return []
        if not self._sorted:
            self._ring.sort()
            self._sorted = True
        h = self._hash(key)
        idx = self._bisect(h)
        seen = []
        for offset in range(len(self._ring)):
            rid = self._ring[(idx + offset) % len(self._ring)][1]
            if rid not in seen:
                seen.append(rid)
                if len(seen) >= n:
                    break
        return seen

    @staticmethod
    def _hash(val: str) -> int:
        return int(hashlib.md5(val.encode()).hexdigest(), 16)

    def _bisect(self, h: int) -> int:
        lo, hi = 0, len(self._ring)
        while lo < hi:
            mid = (lo + hi) // 2
            if self._ring[mid][0] < h:
                lo = mid + 1
            else:
                hi = mid
        return lo % len(self._ring) if self._ring else 0


# ---------------------------------------------------------------------------
# __main__ — comprehensive test / demo
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("ACTIVE-ACTIVE GEO-REPLICATION ENGINE — VERIFICATION SUITE")
    print("=" * 70)

    # ── 1. Set up regions ──────────────────────────────────────────────
    print("\n[1] Setting up regions...")
    us_east = RegionNode("us-east-1", GeoCoord(39.0438, -77.4874))      # Virginia
    us_west = RegionNode("us-west-2", GeoCoord(45.5945, -122.1562))     # Oregon
    eu_west = RegionNode("eu-west-1", GeoCoord(53.3331, -6.2489))       # Ireland
    ap_south = RegionNode("ap-south-1", GeoCoord(19.0760, 72.8777))     # Mumbai
    ap_northeast = RegionNode("ap-northeast-1", GeoCoord(35.6762, 139.6503))  # Tokyo

    all_regions = [us_east, us_west, eu_west, ap_south, ap_northeast]

    router = GeoRouter()
    for r in all_regions:
        router.register_region(r)

    coordinator = ReplicationCoordinator(router)
    coordinator.full_mesh()
    print(f"  Regions: {[r.region_id for r in all_regions]}")
    print("  Topology: full mesh")

    # ── 2. Geo-routing: customers served from nearest region ───────────
    print("\n[2] Geo-routing verification...")

    # New York customer → us-east-1
    nyc = GeoCoord(40.7128, -74.0060)
    ranked_nyc = router.nearest_region(nyc)
    assert ranked_nyc[0][0] == "us-east-1", f"NYC should route to us-east-1, got {ranked_nyc[0][0]}"
    print(f"  NYC ({nyc.lat}, {nyc.lon}) → {ranked_nyc[0][0]} ({ranked_nyc[0][1]:.0f} km)")

    # San Francisco customer → us-west-2
    sfo = GeoCoord(37.7749, -122.4194)
    ranked_sfo = router.nearest_region(sfo)
    assert ranked_sfo[0][0] == "us-west-2", f"SFO should route to us-west-2, got {ranked_sfo[0][0]}"
    print(f"  SFO ({sfo.lat}, {sfo.lon}) → {ranked_sfo[0][0]} ({ranked_sfo[0][1]:.0f} km)")

    # London customer → eu-west-1
    london = GeoCoord(51.5074, -0.1278)
    ranked_ldn = router.nearest_region(london)
    assert ranked_ldn[0][0] == "eu-west-1", f"London should route to eu-west-1, got {ranked_ldn[0][0]}"
    print(f"  London ({london.lat}, {london.lon}) → {ranked_ldn[0][0]} ({ranked_ldn[0][1]:.0f} km)")

    # Mumbai customer → ap-south-1
    mumbai = GeoCoord(19.0760, 72.8777)
    ranked_mum = router.nearest_region(mumbai)
    assert ranked_mum[0][0] == "ap-south-1", f"Mumbai should route to ap-south-1, got {ranked_mum[0][0]}"
    print(f"  Mumbai ({mumbai.lat}, {mumbai.lon}) → {ranked_mum[0][0]} ({ranked_mum[0][1]:.0f} km)")

    # Tokyo customer → ap-northeast-1
    tokyo = GeoCoord(35.6762, 139.6503)
    ranked_tky = router.nearest_region(tokyo)
    assert ranked_tky[0][0] == "ap-northeast-1", f"Tokyo should route to ap-northeast-1, got {ranked_tky[0][0]}"
    print(f"  Tokyo ({tokyo.lat}, {tokyo.lon}) → {ranked_tky[0][0]} ({ranked_tky[0][1]:.0f} km)")

    print("  ✓ All customers routed to nearest region")

    # ── 3. Active-active writes from multiple regions ──────────────────
    print("\n[3] Active-active writes...")

    us_east.put("user:1001", {"name": "Alice", "plan": "enterprise"})
    eu_west.put("user:1002", {"name": "Bob", "plan": "pro"})
    ap_south.put("user:1003", {"name": "Chandra", "plan": "enterprise"})
    us_west.put("config:ttl", 3600)
    ap_northeast.put("user:1004", {"name": "Yuki", "plan": "starter"})

    assert us_east.read("user:1001")["name"] == "Alice"
    assert eu_west.read("user:1002")["name"] == "Bob"
    assert ap_south.read("user:1003")["name"] == "Chandra"
    assert us_west.read("config:ttl") == 3600
    assert ap_northeast.read("user:1004")["name"] == "Yuki"

    # Before replication: each region only sees its own writes
    assert us_east.read("user:1002") is None, "us-east should not yet see eu-west's write"
    print("  ✓ Each region holds local writes before sync")

    # ── 4. Replication – converge all regions ─────────────────────────
    print("\n[4] Replicating across regions...")

    rounds = coordinator.sync_until_converged()
    print(f"  Converged in {rounds} round(s)")

    # All regions should now see all data
    for region in all_regions:
        assert region.read("user:1001")["name"] == "Alice", \
            f"{region.region_id} missing user:1001"
        assert region.read("user:1002")["name"] == "Bob", \
            f"{region.region_id} missing user:1002"
        assert region.read("user:1003")["name"] == "Chandra", \
            f"{region.region_id} missing user:1003"
        assert region.read("config:ttl") == 3600, \
            f"{region.region_id} missing config:ttl"
        assert region.read("user:1004")["name"] == "Yuki", \
            f"{region.region_id} missing user:1004"

    converged, errors = ConsistencyChecker.check_convergence(all_regions)
    assert converged, f"Regions not converged: {errors}"
    print("  ✓ All 5 regions converged to identical state")

    # ── 5. Conflict resolution (concurrent writes to same key) ────────
    print("\n[5] Conflict resolution...")

    # Simulate concurrent writes: two regions write the same key.
    # US-East writes first, EU-West writes slightly later (later ts wins).
    us_east.put("user:conflict", {"source": "us-east"})
    time.sleep(0.01)  # ensure EU-West gets a later timestamp
    eu_west.put("user:conflict", {"source": "eu-west"})

    # After sync, EU-West's write should win (later timestamp)
    coordinator.sync_until_converged()
    for region in all_regions:
        val = region.read("user:conflict")
        assert val["source"] == "eu-west", \
            f"{region.region_id} has wrong conflict resolution: {val}"
    print("  ✓ LWW conflict resolution: later write wins across all regions")

    # Test tie-breaking by region ID (direct CRDT merge test)
    tie_ts = time.time() + 100  # same timestamp for both
    vc_tie = VectorClock({"tie": 1})
    # Apply same-timestamp entries directly to a fresh LWW to verify tie-break
    test_lww = LWWDict()
    test_lww.set("tie", {"source": "us-east"}, tie_ts, "us-east-1", vc_tie)
    test_lww.set("tie", {"source": "us-west"}, tie_ts, "us-west-2", vc_tie)
    tie_val = test_lww.get("tie")
    assert tie_val["source"] == "us-west", f"tie-break wrong: {tie_val}"
    # Also test reverse insertion order gives same result
    test_lww2 = LWWDict()
    test_lww2.set("tie", {"source": "us-west"}, tie_ts, "us-west-2", vc_tie)
    test_lww2.set("tie", {"source": "us-east"}, tie_ts, "us-east-1", vc_tie)
    assert test_lww2.get("tie")["source"] == "us-west"

    # us-west-2 > us-east-1 lexicographically, so us-west wins tie
    print("  ✓ Deterministic tie-break: higher region ID wins")

    # ── 6. Deletes replicate correctly ────────────────────────────────
    print("\n[6] Delete replication...")

    ap_south.remove("config:ttl")
    coordinator.sync_until_converged()
    for region in all_regions:
        assert region.read("config:ttl") is None, \
            f"{region.region_id} still has config:ttl after delete"
    print("  ✓ Deletes propagated to all regions (tombstone)")

    # ── 7. Failover: down region excluded from routing ────────────────
    print("\n[7] Failover routing...")

    router.update_health("us-east-1", HealthStatus.DOWN)
    routed = router.route(nyc)
    assert routed is not None
    assert routed.region_id != "us-east-1", \
        "Down region should not receive traffic"
    print(f"  NYC failover → {routed.region_id} (us-east-1 is DOWN)")

    router.update_health("us-east-1", HealthStatus.HEALTHY)
    routed = router.route(nyc)
    assert routed.region_id == "us-east-1", "Recovered region should serve again"
    print("  ✓ Failover and recovery work correctly")

    # ── 8. Vector clock causality ─────────────────────────────────────
    print("\n[8] Vector clock verification...")

    vc_a = VectorClock({"us-east-1": 3, "eu-west-1": 2})
    vc_b = VectorClock({"us-east-1": 3, "eu-west-1": 1})
    assert vc_a.dominates(vc_b), "vc_a should dominate vc_b"
    assert not vc_b.dominates(vc_a), "vc_b should not dominate vc_a"

    vc_c = VectorClock({"us-east-1": 4, "eu-west-1": 1})
    assert vc_a.concurrent_with(vc_c), "vc_a and vc_c should be concurrent"

    vc_merged = vc_a.merge(vc_c)
    assert vc_merged.as_dict() == {"us-east-1": 4, "eu-west-1": 2}
    print(f"  VC merge: {vc_a} ∪ {vc_c} = {vc_merged}")
    print("  ✓ Vector clocks: dominance, concurrency, merge all correct")

    # ── 9. Consistent hash ring ───────────────────────────────────────
    print("\n[9] Consistent hash ring...")

    ring = ConsistentHashRing(vnodes=150)
    for r in all_regions:
        ring.add_region(r.region_id)

    # Distribution test: 1000 keys should spread across all regions
    distribution: dict[str, int] = defaultdict(int)
    for i in range(1000):
        region = ring.get_region(f"key:{i}")
        distribution[region] += 1

    assert len(distribution) == 5, "All 5 regions should have some keys"
    for rid, count in distribution.items():
        assert count > 50, f"{rid} has too few keys ({count}), distribution skewed"
    print(f"  Distribution: {dict(distribution)}")

    # Replication factor: each key should map to 3 distinct regions
    replicas = ring.get_regions("test-key", n=3)
    assert len(replicas) == 3, f"Expected 3 replicas, got {len(replicas)}"
    assert len(set(replicas)) == 3, "Replicas must be distinct"
    print(f"  Replicas for 'test-key': {replicas}")
    print("  ✓ Consistent hashing distributes evenly with replication")

    # ── 10. Background sync smoke test ────────────────────────────────
    print("\n[10] Background sync...")

    coordinator.start_background_sync(interval_sec=0.05)
    eu_west.put("bg:test", {"background": True})
    time.sleep(0.3)  # allow a few sync cycles
    coordinator.stop_background_sync()

    for region in all_regions:
        val = region.read("bg:test")
        assert val is not None and val["background"] is True, \
            f"{region.region_id} missing bg:test after background sync"
    print("  ✓ Background sync propagated writes automatically")

    # ── 11. Cluster health report ─────────────────────────────────────
    print("\n[11] Cluster health...")
    health = coordinator.cluster_health()
    for rid, h in health.items():
        print(f"  {rid}: {h['items']} items, "
              f"reads={h['stats']['reads']}, writes={h['stats']['writes']}, "
              f"replicated_in={h['stats']['replicated_in']}")

    # ── 12. Serialization round-trip ──────────────────────────────────
    print("\n[12] Op serialization...")
    op = us_east.oplog[0]
    serialized = json.dumps(op.to_dict())
    deserialized = ReplicationOp.from_dict(json.loads(serialized))
    assert deserialized.op_id == op.op_id
    assert deserialized.key == op.key
    assert deserialized.op_type == op.op_type
    print(f"  ✓ ReplicationOp round-trip: {len(serialized)} bytes")

    # ── Summary ───────────────────────────────────────────────────────
    print("\n" + "=" * 70)
    print("ALL ASSERTIONS PASSED — GEO-REPLICATION ENGINE VERIFIED")
    print("=" * 70)
    print(f"  Regions:            {len(all_regions)}")
    print(f"  Topology:           full mesh ({len(all_regions) * (len(all_regions)-1)} links)")
    print(f"  Conflict strategy:  LWW with deterministic tie-break")
    print(f"  Causality tracking: vector clocks")
    print(f"  Routing:            haversine nearest-region + health-aware failover")
    print(f"  Hash ring:          consistent hashing with {ring.vnodes} vnodes")
    print(f"  Replication:        active-active, async, convergent")
