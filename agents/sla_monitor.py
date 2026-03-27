#!/usr/bin/env python3
"""
sla_monitor.py — SLA Monitoring & Alerting Agent
=================================================
Monitors system uptime against a 99.9% SLA target.
Tracks health checks, detects violations, triggers alerts,
and manages incident response workflow.

Usage:
    from agents.sla_monitor import SLAMonitor
    monitor = SLAMonitor(sla_target=99.9)
    monitor.record_check(healthy=True)
    report = monitor.get_report()
"""

import json
import time
import threading
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional
from collections import deque
from enum import Enum

BASE_DIR = Path(__file__).parent.parent
SLA_STATE_FILE = BASE_DIR / "state" / "sla_state.json"
SLA_INCIDENTS_FILE = BASE_DIR / "reports" / "sla_incidents.jsonl"

logging.basicConfig(
    level=logging.INFO,
    format="[SLA_MONITOR] %(asctime)s %(levelname)s %(message)s",
    datefmt="%Y-%m-%dT%H:%M:%S",
)
logger = logging.getLogger("sla_monitor")


class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    PAGE = "page"


class IncidentStatus(str, Enum):
    OPEN = "open"
    ACKNOWLEDGED = "acknowledged"
    MITIGATING = "mitigating"
    RESOLVED = "resolved"


class AlertChannel:
    """Base alert channel. Subclass for Slack, PagerDuty, email, etc."""

    def __init__(self, name: str):
        self.name = name
        self.sent: list[dict] = []

    def send(self, alert: dict) -> bool:
        self.sent.append(alert)
        logger.info("Alert via %s: [%s] %s", self.name, alert["severity"], alert["message"])
        return True


class LogAlertChannel(AlertChannel):
    """Writes alerts to a JSONL log file."""

    def __init__(self, path: Path):
        super().__init__(f"log:{path.name}")
        self.path = path

    def send(self, alert: dict) -> bool:
        super().send(alert)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a") as f:
            f.write(json.dumps(alert, default=str) + "\n")
        return True


class HealthCheck:
    """Single health check result."""

    __slots__ = ("timestamp", "healthy", "latency_ms", "component", "detail")

    def __init__(self, healthy: bool, latency_ms: float = 0.0,
                 component: str = "system", detail: str = "",
                 timestamp: Optional[datetime] = None):
        self.timestamp = timestamp or datetime.utcnow()
        self.healthy = healthy
        self.latency_ms = latency_ms
        self.component = component
        self.detail = detail

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp.isoformat(),
            "healthy": self.healthy,
            "latency_ms": self.latency_ms,
            "component": self.component,
            "detail": self.detail,
        }


class Incident:
    """Tracks an SLA incident from detection through resolution."""

    def __init__(self, incident_id: str, severity: Severity,
                 component: str, description: str):
        self.id = incident_id
        self.severity = severity
        self.component = component
        self.description = description
        self.status = IncidentStatus.OPEN
        self.opened_at = datetime.utcnow()
        self.acknowledged_at: Optional[datetime] = None
        self.resolved_at: Optional[datetime] = None
        self.timeline: list[dict] = [
            {"time": self.opened_at.isoformat(), "action": "opened", "detail": description}
        ]
        self.downtime_seconds: float = 0.0

    def acknowledge(self, responder: str = "auto") -> None:
        if self.status == IncidentStatus.OPEN:
            self.status = IncidentStatus.ACKNOWLEDGED
            self.acknowledged_at = datetime.utcnow()
            self.timeline.append({
                "time": self.acknowledged_at.isoformat(),
                "action": "acknowledged",
                "detail": f"Acknowledged by {responder}",
            })

    def mitigate(self, action: str) -> None:
        self.status = IncidentStatus.MITIGATING
        self.timeline.append({
            "time": datetime.utcnow().isoformat(),
            "action": "mitigating",
            "detail": action,
        })

    def resolve(self, resolution: str) -> None:
        self.status = IncidentStatus.RESOLVED
        self.resolved_at = datetime.utcnow()
        self.downtime_seconds = (self.resolved_at - self.opened_at).total_seconds()
        self.timeline.append({
            "time": self.resolved_at.isoformat(),
            "action": "resolved",
            "detail": resolution,
        })

    @property
    def ttd_seconds(self) -> Optional[float]:
        """Time to detect — always 0 for automated detection."""
        return 0.0

    @property
    def tta_seconds(self) -> Optional[float]:
        """Time to acknowledge."""
        if self.acknowledged_at:
            return (self.acknowledged_at - self.opened_at).total_seconds()
        return None

    @property
    def ttr_seconds(self) -> Optional[float]:
        """Time to resolve."""
        if self.resolved_at:
            return (self.resolved_at - self.opened_at).total_seconds()
        return None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "severity": self.severity.value,
            "component": self.component,
            "description": self.description,
            "status": self.status.value,
            "opened_at": self.opened_at.isoformat(),
            "acknowledged_at": self.acknowledged_at.isoformat() if self.acknowledged_at else None,
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "downtime_seconds": self.downtime_seconds,
            "ttd_seconds": self.ttd_seconds,
            "tta_seconds": self.tta_seconds,
            "ttr_seconds": self.ttr_seconds,
            "timeline": self.timeline,
        }


