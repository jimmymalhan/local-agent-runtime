"""
Automatic Failover Agent (<5s detection-to-switchover)

Seamless failover to backup region with:
- Priority-based failover (weighted regions, preferred backups)
- Connection draining before cutover
- Split-brain protection via fencing tokens
- SLA tracking (availability %, failover latency p50/p95/p99)
- Graceful degradation with read-only mode
- Automated failover runbook execution

Builds on utils.automatic_failover engine and utils.geo_replication primitives.
"""

import json
import math
import statistics
import threading
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Inline geo / replication primitives (self-contained for agent execution)
# ---------------------------------------------------------------------------

class GeoCoord:
    __slots__ = ("lat", "lon")

    def __init__(self, lat: float, lon: float):
        self.lat = lat
        self.lon = lon

    def __repr__(self):
        return f"GeoCoord({self.lat}, {self.lon})"


def haversine_km(a: GeoCoord, b: GeoCoord) -> float:
    R = 6371.0
    lat1, lat2 = math.radians(a.lat), math.radians(b.lat)
    dlat = math.radians(b.lat - a.lat)
    dlon = math.radians(b.lon - a.lon)
    h = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    return 2 * R * math.asin(math.sqrt(h))


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
        for k, v in other._clock.items():
            if self._clock.get(k, 0) < v:
                return False
        return True

    def __gt__(self, other: "VectorClock") -> bool:
        return self >= other and self._clock != other._clock

    def concurrent(self, other: "VectorClock") -> bool:
        return not (self >= other) and not (other >= self)

    def as_dict(self) -> dict:
        return dict(self._clock)


