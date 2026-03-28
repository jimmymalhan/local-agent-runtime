"""
Automatic Failover Engine (<5s detection + switchover)

Monitors region health via heartbeats, detects failures within configurable
thresholds, and seamlessly reroutes traffic to the nearest healthy backup region.
Includes connection draining, data resync on recovery, and split-brain protection.
"""

import json
import math
import threading
import time
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Optional

try:
    from utils.geo_replication import (
        FailoverController,
        GeoCoord,
        GeoRouter,
        HealthStatus,
        RegionNode,
        ReplicatedStore,
        ReplicationMonitor,
        haversine_km,
    )
except ImportError:
    import sys, os
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    from utils.geo_replication import (
        FailoverController,
        GeoCoord,
        GeoRouter,
        HealthStatus,
        RegionNode,
        ReplicatedStore,
        ReplicationMonitor,
        haversine_km,
    )


# ---------------------------------------------------------------------------
# Health probe results
# ---------------------------------------------------------------------------

class ProbeResult(Enum):
    OK = "ok"
    TIMEOUT = "timeout"
    ERROR = "error"
    DEGRADED = "degraded"


@dataclass
class HealthProbe:
    region_id: str
    result: ProbeResult
    latency_ms: float
    timestamp: float = field(default_factory=time.time)

    @property
    def is_healthy(self) -> bool:
        return self.result == ProbeResult.OK

    @property
    def is_degraded(self) -> bool:
        return self.result == ProbeResult.DEGRADED


# ---------------------------------------------------------------------------
# Failover event log
# ---------------------------------------------------------------------------

class FailoverEventType(Enum):
    REGION_DOWN_DETECTED = "region_down_detected"
    FAILOVER_STARTED = "failover_started"
    FAILOVER_COMPLETE = "failover_complete"
    TRAFFIC_REROUTED = "traffic_rerouted"
    REGION_RECOVERY_STARTED = "region_recovery_started"
    REGION_RECOVERY_COMPLETE = "region_recovery_complete"
    SPLIT_BRAIN_DETECTED = "split_brain_detected"
    DRAIN_STARTED = "drain_started"
    DRAIN_COMPLETE = "drain_complete"


@dataclass
class FailoverEvent:
    event_type: FailoverEventType
    region_id: str
    timestamp: float = field(default_factory=time.time)
    details: dict = field(default_factory=dict)

    def __repr__(self) -> str:
        return f"[{self.event_type.value}] {self.region_id} @ {self.timestamp:.3f} {self.details}"


# ---------------------------------------------------------------------------
# Connection drainer — gracefully finish in-flight requests
# ---------------------------------------------------------------------------

class ConnectionDrainer:
    def __init__(self, drain_timeout_s: float = 2.0):
        self.drain_timeout_s = drain_timeout_s
        self._active_connections: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def add_connection(self, region_id: str):
        with self._lock:
            self._active_connections[region_id] += 1

    def remove_connection(self, region_id: str):
        with self._lock:
            self._active_connections[region_id] = max(
                0, self._active_connections[region_id] - 1
            )

    def active_count(self, region_id: str) -> int:
        with self._lock:
            return self._active_connections.get(region_id, 0)

    def drain(self, region_id: str) -> float:
        """Drain connections for a region. Returns time spent draining."""
        start = time.time()
        deadline = start + self.drain_timeout_s
        while time.time() < deadline:
            if self.active_count(region_id) == 0:
                break
            time.sleep(0.01)
        elapsed = time.time() - start
        # Force-close any remaining after timeout
        with self._lock:
            self._active_connections[region_id] = 0
        return elapsed


# ---------------------------------------------------------------------------
# Health checker — continuous heartbeat monitor
# ---------------------------------------------------------------------------