class UptimeTracker:
    """Sliding-window uptime calculator."""

    def __init__(self, window_hours: int = 720):
        self.window = timedelta(hours=window_hours)
        self.checks: deque[HealthCheck] = deque()
        self._lock = threading.Lock()

    def add(self, check: HealthCheck) -> None:
        with self._lock:
            self.checks.append(check)
            self._prune()

    def _prune(self) -> None:
        cutoff = datetime.utcnow() - self.window
        while self.checks and self.checks[0].timestamp < cutoff:
            self.checks.popleft()

    @property
    def total_checks(self) -> int:
        with self._lock:
            self._prune()
            return len(self.checks)

    @property
    def healthy_checks(self) -> int:
        with self._lock:
            self._prune()
            return sum(1 for c in self.checks if c.healthy)

    @property
    def uptime_pct(self) -> float:
        total = self.total_checks
        if total == 0:
            return 100.0
        return (self.healthy_checks / total) * 100.0

    @property
    def avg_latency_ms(self) -> float:
        with self._lock:
            self._prune()
            latencies = [c.latency_ms for c in self.checks if c.healthy]
            return sum(latencies) / len(latencies) if latencies else 0.0

    @property
    def p95_latency_ms(self) -> float:
        with self._lock:
            self._prune()
            latencies = sorted(c.latency_ms for c in self.checks if c.healthy)
            if not latencies:
                return 0.0
            idx = int(len(latencies) * 0.95)
            return latencies[min(idx, len(latencies) - 1)]

    def get_downtime_minutes(self, check_interval_seconds: float = 60.0) -> float:
        with self._lock:
            self._prune()
            unhealthy = sum(1 for c in self.checks if not c.healthy)
            return (unhealthy * check_interval_seconds) / 60.0

    def get_window_stats(self) -> dict:
        return {
            "window_hours": self.window.total_seconds() / 3600,
            "total_checks": self.total_checks,
            "healthy_checks": self.healthy_checks,
            "uptime_pct": round(self.uptime_pct, 4),
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "downtime_minutes": round(self.get_downtime_minutes(), 2),
        }


class SLABudget:
    """Tracks remaining error budget for the SLA period."""

    def __init__(self, sla_target_pct: float = 99.9, period_days: int = 30):
        self.target = sla_target_pct
        self.period_days = period_days
        self.period_total_minutes = period_days * 24 * 60
        self.allowed_downtime_minutes = self.period_total_minutes * (1 - sla_target_pct / 100.0)

    def remaining_budget_minutes(self, used_downtime_minutes: float) -> float:
        return max(0.0, self.allowed_downtime_minutes - used_downtime_minutes)

    def budget_consumed_pct(self, used_downtime_minutes: float) -> float:
        if self.allowed_downtime_minutes == 0:
            return 100.0 if used_downtime_minutes > 0 else 0.0
        return min(100.0, (used_downtime_minutes / self.allowed_downtime_minutes) * 100.0)

    def is_violated(self, used_downtime_minutes: float) -> bool:
        return used_downtime_minutes > self.allowed_downtime_minutes

    def get_status(self, used_downtime_minutes: float) -> dict:
        consumed = self.budget_consumed_pct(used_downtime_minutes)
        return {
            "sla_target_pct": self.target,
            "period_days": self.period_days,
            "allowed_downtime_minutes": round(self.allowed_downtime_minutes, 2),
            "used_downtime_minutes": round(used_downtime_minutes, 2),
            "remaining_budget_minutes": round(self.remaining_budget_minutes(used_downtime_minutes), 2),
            "budget_consumed_pct": round(consumed, 2),
            "violated": self.is_violated(used_downtime_minutes),
            "severity": (
                Severity.PAGE.value if consumed >= 100
                else Severity.CRITICAL.value if consumed >= 80
                else Severity.WARNING.value if consumed >= 50
                else Severity.INFO.value
            ),
        }