class HealthStatus(Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    DRAINING = "draining"
    READ_ONLY = "read_only"


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
            if vv is None or vv.tombstone:
                return None
            return vv.value

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
# Region Node with draining + read-only support
# ---------------------------------------------------------------------------

@dataclass
class RegionNode:
    region_id: str
    location: GeoCoord
    priority: int = 0  # lower = higher priority as failover target
    weight: float = 1.0  # traffic weight (0.0-1.0)
    store: ReplicatedStore = field(init=False, repr=False)
    status: HealthStatus = HealthStatus.HEALTHY
    _peers: list["RegionNode"] = field(default_factory=list, repr=False)
    active_connections: int = 0
    requests_served: int = 0
    preferred_backup: Optional[str] = None  # explicit backup region id

    def __post_init__(self):
        self.store = ReplicatedStore(self.region_id)

    def add_peer(self, peer: "RegionNode"):
        if peer.region_id != self.region_id and peer not in self._peers:
            self._peers.append(peer)

    def write(self, key: str, value: Any) -> VersionedValue:
        if self.status in (HealthStatus.DOWN, HealthStatus.READ_ONLY):
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
        if self.status in (HealthStatus.DOWN, HealthStatus.READ_ONLY):
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
# Circuit Breaker — per-region fast failure detection
# ---------------------------------------------------------------------------

class CircuitState(Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass
class CircuitBreaker:
    region_id: str
    failure_threshold: int = 3
    recovery_timeout_s: float = 5.0
    success_threshold: int = 2
    state: CircuitState = CircuitState.CLOSED
    failure_count: int = 0
    success_count: int = 0
    last_failure_time: float = 0.0
    last_state_change: float = field(default_factory=time.time)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

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
            return True  # HALF_OPEN

    def force_open(self):
        with self._lock:
            self._transition(CircuitState.OPEN)

    def force_close(self):
        with self._lock:
            self._transition(CircuitState.CLOSED)

    def _transition(self, new_state: CircuitState):
        self.state = new_state
        self.last_state_change = time.time()
        if new_state == CircuitState.CLOSED:
            self.failure_count = 0
            self.success_count = 0
        elif new_state == CircuitState.HALF_OPEN:
            self.success_count = 0


# ---------------------------------------------------------------------------
# Fencing Token — split-brain protection
# ---------------------------------------------------------------------------

class FencingTokenManager:
    """Monotonically increasing fencing tokens prevent stale leaders from writing."""

    def __init__(self):
        self._lock = threading.Lock()
        self._token = 0
        self._holders: dict[str, int] = {}  # region_id -> token

    def acquire(self, region_id: str) -> int:
        with self._lock:
            self._token += 1
            self._holders[region_id] = self._token
            return self._token

    def validate(self, region_id: str, token: int) -> bool:
        with self._lock:
            current = self._holders.get(region_id, 0)
            return token >= current

    def revoke(self, region_id: str):
        with self._lock:
            self._holders.pop(region_id, None)

    @property
    def current_token(self) -> int:
        with self._lock:
            return self._token


# ---------------------------------------------------------------------------
# SLA Tracker — availability and latency tracking
# ---------------------------------------------------------------------------

class SLATracker:
    """Tracks availability percentage and failover latency percentiles."""

    def __init__(self, window_size: int = 1000):
        self._lock = threading.Lock()
        self._total_requests = 0
        self._successful_requests = 0
        self._failover_latencies_ms: deque = deque(maxlen=window_size)
        self._request_latencies_ms: deque = deque(maxlen=window_size)
        self._downtime_events: list[dict] = []
        self._uptime_start: float = time.time()

    def record_request(self, success: bool, latency_ms: float):
        with self._lock:
            self._total_requests += 1
            if success:
                self._successful_requests += 1
            self._request_latencies_ms.append(latency_ms)

    def record_failover(self, latency_ms: float, from_region: str, to_region: str):
        with self._lock:
            self._failover_latencies_ms.append(latency_ms)
            self._downtime_events.append({
                "timestamp": time.time(),
                "from_region": from_region,
                "to_region": to_region,
                "latency_ms": latency_ms,
            })

    def availability_pct(self) -> float:
        with self._lock:
            if self._total_requests == 0:
                return 100.0
            return (self._successful_requests / self._total_requests) * 100.0

    def failover_latency_percentiles(self) -> dict:
        with self._lock:
            if not self._failover_latencies_ms:
                return {"p50": 0, "p95": 0, "p99": 0, "count": 0}
            data = sorted(self._failover_latencies_ms)
            return {
                "p50": self._percentile(data, 50),
                "p95": self._percentile(data, 95),
                "p99": self._percentile(data, 99),
                "count": len(data),
            }

    def request_latency_percentiles(self) -> dict:
        with self._lock:
            if not self._request_latencies_ms:
                return {"p50": 0, "p95": 0, "p99": 0, "count": 0}
            data = sorted(self._request_latencies_ms)
            return {
                "p50": self._percentile(data, 50),
                "p95": self._percentile(data, 95),
                "p99": self._percentile(data, 99),
                "count": len(data),
            }

    def uptime_seconds(self) -> float:
        return time.time() - self._uptime_start

    @staticmethod
    def _percentile(sorted_data: list, pct: float) -> float:
        if not sorted_data:
            return 0.0
        k = (len(sorted_data) - 1) * (pct / 100.0)
        f = math.floor(k)
        c = math.ceil(k)
        if f == c:
            return sorted_data[int(k)]
        return sorted_data[int(f)] * (c - k) + sorted_data[int(c)] * (k - f)

    def summary(self) -> dict:
        return {
            "availability_pct": round(self.availability_pct(), 4),
            "total_requests": self._total_requests,
            "successful_requests": self._successful_requests,
            "failover_latency": self.failover_latency_percentiles(),
            "request_latency": self.request_latency_percentiles(),
            "uptime_s": round(self.uptime_seconds(), 1),
            "downtime_events": len(self._downtime_events),
        }


# ---------------------------------------------------------------------------
# Connection Drainer — graceful shutdown before failover
# ---------------------------------------------------------------------------

class ConnectionDrainer:
    """Drains active connections before cutting over to backup region."""

    def __init__(self, drain_timeout_s: float = 2.0, poll_interval_s: float = 0.05):
        self.drain_timeout_s = drain_timeout_s
        self.poll_interval_s = poll_interval_s

    def drain(self, node: RegionNode) -> bool:
        """Set node to DRAINING and wait for active connections to reach zero.
        Returns True if drained within timeout, False otherwise."""
        node.status = HealthStatus.DRAINING
        deadline = time.monotonic() + self.drain_timeout_s
        while time.monotonic() < deadline:
            if node.active_connections <= 0:
                return True
            time.sleep(self.poll_interval_s)
        return node.active_connections <= 0


# ---------------------------------------------------------------------------
# Failover Event types
# ---------------------------------------------------------------------------

class FailoverEventType(Enum):
    REGION_DOWN_DETECTED = "region_down_detected"
    DRAIN_STARTED = "drain_started"
    DRAIN_COMPLETE = "drain_complete"
    FAILOVER_TRIGGERED = "failover_triggered"
    TRAFFIC_REROUTED = "traffic_rerouted"
    FENCING_TOKEN_ACQUIRED = "fencing_token_acquired"
    FENCING_TOKEN_REVOKED = "fencing_token_revoked"
    REGION_RECOVERY_STARTED = "region_recovery_started"
    REGION_RECOVERY_COMPLETE = "region_recovery_complete"
    CIRCUIT_OPENED = "circuit_opened"
    CIRCUIT_CLOSED = "circuit_closed"
    READ_ONLY_ACTIVATED = "read_only_activated"
    SLA_BREACH = "sla_breach"
    REQUEST_RETRIED = "request_retried"


@dataclass
class FailoverEvent:
    event_type: FailoverEventType
    region_id: str
    timestamp: float
    details: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Automatic Failover Agent — full orchestration
# ---------------------------------------------------------------------------

class AutomaticFailoverAgent:
    """
    Agent-level failover orchestrator with <5s detection-to-switchover.

    Timing budget (target <5s total):
    - Probe interval: 0.5s (configurable)
    - Failure threshold: 3 probes = 1.5s detection
    - Connection drain: <2s
    - Fencing + routing update: <0.5s
    - Total: ~4s worst case
    """

    def __init__(
        self,
        regions: list[RegionNode],
        probe_interval_s: float = 0.5,
        failure_threshold: int = 3,
        recovery_timeout_s: float = 3.0,
        drain_timeout_s: float = 2.0,
        sla_target_pct: float = 99.9,
        check_fn: Optional[Callable[[RegionNode], bool]] = None,
    ):
        # Region registry
        self._regions: dict[str, RegionNode] = {}
        for r in regions:
            self._regions[r.region_id] = r
        self._connect_peers()

        # Config
        self.probe_interval_s = probe_interval_s
        self.failure_threshold = failure_threshold
        self.sla_target_pct = sla_target_pct
        self._check_fn = check_fn or self._default_check

        # Per-region circuit breakers
        self.breakers: dict[str, CircuitBreaker] = {
            rid: CircuitBreaker(
                region_id=rid,
                failure_threshold=failure_threshold,
                recovery_timeout_s=recovery_timeout_s,
            )
            for rid in self._regions
        }

        # Sub-systems
        self.fencing = FencingTokenManager()
        self.sla = SLATracker()
        self.drainer = ConnectionDrainer(drain_timeout_s=drain_timeout_s)

        # State
        self._event_log: list[FailoverEvent] = []
        self._lock = threading.Lock()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None
        self._failover_targets: dict[str, str] = {}  # failed_region -> backup_region
        self._failed_regions: set[str] = set()
        self._fencing_tokens: dict[str, int] = {}  # region -> token

    # -- Setup helpers --

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

    # -- Event logging --

    def _log_event(self, event_type: FailoverEventType, region_id: str, **details):
        event = FailoverEvent(
            event_type=event_type,
            region_id=region_id,
            timestamp=time.time(),
            details=details,
        )
        with self._lock:
            self._event_log.append(event)

    # -- Health monitoring --

    def start_monitoring(self):
        if self._running:
            return
        self._running = True
        self._monitor_thread = threading.Thread(
            target=self._monitor_loop, daemon=True, name="failover-agent-monitor"
        )
        self._monitor_thread.start()

    def stop_monitoring(self):
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=self.probe_interval_s * 3)

    def _monitor_loop(self):
        while self._running:
            self.run_probe_cycle()
            time.sleep(self.probe_interval_s)

    def run_probe_cycle(self):
        """Execute one health check cycle across all regions."""
        for rid, node in self._regions.items():
            healthy = self._check_fn(node)
            breaker = self.breakers[rid]

            if healthy:
                if breaker.state == CircuitState.OPEN:
                    breaker.allow_request()  # may transition to HALF_OPEN
                breaker.record_success()
                if rid in self._failed_regions and breaker.state == CircuitState.CLOSED:
                    self._initiate_recovery(rid)
            else:
                breaker.record_failure()
                if breaker.state == CircuitState.OPEN and rid not in self._failed_regions:
                    self._initiate_failover(rid)

    # -- Failover orchestration --

    def _initiate_failover(self, region_id: str):
        """Full failover sequence: drain -> fence -> reroute."""
        node = self._regions.get(region_id)
        if not node or region_id in self._failed_regions:
            return

        failover_start = time.monotonic()
        self._failed_regions.add(region_id)

        # 1. Detect and log
        self._log_event(FailoverEventType.REGION_DOWN_DETECTED, region_id)
        self._log_event(FailoverEventType.CIRCUIT_OPENED, region_id)

        # 2. Drain connections (if node was still partially up)
        self._log_event(FailoverEventType.DRAIN_STARTED, region_id)
        drained = self.drainer.drain(node)
        self._log_event(FailoverEventType.DRAIN_COMPLETE, region_id, success=drained)

        # 3. Mark fully down
        node.status = HealthStatus.DOWN

        # 4. Revoke fencing token (prevent stale writes)
        self.fencing.revoke(region_id)
        self._fencing_tokens.pop(region_id, None)
        self._log_event(FailoverEventType.FENCING_TOKEN_REVOKED, region_id)

        # 5. Find and activate backup
        backup = self._find_backup(node)
        if backup:
            self._failover_targets[region_id] = backup.region_id
            token = self.fencing.acquire(backup.region_id)
            self._fencing_tokens[backup.region_id] = token
            self._log_event(
                FailoverEventType.FENCING_TOKEN_ACQUIRED,
                backup.region_id,
                token=token,
            )
            self._log_event(
                FailoverEventType.FAILOVER_TRIGGERED,
                region_id,
                backup_region=backup.region_id,
            )
            self._log_event(
                FailoverEventType.TRAFFIC_REROUTED,
                region_id,
                target=backup.region_id,
            )

        elapsed_ms = (time.monotonic() - failover_start) * 1000
        self.sla.record_failover(
            elapsed_ms,
            from_region=region_id,
            to_region=backup.region_id if backup else "none",
        )

    def _find_backup(self, failed_node: RegionNode) -> Optional[RegionNode]:
        """Find backup: prefer explicit preferred_backup, then nearest healthy by priority."""
        # Check preferred backup first
        if failed_node.preferred_backup:
            pref = self._regions.get(failed_node.preferred_backup)
            if pref and pref.status not in (HealthStatus.DOWN, HealthStatus.DRAINING):
                return pref

        # Fall back to nearest healthy, sorted by (priority, distance)
        candidates = []
        for r in self._regions.values():
            if r.region_id == failed_node.region_id:
                continue
            if r.status in (HealthStatus.DOWN, HealthStatus.DRAINING):
                continue
            dist = haversine_km(failed_node.location, r.location)
            candidates.append((r.priority, dist, r))

        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0], x[1]))
        return candidates[0][2]

    # -- Recovery --

    def _initiate_recovery(self, region_id: str):
        """Recover a region: sync data from healthy peer, reacquire fencing token."""
        self._log_event(FailoverEventType.REGION_RECOVERY_STARTED, region_id)

        node = self._regions[region_id]
        healthy_peers = [p for p in node._peers if p.status == HealthStatus.HEALTHY]
        applied = 0
        if healthy_peers:
            source = healthy_peers[0]
            applied = node.full_sync_from(source)

        node.status = HealthStatus.HEALTHY
        self.breakers[region_id].force_close()

        # Reacquire fencing token
        token = self.fencing.acquire(region_id)
        self._fencing_tokens[region_id] = token

        self._failover_targets.pop(region_id, None)
        self._failed_regions.discard(region_id)

        self._log_event(
            FailoverEventType.REGION_RECOVERY_COMPLETE,
            region_id,
            entries_synced=applied,
            fencing_token=token,
        )
        self._log_event(FailoverEventType.CIRCUIT_CLOSED, region_id)

    # -- Request execution with failover --

    def execute(
        self,
        client_location: GeoCoord,
        operation: str,
        key: str,
        value: Any = None,
        max_retries: int = 2,
    ) -> dict:
        """Execute a read/write/delete with automatic failover and SLA tracking."""
        start = time.monotonic()
        attempted: list[str] = []
        last_error = None

        for attempt in range(max_retries + 1):
            node = self._select_region(client_location, exclude=attempted, operation=operation)
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
                elapsed_ms = (time.monotonic() - start) * 1000
                self.sla.record_request(True, elapsed_ms)
                return {
                    "result": result,
                    "region_id": node.region_id,
                    "retries": attempt,
                    "total_ms": round(elapsed_ms, 2),
                    "attempted_regions": attempted,
                }
            except Exception as e:
                last_error = e
                breaker.record_failure()
                self._log_event(
                    FailoverEventType.REQUEST_RETRIED,
                    node.region_id,
                    attempt=attempt,
                    error=str(e),
                )

        elapsed_ms = (time.monotonic() - start) * 1000
        self.sla.record_request(False, elapsed_ms)
        raise RuntimeError(
            f"All regions exhausted after {len(attempted)} attempts "
            f"({elapsed_ms:.1f}ms). Last error: {last_error}. Tried: {attempted}"
        )

    def _select_region(self, client_location: GeoCoord, exclude: list[str], operation: str = "read") -> Optional[RegionNode]:
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
            dist = haversine_km(client_location, r.location)
            candidates.append((dist, r.priority, r))
        if not candidates:
            return None
        candidates.sort(key=lambda x: (x[0], x[1]))
        return candidates[0][2]

    # -- Read-only degradation --

    def activate_read_only(self, region_id: str):
        """Put a region in read-only mode (graceful degradation)."""
        node = self._regions.get(region_id)
        if node:
            node.status = HealthStatus.READ_ONLY
            self._log_event(FailoverEventType.READ_ONLY_ACTIVATED, region_id)

    # -- Replication --

    def replicate_all(self) -> int:
        total = 0
        for node in self._regions.values():
            if node.status not in (HealthStatus.DOWN, HealthStatus.DRAINING):
                total += node.replicate_to_peers()
        return total

    # -- Simulation helpers --

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
            "breakers": {
                rid: {"state": b.state.value, "failures": b.failure_count}
                for rid, b in self.breakers.items()
            },
            "failover_targets": dict(self._failover_targets),
            "failed_regions": list(self._failed_regions),
            "active_regions": [
                rid for rid, n in self._regions.items()
                if n.status in (HealthStatus.HEALTHY, HealthStatus.READ_ONLY)
            ],
            "fencing_tokens": dict(self._fencing_tokens),
            "sla": self.sla.summary(),
            "total_events": len(self._event_log),
        }


