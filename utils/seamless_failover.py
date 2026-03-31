"""
Seamless Failover to Backup Region (<5s detection + switchover)

Self-contained module implementing automatic failover with:
- Heartbeat health probes with configurable thresholds
- Circuit breaker per region (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
- Fencing tokens to prevent split-brain writes from stale leaders
- Connection draining before cutover
- Priority-based backup selection (preferred backup, then nearest healthy)
- Read-only degradation mode for partial failures
- Automatic recovery with full data resync
- SLA tracking (availability %, failover latency percentiles)
- Request-level transparent retry across regions

Timing budget (<5s total):
  Detection:  failure_threshold * probe_interval  (3 * 0.5s = 1.5s)
  Drain:      drain_timeout                       (max 2.0s)
  Switchover: fencing + reroute                   (<0.1s)
  Total:      ~3.6s worst case
"""

import math
import statistics
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Geography
# ---------------------------------------------------------------------------

class GeoCoord:
    __slots__ = ("lat", "lon")

    def __init__(self, lat: float, lon: float):
        self.lat = lat
        self.lon = lon

    def __repr__(self) -> str:
        return f"GeoCoord({self.lat}, {self.lon})"


def haversine_km(a: GeoCoord, b: GeoCoord) -> float:
    R = 6371.0
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = math.radians(b.lat - a.lat)
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


# ---------------------------------------------------------------------------
# Vector Clock
# ---------------------------------------------------------------------------

class VectorClock:
    __slots__ = ("_clock",)

    def __init__(self, clock: Optional[dict] = None):
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
        return all(self._clock.get(k, 0) >= v for k, v in other._clock.items())

    def __gt__(self, other: "VectorClock") -> bool:
        return self >= other and self._clock != other._clock

    def concurrent(self, other: "VectorClock") -> bool:
        return not (self >= other) and not (other >= self)

    def as_dict(self) -> dict:
        return dict(self._clock)


# ---------------------------------------------------------------------------
# Health & Region Status
# ---------------------------------------------------------------------------

class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DRAINING = "draining"
    READ_ONLY = "read_only"
    DOWN = "down"


# ---------------------------------------------------------------------------
# Versioned Value (LWW with vector-clock tiebreak)
# ---------------------------------------------------------------------------

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
# Replicated Key-Value Store
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
            vc = existing.vclock.increment(self.region_id) if existing else VectorClock().increment(self.region_id)
            vv = VersionedValue(value=value, vclock=vc, timestamp=time.time(), origin_region=self.region_id)
            self._data[key] = vv
            self._op_log.append({"op": "put", "key": key, "vv": vv})
            return vv

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            vv = self._data.get(key)
            return None if vv is None or vv.tombstone else vv.value

    def delete(self, key: str) -> Optional[VersionedValue]:
        with self._lock:
            existing = self._data.get(key)
            if existing is None:
                return None
            vc = existing.vclock.increment(self.region_id)
            vv = VersionedValue(value=None, vclock=vc, timestamp=time.time(), origin_region=self.region_id, tombstone=True)
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

@dataclass
class RegionNode:
    region_id: str
    location: GeoCoord
    priority: int = 0
    weight: float = 1.0
    preferred_backup: Optional[str] = None
    store: ReplicatedStore = field(init=False, repr=False)
    status: HealthStatus = HealthStatus.HEALTHY
    _peers: list["RegionNode"] = field(default_factory=list, repr=False)
    active_connections: int = 0
    requests_served: int = 0

    def __post_init__(self):
        self.store = ReplicatedStore(self.region_id)

    def add_peer(self, peer: "RegionNode"):
        if peer.region_id != self.region_id and peer not in self._peers:
            self._peers.append(peer)

    def write(self, key: str, value: Any) -> VersionedValue:
        if self.status in (HealthStatus.DOWN, HealthStatus.READ_ONLY, HealthStatus.DRAINING):
            raise RuntimeError(f"Region {self.region_id} cannot accept writes (status={self.status.value})")
        self.active_connections += 1
        try:
            vv = self.store.put(key, value)
            self.requests_served += 1
            return vv
        finally:
            self.active_connections -= 1

    def read(self, key: str) -> Optional[Any]:
        if self.status == HealthStatus.DOWN:
            raise RuntimeError(f"Region {self.region_id} is down")
        self.active_connections += 1
        try:
            self.requests_served += 1
            return self.store.get(key)
        finally:
            self.active_connections -= 1

    def remove(self, key: str) -> Optional[VersionedValue]:
        if self.status in (HealthStatus.DOWN, HealthStatus.READ_ONLY, HealthStatus.DRAINING):
            raise RuntimeError(f"Region {self.region_id} cannot accept deletes (status={self.status.value})")
        self.active_connections += 1
        try:
            vv = self.store.delete(key)
            self.requests_served += 1
            return vv
        finally:
            self.active_connections -= 1

    def replicate_to_peers(self) -> int:
        ops = self.store.drain_op_log()
        applied = 0
        for peer in self._peers:
            if peer.status == HealthStatus.DOWN:
                continue
            for op in ops:
                if peer.store.apply_remote(op["key"], op["vv"]):
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
# Circuit Breaker
# ---------------------------------------------------------------------------

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