class SLAMonitor:
    """
    Full SLA monitoring system.

    Tracks health checks, calculates uptime, manages error budget,
    detects violations, creates incidents, and dispatches alerts.
    """

    def __init__(self, sla_target: float = 99.9, period_days: int = 30,
                 window_hours: int = 720, check_interval_seconds: float = 60.0,
                 consecutive_failures_to_alert: int = 3):
        self.budget = SLABudget(sla_target, period_days)
        self.tracker = UptimeTracker(window_hours)
        self.check_interval = check_interval_seconds
        self.consecutive_failures_to_alert = consecutive_failures_to_alert

        self.channels: list[AlertChannel] = []
        self.incidents: dict[str, Incident] = {}
        self._incident_counter = 0
        self._consecutive_failures = 0
        self._active_incident_id: Optional[str] = None
        self._lock = threading.Lock()

        # Auto-response rules: severity -> list of actions
        self.response_rules: dict[Severity, list[str]] = {
            Severity.WARNING: ["log", "notify"],
            Severity.CRITICAL: ["log", "notify", "escalate"],
            Severity.PAGE: ["log", "notify", "escalate", "page_oncall"],
        }

    def add_channel(self, channel: AlertChannel) -> None:
        self.channels.append(channel)

    def record_check(self, healthy: bool, latency_ms: float = 0.0,
                     component: str = "system", detail: str = "") -> dict:
        """Record a health check and evaluate SLA status."""
        check = HealthCheck(healthy, latency_ms, component, detail)
        self.tracker.add(check)

        with self._lock:
            if not healthy:
                self._consecutive_failures += 1
                if (self._consecutive_failures >= self.consecutive_failures_to_alert
                        and self._active_incident_id is None):
                    self._open_incident(component, detail)
            else:
                if self._active_incident_id is not None:
                    self._resolve_active_incident("Health check recovered")
                self._consecutive_failures = 0

        return self._evaluate()

    def _open_incident(self, component: str, detail: str) -> Incident:
        self._incident_counter += 1
        inc_id = f"INC-{self._incident_counter:05d}"

        budget_status = self.budget.get_status(
            self.tracker.get_downtime_minutes(self.check_interval)
        )
        severity = Severity(budget_status["severity"])

        incident = Incident(
            incident_id=inc_id,
            severity=severity,
            component=component,
            description=f"Consecutive health check failures ({self._consecutive_failures}x): {detail}",
        )
        self.incidents[inc_id] = incident
        self._active_incident_id = inc_id

        self._dispatch_alert({
            "type": "incident_opened",
            "incident_id": inc_id,
            "severity": severity.value,
            "component": component,
            "message": incident.description,
            "timestamp": incident.opened_at.isoformat(),
            "budget_status": budget_status,
        })

        # Auto-acknowledge for automated systems
        incident.acknowledge("sla_monitor_auto")

        # Execute response actions
        self._execute_response(severity, incident)

        logger.warning("Incident %s opened: %s", inc_id, incident.description)
        return incident

    def _resolve_active_incident(self, resolution: str) -> None:
        if self._active_incident_id and self._active_incident_id in self.incidents:
            incident = self.incidents[self._active_incident_id]
            incident.resolve(resolution)

            self._dispatch_alert({
                "type": "incident_resolved",
                "incident_id": incident.id,
                "severity": incident.severity.value,
                "component": incident.component,
                "message": f"Resolved: {resolution}",
                "timestamp": incident.resolved_at.isoformat(),
                "downtime_seconds": incident.downtime_seconds,
                "ttr_seconds": incident.ttr_seconds,
            })

            logger.info("Incident %s resolved (TTR: %.1fs)", incident.id, incident.ttr_seconds)
            self._active_incident_id = None

    def _execute_response(self, severity: Severity, incident: Incident) -> None:
        actions = self.response_rules.get(severity, [])
        for action in actions:
            if action == "log":
                logger.warning("Response[log]: %s — %s", incident.id, incident.description)
            elif action == "notify":
                logger.warning("Response[notify]: Notifying team about %s", incident.id)
            elif action == "escalate":
                incident.mitigate(f"Auto-escalated due to {severity.value} severity")
                logger.critical("Response[escalate]: %s escalated", incident.id)
            elif action == "page_oncall":
                logger.critical("Response[page]: Paging on-call for %s", incident.id)

    def _dispatch_alert(self, alert: dict) -> None:
        for channel in self.channels:
            try:
                channel.send(alert)
            except Exception as e:
                logger.error("Failed to send alert via %s: %s", channel.name, e)

    def _evaluate(self) -> dict:
        downtime = self.tracker.get_downtime_minutes(self.check_interval)
        budget_status = self.budget.get_status(downtime)
        window_stats = self.tracker.get_window_stats()

        return {
            "uptime": window_stats,
            "budget": budget_status,
            "active_incident": self._active_incident_id,
            "total_incidents": len(self.incidents),
            "open_incidents": sum(
                1 for i in self.incidents.values() if i.status != IncidentStatus.RESOLVED
            ),
        }

    def get_report(self) -> dict:
        """Full SLA report with all metrics."""
        downtime = self.tracker.get_downtime_minutes(self.check_interval)
        resolved = [i for i in self.incidents.values() if i.status == IncidentStatus.RESOLVED]

        avg_ttr = 0.0
        if resolved:
            ttrs = [i.ttr_seconds for i in resolved if i.ttr_seconds is not None]
            avg_ttr = sum(ttrs) / len(ttrs) if ttrs else 0.0

        return {
            "generated_at": datetime.utcnow().isoformat(),
            "sla_target": self.budget.target,
            "uptime": self.tracker.get_window_stats(),
            "budget": self.budget.get_status(downtime),
            "incidents": {
                "total": len(self.incidents),
                "open": sum(1 for i in self.incidents.values() if i.status != IncidentStatus.RESOLVED),
                "resolved": len(resolved),
                "avg_ttr_seconds": round(avg_ttr, 2),
            },
            "incident_log": [i.to_dict() for i in self.incidents.values()],
        }

    def save_state(self, path: Optional[Path] = None) -> None:
        path = path or SLA_STATE_FILE
        path.parent.mkdir(parents=True, exist_ok=True)
        report = self.get_report()
        with open(path, "w") as f:
            json.dump(report, f, indent=2, default=str)
        logger.info("SLA state saved to %s", path)

    def load_state(self, path: Optional[Path] = None) -> Optional[dict]:
        path = path or SLA_STATE_FILE
        if path.exists():
            with open(path) as f:
                return json.load(f)
        return None


