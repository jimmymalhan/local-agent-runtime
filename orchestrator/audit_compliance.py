#!/usr/bin/env python3
"""
orchestrator/audit_compliance.py — Comprehensive Audit Logging & Compliance
============================================================================
Immutable audit trail for user actions, data access, system events, and
regulatory compliance (SOC 2, GDPR, HIPAA-style controls).

Features:
  - Append-only, tamper-evident log with HMAC integrity chains
  - Each entry links to the previous via chained hash (blockchain-lite)
  - User action tracking (who did what, when, from where)
  - Data access logging (read/write/delete with field-level detail)
  - Retention policies with automatic archival and purge scheduling
  - Compliance report generation (access summaries, anomaly flags)
  - Export to JSONL for external SIEM ingestion
  - Thread-safe, zero external dependencies
  - Integrates with EventBus for real-time compliance alerting

Usage:
    from orchestrator.audit_compliance import AuditLogger, get_audit_logger

    audit = get_audit_logger()
    audit.log_action("user:jimmy", "task.create", resource="projects.json",
                     detail={"task_id": "t-123", "title": "Build API"})
    audit.log_data_access("agent:executor", "read", resource="state/runtime-lessons.json",
                          fields_accessed=["attempt_count", "strategy"])
    report = audit.compliance_report(hours=24)
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BASE_DIR = Path(__file__).parent.parent
DEFAULT_AUDIT_DIR = BASE_DIR / "state" / "audit"
HMAC_KEY = os.environ.get("AUDIT_HMAC_KEY", "local-agent-runtime-audit-key").encode()
MAX_SEGMENT_SIZE = 5 * 1024 * 1024  # 5 MB per segment file
DEFAULT_RETENTION_DAYS = 90


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------

class AuditEventType(Enum):
    USER_ACTION = "user_action"
    DATA_ACCESS = "data_access"
    DATA_MODIFY = "data_modify"
    DATA_DELETE = "data_delete"
    AUTH_EVENT = "auth_event"
    SYSTEM_EVENT = "system_event"
    COMPLIANCE_CHECK = "compliance_check"
    POLICY_VIOLATION = "policy_violation"
    CONFIG_CHANGE = "config_change"
    AGENT_ACTION = "agent_action"


class AccessLevel(Enum):
    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    ADMIN = "admin"
    EXECUTE = "execute"


class ComplianceFramework(Enum):
    SOC2 = "SOC2"
    GDPR = "GDPR"
    HIPAA = "HIPAA"
    INTERNAL = "INTERNAL"


class Severity(Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"
    ALERT = "alert"


# ---------------------------------------------------------------------------
# Audit Entry — Immutable record
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class AuditEntry:
    """Single immutable audit log entry with chain integrity."""
    entry_id: str
    timestamp: float
    event_type: str  # AuditEventType value
    actor: str  # "user:<name>" or "agent:<name>" or "system"
    action: str  # Dot-namespaced action (e.g. "task.create")
    resource: str  # What was acted upon
    severity: str  # Severity value
    detail: Dict[str, Any]  # Action-specific payload
    source_ip: str  # Origin (localhost for local runtime)
    session_id: str  # Session correlation
    prev_hash: str  # Hash of previous entry (chain link)
    entry_hash: str  # HMAC of this entry's content

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), separators=(",", ":"), sort_keys=True)

    @classmethod
    def from_dict(cls, d: Dict[str, Any]) -> "AuditEntry":
        return cls(**d)


# ---------------------------------------------------------------------------
# Retention Policy
# ---------------------------------------------------------------------------

@dataclass
class RetentionPolicy:
    """Configurable retention rules per event type or compliance framework."""
    framework: str = ComplianceFramework.INTERNAL.value
    retention_days: int = DEFAULT_RETENTION_DAYS
    archive_after_days: int = 30
    require_encryption_at_rest: bool = False
    immutable: bool = True  # entries cannot be modified after write
    min_retention_days: int = 7  # hard floor

    def effective_retention(self) -> int:
        return max(self.retention_days, self.min_retention_days)


# ---------------------------------------------------------------------------
# Compliance Rule Engine
# ---------------------------------------------------------------------------

@dataclass
class ComplianceRule:
    """A single compliance check rule."""
    rule_id: str
    framework: str
    description: str
    check_fn: Callable[[List[AuditEntry]], List[str]]  # returns list of violations
    severity: str = Severity.WARNING.value


class ComplianceRuleEngine:
    """Evaluates audit entries against registered compliance rules."""

    def __init__(self) -> None:
        self._rules: List[ComplianceRule] = []
        self._register_default_rules()

    def add_rule(self, rule: ComplianceRule) -> None:
        self._rules.append(rule)

    def evaluate(self, entries: List[AuditEntry]) -> Dict[str, List[str]]:
        """Run all rules, return {rule_id: [violations]}."""
        results: Dict[str, List[str]] = {}
        for rule in self._rules:
            violations = rule.check_fn(entries)
            if violations:
                results[rule.rule_id] = violations
        return results

    def _register_default_rules(self) -> None:
        # Rule: No single actor should perform >100 actions in 1 minute
        def rate_limit_check(entries: List[AuditEntry]) -> List[str]:
            violations = []
            if not entries:
                return violations
            buckets: Dict[str, List[float]] = {}
            for e in entries:
                buckets.setdefault(e.actor, []).append(e.timestamp)
            for actor, timestamps in buckets.items():
                timestamps.sort()
                window: List[float] = []
                for ts in timestamps:
                    window = [t for t in window if ts - t <= 60.0]
                    window.append(ts)
                    if len(window) > 100:
                        violations.append(
                            f"Actor '{actor}' exceeded 100 actions/min at {ts}"
                        )
                        break
            return violations

        self.add_rule(ComplianceRule(
            rule_id="RATE_LIMIT_001",
            framework=ComplianceFramework.INTERNAL.value,
            description="No actor may exceed 100 actions per minute",
            check_fn=rate_limit_check,
            severity=Severity.ALERT.value,
        ))

        # Rule: Data deletions must be logged with detail
        def deletion_detail_check(entries: List[AuditEntry]) -> List[str]:
            violations = []
            for e in entries:
                if e.event_type == AuditEventType.DATA_DELETE.value and not e.detail:
                    violations.append(
                        f"Deletion by '{e.actor}' on '{e.resource}' at {e.timestamp} "
                        f"has no detail (entry_id={e.entry_id})"
                    )
            return violations

        self.add_rule(ComplianceRule(
            rule_id="DELETE_DETAIL_001",
            framework=ComplianceFramework.SOC2.value,
            description="All data deletions must include detail payload",
            check_fn=deletion_detail_check,
            severity=Severity.CRITICAL.value,
        ))

        # Rule: GDPR — data access to PII fields must log field names
        def gdpr_field_access_check(entries: List[AuditEntry]) -> List[str]:
            pii_indicators = {"email", "name", "address", "phone", "ssn", "dob"}
            violations = []
            for e in entries:
                if e.event_type == AuditEventType.DATA_ACCESS.value:
                    fields = e.detail.get("fields_accessed", [])
                    if not fields:
                        continue
                    for f in fields:
                        if f.lower() in pii_indicators and "purpose" not in e.detail:
                            violations.append(
                                f"PII field '{f}' accessed by '{e.actor}' without "
                                f"stated purpose (entry_id={e.entry_id})"
                            )
            return violations

        self.add_rule(ComplianceRule(
            rule_id="GDPR_PII_001",
            framework=ComplianceFramework.GDPR.value,
            description="PII field access must include a stated purpose",
            check_fn=gdpr_field_access_check,
            severity=Severity.CRITICAL.value,
        ))

        # Rule: Privilege escalation — admin access must be rare
        def privilege_escalation_check(entries: List[AuditEntry]) -> List[str]:
            violations = []
            admin_count: Dict[str, int] = {}
            for e in entries:
                if e.detail.get("access_level") == AccessLevel.ADMIN.value:
                    admin_count[e.actor] = admin_count.get(e.actor, 0) + 1
            for actor, count in admin_count.items():
                if count > 10:
                    violations.append(
                        f"Actor '{actor}' performed {count} admin-level operations"
                    )
            return violations

        self.add_rule(ComplianceRule(
            rule_id="PRIV_ESC_001",
            framework=ComplianceFramework.SOC2.value,
            description="Admin-level operations should be infrequent",
            check_fn=privilege_escalation_check,
            severity=Severity.WARNING.value,
        ))


# ---------------------------------------------------------------------------
# Audit Logger — Core
# ---------------------------------------------------------------------------

class AuditLogger:
    """
    Append-only, tamper-evident audit logger with chained HMAC integrity.

    Each entry's hash covers its content + the previous entry's hash,
    forming an immutable chain. Any tampering breaks the chain and is
    detectable via verify_chain().
    """

    def __init__(
        self,
        audit_dir: Optional[str] = None,
        retention_policy: Optional[RetentionPolicy] = None,
        alert_callback: Optional[Callable[[AuditEntry], None]] = None,
    ) -> None:
        self._dir = Path(audit_dir) if audit_dir else DEFAULT_AUDIT_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        self._retention = retention_policy or RetentionPolicy()
        self._alert_callback = alert_callback
        self._lock = threading.Lock()
        self._rule_engine = ComplianceRuleEngine()
        self._session_id = uuid.uuid4().hex[:12]
        self._prev_hash = "genesis"
        self._entry_count = 0
        self._current_segment = self._dir / "audit_current.jsonl"

        # Recover chain state from existing log
        self._recover_chain()

    # -- Public API ----------------------------------------------------------

    def log_action(
        self,
        actor: str,
        action: str,
        resource: str = "",
        detail: Optional[Dict[str, Any]] = None,
        severity: str = Severity.INFO.value,
        source_ip: str = "127.0.0.1",
    ) -> AuditEntry:
        """Log a user/agent action."""
        return self._append(
            event_type=AuditEventType.USER_ACTION.value,
            actor=actor,
            action=action,
            resource=resource,
            detail=detail or {},
            severity=severity,
            source_ip=source_ip,
        )

    def log_data_access(
        self,
        actor: str,
        access_type: str,
        resource: str,
        fields_accessed: Optional[List[str]] = None,
        purpose: Optional[str] = None,
        detail: Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        """Log data read/write/delete with field-level detail."""
        event_map = {
            "read": AuditEventType.DATA_ACCESS.value,
            "write": AuditEventType.DATA_MODIFY.value,
            "delete": AuditEventType.DATA_DELETE.value,
        }
        event_type = event_map.get(access_type, AuditEventType.DATA_ACCESS.value)
        payload = dict(detail or {})
        payload["access_level"] = access_type
        if fields_accessed:
            payload["fields_accessed"] = fields_accessed
        if purpose:
            payload["purpose"] = purpose
        return self._append(
            event_type=event_type,
            actor=actor,
            action=f"data.{access_type}",
            resource=resource,
            detail=payload,
            severity=Severity.INFO.value,
        )

    def log_auth_event(
        self,
        actor: str,
        action: str,
        success: bool,
        detail: Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        """Log authentication/authorization events."""
        payload = dict(detail or {})
        payload["success"] = success
        severity = Severity.INFO.value if success else Severity.WARNING.value
        return self._append(
            event_type=AuditEventType.AUTH_EVENT.value,
            actor=actor,
            action=action,
            resource="auth",
            detail=payload,
            severity=severity,
        )

    def log_config_change(
        self,
        actor: str,
        config_key: str,
        old_value: Any,
        new_value: Any,
        detail: Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        """Log configuration changes for change management compliance."""
        payload = dict(detail or {})
        payload["config_key"] = config_key
        payload["old_value"] = str(old_value)
        payload["new_value"] = str(new_value)
        return self._append(
            event_type=AuditEventType.CONFIG_CHANGE.value,
            actor=actor,
            action="config.change",
            resource=config_key,
            detail=payload,
            severity=Severity.WARNING.value,
        )

    def log_policy_violation(
        self,
        actor: str,
        rule_id: str,
        description: str,
        detail: Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        """Log a detected policy violation."""
        payload = dict(detail or {})
        payload["rule_id"] = rule_id
        payload["description"] = description
        return self._append(
            event_type=AuditEventType.POLICY_VIOLATION.value,
            actor=actor,
            action="policy.violation",
            resource=rule_id,
            detail=payload,
            severity=Severity.ALERT.value,
        )

    def log_agent_action(
        self,
        agent_name: str,
        action: str,
        resource: str = "",
        detail: Optional[Dict[str, Any]] = None,
    ) -> AuditEntry:
        """Log an autonomous agent action."""
        return self._append(
            event_type=AuditEventType.AGENT_ACTION.value,
            actor=f"agent:{agent_name}",
            action=action,
            resource=resource,
            detail=detail or {},
            severity=Severity.INFO.value,
        )

    # -- Query & Reporting ---------------------------------------------------

    def get_entries(
        self,
        hours: Optional[float] = None,
        actor: Optional[str] = None,
        event_type: Optional[str] = None,
        resource: Optional[str] = None,
        severity: Optional[str] = None,
        limit: int = 1000,
    ) -> List[AuditEntry]:
        """Query audit entries with optional filters."""
        cutoff = time.time() - (hours * 3600) if hours else 0
        results: List[AuditEntry] = []

        for segment in self._all_segments():
            if not segment.exists():
                continue
            try:
                with open(segment, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        d = json.loads(line)
                        if d.get("timestamp", 0) < cutoff:
                            continue
                        if actor and d.get("actor") != actor:
                            continue
                        if event_type and d.get("event_type") != event_type:
                            continue
                        if resource and resource not in d.get("resource", ""):
                            continue
                        if severity and d.get("severity") != severity:
                            continue
                        results.append(AuditEntry.from_dict(d))
                        if len(results) >= limit:
                            return results
            except (json.JSONDecodeError, OSError):
                continue
        return results

    def verify_chain(self, entries: Optional[List[AuditEntry]] = None) -> Tuple[bool, str]:
        """
        Verify the integrity chain of audit entries.
        Returns (is_valid, message).
        """
        if entries is None:
            entries = self.get_entries(limit=100_000)
        if not entries:
            return True, "No entries to verify"

        prev_hash = "genesis"
        for i, entry in enumerate(entries):
            expected_hash = self._compute_hash(entry, prev_hash)
            if entry.entry_hash != expected_hash:
                return False, (
                    f"Chain broken at entry {i} (id={entry.entry_id}): "
                    f"expected hash {expected_hash[:16]}..., "
                    f"got {entry.entry_hash[:16]}..."
                )
            if entry.prev_hash != prev_hash:
                return False, (
                    f"Chain broken at entry {i} (id={entry.entry_id}): "
                    f"prev_hash mismatch"
                )
            prev_hash = entry.entry_hash
        return True, f"Chain verified: {len(entries)} entries intact"

    def compliance_report(
        self, hours: float = 24, frameworks: Optional[List[str]] = None
    ) -> Dict[str, Any]:
        """Generate a compliance report for the given time window."""
        entries = self.get_entries(hours=hours, limit=100_000)
        violations = self._rule_engine.evaluate(entries)

        # Build summary statistics
        actor_counts: Dict[str, int] = {}
        type_counts: Dict[str, int] = {}
        severity_counts: Dict[str, int] = {}
        resource_access: Dict[str, int] = {}

        for e in entries:
            actor_counts[e.actor] = actor_counts.get(e.actor, 0) + 1
            type_counts[e.event_type] = type_counts.get(e.event_type, 0) + 1
            severity_counts[e.severity] = severity_counts.get(e.severity, 0) + 1
            if e.resource:
                resource_access[e.resource] = resource_access.get(e.resource, 0) + 1

        # Chain integrity check
        valid, chain_msg = self.verify_chain(entries)

        report = {
            "generated_at": time.time(),
            "window_hours": hours,
            "total_entries": len(entries),
            "chain_integrity": {"valid": valid, "message": chain_msg},
            "actors": actor_counts,
            "event_types": type_counts,
            "severity_distribution": severity_counts,
            "top_resources": dict(
                sorted(resource_access.items(), key=lambda x: -x[1])[:20]
            ),
            "compliance_violations": violations,
            "violation_count": sum(len(v) for v in violations.values()),
            "retention_policy": {
                "framework": self._retention.framework,
                "retention_days": self._retention.effective_retention(),
                "immutable": self._retention.immutable,
            },
        }

        # Log the compliance check itself
        self._append(
            event_type=AuditEventType.COMPLIANCE_CHECK.value,
            actor="system",
            action="compliance.report",
            resource="audit_log",
            detail={
                "window_hours": hours,
                "total_entries": len(entries),
                "violation_count": report["violation_count"],
            },
            severity=Severity.INFO.value,
        )

        return report

    def export_jsonl(self, output_path: str, hours: Optional[float] = None) -> int:
        """Export entries to JSONL file for SIEM ingestion. Returns count."""
        entries = self.get_entries(hours=hours, limit=1_000_000)
        with open(output_path, "w") as f:
            for entry in entries:
                f.write(entry.to_json() + "\n")
        return len(entries)

    @property
    def entry_count(self) -> int:
        return self._entry_count

    # -- Retention Management ------------------------------------------------

    def enforce_retention(self) -> Dict[str, Any]:
        """Archive/purge entries beyond retention window. Returns summary."""
        cutoff = time.time() - (self._retention.effective_retention() * 86400)
        archive_cutoff = time.time() - (self._retention.archive_after_days * 86400)
        archived = 0
        purged = 0

        archive_dir = self._dir / "archive"
        archive_dir.mkdir(exist_ok=True)

        for segment in sorted(self._dir.glob("audit_segment_*.jsonl")):
            entries_to_keep: List[str] = []
            entries_to_archive: List[str] = []

            with open(segment, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        d = json.loads(line)
                        ts = d.get("timestamp", 0)
                        if ts < cutoff:
                            purged += 1
                        elif ts < archive_cutoff:
                            entries_to_archive.append(line)
                            archived += 1
                        else:
                            entries_to_keep.append(line)
                    except json.JSONDecodeError:
                        continue

            if entries_to_archive:
                archive_file = archive_dir / segment.name
                with open(archive_file, "a") as f:
                    for line in entries_to_archive:
                        f.write(line + "\n")

            if not entries_to_keep:
                segment.unlink(missing_ok=True)
            elif purged > 0 or archived > 0:
                with open(segment, "w") as f:
                    for line in entries_to_keep:
                        f.write(line + "\n")

        return {"archived": archived, "purged": purged}

    # -- Internal ------------------------------------------------------------

    def _append(
        self,
        event_type: str,
        actor: str,
        action: str,
        resource: str,
        detail: Dict[str, Any],
        severity: str,
        source_ip: str = "127.0.0.1",
    ) -> AuditEntry:
        with self._lock:
            entry_id = f"aud-{uuid.uuid4().hex[:12]}"
            ts = time.time()

            # Build entry without hashes first to compute them
            prev_hash = self._prev_hash
            # Create a temporary entry to compute hash
            temp = AuditEntry(
                entry_id=entry_id,
                timestamp=ts,
                event_type=event_type,
                actor=actor,
                action=action,
                resource=resource,
                severity=severity,
                detail=detail,
                source_ip=source_ip,
                session_id=self._session_id,
                prev_hash=prev_hash,
                entry_hash="",  # placeholder
            )
            entry_hash = self._compute_hash(temp, prev_hash)

            entry = AuditEntry(
                entry_id=entry_id,
                timestamp=ts,
                event_type=event_type,
                actor=actor,
                action=action,
                resource=resource,
                severity=severity,
                detail=detail,
                source_ip=source_ip,
                session_id=self._session_id,
                prev_hash=prev_hash,
                entry_hash=entry_hash,
            )

            # Write to current segment
            self._write_entry(entry)
            self._prev_hash = entry_hash
            self._entry_count += 1

            # Rotate segment if needed
            self._maybe_rotate()

            # Alert callback for real-time compliance monitoring
            if self._alert_callback and severity in (
                Severity.CRITICAL.value,
                Severity.ALERT.value,
            ):
                try:
                    self._alert_callback(entry)
                except Exception:
                    pass  # never let callback failure break audit logging

        return entry

    def _write_entry(self, entry: AuditEntry) -> None:
        with open(self._current_segment, "a") as f:
            f.write(entry.to_json() + "\n")
            f.flush()
            os.fsync(f.fileno())

    def _compute_hash(self, entry: AuditEntry, prev_hash: str) -> str:
        """HMAC-SHA256 of entry content chained with previous hash."""
        content = (
            f"{entry.entry_id}|{entry.timestamp}|{entry.event_type}|"
            f"{entry.actor}|{entry.action}|{entry.resource}|"
            f"{entry.severity}|{json.dumps(entry.detail, sort_keys=True)}|"
            f"{entry.source_ip}|{entry.session_id}|{prev_hash}"
        )
        return hmac.new(HMAC_KEY, content.encode(), hashlib.sha256).hexdigest()

    def _maybe_rotate(self) -> None:
        if self._current_segment.exists():
            size = self._current_segment.stat().st_size
            if size >= MAX_SEGMENT_SIZE:
                ts = int(time.time())
                archived = self._dir / f"audit_segment_{ts}.jsonl"
                self._current_segment.rename(archived)

    def _recover_chain(self) -> None:
        """Recover prev_hash and entry_count from existing log on startup."""
        for segment in self._all_segments():
            if not segment.exists():
                continue
            try:
                with open(segment, "r") as f:
                    for line in f:
                        line = line.strip()
                        if not line:
                            continue
                        d = json.loads(line)
                        self._prev_hash = d.get("entry_hash", self._prev_hash)
                        self._entry_count += 1
            except (json.JSONDecodeError, OSError):
                continue

    def _all_segments(self) -> List[Path]:
        """Return all segment files in chronological order."""
        segments = sorted(self._dir.glob("audit_segment_*.jsonl"))
        if self._current_segment.exists():
            segments.append(self._current_segment)
        return segments


# ---------------------------------------------------------------------------
# Singleton
# ---------------------------------------------------------------------------

_global_audit_logger: Optional[AuditLogger] = None
_global_lock = threading.Lock()


def get_audit_logger(**kwargs: Any) -> AuditLogger:
    """Get or create the global AuditLogger singleton."""
    global _global_audit_logger
    with _global_lock:
        if _global_audit_logger is None:
            _global_audit_logger = AuditLogger(**kwargs)
        return _global_audit_logger


def reset_audit_logger() -> None:
    """Reset global singleton (for testing)."""
    global _global_audit_logger
    with _global_lock:
        _global_audit_logger = None


# ---------------------------------------------------------------------------
# Convenience decorators
# ---------------------------------------------------------------------------

def audit_action(actor: str, action: str, resource: str = ""):
    """Decorator to automatically audit function calls."""
    def decorator(fn: Callable) -> Callable:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            logger = get_audit_logger()
            start = time.time()
            error = None
            try:
                result = fn(*args, **kwargs)
                return result
            except Exception as exc:
                error = str(exc)
                raise
            finally:
                duration = time.time() - start
                logger.log_action(
                    actor=actor,
                    action=action,
                    resource=resource,
                    detail={
                        "duration_ms": round(duration * 1000, 2),
                        "error": error,
                    },
                    severity=Severity.CRITICAL.value if error else Severity.INFO.value,
                )
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper
    return decorator


def audit_data_access(actor: str, resource: str, access_type: str = "read"):
    """Decorator to audit data access patterns."""
    def decorator(fn: Callable) -> Callable:
        def wrapper(*args: Any, **kwargs: Any) -> Any:
            logger = get_audit_logger()
            logger.log_data_access(
                actor=actor,
                access_type=access_type,
                resource=resource,
                detail={"function": fn.__name__},
            )
            return fn(*args, **kwargs)
        wrapper.__name__ = fn.__name__
        wrapper.__doc__ = fn.__doc__
        return wrapper
    return decorator


# ===========================================================================
# __main__ — Verification assertions
# ===========================================================================

if __name__ == "__main__":
    import shutil
    import tempfile

    print("=" * 70)
    print("Audit Compliance Module — Verification Suite")
    print("=" * 70)

    # Use temp directory for isolated testing
    test_dir = tempfile.mkdtemp(prefix="audit_test_")
    alerts_received: List[AuditEntry] = []

    def alert_handler(entry: AuditEntry) -> None:
        alerts_received.append(entry)

    try:
        reset_audit_logger()
        logger = AuditLogger(
            audit_dir=test_dir,
            retention_policy=RetentionPolicy(
                framework=ComplianceFramework.SOC2.value,
                retention_days=90,
            ),
            alert_callback=alert_handler,
        )

        # -------------------------------------------------------------------
        # Test 1: Basic action logging
        # -------------------------------------------------------------------
        print("\n[Test 1] Basic action logging...")
        e1 = logger.log_action(
            actor="user:jimmy",
            action="task.create",
            resource="projects.json",
            detail={"task_id": "t-123", "title": "Build API"},
        )
        assert e1.entry_id.startswith("aud-"), f"Bad entry_id: {e1.entry_id}"
        assert e1.actor == "user:jimmy"
        assert e1.action == "task.create"
        assert e1.event_type == AuditEventType.USER_ACTION.value
        assert e1.prev_hash == "genesis", f"First entry prev_hash should be genesis"
        assert len(e1.entry_hash) == 64, "Hash should be 64-char hex (SHA256)"
        print(f"  PASS — entry_id={e1.entry_id}, hash={e1.entry_hash[:16]}...")

        # -------------------------------------------------------------------
        # Test 2: Chain integrity
        # -------------------------------------------------------------------
        print("\n[Test 2] Chain integrity (3 entries)...")
        e2 = logger.log_action("user:jimmy", "task.update", "projects.json")
        e3 = logger.log_action("agent:executor", "task.execute", "agents/executor.py")

        assert e2.prev_hash == e1.entry_hash, "e2 should chain from e1"
        assert e3.prev_hash == e2.entry_hash, "e3 should chain from e2"

        entries = logger.get_entries()
        valid, msg = logger.verify_chain(entries)
        assert valid, f"Chain verification failed: {msg}"
        print(f"  PASS — {msg}")

        # -------------------------------------------------------------------
        # Test 3: Data access logging
        # -------------------------------------------------------------------
        print("\n[Test 3] Data access logging...")
        e4 = logger.log_data_access(
            actor="agent:executor",
            access_type="read",
            resource="state/runtime-lessons.json",
            fields_accessed=["attempt_count", "strategy"],
            purpose="task retry evaluation",
        )
        assert e4.event_type == AuditEventType.DATA_ACCESS.value
        assert e4.detail["fields_accessed"] == ["attempt_count", "strategy"]
        assert e4.detail["purpose"] == "task retry evaluation"
        print(f"  PASS — data access logged with fields and purpose")

        e5 = logger.log_data_access(
            actor="user:jimmy",
            access_type="write",
            resource="state/agent_stats.json",
            detail={"changes": {"success_rate": "0.49 -> 0.52"}},
        )
        assert e5.event_type == AuditEventType.DATA_MODIFY.value
        print(f"  PASS — data modify logged")

        e6 = logger.log_data_access(
            actor="system",
            access_type="delete",
            resource="state/old_checkpoint.json",
            detail={"reason": "retention policy enforcement"},
        )
        assert e6.event_type == AuditEventType.DATA_DELETE.value
        print(f"  PASS — data delete logged")

        # -------------------------------------------------------------------
        # Test 4: Auth event logging
        # -------------------------------------------------------------------
        print("\n[Test 4] Auth event logging...")
        e7 = logger.log_auth_event(
            actor="user:jimmy",
            action="login",
            success=True,
            detail={"method": "ssh_key"},
        )
        assert e7.event_type == AuditEventType.AUTH_EVENT.value
        assert e7.detail["success"] is True
        assert e7.severity == Severity.INFO.value

        e8 = logger.log_auth_event(
            actor="user:unknown",
            action="login",
            success=False,
            detail={"method": "password", "reason": "invalid credentials"},
        )
        assert e8.severity == Severity.WARNING.value
        print(f"  PASS — auth events logged with correct severity")

        # -------------------------------------------------------------------
        # Test 5: Config change logging
        # -------------------------------------------------------------------
        print("\n[Test 5] Config change logging...")
        e9 = logger.log_config_change(
            actor="user:jimmy",
            config_key="rescue_budget_pct",
            old_value=10,
            new_value=15,
            detail={"reason": "increase rescue capacity during incident"},
        )
        assert e9.event_type == AuditEventType.CONFIG_CHANGE.value
        assert e9.detail["old_value"] == "10"
        assert e9.detail["new_value"] == "15"
        print(f"  PASS — config change logged with old/new values")

        # -------------------------------------------------------------------
        # Test 6: Policy violation logging & alert callback
        # -------------------------------------------------------------------
        print("\n[Test 6] Policy violation + alert callback...")
        alerts_before = len(alerts_received)
        e10 = logger.log_policy_violation(
            actor="agent:rogue",
            rule_id="RATE_LIMIT_001",
            description="Exceeded 100 actions per minute",
            detail={"action_count": 150, "window": "60s"},
        )
        assert e10.event_type == AuditEventType.POLICY_VIOLATION.value
        assert e10.severity == Severity.ALERT.value
        assert len(alerts_received) == alerts_before + 1, "Alert callback should fire"
        assert alerts_received[-1].entry_id == e10.entry_id
        print(f"  PASS — violation logged, alert callback fired")

        # -------------------------------------------------------------------
        # Test 7: Agent action logging
        # -------------------------------------------------------------------
        print("\n[Test 7] Agent action logging...")
        e11 = logger.log_agent_action(
            agent_name="executor",
            action="task.complete",
            resource="t-456",
            detail={"quality_score": 85, "duration_s": 12.5},
        )
        assert e11.actor == "agent:executor"
        assert e11.event_type == AuditEventType.AGENT_ACTION.value
        print(f"  PASS — agent action logged")

        # -------------------------------------------------------------------
        # Test 8: Query with filters
        # -------------------------------------------------------------------
        print("\n[Test 8] Query with filters...")
        jimmy_entries = logger.get_entries(actor="user:jimmy")
        assert len(jimmy_entries) >= 4, f"Expected ≥4 jimmy entries, got {len(jimmy_entries)}"

        agent_entries = logger.get_entries(
            event_type=AuditEventType.AGENT_ACTION.value
        )
        assert len(agent_entries) >= 1

        alert_entries = logger.get_entries(severity=Severity.ALERT.value)
        assert len(alert_entries) >= 1

        resource_entries = logger.get_entries(resource="runtime-lessons")
        assert len(resource_entries) >= 1
        print(f"  PASS — filters: actor={len(jimmy_entries)}, agent={len(agent_entries)}, "
              f"alert={len(alert_entries)}, resource={len(resource_entries)}")

        # -------------------------------------------------------------------
        # Test 9: Compliance report generation
        # -------------------------------------------------------------------
        print("\n[Test 9] Compliance report...")
        report = logger.compliance_report(hours=1)
        assert report["total_entries"] > 0
        assert report["chain_integrity"]["valid"] is True
        assert "actors" in report
        assert "user:jimmy" in report["actors"]
        assert "compliance_violations" in report
        assert report["retention_policy"]["framework"] == ComplianceFramework.SOC2.value
        print(f"  PASS — report: {report['total_entries']} entries, "
              f"{report['violation_count']} violations, chain={report['chain_integrity']['valid']}")

        # -------------------------------------------------------------------
        # Test 10: Compliance rule engine — deletion without detail
        # -------------------------------------------------------------------
        print("\n[Test 10] Compliance rule: deletion without detail...")
        bare_delete = logger.log_data_access(
            actor="agent:cleanup",
            access_type="delete",
            resource="state/temp.json",
        )
        # The detail will have access_level but that should be fine
        # Let's add one with truly empty detail via _append
        rule_engine = logger._rule_engine
        test_entries_for_rules = [
            AuditEntry(
                entry_id="test-del-1",
                timestamp=time.time(),
                event_type=AuditEventType.DATA_DELETE.value,
                actor="agent:bad",
                action="data.delete",
                resource="important.json",
                severity=Severity.INFO.value,
                detail={},
                source_ip="127.0.0.1",
                session_id="test",
                prev_hash="x",
                entry_hash="y",
            )
        ]
        violations = rule_engine.evaluate(test_entries_for_rules)
        assert "DELETE_DETAIL_001" in violations, "Should flag empty-detail deletion"
        print(f"  PASS — DELETE_DETAIL_001 triggered: {violations['DELETE_DETAIL_001'][0][:60]}...")

        # -------------------------------------------------------------------
        # Test 11: GDPR PII access check
        # -------------------------------------------------------------------
        print("\n[Test 11] GDPR PII field access rule...")
        pii_entries = [
            AuditEntry(
                entry_id="test-pii-1",
                timestamp=time.time(),
                event_type=AuditEventType.DATA_ACCESS.value,
                actor="agent:reader",
                action="data.read",
                resource="users.json",
                severity=Severity.INFO.value,
                detail={"fields_accessed": ["email", "name"], "access_level": "read"},
                source_ip="127.0.0.1",
                session_id="test",
                prev_hash="x",
                entry_hash="y",
            )
        ]
        violations = rule_engine.evaluate(pii_entries)
        assert "GDPR_PII_001" in violations, "Should flag PII access without purpose"
        assert len(violations["GDPR_PII_001"]) == 2, "Two PII fields without purpose"
        print(f"  PASS — GDPR_PII_001 triggered for 2 PII fields")

        # Test that adding purpose clears the violation
        pii_with_purpose = [
            AuditEntry(
                entry_id="test-pii-2",
                timestamp=time.time(),
                event_type=AuditEventType.DATA_ACCESS.value,
                actor="agent:reader",
                action="data.read",
                resource="users.json",
                severity=Severity.INFO.value,
                detail={
                    "fields_accessed": ["email"],
                    "access_level": "read",
                    "purpose": "send notification",
                },
                source_ip="127.0.0.1",
                session_id="test",
                prev_hash="x",
                entry_hash="y",
            )
        ]
        violations2 = rule_engine.evaluate(pii_with_purpose)
        assert "GDPR_PII_001" not in violations2, "Purpose provided — no violation"
        print(f"  PASS — PII access with purpose: no violation")

        # -------------------------------------------------------------------
        # Test 12: Privilege escalation check
        # -------------------------------------------------------------------
        print("\n[Test 12] Privilege escalation rule...")
        admin_entries = [
            AuditEntry(
                entry_id=f"test-admin-{i}",
                timestamp=time.time(),
                event_type=AuditEventType.USER_ACTION.value,
                actor="user:admin_abuser",
                action="admin.action",
                resource="system",
                severity=Severity.INFO.value,
                detail={"access_level": AccessLevel.ADMIN.value},
                source_ip="127.0.0.1",
                session_id="test",
                prev_hash="x",
                entry_hash="y",
            )
            for i in range(15)
        ]
        violations = rule_engine.evaluate(admin_entries)
        assert "PRIV_ESC_001" in violations
        print(f"  PASS — PRIV_ESC_001 triggered: {violations['PRIV_ESC_001'][0]}")

        # -------------------------------------------------------------------
        # Test 13: Chain tamper detection
        # -------------------------------------------------------------------
        print("\n[Test 13] Tamper detection...")
        all_entries = logger.get_entries(limit=100_000)
        # Tamper with one entry
        if len(all_entries) >= 3:
            tampered = list(all_entries)
            original = tampered[1]
            tampered[1] = AuditEntry(
                entry_id=original.entry_id,
                timestamp=original.timestamp,
                event_type=original.event_type,
                actor="TAMPERED_ACTOR",
                action=original.action,
                resource=original.resource,
                severity=original.severity,
                detail=original.detail,
                source_ip=original.source_ip,
                session_id=original.session_id,
                prev_hash=original.prev_hash,
                entry_hash=original.entry_hash,
            )
            valid, msg = logger.verify_chain(tampered)
            assert not valid, "Tampered chain should be invalid"
            assert "Chain broken" in msg
            print(f"  PASS — tamper detected: {msg[:60]}...")

        # -------------------------------------------------------------------
        # Test 14: Export to JSONL
        # -------------------------------------------------------------------
        print("\n[Test 14] JSONL export...")
        export_path = os.path.join(test_dir, "export.jsonl")
        count = logger.export_jsonl(export_path, hours=1)
        assert count > 0
        with open(export_path) as f:
            lines = f.readlines()
        assert len(lines) == count
        # Verify each line is valid JSON
        for line in lines:
            d = json.loads(line)
            assert "entry_id" in d
            assert "entry_hash" in d
        print(f"  PASS — exported {count} entries to JSONL")

        # -------------------------------------------------------------------
        # Test 15: Retention policy
        # -------------------------------------------------------------------
        print("\n[Test 15] Retention policy enforcement...")
        rp = RetentionPolicy(retention_days=90, min_retention_days=7)
        assert rp.effective_retention() == 90
        rp2 = RetentionPolicy(retention_days=3, min_retention_days=7)
        assert rp2.effective_retention() == 7, "Should enforce minimum"
        print(f"  PASS — retention effective: {rp.effective_retention()}d, "
              f"min enforced: {rp2.effective_retention()}d")

        # -------------------------------------------------------------------
        # Test 16: Decorator — audit_action
        # -------------------------------------------------------------------
        print("\n[Test 16] @audit_action decorator...")
        import orchestrator.audit_compliance as _mod
        dec_dir = os.path.join(test_dir, "decorator_test")
        dec_logger = AuditLogger(audit_dir=dec_dir)

        # Monkey-patch singleton for decorator test
        _orig = _mod._global_audit_logger
        _mod._global_audit_logger = dec_logger

        @audit_action(actor="user:jimmy", action="deploy.start", resource="production")
        def do_deploy(version: str) -> str:
            return f"deployed {version}"

        result = do_deploy("v42")
        assert result == "deployed v42"
        dec_entries = [e for e in dec_logger.get_entries() if e.action == "deploy.start"]
        assert len(dec_entries) >= 1, f"Expected deploy entries, got {len(dec_entries)}"
        assert dec_entries[0].detail["error"] is None
        assert dec_entries[0].detail["duration_ms"] >= 0
        print(f"  PASS — decorator logged deploy action, duration={dec_entries[0].detail['duration_ms']}ms")

        # Test decorator with exception
        @audit_action(actor="user:jimmy", action="deploy.fail", resource="production")
        def do_bad_deploy() -> None:
            raise RuntimeError("deploy failed")

        try:
            do_bad_deploy()
        except RuntimeError:
            pass

        err_entries = [e for e in dec_logger.get_entries() if e.action == "deploy.fail"]
        assert len(err_entries) >= 1
        assert err_entries[0].detail["error"] == "deploy failed"
        assert err_entries[0].severity == Severity.CRITICAL.value
        print(f"  PASS — decorator caught error, severity=critical")

        _mod._global_audit_logger = _orig  # restore

        # -------------------------------------------------------------------
        # Test 17: Thread safety
        # -------------------------------------------------------------------
        print("\n[Test 17] Thread safety (concurrent writes)...")
        reset_audit_logger()
        thread_logger = AuditLogger(audit_dir=os.path.join(test_dir, "thread_test"))
        errors: List[str] = []

        def write_entries(thread_id: int, count: int) -> None:
            try:
                for i in range(count):
                    thread_logger.log_action(
                        actor=f"thread:{thread_id}",
                        action=f"test.write.{i}",
                        resource="concurrent",
                    )
            except Exception as exc:
                errors.append(f"Thread {thread_id}: {exc}")

        threads = [
            threading.Thread(target=write_entries, args=(t, 20))
            for t in range(5)
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors, f"Thread errors: {errors}"
        assert thread_logger.entry_count == 100, (
            f"Expected 100 entries, got {thread_logger.entry_count}"
        )
        valid, msg = thread_logger.verify_chain()
        assert valid, f"Chain broken after concurrent writes: {msg}"
        print(f"  PASS — 5 threads × 20 writes = {thread_logger.entry_count} entries, chain intact")

        # -------------------------------------------------------------------
        # Test 18: Entry count tracks correctly
        # -------------------------------------------------------------------
        print("\n[Test 18] Entry count tracking...")
        reset_audit_logger()
        count_logger = AuditLogger(audit_dir=os.path.join(test_dir, "count_test"))
        assert count_logger.entry_count == 0
        for i in range(5):
            count_logger.log_action("system", f"test.{i}")
        assert count_logger.entry_count == 5
        print(f"  PASS — count={count_logger.entry_count}")

        # -------------------------------------------------------------------
        # Test 19: Recovery from existing log
        # -------------------------------------------------------------------
        print("\n[Test 19] Chain recovery on restart...")
        recovery_dir = os.path.join(test_dir, "recovery_test")
        reset_audit_logger()
        log_a = AuditLogger(audit_dir=recovery_dir)
        log_a.log_action("user:a", "first")
        log_a.log_action("user:a", "second")
        last_hash = log_a._prev_hash
        count_before = log_a.entry_count

        # Simulate restart
        log_b = AuditLogger(audit_dir=recovery_dir)
        assert log_b._prev_hash == last_hash, "Should recover prev_hash"
        assert log_b.entry_count == count_before, "Should recover entry count"
        e_new = log_b.log_action("user:b", "third")
        assert e_new.prev_hash == last_hash, "New entry should chain from recovered hash"

        all_recovered = log_b.get_entries()
        valid, msg = log_b.verify_chain(all_recovered)
        assert valid, f"Recovered chain invalid: {msg}"
        print(f"  PASS — recovered {log_b.entry_count} entries, chain valid after restart")

        # -------------------------------------------------------------------
        # Test 20: Immutable entry (frozen dataclass)
        # -------------------------------------------------------------------
        print("\n[Test 20] Entry immutability...")
        try:
            e1.actor = "tampered"  # type: ignore
            assert False, "Should have raised FrozenInstanceError"
        except AttributeError:
            pass
        print(f"  PASS — AuditEntry is immutable (frozen dataclass)")

        # -------------------------------------------------------------------
        # Test 21: Custom compliance rule
        # -------------------------------------------------------------------
        print("\n[Test 21] Custom compliance rule...")
        engine = ComplianceRuleEngine()

        def no_system_deletes(entries: List[AuditEntry]) -> List[str]:
            return [
                f"System actor deleted {e.resource}"
                for e in entries
                if e.actor == "system" and e.event_type == AuditEventType.DATA_DELETE.value
            ]

        engine.add_rule(ComplianceRule(
            rule_id="CUSTOM_001",
            framework="INTERNAL",
            description="System should not delete data directly",
            check_fn=no_system_deletes,
            severity=Severity.CRITICAL.value,
        ))

        test_custom = [
            AuditEntry(
                entry_id="c1", timestamp=time.time(),
                event_type=AuditEventType.DATA_DELETE.value,
                actor="system", action="data.delete", resource="secrets.json",
                severity="info", detail={}, source_ip="127.0.0.1",
                session_id="t", prev_hash="x", entry_hash="y",
            )
        ]
        v = engine.evaluate(test_custom)
        assert "CUSTOM_001" in v
        print(f"  PASS — custom rule triggered: {v['CUSTOM_001'][0]}")

        # -------------------------------------------------------------------
        # Summary
        # -------------------------------------------------------------------
        print("\n" + "=" * 70)
        print("ALL 21 TESTS PASSED")
        print("=" * 70)
        print(f"\nAudit compliance module verified:")
        print(f"  - Immutable, chained-hash audit entries")
        print(f"  - User action, data access, auth, config change, policy violation logging")
        print(f"  - HMAC-SHA256 tamper-evident chain with genesis anchor")
        print(f"  - Compliance rule engine (rate limit, deletion, GDPR PII, privilege escalation)")
        print(f"  - Chain verification detects tampering")
        print(f"  - JSONL export for SIEM ingestion")
        print(f"  - Retention policy with min-floor enforcement")
        print(f"  - @audit_action and @audit_data_access decorators")
        print(f"  - Thread-safe concurrent writes (100 entries, chain intact)")
        print(f"  - Recovery from existing log on restart")
        print(f"  - Frozen dataclass immutability")
        print(f"  - Custom compliance rules")

    finally:
        shutil.rmtree(test_dir, ignore_errors=True)
        reset_audit_logger()