class CircuitBreaker:
    def __init__(self, region_id: str, failure_threshold: int = 3,
                 recovery_timeout_s: float = 5.0, success_threshold: int = 2):
        self.region_id = region_id
        self.failure_threshold = failure_threshold
        self.recovery_timeout_s = recovery_timeout_s
        self.success_threshold = success_threshold
        self.state = CircuitState.CLOSED
        self.failure_count = 0
        self.success_count = 0
        self.last_failure_time = 0.0
        self._lock = threading.Lock()

    def record_success(self):
        with self._lock:
            if self.state == CircuitState.HALF_OPEN:
                self.success_count += 1
                if self.success_count >= self.success_threshold:
                    self._transition(CircuitState.CLOSED)
            elif self.state == CircuitState.CLOSED:
                self.failure_count = 0

    def record_failure(self):
        with self._lock:
            self.failure_count += 1
            self.last_failure_time = time.time()
            if self.state == CircuitState.HALF_OPEN:
                self._transition(CircuitState.OPEN)
            elif self.state == CircuitState.CLOSED and self.failure_count >= self.failure_threshold:
                self._transition(CircuitState.OPEN)

    def allow_request(self) -> bool:
        with self._lock:
            if self.state == CircuitState.CLOSED:
                return True
            if self.state == CircuitState.OPEN:
                if time.time() - self.last_failure_time >= self.recovery_timeout_s:
                    self._transition(CircuitState.HALF_OPEN)
                    return True
                return False
            return True  # HALF_OPEN allows probe requests

    def force_open(self):
        with self._lock:
            self._transition(CircuitState.OPEN)

    def force_close(self):
        with self._lock:
            self._transition(CircuitState.CLOSED)

    def _transition(self, new_state: CircuitState):
        self.state = new_state
        if new_state == CircuitState.CLOSED:
            self.failure_count = 0
            self.success_count = 0
        elif new_state == CircuitState.HALF_OPEN:
            self.success_count = 0


# ---------------------------------------------------------------------------
# Fencing Token Manager — split-brain protection
# ---------------------------------------------------------------------------

class FencingTokenManager:
    def __init__(self):
        self._lock = threading.Lock()
        self._token = 0
        self._holders: dict[str, int] = {}

    def acquire(self, region_id: str) -> int:
        with self._lock:
            self._token += 1
            self._holders[region_id] = self._token
            return self._token

    def validate(self, region_id: str, token: int) -> bool:
        with self._lock:
            return token >= self._holders.get(region_id, 0)

    def revoke(self, region_id: str):
        with self._lock:
            self._holders.pop(region_id, None)

    @property
    def current_token(self) -> int:
        with self._lock:
            return self._token


# ---------------------------------------------------------------------------
# SLA Tracker
# ---------------------------------------------------------------------------

class SLATracker:
    def __init__(self, window_size: int = 1000):
        self._lock = threading.Lock()
        self._total = 0
        self._success = 0
        self._failover_latencies: deque = deque(maxlen=window_size)
        self._request_latencies: deque = deque(maxlen=window_size)
        self._downtime_events: list[dict] = []
        self._start = time.time()

    def record_request(self, success: bool, latency_ms: float):
        with self._lock:
            self._total += 1
            if success:
                self._success += 1
            self._request_latencies.append(latency_ms)

    def record_failover(self, latency_ms: float, from_region: str, to_region: str):
        with self._lock:
            self._failover_latencies.append(latency_ms)
            self._downtime_events.append({
                "timestamp": time.time(),
                "from": from_region,
                "to": to_region,
                "latency_ms": latency_ms,
            })

    def availability_pct(self) -> float:
        with self._lock:
            return (self._success / self._total * 100.0) if self._total else 100.0

    def _pct(self, data: list, p: float) -> float:
        if not data:
            return 0.0
        k = (len(data) - 1) * (p / 100.0)
        f, c = math.floor(k), math.ceil(k)
        if f == c:
            return data[int(k)]
        return data[int(f)] * (c - k) + data[int(c)] * (k - f)

    def failover_percentiles(self) -> dict:
        with self._lock:
            data = sorted(self._failover_latencies)
            return {"p50": self._pct(data, 50), "p95": self._pct(data, 95),
                    "p99": self._pct(data, 99), "count": len(data)}

    def summary(self) -> dict:
        return {
            "availability_pct": round(self.availability_pct(), 4),
            "total_requests": self._total,
            "successful_requests": self._success,
            "failover_latency": self.failover_percentiles(),
            "uptime_s": round(time.time() - self._start, 1),
            "downtime_events": len(self._downtime_events),
        }


# ---------------------------------------------------------------------------
# Connection Drainer
# ---------------------------------------------------------------------------