def run_monitor_loop(monitor: SLAMonitor, check_fn, interval_seconds: float = 60.0,
                     max_iterations: Optional[int] = None) -> None:
    """
    Continuous monitoring loop.

    Args:
        monitor: SLAMonitor instance
        check_fn: Callable that returns (healthy: bool, latency_ms: float, detail: str)
        interval_seconds: Seconds between checks
        max_iterations: Stop after N iterations (None = forever)
    """
    iteration = 0
    while max_iterations is None or iteration < max_iterations:
        try:
            healthy, latency_ms, detail = check_fn()
            result = monitor.record_check(
                healthy=healthy,
                latency_ms=latency_ms,
                component="system",
                detail=detail,
            )

            if iteration % 10 == 0:
                logger.info(
                    "Uptime: %.3f%% | Budget: %.1f%% consumed | Incidents: %d open",
                    result["uptime"]["uptime_pct"],
                    result["budget"]["budget_consumed_pct"],
                    result["open_incidents"],
                )

            if iteration % 60 == 0:
                monitor.save_state()

        except Exception as e:
            logger.error("Monitor loop error: %s", e)
            monitor.record_check(healthy=False, detail=f"Monitor error: {e}")

        iteration += 1
        if max_iterations is None or iteration < max_iterations:
            time.sleep(interval_seconds)