class HealthChecker:
    def __init__(
        self,
        probe_interval_s: float = 0.5,
        failure_threshold: int = 3,
        recovery_threshold: int = 3,
        timeout_ms: float = 1000.0,
        degraded_latency_ms: float = 500.0,
    ):
        self.probe_interval_s = probe_interval_s
        self.failure_threshold = failure_threshold
        self.recovery_threshold = recovery_threshold
        self.timeout_ms = timeout_ms
        self.degraded_latency_ms = degraded_latency_ms

        self._consecutive_failures: dict[str, int] = defaultdict(int)
        self._consecutive_successes: dict[str, int] = defaultdict(int)
        self._last_probe: dict[str, HealthProbe] = {}
        self._probe_history: dict[str, list[HealthProbe]] = defaultdict(list)
        self._lock = threading.Lock()

        # Pluggable probe function: region_id -> (ok: bool, latency_ms: float)
        self._probe_fn: Optional[Callable[[str], tuple[bool, float]]] = None

        # Simulated failures for testing
        self._simulated_failures: set[str] = set()

    def set_probe_fn(self, fn: Callable[[str], tuple[bool, float]]):
        self._probe_fn = fn

    def simulate_failure(self, region_id: str):
        self._simulated_failures.add(region_id)

    def clear_simulated_failure(self, region_id: str):
        self._simulated_failures.discard(region_id)

    def probe(self, region_id: str) -> HealthProbe:
        """Execute a single health probe against a region."""
        if region_id in self._simulated_failures:
            result = HealthProbe(
                region_id=region_id,
                result=ProbeResult.TIMEOUT,
                latency_ms=self.timeout_ms,
            )
        elif self._probe_fn:
            try:
                ok, latency = self._probe_fn(region_id)
                if not ok:
                    probe_result = ProbeResult.ERROR
                elif latency > self.degraded_latency_ms:
                    probe_result = ProbeResult.DEGRADED
                else:
                    probe_result = ProbeResult.OK
                result = HealthProbe(
                    region_id=region_id,
                    result=probe_result,
                    latency_ms=latency,
                )
            except Exception:
                result = HealthProbe(
                    region_id=region_id,
                    result=ProbeResult.ERROR,
                    latency_ms=self.timeout_ms,
                )
        else:
            # Default: region is healthy with low latency
            result = HealthProbe(
                region_id=region_id,
                result=ProbeResult.OK,
                latency_ms=1.0,
            )

        with self._lock:
            self._last_probe[region_id] = result
            self._probe_history[region_id].append(result)
            # Keep last 100 probes
            if len(self._probe_history[region_id]) > 100:
                self._probe_history[region_id] = self._probe_history[region_id][-100:]

        return result

    def update_counters(self, region_id: str, probe: HealthProbe) -> Optional[str]:
        """
        Update failure/success counters. Returns:
          'down' if failure threshold crossed,
          'recovered' if recovery threshold crossed,
          'degraded' if probe shows degradation,
          None otherwise.
        """
        with self._lock:
            if not probe.is_healthy:
                self._consecutive_failures[region_id] += 1
                self._consecutive_successes[region_id] = 0
                if self._consecutive_failures[region_id] >= self.failure_threshold:
                    return "down"
                return None
            else:
                self._consecutive_failures[region_id] = 0
                self._consecutive_successes[region_id] += 1
                if self._consecutive_successes[region_id] >= self.recovery_threshold:
                    return "recovered"
                if probe.is_degraded:
                    return "degraded"
                return None

    def get_probe_history(self, region_id: str, count: int = 10) -> list[HealthProbe]:
        with self._lock:
            return list(self._probe_history.get(region_id, [])[-count:])

    def reset(self, region_id: str):
        with self._lock:
            self._consecutive_failures[region_id] = 0
            self._consecutive_successes[region_id] = 0


# ---------------------------------------------------------------------------
# Split-brain detector
# ---------------------------------------------------------------------------

class SplitBrainDetector:
    """
    Detects split-brain scenarios where partitioned regions diverge.
    Compares key checksums across regions to find inconsistencies
    that exceed normal replication lag.
    """

    def __init__(self, max_divergence_pct: float = 5.0):
        self.max_divergence_pct = max_divergence_pct

    def check(self, router: GeoRouter) -> tuple[bool, dict]:
        """Returns (is_split_brain, details)."""
        consistency = router.global_consistency_check()
        total = len(consistency)
        if total == 0:
            return False, {"total_keys": 0, "divergent_keys": 0}

        divergent = sum(1 for v in consistency.values() if not v)
        pct = (divergent / total) * 100

        details = {
            "total_keys": total,
            "divergent_keys": divergent,
            "divergence_pct": round(pct, 2),
            "threshold_pct": self.max_divergence_pct,
            "divergent_key_names": [k for k, v in consistency.items() if not v],
        }

        return pct > self.max_divergence_pct, details