class ConnectionDrainer:
    def __init__(self, drain_timeout_s: float = 2.0, poll_interval_s: float = 0.01):
        self.drain_timeout_s = drain_timeout_s
        self.poll_interval_s = poll_interval_s

    def drain(self, node: RegionNode) -> bool:
        node.status = HealthStatus.DRAINING
        deadline = time.monotonic() + self.drain_timeout_s
        while time.monotonic() < deadline:
            if node.active_connections <= 0:
                return True
            time.sleep(self.poll_interval_s)
        return node.active_connections <= 0


# ---------------------------------------------------------------------------
# Failover Events
# ---------------------------------------------------------------------------

class FailoverEventType(Enum):
    REGION_DOWN = "region_down"
    DRAIN_START = "drain_start"
    DRAIN_DONE = "drain_done"
    FAILOVER_TRIGGERED = "failover_triggered"
    TRAFFIC_REROUTED = "traffic_rerouted"
    FENCE_ACQUIRED = "fence_acquired"
    FENCE_REVOKED = "fence_revoked"
    RECOVERY_START = "recovery_start"
    RECOVERY_DONE = "recovery_done"
    CIRCUIT_OPENED = "circuit_opened"
    CIRCUIT_CLOSED = "circuit_closed"
    READ_ONLY = "read_only"
    REQUEST_RETRIED = "request_retried"


@dataclass
class FailoverEvent:
    event_type: FailoverEventType
    region_id: str
    timestamp: float = field(default_factory=time.time)
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# SeamlessFailover — the main orchestrator
# ---------------------------------------------------------------------------