if __name__ == "__main__":
    print("=" * 60)
    print("SLA Monitor — Verification Suite")
    print("=" * 60)

    # --- Test 1: SLA Budget calculations for 99.9% over 30 days ---
    budget = SLABudget(sla_target_pct=99.9, period_days=30)
    # 30 days = 43200 minutes. 0.1% = 43.2 minutes allowed downtime
    assert abs(budget.allowed_downtime_minutes - 43.2) < 0.01, \
        f"Expected 43.2 min, got {budget.allowed_downtime_minutes}"
    assert abs(budget.remaining_budget_minutes(10.0) - 33.2) < 0.01
    assert not budget.is_violated(43.0)
    assert budget.is_violated(43.3)
    assert abs(budget.budget_consumed_pct(21.6) - 50.0) < 0.1

    status = budget.get_status(0.0)
    assert status["violated"] is False
    assert status["severity"] == "info"

    status_warn = budget.get_status(22.0)
    assert status_warn["severity"] == "warning"

    status_crit = budget.get_status(35.0)
    assert status_crit["severity"] == "critical"

    status_page = budget.get_status(44.0)
    assert status_page["violated"] is True
    assert status_page["severity"] == "page"
    print("[PASS] SLA Budget calculations correct")

    # --- Test 2: Uptime tracking ---
    tracker = UptimeTracker(window_hours=24)
    for _ in range(990):
        tracker.add(HealthCheck(healthy=True, latency_ms=50.0))
    for _ in range(10):
        tracker.add(HealthCheck(healthy=False, latency_ms=0.0))

    assert tracker.total_checks == 1000
    assert tracker.healthy_checks == 990
    assert abs(tracker.uptime_pct - 99.0) < 0.01, f"Expected 99.0%, got {tracker.uptime_pct}"
    assert tracker.avg_latency_ms == 50.0
    print("[PASS] Uptime tracking correct (99.0% with 10/1000 failures)")

    # --- Test 3: Incident lifecycle ---
    inc = Incident("INC-00001", Severity.CRITICAL, "api", "Health check failed 3x")
    assert inc.status == IncidentStatus.OPEN
    assert inc.tta_seconds is None

    inc.acknowledge("engineer_1")
    assert inc.status == IncidentStatus.ACKNOWLEDGED
    assert inc.tta_seconds is not None
    assert inc.tta_seconds >= 0

    inc.mitigate("Restarted service")
    assert inc.status == IncidentStatus.MITIGATING

    inc.resolve("Root cause: OOM, increased memory limit")
    assert inc.status == IncidentStatus.RESOLVED
    assert inc.ttr_seconds is not None
    assert inc.ttr_seconds >= 0
    assert inc.downtime_seconds >= 0
    assert len(inc.timeline) == 4

    d = inc.to_dict()
    assert d["id"] == "INC-00001"
    assert d["severity"] == "critical"
    assert d["status"] == "resolved"
    print("[PASS] Incident lifecycle (open → ack → mitigate → resolve)")

    # --- Test 4: Alert dispatch ---
    channel = AlertChannel("test")
    log_channel = LogAlertChannel(Path("/tmp/sla_test_alerts.jsonl"))

    monitor = SLAMonitor(
        sla_target=99.9,
        period_days=30,
        check_interval_seconds=60.0,
        consecutive_failures_to_alert=3,
    )
    monitor.add_channel(channel)
    monitor.add_channel(log_channel)

    # Record healthy checks
    for _ in range(100):
        result = monitor.record_check(healthy=True, latency_ms=45.0)
    assert result["active_incident"] is None
    assert result["open_incidents"] == 0
    assert result["uptime"]["uptime_pct"] == 100.0
    print("[PASS] Healthy checks — no incidents")

    # Record failures — need 3 consecutive to trigger
    monitor.record_check(healthy=False, detail="timeout")
    assert monitor._active_incident_id is None  # only 1 failure
    monitor.record_check(healthy=False, detail="timeout")
    assert monitor._active_incident_id is None  # only 2 failures
    result = monitor.record_check(healthy=False, detail="timeout")
    assert monitor._active_incident_id is not None  # 3rd failure triggers
    assert result["open_incidents"] == 1
    assert result["total_incidents"] == 1

    inc_id = monitor._active_incident_id
    assert inc_id in monitor.incidents
    assert monitor.incidents[inc_id].status in (
        IncidentStatus.ACKNOWLEDGED, IncidentStatus.MITIGATING
    )  # auto-ack'd, may escalate depending on budget severity
    print("[PASS] 3 consecutive failures trigger incident + auto-response")

    # Alerts were sent
    assert len(channel.sent) >= 1
    assert channel.sent[0]["type"] == "incident_opened"
    print("[PASS] Alerts dispatched to channels")

    # Recovery resolves incident
    result = monitor.record_check(healthy=True, latency_ms=30.0)
    assert result["active_incident"] is None
    assert result["open_incidents"] == 0
    assert monitor.incidents[inc_id].status == IncidentStatus.RESOLVED
    assert monitor.incidents[inc_id].ttr_seconds is not None

    resolve_alerts = [a for a in channel.sent if a.get("type") == "incident_resolved"]
    assert len(resolve_alerts) == 1
    print("[PASS] Recovery auto-resolves incident")

    # --- Test 5: Full report ---
    report = monitor.get_report()
    assert report["sla_target"] == 99.9
    assert report["incidents"]["total"] == 1
    assert report["incidents"]["resolved"] == 1
    assert report["incidents"]["open"] == 0
    assert report["incidents"]["avg_ttr_seconds"] >= 0
    assert len(report["incident_log"]) == 1
    assert report["incident_log"][0]["status"] == "resolved"
    print("[PASS] Full SLA report generation")

    # --- Test 6: Multiple incidents ---
    for _ in range(5):
        monitor.record_check(healthy=False, detail="disk full")
    assert monitor._active_incident_id is not None
    assert monitor.incidents[monitor._active_incident_id].severity in (
        Severity.INFO, Severity.WARNING, Severity.CRITICAL, Severity.PAGE
    )
    monitor.record_check(healthy=True, latency_ms=20.0)
    assert len(monitor.incidents) == 2
    print("[PASS] Multiple incidents tracked independently")

    # --- Test 7: SLA violation detection ---
    violation_monitor = SLAMonitor(
        sla_target=99.9,
        period_days=1,  # 1 day = 1440 min, allowed = 1.44 min
        check_interval_seconds=60.0,
        consecutive_failures_to_alert=1,
    )
    # 2 failures * 60s each = 2 min downtime > 1.44 min allowed
    violation_monitor.record_check(healthy=False, detail="outage")
    violation_monitor.record_check(healthy=False, detail="outage")
    violation_report = violation_monitor.get_report()
    assert violation_report["budget"]["violated"] is True, "Should detect SLA violation"
    assert violation_report["budget"]["severity"] == "page"
    print("[PASS] SLA violation correctly detected")

    # --- Test 8: Save and load state ---
    import tempfile
    with tempfile.NamedTemporaryFile(suffix=".json", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    monitor.save_state(tmp_path)
    loaded = monitor.load_state(tmp_path)
    assert loaded is not None
    assert loaded["sla_target"] == 99.9
    assert loaded["incidents"]["total"] == 2
    tmp_path.unlink()
    print("[PASS] State persistence (save/load)")

    # --- Test 9: Monitor loop (bounded) ---
    _counter = {"n": 0}

    def mock_check():
        _counter["n"] += 1
        return (True, 25.0, "ok")

    loop_monitor = SLAMonitor(sla_target=99.9)
    run_monitor_loop(loop_monitor, mock_check, interval_seconds=0.01, max_iterations=5)
    assert _counter["n"] == 5
    assert loop_monitor.tracker.total_checks == 5
    print("[PASS] Monitor loop runs bounded iterations")

    # --- Test 10: Error budget math ---
    # 99.9% over 365 days = 525.6 min (~8.76 hours) allowed downtime
    yearly = SLABudget(sla_target_pct=99.9, period_days=365)
    assert abs(yearly.allowed_downtime_minutes - 525.6) < 0.1
    assert abs(yearly.remaining_budget_minutes(100.0) - 425.6) < 0.1
    # 99.95% over 30 days = 21.6 min allowed
    strict = SLABudget(sla_target_pct=99.95, period_days=30)
    assert abs(strict.allowed_downtime_minutes - 21.6) < 0.1
    print("[PASS] Error budget math for different SLA tiers")

    print()
    print("=" * 60)
    print("All 10 tests passed. SLA monitor verified.")
    print("=" * 60)
