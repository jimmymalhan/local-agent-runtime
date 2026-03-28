"""
Active-Active Geo-Replication Engine

Serves customers from the nearest region with conflict-free replicated data.
Uses vector clocks for causal ordering and CRDTs for merge-without-conflict semantics.
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
    R = 6371.0
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = math.radians(b.lat - a.lat)
    dlon = math.radians(b.lon - a.lon)
    h = (math.sin(dlat / 2) ** 2 +
         math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2)
    return 2 * R * math.asin(math.sqrt(h))


# ---------------------------------------------------------------------------
# Vector Clock – causal ordering across regions
# ---------------------------------------------------------------------------

class VectorClock:
    __slots__ = ("_clock",)

    def __init__(self, clock: Optional[dict[str, int]] = None):
        self._clock: dict[str, int] = dict(clock) if clock else {}

    def increment(self, node_id: str) -> "VectorClock":
        new = dict(self._clock)
        new[node_id] = new.get(node_id, 0) + 1
        return VectorClock(new)

    def merge(self, other: "VectorClock") -> "VectorClock":
        merged = dict(self._clock)
        for k, v in other._clock.items():
            merged[k] = max(merged.get(k, 0), v)
        return VectorClock(merged)

    def __ge__(self, other: "VectorClock") -> bool:
        for k, v in other._clock.items():
            if self._clock.get(k, 0) < v:
                return False
        return True

    def __gt__(self, other: "VectorClock") -> bool:
        return self >= other and self._clock != other._clock

    def concurrent(self, other: "VectorClock") -> bool:
        return not (self >= other) and not (other >= self)

    def as_dict(self) -> dict[str, int]:
        return dict(self._clock)

    def __repr__(self) -> str:
        return f"VC({self._clock})"


# ---------------------------------------------------------------------------
# CRDT: Last-Writer-Wins Register with vector-clock tiebreak
# ---------------------------------------------------------------------------

class ConflictResolution(Enum):
    LWW = "last_writer_wins"
    MERGE = "merge_all"


@dataclass
class VersionedValue:
    value: Any
    vclock: VectorClock
    timestamp: float
    origin_region: str
    tombstone: bool = False

    def supersedes(self, other: "VersionedValue") -> bool:
        if self.vclock > other.vclock:
            return True
        if self.vclock.concurrent(other.vclock):
            return self.timestamp > other.timestamp
        return False


# ---------------------------------------------------------------------------
# Replicated Data Store (per-region)
# ---------------------------------------------------------------------------

class ReplicatedStore:
    def __init__(self, region_id: str):
        self.region_id = region_id
        self._data: dict[str, VersionedValue] = {}
        self._lock = threading.Lock()
        self._op_log: list[dict] = []

    def put(self, key: str, value: Any) -> VersionedValue:
        with self._lock:
            existing = self._data.get(key)
            if existing:
                new_vc = existing.vclock.increment(self.region_id)
            else:
                new_vc = VectorClock().increment(self.region_id)
            vv = VersionedValue(
                value=value,
                vclock=new_vc,
                timestamp=time.time(),
                origin_region=self.region_id,
            )
            self._data[key] = vv
            self._op_log.append({"op": "put", "key": key, "vv": vv})
            return vv

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            vv = self._data.get(key)
            if vv is None or vv.tombstone:
                return None
            return vv.value

    def delete(self, key: str) -> Optional[VersionedValue]:
        with self._lock:
            existing = self._data.get(key)
            if existing is None:
                return None
            new_vc = existing.vclock.increment(self.region_id)
            vv = VersionedValue(
                value=None,
                vclock=new_vc,
                timestamp=time.time(),
                origin_region=self.region_id,
                tombstone=True,
            )
            self._data[key] = vv
            self._op_log.append({"op": "delete", "key": key, "vv": vv})
            return vv

    def apply_remote(self, key: str, remote_vv: VersionedValue) -> bool:
        with self._lock:
            local = self._data.get(key)
            if local is None or remote_vv.supersedes(local):
                self._data[key] = remote_vv
                return True
            return False

    def keys(self) -> list[str]:
        with self._lock:
            return [k for k, v in self._data.items() if not v.tombstone]

    def snapshot(self) -> dict[str, VersionedValue]:
        with self._lock:
            return dict(self._data)

    def drain_op_log(self) -> list[dict]:
        with self._lock:
            ops = list(self._op_log)
            self._op_log.clear()
            return ops


# ---------------------------------------------------------------------------
# Region Node
# ---------------------------------------------------------------------------

class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"


@dataclass
class RegionNode:
    region_id: str
    location: GeoCoord
    store: ReplicatedStore = field(init=False)
    status: HealthStatus = HealthStatus.HEALTHY
    _peers: list["RegionNode"] = field(default_factory=list, repr=False)
    replication_lag_ms: float = 0.0
    requests_served: int = 0

    def __post_init__(self):
        self.store = ReplicatedStore(self.region_id)

    def add_peer(self, peer: "RegionNode"):
        if peer.region_id != self.region_id and peer not in self._peers:
            self._peers.append(peer)

    def write(self, key: str, value: Any) -> VersionedValue:
        vv = self.store.put(key, value)
        self.requests_served += 1
        return vv

    def read(self, key: str) -> Optional[Any]:
        self.requests_served += 1
        return self.store.get(key)

    def remove(self, key: str) -> Optional[VersionedValue]:
        vv = self.store.delete(key)
        self.requests_served += 1
        return vv

    def replicate_to_peers(self) -> int:
        ops = self.store.drain_op_log()
        applied = 0
        for peer in self._peers:
            if peer.status == HealthStatus.DOWN:
                continue
            for op in ops:
                key = op["key"]
                vv = op["vv"]
                if peer.store.apply_remote(key, vv):
                    applied += 1
        return applied

    def full_sync_from(self, source: "RegionNode") -> int:
        snap = source.store.snapshot()
        applied = 0
        for key, vv in snap.items():
            if self.store.apply_remote(key, vv):
                applied += 1
        return applied


# ---------------------------------------------------------------------------
# Geo-Router: routes customers to nearest healthy region
# ---------------------------------------------------------------------------

class GeoRouter:
    def __init__(self):
        self._regions: dict[str, RegionNode] = {}

    def register_region(self, node: RegionNode):
        self._regions[node.region_id] = node

    def connect_all(self):
        nodes = list(self._regions.values())
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                a.add_peer(b)
                b.add_peer(a)

    @property
    def regions(self) -> dict[str, RegionNode]:
        return dict(self._regions)

    def nearest_healthy(self, client_location: GeoCoord) -> Optional[RegionNode]:
        candidates = [
            (haversine_km(client_location, r.location), r)
            for r in self._regions.values()
            if r.status != HealthStatus.DOWN
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    def route_read(self, client_location: GeoCoord, key: str) -> Optional[Any]:
        node = self.nearest_healthy(client_location)
        if node is None:
            raise RuntimeError("All regions are down")
        return node.read(key)

    def route_write(self, client_location: GeoCoord, key: str, value: Any) -> tuple[str, VersionedValue]:
        node = self.nearest_healthy(client_location)
        if node is None:
            raise RuntimeError("All regions are down")
        vv = node.write(key, value)
        return node.region_id, vv

    def replicate_all(self) -> int:
        total = 0
        for node in self._regions.values():
            if node.status != HealthStatus.DOWN:
                total += node.replicate_to_peers()
        return total

    def global_consistency_check(self) -> dict[str, bool]:
        keys: set[str] = set()
        for node in self._regions.values():
            keys.update(node.store.keys())
        result = {}
        for key in keys:
            values = set()
            for node in self._regions.values():
                v = node.store.get(key)
                values.add(json.dumps(v, sort_keys=True, default=str))
            result[key] = len(values) == 1
        return result


# ---------------------------------------------------------------------------
# Conflict-Free Counter CRDT (GCounter) — for distributed metrics
# ---------------------------------------------------------------------------

class GCounter:
    def __init__(self):
        self._counts: dict[str, int] = {}

    def increment(self, node_id: str, amount: int = 1):
        self._counts[node_id] = self._counts.get(node_id, 0) + amount

    def value(self) -> int:
        return sum(self._counts.values())

    def merge(self, other: "GCounter") -> "GCounter":
        merged = GCounter()
        all_keys = set(self._counts) | set(other._counts)
        for k in all_keys:
            merged._counts[k] = max(
                self._counts.get(k, 0),
                other._counts.get(k, 0),
            )
        return merged


# ---------------------------------------------------------------------------
# Replication Monitor — tracks lag and convergence
# ---------------------------------------------------------------------------

class ReplicationMonitor:
    def __init__(self, router: GeoRouter):
        self.router = router
        self._history: list[dict] = []

    def measure_convergence(self) -> dict:
        consistency = self.router.global_consistency_check()
        total = len(consistency)
        consistent = sum(1 for v in consistency.values() if v)
        record = {
            "timestamp": time.time(),
            "total_keys": total,
            "consistent_keys": consistent,
            "convergence_pct": (consistent / total * 100) if total > 0 else 100.0,
            "details": consistency,
        }
        self._history.append(record)
        return record

    def region_stats(self) -> list[dict]:
        return [
            {
                "region": node.region_id,
                "status": node.status.value,
                "keys": len(node.store.keys()),
                "requests": node.requests_served,
                "location": (node.location.lat, node.location.lon),
            }
            for node in self.router.regions.values()
        ]


# ---------------------------------------------------------------------------
# Failover Controller
# ---------------------------------------------------------------------------

class FailoverController:
    def __init__(self, router: GeoRouter):
        self.router = router

    def mark_down(self, region_id: str):
        node = self.router.regions.get(region_id)
        if node:
            node.status = HealthStatus.DOWN

    def mark_healthy(self, region_id: str):
        node = self.router.regions.get(region_id)
        if node:
            node.status = HealthStatus.HEALTHY

    def recover_region(self, region_id: str) -> int:
        node = self.router.regions.get(region_id)
        if not node:
            return 0
        healthy_peers = [
            p for p in node._peers if p.status != HealthStatus.DOWN
        ]
        if not healthy_peers:
            return 0
        source = healthy_peers[0]
        applied = node.full_sync_from(source)
        node.status = HealthStatus.HEALTHY
        return applied


# ---------------------------------------------------------------------------
# __main__ — full verification suite
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    # --- Setup: 4 global regions ---
    us_east = RegionNode("us-east-1", GeoCoord(39.0438, -77.4874))
    eu_west = RegionNode("eu-west-1", GeoCoord(53.3498, -6.2603))
    ap_south = RegionNode("ap-south-1", GeoCoord(19.0760, 72.8777))
    us_west = RegionNode("us-west-2", GeoCoord(45.5945, -122.1562))

    router = GeoRouter()
    for r in [us_east, eu_west, ap_south, us_west]:
        router.register_region(r)
    router.connect_all()

    # --- Test 1: Nearest-region routing ---
    nyc = GeoCoord(40.7128, -74.0060)
    london = GeoCoord(51.5074, -0.1278)
    mumbai = GeoCoord(19.0760, 72.8777)
    portland = GeoCoord(45.5152, -122.6784)

    nearest_nyc = router.nearest_healthy(nyc)
    nearest_london = router.nearest_healthy(london)
    nearest_mumbai = router.nearest_healthy(mumbai)
    nearest_portland = router.nearest_healthy(portland)

    assert nearest_nyc.region_id == "us-east-1", f"NYC should route to us-east-1, got {nearest_nyc.region_id}"
    assert nearest_london.region_id == "eu-west-1", f"London should route to eu-west-1, got {nearest_london.region_id}"
    assert nearest_mumbai.region_id == "ap-south-1", f"Mumbai should route to ap-south-1, got {nearest_mumbai.region_id}"
    assert nearest_portland.region_id == "us-west-2", f"Portland should route to us-west-2, got {nearest_portland.region_id}"
    print("[PASS] Test 1: Nearest-region routing correct for all 4 cities")

    # --- Test 2: Write to nearest, replicate to all ---
    region_id, vv = router.route_write(nyc, "user:1001", {"name": "Alice", "plan": "pro"})
    assert region_id == "us-east-1"
    replicated = router.replicate_all()
    assert replicated >= 3, f"Expected replication to 3 peers, got {replicated}"

    for node in [us_east, eu_west, ap_south, us_west]:
        val = node.read("user:1001")
        assert val == {"name": "Alice", "plan": "pro"}, f"{node.region_id} missing replicated data"
    print("[PASS] Test 2: Write replicated to all 4 regions")

    # --- Test 3: Concurrent writes with LWW conflict resolution ---
    vv_eu = eu_west.write("config:theme", "dark")
    time.sleep(0.001)
    vv_ap = ap_south.write("config:theme", "light")

    router.replicate_all()

    values = set()
    for node in [us_east, eu_west, ap_south, us_west]:
        v = node.read("config:theme")
        values.add(v)
    assert len(values) == 1, f"Conflict not resolved: divergent values {values}"
    assert "light" in values or "dark" in values
    print(f"[PASS] Test 3: Concurrent write conflict resolved to '{values.pop()}'")

    # --- Test 4: Delete replication (tombstones) ---
    us_east.write("session:tmp", "abc123")
    router.replicate_all()
    for node in [us_east, eu_west, ap_south, us_west]:
        assert node.read("session:tmp") == "abc123"

    us_east.remove("session:tmp")
    router.replicate_all()
    for node in [us_east, eu_west, ap_south, us_west]:
        assert node.read("session:tmp") is None, f"Tombstone not replicated to {node.region_id}"
    print("[PASS] Test 4: Delete tombstones replicated correctly")

    # --- Test 5: Region failover ---
    failover = FailoverController(router)
    failover.mark_down("eu-west-1")

    nearest_london_after = router.nearest_healthy(london)
    assert nearest_london_after.region_id != "eu-west-1", "Down region should not serve traffic"
    print(f"[PASS] Test 5: London rerouted to {nearest_london_after.region_id} after eu-west-1 down")

    # --- Test 6: Region recovery with full sync ---
    us_east.write("critical:data", {"version": 42, "payload": "important"})
    router.replicate_all()

    applied = failover.recover_region("eu-west-1")
    assert applied > 0, "Recovery should sync missing data"
    val = eu_west.read("critical:data")
    assert val == {"version": 42, "payload": "important"}, f"Recovery data mismatch: {val}"
    print(f"[PASS] Test 6: eu-west-1 recovered, synced {applied} entries")

    # --- Test 7: Convergence monitoring ---
    monitor = ReplicationMonitor(router)
    report = monitor.measure_convergence()
    assert report["convergence_pct"] == 100.0, f"Not converged: {report['convergence_pct']}%"
    print(f"[PASS] Test 7: Global convergence at {report['convergence_pct']}%")

    # --- Test 8: GCounter CRDT for distributed metrics ---
    c1 = GCounter()
    c2 = GCounter()
    c1.increment("us-east-1", 100)
    c1.increment("us-east-1", 50)
    c2.increment("eu-west-1", 200)
    c2.increment("ap-south-1", 75)

    merged = c1.merge(c2)
    assert merged.value() == 425, f"GCounter merge wrong: {merged.value()}"
    print(f"[PASS] Test 8: GCounter CRDT merged correctly, total={merged.value()}")

    # --- Test 9: Haversine distance sanity ---
    d_nyc_london = haversine_km(nyc, london)
    assert 5500 < d_nyc_london < 5700, f"NYC-London distance off: {d_nyc_london}"
    d_nyc_mumbai = haversine_km(nyc, mumbai)
    assert 12500 < d_nyc_mumbai < 13000, f"NYC-Mumbai distance off: {d_nyc_mumbai}"
    print(f"[PASS] Test 9: Haversine distances correct (NYC-LDN: {d_nyc_london:.0f}km)")

    # --- Test 10: All-regions-down raises error ---
    for rid in router.regions:
        failover.mark_down(rid)
    try:
        router.route_read(nyc, "anything")
        assert False, "Should have raised RuntimeError"
    except RuntimeError as e:
        assert "All regions are down" in str(e)
    print("[PASS] Test 10: All-regions-down raises RuntimeError")

    # Restore
    for rid in router.regions:
        failover.mark_healthy(rid)

    # --- Test 11: Vector clock ordering ---
    vc1 = VectorClock({"a": 1, "b": 2})
    vc2 = VectorClock({"a": 1, "b": 3})
    vc3 = VectorClock({"a": 2, "b": 1})

    assert vc2 > vc1, "vc2 should dominate vc1"
    assert not (vc1 > vc2), "vc1 should not dominate vc2"
    assert vc1.concurrent(vc3), "vc1 and vc3 should be concurrent"
    print("[PASS] Test 11: Vector clock ordering verified")

    # --- Test 12: Multi-key workload ---
    for i in range(50):
        loc = nyc if i % 2 == 0 else mumbai
        router.route_write(loc, f"item:{i}", {"id": i, "data": f"value-{i}"})
    router.replicate_all()

    report = monitor.measure_convergence()
    assert report["convergence_pct"] == 100.0
    stats = monitor.region_stats()
    total_requests = sum(s["requests"] for s in stats)
    assert total_requests > 50, f"Expected >50 requests tracked, got {total_requests}"
    print(f"[PASS] Test 12: 50-key workload converged, {total_requests} total requests across regions")

    # --- Test 13: Idempotent replication ---
    router.replicate_all()
    router.replicate_all()
    report = monitor.measure_convergence()
    assert report["convergence_pct"] == 100.0
    print("[PASS] Test 13: Idempotent replication — double-replicate stays converged")

    # --- Summary ---
    print("\n" + "=" * 60)
    print("ALL 13 TESTS PASSED — Active-Active Geo-Replication Verified")
    print("=" * 60)
    print("\nRegion stats:")
    for s in monitor.region_stats():
        print(f"  {s['region']:12s} | status={s['status']:8s} | keys={s['keys']:3d} | requests={s['requests']}")