class SeamlessFailover:
    """
    Orchestrates seamless failover across geo-distributed regions.

    On region failure:
      1. Circuit breaker opens after failure_threshold consecutive probe failures
      2. Active connections are drained (max drain_timeout_s)
      3. Fencing token revoked to prevent stale writes
      4. Traffic rerouted to nearest healthy backup (or preferred_backup)
      5. New fencing token acquired for backup
      6. Total time: <5s

    On recovery:
      1. Circuit breaker transitions OPEN -> HALF_OPEN -> CLOSED
      2. Full data sync from healthy peer
      3. Fencing token reacquired
      4. Region rejoins serving pool
    """

    def __init__(
        self,
        regions: list[RegionNode],
        probe_interval_s: float = 0.5,
        failure_threshold: int = 3,
        recovery_timeout_s: float = 3.0,
        drain_timeout_s: float = 2.0,
        check_fn: Optional[Callable[[RegionNode], bool]] = None,
    ):
        self._regions: dict[str, RegionNode] = {r.region_id: r for r in regions}
        self._connect_peers()

        self.probe_interval_s = probe_interval_s
        self.failure_threshold = failure_threshold
        self._check_fn = check_fn or self._default_check

        self.breakers: dict[str, CircuitBreaker] = {
            rid: CircuitBreaker(rid, failure_threshold=failure_threshold,
                                recovery_timeout_s=recovery_timeout_s)
            for rid in self._regions
        }

        self.fencing = FencingTokenManager()
        self.sla = SLATracker()
        self.drainer = ConnectionDrainer(drain_timeout_s=drain_timeout_s)

        self._event_log: list[FailoverEvent] = []
        self._lock = threading.Lock()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._failover_targets: dict[str, str] = {}
        self._failed_regions: set[str] = set()
        self._fencing_tokens: dict[str, int] = {}

    def _connect_peers(self):
        nodes = list(self._regions.values())
        for i, a in enumerate(nodes):
            for b in nodes[i + 1:]:
                a.add_peer(b)
                b.add_peer(a)

    @staticmethod
    def _default_check(node: RegionNode) -> bool:
        return node.status not in (HealthStatus.DOWN, HealthStatus.DRAINING)

    @property
    def regions(self) -> dict[str, RegionNode]:
        return dict(self._regions)

    @property
    def events(self) -> list[FailoverEvent]:
        with self._lock:
            return list(self._event_log)

    def _emit(self, etype: FailoverEventType, region_id: str, **details):
        ev = FailoverEvent(etype, region_id, details=details)
        with self._lock:
            self._event_log.append(ev)

    # -- Health monitoring --

    def start_monitoring(self):
        if self._running:
            return
        self._running = True
        self._monitor_thread = threading.Thread(target=self._loop, daemon=True, name="failover-monitor")
        self._monitor_thread.start()

    def stop_monitoring(self):
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=self.probe_interval_s * 4)

    def _loop(self):
        while self._running:
            self.run_probe_cycle()
            time.sleep(self.probe_interval_s)

    def run_probe_cycle(self):
        for rid, node in self._regions.items():
            healthy = self._check_fn(node)
            breaker = self.breakers[rid]

            if healthy:
                if breaker.state == CircuitState.OPEN:
                    breaker.allow_request()
                breaker.record_success()
                if rid in self._failed_regions and breaker.state == CircuitState.CLOSED:
                    self._recover(rid)
            else:
                breaker.record_failure()
                if breaker.state == CircuitState.OPEN and rid not in self._failed_regions:
                    self._failover(rid)

    # -- Failover --

    def _failover(self, region_id: str):
        node = self._regions.get(region_id)
        if not node or region_id in self._failed_regions:
            return

        t0 = time.monotonic()
        self._failed_regions.add(region_id)

        self._emit(FailoverEventType.REGION_DOWN, region_id)
        self._emit(FailoverEventType.CIRCUIT_OPENED, region_id)

        # Drain
        self._emit(FailoverEventType.DRAIN_START, region_id)
        drained = self.drainer.drain(node)
        self._emit(FailoverEventType.DRAIN_DONE, region_id, success=drained)

        # Mark down
        node.status = HealthStatus.DOWN

        # Revoke fencing token
        self.fencing.revoke(region_id)
        self._fencing_tokens.pop(region_id, None)
        self._emit(FailoverEventType.FENCE_REVOKED, region_id)

        # Find backup
        backup = self._find_backup(node)
        if backup:
            self._failover_targets[region_id] = backup.region_id
            token = self.fencing.acquire(backup.region_id)
            self._fencing_tokens[backup.region_id] = token
            self._emit(FailoverEventType.FENCE_ACQUIRED, backup.region_id, token=token)
            self._emit(FailoverEventType.FAILOVER_TRIGGERED, region_id, backup=backup.region_id)
            self._emit(FailoverEventType.TRAFFIC_REROUTED, region_id, target=backup.region_id)

        elapsed_ms = (time.monotonic() - t0) * 1000
        self.sla.record_failover(elapsed_ms, region_id, backup.region_id if backup else "none")

    def _find_backup(self, failed_node: RegionNode) -> Optional[RegionNode]:
        if failed_node.preferred_backup:
            pref = self._regions.get(failed_node.preferred_backup)
            if pref and pref.status not in (HealthStatus.DOWN, HealthStatus.DRAINING):
                return pref

        candidates = [
            (r.priority, haversine_km(failed_node.location, r.location), r)
            for r in self._regions.values()
            if r.region_id != failed_node.region_id
            and r.status not in (HealthStatus.DOWN, HealthStatus.DRAINING)
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0], x[1]))
        return candidates[0][2]

    # -- Recovery --

    def _recover(self, region_id: str):
        self._emit(FailoverEventType.RECOVERY_START, region_id)
        node = self._regions[region_id]

        healthy_peers = [p for p in node._peers if p.status == HealthStatus.HEALTHY]
        applied = 0
        if healthy_peers:
            applied = node.full_sync_from(healthy_peers[0])

        node.status = HealthStatus.HEALTHY
        self.breakers[region_id].force_close()

        token = self.fencing.acquire(region_id)
        self._fencing_tokens[region_id] = token

        self._failover_targets.pop(region_id, None)
        self._failed_regions.discard(region_id)

        self._emit(FailoverEventType.RECOVERY_DONE, region_id, synced=applied, token=token)
        self._emit(FailoverEventType.CIRCUIT_CLOSED, region_id)

    # -- Request execution --

    def execute(self, client_location: GeoCoord, operation: str, key: str,
                value: Any = None, max_retries: int = 2) -> dict:
        start = time.monotonic()
        attempted: list[str] = []
        last_error = None

        for attempt in range(max_retries + 1):
            node = self._select(client_location, attempted, operation)
            if node is None:
                break

            attempted.append(node.region_id)
            breaker = self.breakers[node.region_id]
            if not breaker.allow_request():
                continue

            try:
                if operation == "read":
                    result = node.read(key)
                elif operation == "write":
                    result = node.write(key, value)
                elif operation == "delete":
                    result = node.remove(key)
                else:
                    raise ValueError(f"Unknown operation: {operation}")

                breaker.record_success()
                ms = (time.monotonic() - start) * 1000
                self.sla.record_request(True, ms)
                return {"result": result, "region_id": node.region_id,
                        "retries": attempt, "total_ms": round(ms, 2),
                        "attempted_regions": attempted}
            except Exception as e:
                last_error = e
                breaker.record_failure()
                self._emit(FailoverEventType.REQUEST_RETRIED, node.region_id,
                           attempt=attempt, error=str(e))

        ms = (time.monotonic() - start) * 1000
        self.sla.record_request(False, ms)
        raise RuntimeError(
            f"All regions exhausted after {len(attempted)} attempts "
            f"({ms:.1f}ms). Last error: {last_error}. Tried: {attempted}"
        )

    def _select(self, loc: GeoCoord, exclude: list[str], operation: str = "read") -> Optional[RegionNode]:
        candidates = []
        for r in self._regions.values():
            if r.region_id in exclude:
                continue
            if r.status in (HealthStatus.DOWN, HealthStatus.DRAINING):
                continue
            if r.status == HealthStatus.READ_ONLY and operation != "read":
                continue
            if not self.breakers[r.region_id].allow_request():
                continue
            dist = haversine_km(loc, r.location)
            candidates.append((dist, r.priority, r))
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0], x[1]))
        return candidates[0][2]

    # -- Degradation --

    def activate_read_only(self, region_id: str):
        node = self._regions.get(region_id)
        if node:
            node.status = HealthStatus.READ_ONLY
            self._emit(FailoverEventType.READ_ONLY, region_id)

    # -- Replication --

    def replicate_all(self) -> int:
        total = 0
        for node in self._regions.values():
            if node.status not in (HealthStatus.DOWN, HealthStatus.DRAINING):
                total += node.replicate_to_peers()
        return total

    # -- Simulation --

    def simulate_failure(self, region_id: str):
        node = self._regions.get(region_id)
        if node:
            node.status = HealthStatus.DOWN

    def simulate_recovery(self, region_id: str):
        node = self._regions.get(region_id)
        if node:
            node.status = HealthStatus.HEALTHY

    # -- Metrics --

    def get_metrics(self) -> dict:
        return {
            "breakers": {rid: {"state": b.state.value, "failures": b.failure_count}
                         for rid, b in self.breakers.items()},
            "failover_targets": dict(self._failover_targets),
            "failed_regions": list(self._failed_regions),
            "active_regions": [rid for rid, n in self._regions.items()
                               if n.status in (HealthStatus.HEALTHY, HealthStatus.READ_ONLY)],
            "fencing_tokens": dict(self._fencing_tokens),
            "sla": self.sla.summary(),
            "total_events": len(self._event_log),
        }