# ---------------------------------------------------------------------------
# Automatic Failover Manager
# ---------------------------------------------------------------------------

class AutoFailoverManager:
    """
    Orchestrates automatic failover with <5s detection and switchover.

    Lifecycle:
      1. HealthChecker probes each region at probe_interval_s
      2. After failure_threshold consecutive failures -> region marked DOWN
      3. ConnectionDrainer drains in-flight requests (max drain_timeout_s)
      4. GeoRouter automatically routes to next-nearest healthy region
      5. On recovery: full resync from healthy peer, then mark HEALTHY

    Total failover time budget:
      - Detection: failure_threshold * probe_interval_s  (e.g. 3 * 0.5s = 1.5s)
      - Drain: drain_timeout_s (e.g. 2.0s)
      - Switchover: <0.1s (instant re-routing via GeoRouter)
      - Total: ~3.6s < 5s target
    """

    def __init__(
        self,
        router: GeoRouter,
        probe_interval_s: float = 0.5,
        failure_threshold: int = 3,
        recovery_threshold: int = 3,
        drain_timeout_s: float = 2.0,
        max_divergence_pct: float = 5.0,
    ):
        self.router = router
        self.failover_ctl = FailoverController(router)
        self.health_checker = HealthChecker(
            probe_interval_s=probe_interval_s,
            failure_threshold=failure_threshold,
            recovery_threshold=recovery_threshold,
        )
        self.drainer = ConnectionDrainer(drain_timeout_s=drain_timeout_s)
        self.split_brain = SplitBrainDetector(max_divergence_pct=max_divergence_pct)
        self.monitor = ReplicationMonitor(router)

        self._events: list[FailoverEvent] = []
        self._lock = threading.Lock()
        self._running = False
        self._monitor_thread: Optional[threading.Thread] = None

        # Callbacks
        self._on_failover: Optional[Callable[[str, str], None]] = None  # (down_region, backup_region)
        self._on_recovery: Optional[Callable[[str], None]] = None  # (recovered_region)

        # Track which regions we've failed over, and their backup
        self._failover_map: dict[str, str] = {}  # down_region -> backup_region

    def set_on_failover(self, fn: Callable[[str, str], None]):
        self._on_failover = fn

    def set_on_recovery(self, fn: Callable[[str], None]):
        self._on_recovery = fn

    def _emit(self, event_type: FailoverEventType, region_id: str, **details):
        event = FailoverEvent(event_type=event_type, region_id=region_id, details=details)
        with self._lock:
            self._events.append(event)
        return event

    @property
    def events(self) -> list[FailoverEvent]:
        with self._lock:
            return list(self._events)

    def _find_backup_region(self, failed_region_id: str) -> Optional[str]:
        """Find nearest healthy region to serve as backup."""
        failed = self.router.regions.get(failed_region_id)
        if not failed:
            return None

        candidates = [
            (haversine_km(failed.location, r.location), r.region_id)
            for r in self.router.regions.values()
            if r.region_id != failed_region_id and r.status != HealthStatus.DOWN
        ]
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0])
        return candidates[0][1]

    def execute_failover(self, region_id: str) -> dict:
        """
        Execute a complete failover for a region. Returns timing breakdown.

        Steps:
          1. Mark region as DOWN
          2. Drain connections
          3. Find backup region
          4. Log rerouting
          5. Total time must be <5s
        """
        t_start = time.time()
        result = {
            "region": region_id,
            "success": False,
            "backup_region": None,
            "detection_time_ms": 0,
            "drain_time_ms": 0,
            "switchover_time_ms": 0,
            "total_time_ms": 0,
        }

        # Step 1: Mark DOWN
        self._emit(FailoverEventType.FAILOVER_STARTED, region_id)
        self.failover_ctl.mark_down(region_id)
        self._emit(FailoverEventType.REGION_DOWN_DETECTED, region_id)
        t_after_detect = time.time()
        result["detection_time_ms"] = (t_after_detect - t_start) * 1000

        # Step 2: Drain connections
        self._emit(FailoverEventType.DRAIN_STARTED, region_id)
        drain_time = self.drainer.drain(region_id)
        self._emit(FailoverEventType.DRAIN_COMPLETE, region_id, drain_time_s=drain_time)
        t_after_drain = time.time()
        result["drain_time_ms"] = drain_time * 1000

        # Step 3: Find backup and reroute
        backup = self._find_backup_region(region_id)
        if backup:
            self._failover_map[region_id] = backup
            self._emit(
                FailoverEventType.TRAFFIC_REROUTED,
                region_id,
                backup_region=backup,
            )
            result["backup_region"] = backup
            result["success"] = True

            if self._on_failover:
                self._on_failover(region_id, backup)
        else:
            result["success"] = False

        t_end = time.time()
        result["switchover_time_ms"] = (t_end - t_after_drain) * 1000
        result["total_time_ms"] = (t_end - t_start) * 1000

        self._emit(
            FailoverEventType.FAILOVER_COMPLETE,
            region_id,
            **result,
        )
        return result

    def execute_recovery(self, region_id: str) -> dict:
        """
        Recover a previously failed region.

        Steps:
          1. Full sync from healthy peer
          2. Verify data consistency
          3. Mark HEALTHY
          4. Resume traffic
        """
        t_start = time.time()
        self._emit(FailoverEventType.REGION_RECOVERY_STARTED, region_id)

        # Sync data from a healthy peer
        applied = self.failover_ctl.recover_region(region_id)

        # Check for split brain after recovery
        is_split, sb_details = self.split_brain.check(self.router)
        if is_split:
            self._emit(
                FailoverEventType.SPLIT_BRAIN_DETECTED,
                region_id,
                **sb_details,
            )

        t_end = time.time()
        recovery_time_ms = (t_end - t_start) * 1000

        # Remove from failover map
        self._failover_map.pop(region_id, None)

        self._emit(
            FailoverEventType.REGION_RECOVERY_COMPLETE,
            region_id,
            entries_synced=applied,
            recovery_time_ms=recovery_time_ms,
        )

        self.health_checker.reset(region_id)

        if self._on_recovery:
            self._on_recovery(region_id)

        return {
            "region": region_id,
            "entries_synced": applied,
            "recovery_time_ms": recovery_time_ms,
            "split_brain": is_split,
        }

    def run_probe_cycle(self) -> dict[str, Optional[str]]:
        """
        Run one probe cycle across all regions.
        Returns dict of region_id -> state_change ('down', 'recovered', or None).
        """
        results = {}
        for region_id in self.router.regions:
            probe = self.health_checker.probe(region_id)
            state_change = self.health_checker.update_counters(region_id, probe)

            if state_change == "down":
                node = self.router.regions.get(region_id)
                if node and node.status != HealthStatus.DOWN:
                    self.execute_failover(region_id)
            elif state_change == "recovered":
                node = self.router.regions.get(region_id)
                if node and node.status == HealthStatus.DOWN:
                    self.execute_recovery(region_id)

            results[region_id] = state_change
        return results

    def start_monitoring(self):
        """Start background health monitoring thread."""
        if self._running:
            return
        self._running = True
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()

    def stop_monitoring(self):
        """Stop background health monitoring."""
        self._running = False
        if self._monitor_thread:
            self._monitor_thread.join(timeout=5.0)
            self._monitor_thread = None

    def _monitor_loop(self):
        while self._running:
            self.run_probe_cycle()
            time.sleep(self.health_checker.probe_interval_s)

    def status(self) -> dict:
        """Get current failover status across all regions."""
        regions = {}
        for rid, node in self.router.regions.items():
            last_probe = self.health_checker._last_probe.get(rid)
            regions[rid] = {
                "status": node.status.value,
                "last_probe": last_probe.result.value if last_probe else "unknown",
                "last_latency_ms": last_probe.latency_ms if last_probe else None,
                "backup_region": self._failover_map.get(rid),
            }
        return {
            "regions": regions,
            "active_failovers": dict(self._failover_map),
            "total_events": len(self._events),
        }