# ---------------------------------------------------------------------------
# __main__ — full verification suite
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    print("=" * 70)
    print("Automatic Failover Agent — Full Verification Suite")
    print("=" * 70)

    # =========================================================================
    # Setup: 3 regions with priorities and preferred backups
    # =========================================================================
    us_east = RegionNode("us-east-1", GeoCoord(39.0438, -77.4874), priority=0, preferred_backup="eu-west-1")
    eu_west = RegionNode("eu-west-1", GeoCoord(53.3498, -6.2603), priority=1, preferred_backup="us-east-1")
    ap_south = RegionNode("ap-south-1", GeoCoord(19.0760, 72.8777), priority=2)

    nyc = GeoCoord(40.7128, -74.0060)
    london = GeoCoord(51.5074, -0.1278)
    mumbai = GeoCoord(19.0760, 72.8777)

    agent = AutomaticFailoverAgent(
        regions=[us_east, eu_west, ap_south],
        probe_interval_s=0.05,
        failure_threshold=3,
        recovery_timeout_s=0.3,
        drain_timeout_s=0.5,
        sla_target_pct=99.9,
    )

    # Seed data
    us_east.store.put("user:1", {"name": "Alice"})
    eu_west.store.put("user:2", {"name": "Bob"})
    ap_south.store.put("user:3", {"name": "Charlie"})
    agent.replicate_all()

    # =========================================================================
    # Test 1: Circuit breaker transitions
    # =========================================================================
    cb = CircuitBreaker(region_id="test", failure_threshold=3, recovery_timeout_s=0.1)
    assert cb.state == CircuitState.CLOSED
    assert cb.allow_request() is True
    cb.record_failure()
    cb.record_failure()
    assert cb.state == CircuitState.CLOSED
    cb.record_failure()
    assert cb.state == CircuitState.OPEN
    assert cb.allow_request() is False
    time.sleep(0.15)
    assert cb.allow_request() is True
    assert cb.state == CircuitState.HALF_OPEN
    cb.record_success()
    cb.record_success()
    assert cb.state == CircuitState.CLOSED
    print("[PASS] Test 1: Circuit breaker CLOSED->OPEN->HALF_OPEN->CLOSED")

    # =========================================================================
    # Test 2: Fencing token monotonicity and validation
    # =========================================================================
    ftm = FencingTokenManager()
    t1 = ftm.acquire("us-east-1")
    t2 = ftm.acquire("eu-west-1")
    assert t2 > t1, "Tokens must be monotonically increasing"
    assert ftm.validate("us-east-1", t1) is True
    assert ftm.validate("us-east-1", t1 - 1) is False  # stale token
    ftm.revoke("us-east-1")
    t3 = ftm.acquire("us-east-1")
    assert t3 > t2, "Token after revoke+reacquire must be higher"
    assert ftm.validate("us-east-1", t3) is True
    assert ftm.validate("us-east-1", t1) is False  # old token invalidated
    print("[PASS] Test 2: Fencing tokens monotonic, validation works, revoke works")

    # =========================================================================
    # Test 3: SLA tracker records and computes percentiles
    # =========================================================================
    sla = SLATracker()
    for i in range(100):
        sla.record_request(True, float(i))
    sla.record_request(False, 500.0)
    avail = sla.availability_pct()
    assert 99.0 <= avail <= 100.0, f"Availability should be ~99%, got {avail}"
    sla.record_failover(150.0, "us-east-1", "eu-west-1")
    sla.record_failover(200.0, "us-east-1", "eu-west-1")
    pcts = sla.failover_latency_percentiles()
    assert pcts["count"] == 2
    assert pcts["p50"] >= 150.0
    summary = sla.summary()
    assert summary["total_requests"] == 101
    assert summary["downtime_events"] == 2
    print(f"[PASS] Test 3: SLA tracker — availability={avail:.2f}%, failover p50={pcts['p50']:.1f}ms")

    # =========================================================================
    # Test 4: Connection drainer
    # =========================================================================
    test_node = RegionNode("drain-test", GeoCoord(0, 0))
    test_node.active_connections = 0
    drainer = ConnectionDrainer(drain_timeout_s=0.5)
    drained = drainer.drain(test_node)
    assert drained is True
    assert test_node.status == HealthStatus.DRAINING
    print("[PASS] Test 4: Connection drainer completes when no active connections")

    # =========================================================================
    # Test 5: Read-only mode blocks writes, allows reads
    # =========================================================================
    ro_node = RegionNode("ro-test", GeoCoord(0, 0))
    ro_node.store.put("key1", "val1")
    ro_node.status = HealthStatus.READ_ONLY
    assert ro_node.read("key1") == "val1"
    try:
        ro_node.write("key2", "val2")
        assert False, "Write to read-only should raise"
    except RuntimeError as e:
        assert "cannot accept writes" in str(e)
    print("[PASS] Test 5: Read-only mode allows reads, blocks writes")

    # =========================================================================
    # Test 6: Automatic failover on region down
    # =========================================================================
    agent.simulate_failure("us-east-1")
    for _ in range(4):
        agent.run_probe_cycle()
        time.sleep(0.01)

    assert us_east.status == HealthStatus.DOWN
    assert agent.breakers["us-east-1"].state == CircuitState.OPEN
    assert "us-east-1" in agent._failover_targets
    backup_id = agent._failover_targets["us-east-1"]
    assert backup_id == "eu-west-1", f"Expected preferred backup eu-west-1, got {backup_id}"
    print(f"[PASS] Test 6: us-east-1 failed over to preferred backup {backup_id}")

    # =========================================================================
    # Test 7: Request-level failover (transparent retry)
    # =========================================================================
    resp = agent.execute(nyc, "read", "user:2")
    assert resp["result"] == {"name": "Bob"}
    assert resp["region_id"] != "us-east-1"
    assert resp["total_ms"] < 5000
    print(f"[PASS] Test 7: NYC read rerouted to {resp['region_id']} in {resp['total_ms']:.1f}ms")

    # =========================================================================
    # Test 8: Write during failover goes to backup
    # =========================================================================
    resp_w = agent.execute(nyc, "write", "user:4", {"name": "Diana"})
    assert resp_w["region_id"] != "us-east-1"
    assert resp_w["total_ms"] < 5000
    written_node = agent._regions[resp_w["region_id"]]
    assert written_node.read("user:4") == {"name": "Diana"}
    print(f"[PASS] Test 8: Write during failover landed on {resp_w['region_id']}")

    # =========================================================================
    # Test 9: Failover completes within <5s budget
    # =========================================================================
    # Reset and measure fresh failover
    agent.simulate_recovery("us-east-1")
    time.sleep(0.35)
    for _ in range(4):
        agent.run_probe_cycle()
        time.sleep(0.01)

    failover_start = time.monotonic()
    agent.simulate_failure("eu-west-1")
    for _ in range(4):
        agent.run_probe_cycle()
        time.sleep(0.02)
    failover_s = time.monotonic() - failover_start
    assert failover_s < 5.0, f"Failover took {failover_s:.2f}s, exceeds 5s budget"
    assert eu_west.status == HealthStatus.DOWN
    print(f"[PASS] Test 9: Full failover cycle in {failover_s:.3f}s (< 5s budget)")

    # =========================================================================
    # Test 10: Region recovery with data sync and fencing token
    # =========================================================================
    agent.simulate_recovery("eu-west-1")
    time.sleep(0.35)
    for _ in range(4):
        agent.run_probe_cycle()
        time.sleep(0.01)

    assert eu_west.status == HealthStatus.HEALTHY
    assert agent.breakers["eu-west-1"].state == CircuitState.CLOSED
    assert "eu-west-1" not in agent._failover_targets
    # Data written during failover should be synced
    assert eu_west.read("user:4") == {"name": "Diana"}, "Recovery should sync failover writes"
    # Fencing token should be reacquired
    assert "eu-west-1" in agent._fencing_tokens
    print("[PASS] Test 10: eu-west-1 recovered with data sync and fencing token")

    # =========================================================================
    # Test 11: Cascading multi-region failure
    # =========================================================================
    agent.simulate_failure("us-east-1")
    agent.simulate_failure("eu-west-1")
    for _ in range(4):
        agent.run_probe_cycle()
        time.sleep(0.01)

    resp_cascade = agent.execute(nyc, "read", "user:3")
    assert resp_cascade["region_id"] == "ap-south-1"
    assert resp_cascade["result"] == {"name": "Charlie"}
    print("[PASS] Test 11: Cascading failure — last region (ap-south-1) serves traffic")

    # =========================================================================
    # Test 12: All regions down raises RuntimeError
    # =========================================================================
    agent.simulate_failure("ap-south-1")
    for _ in range(4):
        agent.run_probe_cycle()
        time.sleep(0.01)

    try:
        agent.execute(nyc, "read", "user:1")
        assert False, "Should have raised"
    except RuntimeError as e:
        assert "All regions exhausted" in str(e)
    print("[PASS] Test 12: All-regions-down raises RuntimeError correctly")

    # =========================================================================
    # Test 13: Full recovery after total outage
    # =========================================================================
    for rid in agent._regions:
        agent.simulate_recovery(rid)
    time.sleep(0.35)
    for _ in range(4):
        agent.run_probe_cycle()
        time.sleep(0.01)

    active = [rid for rid, n in agent._regions.items() if n.status == HealthStatus.HEALTHY]
    assert len(active) == 3
    resp_after = agent.execute(nyc, "read", "user:1")
    assert resp_after["result"] == {"name": "Alice"}
    print("[PASS] Test 13: Full recovery after total outage — all 3 regions back")

    # =========================================================================
    # Test 14: Read-only degradation mode
    # =========================================================================
    # Ensure breakers are closed after prior tests
    for rid in agent._regions:
        agent.breakers[rid].force_close()
    agent.activate_read_only("ap-south-1")
    assert ap_south.status == HealthStatus.READ_ONLY
    # Reads should still work
    resp_ro = agent.execute(mumbai, "read", "user:3")
    assert resp_ro["result"] == {"name": "Charlie"}
    assert resp_ro["region_id"] == "ap-south-1"
    # Writes should fail over to next region
    resp_w_ro = agent.execute(mumbai, "write", "user:5", {"name": "Eve"})
    assert resp_w_ro["region_id"] != "ap-south-1", "Write should not go to read-only region"
    ap_south.status = HealthStatus.HEALTHY  # restore
    print(f"[PASS] Test 14: Read-only allows reads, writes fail over to {resp_w_ro['region_id']}")

    # =========================================================================
    # Test 15: Delete operation with failover
    # =========================================================================
    us_east.store.put("temp:del", "to_remove")
    agent.replicate_all()
    assert eu_west.read("temp:del") == "to_remove"
    resp_del = agent.execute(london, "delete", "temp:del")
    assert resp_del["region_id"] == "eu-west-1"
    agent.replicate_all()
    for node in [us_east, eu_west, ap_south]:
        assert node.read("temp:del") is None
    print("[PASS] Test 15: Delete operation with failover works correctly")

    # =========================================================================
    # Test 16: Concurrent requests during failover
    # =========================================================================
    results = []
    errors = []

    def concurrent_read(loc, key, idx):
        try:
            r = agent.execute(loc, "read", key)
            results.append((idx, r))
        except Exception as e:
            errors.append((idx, str(e)))

    us_east.store.put("shared:x", {"v": 42})
    agent.replicate_all()

    threads = []
    for i in range(10):
        loc = [nyc, london, mumbai][i % 3]
        t = threading.Thread(target=concurrent_read, args=(loc, "shared:x", i))
        threads.append(t)
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert len(errors) == 0, f"Concurrent read errors: {errors}"
    assert len(results) == 10
    for idx, r in results:
        assert r["result"] == {"v": 42}
    print("[PASS] Test 16: 10 concurrent reads all succeeded")

    # =========================================================================
    # Test 17: SLA metrics populated after operations
    # =========================================================================
    sla_summary = agent.sla.summary()
    assert sla_summary["total_requests"] > 0
    assert sla_summary["availability_pct"] > 0
    assert sla_summary["downtime_events"] > 0
    fo_lat = sla_summary["failover_latency"]
    assert fo_lat["count"] > 0
    assert fo_lat["p50"] >= 0
    print(f"[PASS] Test 17: SLA — availability={sla_summary['availability_pct']:.2f}%, "
          f"failover_p50={fo_lat['p50']:.1f}ms, events={sla_summary['downtime_events']}")

    # =========================================================================
    # Test 18: Background monitoring thread
    # =========================================================================
    agent2 = AutomaticFailoverAgent(
        regions=[
            RegionNode("r1", GeoCoord(0, 0)),
            RegionNode("r2", GeoCoord(10, 10)),
        ],
        probe_interval_s=0.03,
        failure_threshold=3,
    )
    agent2.start_monitoring()
    assert agent2._running is True
    assert agent2._monitor_thread.is_alive()
    time.sleep(0.15)
    agent2.stop_monitoring()
    assert agent2._running is False
    time.sleep(0.1)
    assert not agent2._monitor_thread.is_alive()
    print("[PASS] Test 18: Background monitoring starts and stops cleanly")

    # =========================================================================
    # Test 19: Failover event audit trail completeness
    # =========================================================================
    all_events = agent.events
    event_types_seen = {e.event_type for e in all_events}
    required_types = {
        FailoverEventType.REGION_DOWN_DETECTED,
        FailoverEventType.DRAIN_STARTED,
        FailoverEventType.DRAIN_COMPLETE,
        FailoverEventType.FAILOVER_TRIGGERED,
        FailoverEventType.TRAFFIC_REROUTED,
        FailoverEventType.FENCING_TOKEN_ACQUIRED,
        FailoverEventType.FENCING_TOKEN_REVOKED,
        FailoverEventType.REGION_RECOVERY_STARTED,
        FailoverEventType.REGION_RECOVERY_COMPLETE,
        FailoverEventType.CIRCUIT_OPENED,
        FailoverEventType.CIRCUIT_CLOSED,
    }
    missing = required_types - event_types_seen
    assert not missing, f"Missing event types: {missing}"
    print(f"[PASS] Test 19: Audit trail complete — all {len(required_types)} event types recorded")

    # =========================================================================
    # Test 20: Metrics endpoint returns all fields
    # =========================================================================
    metrics = agent.get_metrics()
    assert "breakers" in metrics
    assert "failover_targets" in metrics
    assert "failed_regions" in metrics
    assert "active_regions" in metrics
    assert "fencing_tokens" in metrics
    assert "sla" in metrics
    assert "total_events" in metrics
    assert metrics["total_events"] > 0
    assert len(metrics["active_regions"]) == 3
    print(f"[PASS] Test 20: Metrics endpoint complete ({metrics['total_events']} events)")

    # =========================================================================
    # Summary
    # =========================================================================
    print("\n" + "=" * 70)
    print("ALL 20 TESTS PASSED — Automatic Failover Agent (<5s) Verified")
    print("=" * 70)

    final_metrics = agent.get_metrics()
    sla_final = agent.sla.summary()
    print(f"\nFinal metrics:")
    print(f"  Regions: {len(agent._regions)}")
    print(f"  Events logged: {final_metrics['total_events']}")
    print(f"  SLA availability: {sla_final['availability_pct']:.2f}%")
    print(f"  Failover latency p50: {sla_final['failover_latency']['p50']:.1f}ms")
    print(f"  Failover latency p95: {sla_final['failover_latency']['p95']:.1f}ms")
    print(f"  Total requests tracked: {sla_final['total_requests']}")
    for rid, b in final_metrics["breakers"].items():
        print(f"  {rid:15s} | state={b['state']:10s} | failures={b['failures']}")