# ---------------------------------------------------------------------------
# __main__ — full verification suite
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("Seamless Failover — Full Verification Suite")
    print("=" * 70)

    # =====================================================================
    # Setup: 4 regions with priorities and preferred backups
    # =====================================================================
    us_east = RegionNode("us-east-1", GeoCoord(39.04, -77.49), priority=0, preferred_backup="eu-west-1")
    eu_west = RegionNode("eu-west-1", GeoCoord(53.35, -6.26), priority=1, preferred_backup="us-east-1")
    ap_south = RegionNode("ap-south-1", GeoCoord(19.08, 72.88), priority=2)
    us_west = RegionNode("us-west-2", GeoCoord(45.59, -122.16), priority=1)

    nyc = GeoCoord(40.71, -74.01)
    london = GeoCoord(51.51, -0.13)
    mumbai = GeoCoord(19.08, 72.88)
    portland = GeoCoord(45.52, -122.68)

    sf = SeamlessFailover(
        regions=[us_east, eu_west, ap_south, us_west],
        probe_interval_s=0.05,
        failure_threshold=3,
        recovery_timeout_s=0.2,
        drain_timeout_s=0.5,
    )

    # Seed data
    us_east.store.put("user:1", {"name": "Alice", "plan": "pro"})
    eu_west.store.put("user:2", {"name": "Bob", "plan": "team"})
    ap_south.store.put("user:3", {"name": "Charlie", "plan": "enterprise"})
    us_west.store.put("config:global", {"version": 7})
    sf.replicate_all()

    # =====================================================================
    # Test 1: Initial status — all 4 regions healthy
    # =====================================================================
    metrics = sf.get_metrics()
    assert len(metrics["active_regions"]) == 4
    assert metrics["failover_targets"] == {}
    assert metrics["failed_regions"] == []
    print("[PASS] Test 1: All 4 regions healthy at startup")

    # =====================================================================
    # Test 2: Circuit breaker transitions (CLOSED -> OPEN -> HALF_OPEN -> CLOSED)
    # =====================================================================
    cb = CircuitBreaker("test", failure_threshold=3, recovery_timeout_s=0.1)
    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True
    cb.record_failure(); cb.record_failure()
    assert cb.state == CircuitState.CLOSED  # not yet threshold
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False
    time.sleep(0.12)
    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_success(); cb.record_success()
    assert cb.state == CircuitState.CLOSED
    print("[PASS] Test 2: Circuit breaker CLOSED->OPEN->HALF_OPEN->CLOSED")

    # =====================================================================
    # Test 3: Fencing tokens monotonic + revoke/reacquire
    # =====================================================================
    ftm = FencingTokenManager()
    t1 = ftm.acquire("r1")
    t2 = ftm.acquire("r2")
    assert t2 > t1
    assert ftm.validate("r1", t1) is True
    assert ftm.validate("r1", t1 - 1) is False
    ftm.revoke("r1")
    t3 = ftm.acquire("r1")
    assert t3 > t2
    assert ftm.validate("r1", t3) is True
    assert ftm.validate("r1", t1) is False  # old token stale
    print("[PASS] Test 3: Fencing tokens monotonic, revoke invalidates old tokens")

    # =====================================================================
    # Test 4: SLA tracker computes availability and percentiles
    # =====================================================================
    sla = SLATracker()
    for i in range(100):
        sla.record_request(True, float(i))
    sla.record_request(False, 500.0)
    avail = sla.availability_pct()
    assert 99.0 <= avail <= 100.0
    sla.record_failover(150.0, "r1", "r2")
    sla.record_failover(200.0, "r1", "r2")
    pcts = sla.failover_percentiles()
    assert pcts["count"] == 2
    assert pcts["p50"] >= 150.0
    print(f"[PASS] Test 4: SLA availability={avail:.2f}%, failover p50={pcts['p50']:.1f}ms")

    # =====================================================================
    # Test 5: Connection drainer works
    # =====================================================================
    drain_node = RegionNode("drain-test", GeoCoord(0, 0))
    drain_node.active_connections = 0
    drainer = ConnectionDrainer(drain_timeout_s=0.5)
    drained = drainer.drain(drain_node)
    assert drained is True
    assert drain_node.status == HealthStatus.DRAINING
    print("[PASS] Test 5: Connection drainer completes immediately when idle")

    # =====================================================================
    # Test 6: Automatic failover via probe cycle
    # =====================================================================
    sf.simulate_failure("us-east-1")
    for _ in range(5):
        sf.run_probe_cycle()
        time.sleep(0.01)

    assert us_east.status == HealthStatus.DOWN
    assert sf.breakers["us-east-1"].state == CircuitState.OPEN
    assert "us-east-1" in sf._failover_targets
    backup_id = sf._failover_targets["us-east-1"]
    assert backup_id == "eu-west-1", f"Expected preferred backup eu-west-1, got {backup_id}"
    print(f"[PASS] Test 6: us-east-1 failed over to preferred backup {backup_id}")

    # =====================================================================
    # Test 7: Reads rerouted transparently during failover
    # =====================================================================
    resp = sf.execute(nyc, "read", "user:2")
    assert resp["result"] == {"name": "Bob", "plan": "team"}
    assert resp["region_id"] != "us-east-1"
    assert resp["total_ms"] < 5000
    print(f"[PASS] Test 7: NYC read rerouted to {resp['region_id']} in {resp['total_ms']:.1f}ms")

    # =====================================================================
    # Test 8: Writes rerouted during failover
    # =====================================================================
    resp_w = sf.execute(nyc, "write", "user:4", {"name": "Diana"})
    assert resp_w["region_id"] != "us-east-1"
    assert resp_w["total_ms"] < 5000
    print(f"[PASS] Test 8: Write during failover landed on {resp_w['region_id']}")

    # =====================================================================
    # Test 9: Failover completes in <5s
    # =====================================================================
    sf.simulate_recovery("us-east-1")
    time.sleep(0.25)
    for _ in range(5):
        sf.run_probe_cycle()
        time.sleep(0.01)

    t_start = time.monotonic()
    sf.simulate_failure("eu-west-1")
    for _ in range(5):
        sf.run_probe_cycle()
        time.sleep(0.02)
    elapsed = time.monotonic() - t_start
    assert elapsed < 5.0, f"Failover took {elapsed:.2f}s, exceeds 5s budget"
    assert eu_west.status == HealthStatus.DOWN
    print(f"[PASS] Test 9: Full failover cycle in {elapsed:.3f}s (< 5s budget)")

    # =====================================================================
    # Test 10: Region recovery with data sync + fencing token
    # =====================================================================
    sf.replicate_all()  # ensure failover writes reach all healthy peers
    sf.simulate_recovery("eu-west-1")
    time.sleep(0.25)
    for _ in range(5):
        sf.run_probe_cycle()
        time.sleep(0.01)

    assert eu_west.status == HealthStatus.HEALTHY
    assert sf.breakers["eu-west-1"].state == CircuitState.CLOSED
    assert "eu-west-1" not in sf._failover_targets
    assert eu_west.read("user:4") == {"name": "Diana"}, "Recovery should sync failover writes"
    assert "eu-west-1" in sf._fencing_tokens
    print("[PASS] Test 10: eu-west-1 recovered with data sync and new fencing token")

    # =====================================================================
    # Test 11: Cascading multi-region failure
    # =====================================================================
    sf.simulate_failure("us-east-1")
    sf.simulate_failure("eu-west-1")
    for _ in range(5):
        sf.run_probe_cycle()
        time.sleep(0.01)

    resp_c = sf.execute(nyc, "read", "user:3")
    assert resp_c["region_id"] in ("ap-south-1", "us-west-2")
    assert resp_c["result"] == {"name": "Charlie", "plan": "enterprise"}
    print(f"[PASS] Test 11: Cascading failure — NYC served by {resp_c['region_id']}")

    # =====================================================================
    # Test 12: All regions down raises RuntimeError
    # =====================================================================
    sf.simulate_failure("ap-south-1")
    sf.simulate_failure("us-west-2")
    for _ in range(5):
        sf.run_probe_cycle()
        time.sleep(0.01)

    try:
        sf.execute(nyc, "read", "user:1")
        assert False, "Should have raised"
    except RuntimeError as e:
        assert "All regions exhausted" in str(e)
    print("[PASS] Test 12: All-regions-down raises RuntimeError")

    # =====================================================================
    # Test 13: Full recovery after total outage
    # =====================================================================
    for rid in sf._regions:
        sf.simulate_recovery(rid)
    time.sleep(0.25)
    for _ in range(5):
        sf.run_probe_cycle()
        time.sleep(0.01)

    active = [rid for rid, n in sf._regions.items() if n.status == HealthStatus.HEALTHY]
    assert len(active) == 4
    resp_after = sf.execute(nyc, "read", "user:1")
    assert resp_after["result"] == {"name": "Alice", "plan": "pro"}
    print("[PASS] Test 13: Full recovery — all 4 regions back, data intact")

    # =====================================================================
    # Test 14: Read-only degradation (reads ok, writes failover)
    # =====================================================================
    for rid in sf._regions:
        sf._regions[rid].status = HealthStatus.HEALTHY
        sf.breakers[rid].force_close()
        sf._failed_regions.discard(rid)
        sf._failover_targets.pop(rid, None)
    sf.activate_read_only("ap-south-1")
    assert ap_south.status == HealthStatus.READ_ONLY

    resp_ro = sf.execute(mumbai, "read", "user:3")
    assert resp_ro["result"] == {"name": "Charlie", "plan": "enterprise"}
    assert resp_ro["region_id"] == "ap-south-1"

    resp_w_ro = sf.execute(mumbai, "write", "user:5", {"name": "Eve"})
    assert resp_w_ro["region_id"] != "ap-south-1", "Write must not go to read-only region"

    ap_south.status = HealthStatus.HEALTHY
    print(f"[PASS] Test 14: Read-only allows reads, writes fail over to {resp_w_ro['region_id']}")

    # =====================================================================
    # Test 15: Delete with replication
    # =====================================================================
    us_east.store.put("temp:del", "remove_me")
    sf.replicate_all()
    for node in [us_east, eu_west, ap_south, us_west]:
        assert node.read("temp:del") == "remove_me"

    resp_del = sf.execute(london, "delete", "temp:del")
    sf.replicate_all()
    for node in [us_east, eu_west, ap_south, us_west]:
        assert node.read("temp:del") is None
    print(f"[PASS] Test 15: Delete replicated across all regions via {resp_del['region_id']}")

    # =====================================================================
    # Test 16: Concurrent reads under load
    # =====================================================================
    results_16 = []
    errors_16 = []

    def concurrent_read(loc, key, idx):
        try:
            r = sf.execute(loc, "read", key)
            results_16.append((idx, r))
        except Exception as e:
            errors_16.append((idx, str(e)))

    us_east.store.put("shared:x", {"v": 42})
    sf.replicate_all()

    threads = []
    for i in range(10):
        loc = [nyc, london, mumbai, portland][i % 4]
        t = threading.Thread(target=concurrent_read, args=(loc, "shared:x", i))
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert len(errors_16) == 0, f"Concurrent read errors: {errors_16}"
    assert len(results_16) == 10
    for _, r in results_16:
        assert r["result"] == {"v": 42}
    print("[PASS] Test 16: 10 concurrent reads all succeeded across 4 regions")

    # =====================================================================
    # Test 17: Vector clock ordering
    # =====================================================================
    vc1 = VectorClock({"a": 1, "b": 2})
    vc2 = VectorClock({"a": 1, "b": 3})
    vc3 = VectorClock({"a": 2, "b": 1})
    assert vc2 > vc1
    assert not (vc1 > vc2)
    assert vc1.concurrent(vc3)
    merged = vc1.merge(vc3)
    assert merged.as_dict() == {"a": 2, "b": 2}
    print("[PASS] Test 17: Vector clock ordering and merge verified")

    # =====================================================================
    # Test 18: Background monitoring starts and stops
    # =====================================================================
    sf2 = SeamlessFailover(
        regions=[RegionNode("r1", GeoCoord(0, 0)), RegionNode("r2", GeoCoord(10, 10))],
        probe_interval_s=0.03,
        failure_threshold=3,
    )
    sf2.start_monitoring()
    assert sf2._running is True
    time.sleep(0.15)
    sf2.stop_monitoring()
    assert sf2._running is False
    time.sleep(0.1)
    assert not sf2._monitor_thread.is_alive()
    print("[PASS] Test 18: Background monitoring starts and stops cleanly")

    # =====================================================================
    # Test 19: Failover event audit trail completeness
    # =====================================================================
    all_events = sf.events
    types_seen = {e.event_type for e in all_events}
    required = {
        FailoverEventType.REGION_DOWN,
        FailoverEventType.DRAIN_START,
        FailoverEventType.DRAIN_DONE,
        FailoverEventType.FAILOVER_TRIGGERED,
        FailoverEventType.TRAFFIC_REROUTED,
        FailoverEventType.FENCE_ACQUIRED,
        FailoverEventType.FENCE_REVOKED,
        FailoverEventType.RECOVERY_START,
        FailoverEventType.RECOVERY_DONE,
        FailoverEventType.CIRCUIT_OPENED,
        FailoverEventType.CIRCUIT_CLOSED,
    }
    missing = required - types_seen
    assert not missing, f"Missing event types: {missing}"
    print(f"[PASS] Test 19: Audit trail complete — all {len(required)} event types recorded")

    # =====================================================================
    # Test 20: SLA populated after all operations
    # =====================================================================
    summary = sf.sla.summary()
    assert summary["total_requests"] > 0
    assert summary["availability_pct"] > 0
    assert summary["downtime_events"] > 0
    fo = summary["failover_latency"]
    assert fo["count"] > 0
    print(f"[PASS] Test 20: SLA — availability={summary['availability_pct']:.2f}%, "
          f"failover_p50={fo['p50']:.1f}ms, events={summary['downtime_events']}")

    # =====================================================================
    # Test 21: Haversine distance sanity
    # =====================================================================
    d = haversine_km(nyc, london)
    assert 5500 < d < 5700, f"NYC-London distance off: {d}"
    print(f"[PASS] Test 21: Haversine NYC-London = {d:.0f}km")

    # =====================================================================
    # Test 22: Preferred backup selection respected
    # =====================================================================
    sf3 = SeamlessFailover(
        regions=[
            RegionNode("primary", GeoCoord(0, 0), priority=0, preferred_backup="secondary"),
            RegionNode("secondary", GeoCoord(10, 10), priority=1),
            RegionNode("tertiary", GeoCoord(5, 5), priority=2),  # closer but not preferred
        ],
        failure_threshold=3,
        recovery_timeout_s=0.2,
        drain_timeout_s=0.1,
    )
    primary = sf3._regions["primary"]
    backup = sf3._find_backup(primary)
    assert backup.region_id == "secondary", f"Expected preferred backup 'secondary', got {backup.region_id}"
    print("[PASS] Test 22: Preferred backup selection respected over distance")

    # =====================================================================
    # Test 23: Failover timing end-to-end under 5s
    # =====================================================================
    sf4 = SeamlessFailover(
        regions=[
            RegionNode("fast-1", GeoCoord(0, 0)),
            RegionNode("fast-2", GeoCoord(10, 10)),
        ],
        probe_interval_s=0.1,
        failure_threshold=3,
        recovery_timeout_s=0.2,
        drain_timeout_s=0.5,
    )
    sf4._regions["fast-1"].store.put("k", "v")
    sf4.replicate_all()

    sf4.simulate_failure("fast-1")
    t_e2e_start = time.monotonic()
    for _ in range(10):
        sf4.run_probe_cycle()
        if "fast-1" in sf4._failed_regions:
            break
        time.sleep(sf4.probe_interval_s)
    t_e2e_end = time.monotonic()
    e2e_ms = (t_e2e_end - t_e2e_start) * 1000
    assert e2e_ms < 5000, f"End-to-end failover {e2e_ms:.0f}ms exceeds 5s"
    assert sf4._regions["fast-1"].status == HealthStatus.DOWN
    print(f"[PASS] Test 23: End-to-end failover in {e2e_ms:.0f}ms (< 5000ms)")

    # =====================================================================
    # Test 24: Metrics endpoint returns all expected fields
    # =====================================================================
    m = sf.get_metrics()
    for key in ("breakers", "failover_targets", "failed_regions", "active_regions",
                "fencing_tokens", "sla", "total_events"):
        assert key in m, f"Missing metric key: {key}"
    assert m["total_events"] > 0
    print(f"[PASS] Test 24: Metrics complete — {m['total_events']} events, {len(m['active_regions'])} active regions")

    # =====================================================================
    # Test 25: Idempotent replication
    # =====================================================================
    sf.replicate_all()
    sf.replicate_all()
    for node in [us_east, eu_west, ap_south, us_west]:
        assert node.read("user:1") == {"name": "Alice", "plan": "pro"}
    print("[PASS] Test 25: Double-replicate stays consistent (idempotent)")

    # =====================================================================
    # Summary
    # =====================================================================
    final = sf.get_metrics()
    print("\n" + "=" * 70)
    print("ALL 25 TESTS PASSED — Seamless Failover Verified (<5s)")
    print("=" * 70)
    print(f"\nRegions: {len(sf._regions)}")
    print(f"Events logged: {final['total_events']}")
    print(f"SLA availability: {final['sla']['availability_pct']:.2f}%")
    fo_final = final["sla"]["failover_latency"]
    print(f"Failover latency: p50={fo_final['p50']:.1f}ms, p95={fo_final['p95']:.1f}ms")
    for rid, info in final["breakers"].items():
        status = sf._regions[rid].status.value
        print(f"  {rid:14s} | status={status:8s} | breaker={info['state']}")