# ---------------------------------------------------------------------------
# Failover-aware client — wraps reads/writes with automatic retry on failover
# ---------------------------------------------------------------------------

class FailoverAwareClient:
    """
    Client that transparently handles failover during reads and writes.
    If a region goes down mid-request, automatically retries on backup region.
    """

    def __init__(self, manager: AutoFailoverManager, client_location: GeoCoord):
        self.manager = manager
        self.location = client_location
        self._request_count = 0
        self._failover_retries = 0

    def read(self, key: str, max_retries: int = 2) -> Optional[Any]:
        for attempt in range(max_retries + 1):
            node = self.manager.router.nearest_healthy(self.location)
            if node is None:
                raise RuntimeError("All regions are down — no failover target available")
            self.manager.drainer.add_connection(node.region_id)
            try:
                result = node.read(key)
                self._request_count += 1
                return result
            except Exception:
                self._failover_retries += 1
                if attempt == max_retries:
                    raise
            finally:
                self.manager.drainer.remove_connection(node.region_id)
        return None

    def write(self, key: str, value: Any, max_retries: int = 2) -> tuple[str, Any]:
        for attempt in range(max_retries + 1):
            node = self.manager.router.nearest_healthy(self.location)
            if node is None:
                raise RuntimeError("All regions are down — no failover target available")
            self.manager.drainer.add_connection(node.region_id)
            try:
                vv = node.write(key, value)
                self._request_count += 1
                return node.region_id, vv
            except Exception:
                self._failover_retries += 1
                if attempt == max_retries:
                    raise
            finally:
                self.manager.drainer.remove_connection(node.region_id)
        raise RuntimeError("Write failed after retries")

    @property
    def stats(self) -> dict:
        return {
            "requests": self._request_count,
            "failover_retries": self._failover_retries,
        }


# ---------------------------------------------------------------------------
# __main__ — full verification suite
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import sys
    sys.path.insert(0, ".")

    # =====================================================================
    # Setup: 4 global regions
    # =====================================================================
    us_east = RegionNode("us-east-1", GeoCoord(39.0438, -77.4874))
    eu_west = RegionNode("eu-west-1", GeoCoord(53.3498, -6.2603))
    ap_south = RegionNode("ap-south-1", GeoCoord(19.0760, 72.8777))
    us_west = RegionNode("us-west-2", GeoCoord(45.5945, -122.1562))

    router = GeoRouter()
    for r in [us_east, eu_west, ap_south, us_west]:
        router.register_region(r)
    router.connect_all()

    # Seed data across all regions
    us_east.write("user:1001", {"name": "Alice", "plan": "pro"})
    eu_west.write("user:1002", {"name": "Bob", "plan": "team"})
    ap_south.write("user:1003", {"name": "Chandra", "plan": "enterprise"})
    us_west.write("config:global", {"version": 7, "feature_flags": ["geo", "failover"]})
    router.replicate_all()

    nyc = GeoCoord(40.7128, -74.0060)
    london = GeoCoord(51.5074, -0.1278)
    mumbai = GeoCoord(19.0760, 72.8777)
    portland = GeoCoord(45.5152, -122.6784)

    # =====================================================================
    # Test 1: AutoFailoverManager instantiation and initial status
    # =====================================================================
    manager = AutoFailoverManager(
        router=router,
        probe_interval_s=0.1,
        failure_threshold=3,
        recovery_threshold=2,
        drain_timeout_s=0.5,
    )

    status = manager.status()
    assert len(status["regions"]) == 4
    assert status["active_failovers"] == {}
    for rid, info in status["regions"].items():
        assert info["status"] == "healthy"
    print("[PASS] Test 1: AutoFailoverManager initialized with 4 healthy regions")

    # =====================================================================
    # Test 2: Manual failover executes in <5s
    # =====================================================================
    result = manager.execute_failover("eu-west-1")
    assert result["success"] is True
    assert result["backup_region"] is not None
    assert result["total_time_ms"] < 5000, f"Failover took {result['total_time_ms']:.1f}ms, exceeds 5s"
    assert eu_west.status == HealthStatus.DOWN
    print(f"[PASS] Test 2: Failover completed in {result['total_time_ms']:.1f}ms (<5000ms), backup={result['backup_region']}")

    # =====================================================================
    # Test 3: Traffic rerouted after failover
    # =====================================================================
    routed = router.nearest_healthy(london)
    assert routed.region_id != "eu-west-1", "Down region must not serve traffic"
    val = router.route_read(london, "user:1001")
    assert val == {"name": "Alice", "plan": "pro"}, f"Rerouted read returned wrong data: {val}"
    print(f"[PASS] Test 3: London traffic rerouted to {routed.region_id}, data intact")

    # =====================================================================
    # Test 4: Region recovery with full resync
    # =====================================================================
    # Write new data while eu-west is down
    us_east.write("user:1004", {"name": "Diana", "plan": "pro"})
    router.replicate_all()

    recovery = manager.execute_recovery("eu-west-1")
    assert recovery["entries_synced"] > 0
    assert eu_west.status == HealthStatus.HEALTHY
    val = eu_west.read("user:1004")
    assert val == {"name": "Diana", "plan": "pro"}, f"Recovery missed data: {val}"
    print(f"[PASS] Test 4: eu-west-1 recovered, synced {recovery['entries_synced']} entries in {recovery['recovery_time_ms']:.1f}ms")

    # =====================================================================
    # Test 5: Health probe detection triggers automatic failover
    # =====================================================================
    manager2 = AutoFailoverManager(
        router=router,
        probe_interval_s=0.05,
        failure_threshold=3,
        recovery_threshold=2,
        drain_timeout_s=0.1,
    )

    # Simulate ap-south-1 going down
    manager2.health_checker.simulate_failure("ap-south-1")

    t_detect_start = time.time()
    # Run probe cycles until failover triggers
    for _ in range(10):
        changes = manager2.run_probe_cycle()
        if changes.get("ap-south-1") == "down":
            break
        time.sleep(0.05)
    t_detect_end = time.time()

    detection_ms = (t_detect_end - t_detect_start) * 1000
    assert ap_south.status == HealthStatus.DOWN, "ap-south-1 should be DOWN after probe failures"
    assert detection_ms < 5000, f"Detection took {detection_ms:.0f}ms, exceeds 5s"
    print(f"[PASS] Test 5: Automatic failure detection in {detection_ms:.0f}ms")

    # =====================================================================
    # Test 6: Automatic recovery after health restored
    # =====================================================================
    manager2.health_checker.clear_simulated_failure("ap-south-1")
    manager2.health_checker.reset("ap-south-1")

    # Need to manually set it healthy for probe to detect recovery correctly
    # (since the region is currently DOWN, probes go through simulated path)
    for _ in range(5):
        changes = manager2.run_probe_cycle()
        if changes.get("ap-south-1") == "recovered":
            break
        time.sleep(0.05)

    assert ap_south.status == HealthStatus.HEALTHY, "ap-south-1 should recover"
    print("[PASS] Test 6: Automatic recovery after health probes pass")

    # =====================================================================
    # Test 7: Connection drainer works correctly
    # =====================================================================
    drainer = ConnectionDrainer(drain_timeout_s=1.0)

    # Simulate 5 active connections
    for _ in range(5):
        drainer.add_connection("us-east-1")
    assert drainer.active_count("us-east-1") == 5

    # Simulate connections finishing in background
    def finish_connections():
        time.sleep(0.1)
        for _ in range(5):
            drainer.remove_connection("us-east-1")

    t = threading.Thread(target=finish_connections)
    t.start()
    drain_time = drainer.drain("us-east-1")
    t.join()

    assert drainer.active_count("us-east-1") == 0
    assert drain_time < 1.0, f"Drain took {drain_time:.2f}s, should be <1s"
    print(f"[PASS] Test 7: Connection drain completed in {drain_time:.3f}s")

    # =====================================================================
    # Test 8: Split-brain detection
    # =====================================================================
    detector = SplitBrainDetector(max_divergence_pct=5.0)

    # All consistent after full replication
    router.replicate_all()
    is_split, details = detector.check(router)
    assert not is_split, f"Should not detect split brain when consistent: {details}"
    print(f"[PASS] Test 8: No split-brain when data is consistent ({details['divergent_keys']}/{details['total_keys']} divergent)")

    # =====================================================================
    # Test 9: Split-brain detection catches divergence
    # =====================================================================
    # Create intentional divergence by writing without replicating
    us_east.write("diverge:1", "value_a")
    eu_west.write("diverge:1", "value_b")
    # Don't replicate — these are concurrent writes that haven't been resolved

    is_split, details = detector.check(router)
    # At least one divergent key
    assert details["divergent_keys"] >= 1, "Should detect divergent key"
    print(f"[PASS] Test 9: Split-brain detector found {details['divergent_keys']} divergent key(s)")

    # Resolve by replicating
    router.replicate_all()

    # =====================================================================
    # Test 10: FailoverAwareClient seamless reads/writes
    # =====================================================================
    manager3 = AutoFailoverManager(
        router=router,
        probe_interval_s=0.1,
        failure_threshold=3,
        recovery_threshold=2,
        drain_timeout_s=0.1,
    )
    client = FailoverAwareClient(manager3, nyc)

    # Normal read
    val = client.read("user:1001")
    assert val == {"name": "Alice", "plan": "pro"}

    # Normal write
    region, vv = client.write("client:test", {"wrote": True})
    assert region == "us-east-1"  # NYC is closest to us-east-1

    # Verify write
    val = client.read("client:test")
    assert val == {"wrote": True}
    print(f"[PASS] Test 10: FailoverAwareClient read/write works, served by {region}")

    # =====================================================================
    # Test 11: Client handles region going down mid-session
    # =====================================================================
    manager3.execute_failover("us-east-1")
    # Client should now route to next nearest (us-west-2)
    # Data is already replicated, so reads should work
    router.replicate_all()

    val = client.read("user:1001")
    assert val is not None, "Client should failover to backup region transparently"

    region, _ = client.write("failover:write", {"during_failover": True})
    assert region != "us-east-1", f"Should not write to downed region, got {region}"
    print(f"[PASS] Test 11: Client seamlessly failed over to {region} for writes")

    # Recover
    manager3.execute_recovery("us-east-1")

    # =====================================================================
    # Test 12: Event log captures full failover timeline
    # =====================================================================
    events = manager.events
    event_types = [e.event_type for e in events]
    assert FailoverEventType.FAILOVER_STARTED in event_types
    assert FailoverEventType.REGION_DOWN_DETECTED in event_types
    assert FailoverEventType.DRAIN_STARTED in event_types
    assert FailoverEventType.DRAIN_COMPLETE in event_types
    assert FailoverEventType.TRAFFIC_REROUTED in event_types
    assert FailoverEventType.FAILOVER_COMPLETE in event_types
    assert FailoverEventType.REGION_RECOVERY_STARTED in event_types
    assert FailoverEventType.REGION_RECOVERY_COMPLETE in event_types
    print(f"[PASS] Test 12: Event log captured {len(events)} events with full timeline")

    # =====================================================================
    # Test 13: Cascading failover — two regions go down
    # =====================================================================
    manager4 = AutoFailoverManager(
        router=router,
        probe_interval_s=0.1,
        failure_threshold=3,
        recovery_threshold=2,
        drain_timeout_s=0.1,
    )

    r1 = manager4.execute_failover("us-east-1")
    r2 = manager4.execute_failover("eu-west-1")
    assert r1["success"] and r2["success"]

    # With 2 regions down, remaining 2 should still serve traffic
    routed_nyc = router.nearest_healthy(nyc)
    routed_london = router.nearest_healthy(london)
    assert routed_nyc is not None
    assert routed_london is not None
    assert routed_nyc.region_id in ("ap-south-1", "us-west-2")
    assert routed_london.region_id in ("ap-south-1", "us-west-2")
    print(f"[PASS] Test 13: Cascading failover — NYC->{routed_nyc.region_id}, London->{routed_london.region_id}")

    # Recover both
    manager4.execute_recovery("us-east-1")
    manager4.execute_recovery("eu-west-1")

    # =====================================================================
    # Test 14: Background monitoring thread starts and stops
    # =====================================================================
    manager5 = AutoFailoverManager(
        router=router,
        probe_interval_s=0.05,
        failure_threshold=3,
        recovery_threshold=2,
        drain_timeout_s=0.1,
    )
    manager5.start_monitoring()
    assert manager5._running is True
    time.sleep(0.2)  # Let a few probe cycles run
    manager5.stop_monitoring()
    assert manager5._running is False
    print("[PASS] Test 14: Background monitoring thread started and stopped cleanly")

    # =====================================================================
    # Test 15: End-to-end failover timing budget verification
    # =====================================================================
    manager6 = AutoFailoverManager(
        router=router,
        probe_interval_s=0.1,    # 100ms between probes
        failure_threshold=3,      # 3 failures to trigger
        recovery_threshold=2,
        drain_timeout_s=0.5,      # 500ms drain
    )

    manager6.health_checker.simulate_failure("us-west-2")

    t_start = time.time()
    # Run probes until failover triggers
    triggered = False
    for _ in range(20):
        changes = manager6.run_probe_cycle()
        if changes.get("us-west-2") == "down":
            triggered = True
            break
        time.sleep(manager6.health_checker.probe_interval_s)
    t_end = time.time()

    total_ms = (t_end - t_start) * 1000
    assert triggered, "Failover should have triggered"
    assert total_ms < 5000, f"Total failover time {total_ms:.0f}ms exceeds 5s budget"
    assert us_west.status == HealthStatus.DOWN
    print(f"[PASS] Test 15: End-to-end failover in {total_ms:.0f}ms (budget: <5000ms)")

    # Recover for cleanup
    manager6.health_checker.clear_simulated_failure("us-west-2")
    manager6.execute_recovery("us-west-2")

    # =====================================================================
    # Test 16: Failover callback invocation
    # =====================================================================
    callback_log = []

    def on_failover(down: str, backup: str):
        callback_log.append(("failover", down, backup))

    def on_recovery(region: str):
        callback_log.append(("recovery", region))

    manager7 = AutoFailoverManager(
        router=router,
        probe_interval_s=0.1,
        failure_threshold=3,
        recovery_threshold=2,
        drain_timeout_s=0.1,
    )
    manager7.set_on_failover(on_failover)
    manager7.set_on_recovery(on_recovery)

    manager7.execute_failover("ap-south-1")
    manager7.execute_recovery("ap-south-1")

    assert len(callback_log) == 2
    assert callback_log[0][0] == "failover"
    assert callback_log[0][1] == "ap-south-1"
    assert callback_log[1] == ("recovery", "ap-south-1")
    print(f"[PASS] Test 16: Failover/recovery callbacks invoked correctly")

    # =====================================================================
    # Test 17: All-regions-down scenario
    # =====================================================================
    manager8 = AutoFailoverManager(
        router=router,
        probe_interval_s=0.1,
        failure_threshold=3,
        recovery_threshold=2,
        drain_timeout_s=0.1,
    )

    for rid in router.regions:
        manager8.execute_failover(rid)

    client_down = FailoverAwareClient(manager8, nyc)
    try:
        client_down.read("anything")
        assert False, "Should raise RuntimeError when all regions down"
    except RuntimeError as e:
        assert "All regions are down" in str(e)
    print("[PASS] Test 17: All-regions-down raises RuntimeError in client")

    # Recover all
    for rid in list(router.regions.keys()):
        manager8.execute_recovery(rid)

    # =====================================================================
    # Test 18: Health probe history tracking
    # =====================================================================
    manager9 = AutoFailoverManager(
        router=router,
        probe_interval_s=0.05,
        failure_threshold=3,
        recovery_threshold=2,
        drain_timeout_s=0.1,
    )

    for _ in range(5):
        manager9.run_probe_cycle()

    history = manager9.health_checker.get_probe_history("us-east-1", count=5)
    assert len(history) == 5
    assert all(isinstance(p, HealthProbe) for p in history)
    assert all(p.region_id == "us-east-1" for p in history)
    print(f"[PASS] Test 18: Probe history tracked ({len(history)} entries)")

    # =====================================================================
    # Summary
    # =====================================================================
    print("\n" + "=" * 60)
    print("ALL 18 TESTS PASSED — Automatic Failover Engine Verified (<5s)")
    print("=" * 60)
    print("\nFinal region status:")
    final_status = manager9.status()
    for rid, info in final_status["regions"].items():
        print(f"  {rid:12s} | status={info['status']:8s} | last_probe={info['last_probe']}")
