#!/usr/bin/env python3
"""
orchestrator/model_versioning.py — Model versioning & rollback capability
=========================================================================
Version all models, track performance per version, quick rollback.

Features:
  - Register model versions with metadata and config
  - Track performance metrics (accuracy, latency, quality score) per version
  - Promote/demote versions (canary → active → retired)
  - Instant rollback to any previous version
  - Performance comparison across versions
  - Automatic rollback on regression detection
  - Persistent JSONL audit log + JSON registry

Usage:
    from orchestrator.model_versioning import ModelVersionManager
    mv = ModelVersionManager()
    mv.register("executor", "v3", model="nexus-local", config={...})
    mv.record_metric("executor", "v3", "quality", 82.5)
    mv.promote("executor", "v3")       # canary → active
    mv.rollback("executor")            # active → previous active
    history = mv.get_history("executor")
"""

import json
import hashlib
import threading
import statistics
from copy import deepcopy
from pathlib import Path
from datetime import datetime, timezone
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple
from enum import Enum


# ── Constants ────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).parent.parent
REGISTRY_DIR = BASE_DIR / "state" / "model_versions"
REGISTRY_FILE = REGISTRY_DIR / "registry.json"
AUDIT_LOG = REGISTRY_DIR / "audit.jsonl"
METRICS_DIR = REGISTRY_DIR / "metrics"
MAX_METRICS_PER_VERSION = 1000
MAX_VERSIONS_PER_MODEL = 50


# ── Enums & Data Classes ────────────────────────────────────────────────────

class VersionStatus(str, Enum):
    CANARY = "canary"
    ACTIVE = "active"
    RETIRED = "retired"
    ROLLED_BACK = "rolled_back"


@dataclass
class PerformanceMetric:
    name: str
    value: float
    timestamp: str
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ModelVersion:
    model_name: str
    version_tag: str
    model_id: str
    status: str = VersionStatus.CANARY.value
    config: Dict[str, Any] = field(default_factory=dict)
    created_at: str = ""
    promoted_at: Optional[str] = None
    retired_at: Optional[str] = None
    checksum: str = ""
    parent_version: Optional[str] = None
    metrics_summary: Dict[str, float] = field(default_factory=dict)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = _now()
        if not self.checksum:
            self.checksum = _checksum(
                f"{self.model_name}:{self.version_tag}:{self.model_id}:{json.dumps(self.config, sort_keys=True)}"
            )


# ── Helpers ──────────────────────────────────────────────────────────────────

def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _checksum(data: str) -> str:
    return hashlib.sha256(data.encode()).hexdigest()[:16]


# ── Core Manager ─────────────────────────────────────────────────────────────

class ModelVersionManager:
    """
    Thread-safe model version registry with performance tracking and rollback.
    """

    def __init__(self, registry_dir: Optional[Path] = None):
        self._dir = registry_dir or REGISTRY_DIR
        self._dir.mkdir(parents=True, exist_ok=True)
        (self._dir / "metrics").mkdir(exist_ok=True)
        self._registry_file = self._dir / "registry.json"
        self._audit_log = self._dir / "audit.jsonl"
        self._lock = threading.Lock()
        self._registry: Dict[str, Dict[str, dict]] = {}  # model_name → {version_tag → ModelVersion dict}
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self):
        if self._registry_file.exists():
            try:
                self._registry = json.loads(self._registry_file.read_text())
            except (json.JSONDecodeError, OSError):
                self._registry = {}

    def _save(self):
        tmp = self._registry_file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._registry, indent=2, default=str))
        tmp.replace(self._registry_file)

    def _audit(self, action: str, model_name: str, version_tag: str = "", detail: str = ""):
        entry = {
            "ts": _now(),
            "action": action,
            "model": model_name,
            "version": version_tag,
            "detail": detail,
        }
        try:
            with open(self._audit_log, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except OSError:
            pass

    # ── Registration ─────────────────────────────────────────────────────────

    def register(
        self,
        model_name: str,
        version_tag: str,
        model_id: str,
        config: Optional[Dict[str, Any]] = None,
        parent_version: Optional[str] = None,
    ) -> ModelVersion:
        """Register a new model version. Starts in CANARY status."""
        with self._lock:
            if model_name not in self._registry:
                self._registry[model_name] = {}

            if version_tag in self._registry[model_name]:
                raise ValueError(
                    f"Version {version_tag} already registered for {model_name}"
                )

            # Auto-detect parent if not specified
            if parent_version is None:
                active = self._find_active(model_name)
                if active:
                    parent_version = active["version_tag"]

            mv = ModelVersion(
                model_name=model_name,
                version_tag=version_tag,
                model_id=model_id,
                config=config or {},
                parent_version=parent_version,
            )

            self._registry[model_name][version_tag] = asdict(mv)
            self._prune_versions(model_name)
            self._save()
            self._audit("register", model_name, version_tag, f"model_id={model_id}")
            return mv

    def _prune_versions(self, model_name: str):
        """Remove oldest retired versions beyond MAX_VERSIONS_PER_MODEL."""
        versions = self._registry.get(model_name, {})
        if len(versions) <= MAX_VERSIONS_PER_MODEL:
            return
        retired = [
            (tag, v) for tag, v in versions.items()
            if v["status"] in (VersionStatus.RETIRED.value, VersionStatus.ROLLED_BACK.value)
        ]
        retired.sort(key=lambda x: x[1].get("retired_at", ""))
        to_remove = len(versions) - MAX_VERSIONS_PER_MODEL
        for tag, _ in retired[:to_remove]:
            del versions[tag]
            metrics_file = self._dir / "metrics" / f"{model_name}_{tag}.jsonl"
            if metrics_file.exists():
                metrics_file.unlink()

    # ── Metrics ──────────────────────────────────────────────────────────────

    def record_metric(
        self,
        model_name: str,
        version_tag: str,
        metric_name: str,
        value: float,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> PerformanceMetric:
        """Record a performance metric for a model version."""
        with self._lock:
            self._ensure_version_exists(model_name, version_tag)

            pm = PerformanceMetric(
                name=metric_name,
                value=value,
                timestamp=_now(),
                metadata=metadata or {},
            )

            # Append to metrics file
            metrics_file = self._dir / "metrics" / f"{model_name}_{version_tag}.jsonl"
            with open(metrics_file, "a") as f:
                f.write(json.dumps(asdict(pm)) + "\n")

            # Update summary
            self._update_metrics_summary(model_name, version_tag, metric_name)
            self._save()
            return pm

    def _update_metrics_summary(self, model_name: str, version_tag: str, metric_name: str):
        """Recompute summary stats for a specific metric."""
        metrics = self._load_metrics(model_name, version_tag)
        values = [m["value"] for m in metrics if m["name"] == metric_name]
        if not values:
            return
        summary = self._registry[model_name][version_tag].setdefault("metrics_summary", {})
        summary[f"{metric_name}_mean"] = round(statistics.mean(values), 4)
        summary[f"{metric_name}_latest"] = values[-1]
        summary[f"{metric_name}_count"] = len(values)
        if len(values) >= 2:
            summary[f"{metric_name}_stdev"] = round(statistics.stdev(values), 4)
            summary[f"{metric_name}_min"] = min(values)
            summary[f"{metric_name}_max"] = max(values)

    def _load_metrics(self, model_name: str, version_tag: str) -> List[dict]:
        """Load all raw metrics for a model version."""
        metrics_file = self._dir / "metrics" / f"{model_name}_{version_tag}.jsonl"
        if not metrics_file.exists():
            return []
        metrics = []
        for line in metrics_file.read_text().splitlines():
            line = line.strip()
            if line:
                try:
                    metrics.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return metrics[-MAX_METRICS_PER_VERSION:]

    def get_metrics(self, model_name: str, version_tag: str) -> List[dict]:
        """Public access to raw metrics for a model version."""
        with self._lock:
            self._ensure_version_exists(model_name, version_tag)
            return self._load_metrics(model_name, version_tag)

    # ── Promotion / Demotion ─────────────────────────────────────────────────

    def promote(self, model_name: str, version_tag: str) -> str:
        """
        Promote a version: canary → active.
        If another version is active, it becomes retired.
        Returns the new status.
        """
        with self._lock:
            self._ensure_version_exists(model_name, version_tag)
            version = self._registry[model_name][version_tag]
            current_status = version["status"]

            if current_status == VersionStatus.ACTIVE.value:
                return current_status  # already active

            promotable = (VersionStatus.CANARY.value, VersionStatus.RETIRED.value, VersionStatus.ROLLED_BACK.value)
            if current_status not in promotable:
                raise ValueError(
                    f"Cannot promote from {current_status}. Must be canary, retired, or rolled_back."
                )

            # Retire current active
            current_active = self._find_active(model_name)
            if current_active and current_active["version_tag"] != version_tag:
                current_active["status"] = VersionStatus.RETIRED.value
                current_active["retired_at"] = _now()
                self._audit(
                    "retire", model_name, current_active["version_tag"],
                    f"replaced by {version_tag}"
                )

            version["status"] = VersionStatus.ACTIVE.value
            version["promoted_at"] = _now()
            self._save()
            self._audit("promote", model_name, version_tag, "canary → active")
            return VersionStatus.ACTIVE.value

    def retire(self, model_name: str, version_tag: str) -> str:
        """Manually retire a version."""
        with self._lock:
            self._ensure_version_exists(model_name, version_tag)
            version = self._registry[model_name][version_tag]
            version["status"] = VersionStatus.RETIRED.value
            version["retired_at"] = _now()
            self._save()
            self._audit("retire", model_name, version_tag, "manual retire")
            return VersionStatus.RETIRED.value

    # ── Rollback ─────────────────────────────────────────────────────────────

    def rollback(self, model_name: str, target_version: Optional[str] = None) -> Tuple[str, str]:
        """
        Roll back to a previous version.
        If target_version is None, rolls back to the parent of the current active version.
        Returns (rolled_back_from, rolled_back_to).
        """
        with self._lock:
            if model_name not in self._registry:
                raise ValueError(f"Model {model_name} not found")

            current_active = self._find_active(model_name)
            if current_active is None:
                raise ValueError(f"No active version for {model_name}")

            from_tag = current_active["version_tag"]

            # Determine target
            if target_version is None:
                target_version = current_active.get("parent_version")
                if target_version is None:
                    raise ValueError(
                        f"No parent version for {from_tag}. Specify target_version explicitly."
                    )

            if target_version not in self._registry[model_name]:
                raise ValueError(f"Target version {target_version} not found for {model_name}")

            if target_version == from_tag:
                raise ValueError("Cannot roll back to the same version")

            # Mark current as rolled back
            current_active["status"] = VersionStatus.ROLLED_BACK.value
            current_active["retired_at"] = _now()

            # Reactivate target
            target = self._registry[model_name][target_version]
            target["status"] = VersionStatus.ACTIVE.value
            target["promoted_at"] = _now()

            self._save()
            self._audit("rollback", model_name, from_tag, f"rolled back to {target_version}")
            return from_tag, target_version

    def auto_rollback_on_regression(
        self,
        model_name: str,
        version_tag: str,
        metric_name: str,
        threshold: float,
        min_samples: int = 5,
    ) -> Optional[Tuple[str, str]]:
        """
        Check if a version's metric mean is below threshold.
        If so, automatically roll back to parent.
        Returns (from, to) if rollback happened, None otherwise.
        """
        with self._lock:
            self._ensure_version_exists(model_name, version_tag)
            version = self._registry[model_name][version_tag]

            if version["status"] != VersionStatus.ACTIVE.value:
                return None

            metrics = self._load_metrics(model_name, version_tag)
            values = [m["value"] for m in metrics if m["name"] == metric_name]

            if len(values) < min_samples:
                return None

            mean_val = statistics.mean(values)
            if mean_val >= threshold:
                return None

        # Regression detected — rollback (release lock, reacquire via rollback)
        self._audit(
            "regression_detected", model_name, version_tag,
            f"{metric_name} mean={mean_val:.4f} < threshold={threshold}"
        )
        return self.rollback(model_name)

    # ── Comparison ───────────────────────────────────────────────────────────

    def compare_versions(
        self,
        model_name: str,
        version_a: str,
        version_b: str,
        metric_name: str,
    ) -> Dict[str, Any]:
        """Compare a specific metric between two versions."""
        with self._lock:
            self._ensure_version_exists(model_name, version_a)
            self._ensure_version_exists(model_name, version_b)

            metrics_a = self._load_metrics(model_name, version_a)
            metrics_b = self._load_metrics(model_name, version_b)

            values_a = [m["value"] for m in metrics_a if m["name"] == metric_name]
            values_b = [m["value"] for m in metrics_b if m["name"] == metric_name]

            def _stats(values):
                if not values:
                    return {"count": 0}
                result = {"count": len(values), "mean": round(statistics.mean(values), 4)}
                if len(values) >= 2:
                    result["stdev"] = round(statistics.stdev(values), 4)
                    result["min"] = min(values)
                    result["max"] = max(values)
                return result

            stats_a = _stats(values_a)
            stats_b = _stats(values_b)

            improvement = None
            if stats_a.get("mean") is not None and stats_b.get("mean") is not None:
                improvement = round(stats_b["mean"] - stats_a["mean"], 4)

            return {
                "model": model_name,
                "metric": metric_name,
                version_a: stats_a,
                version_b: stats_b,
                "improvement": improvement,
                "better": version_b if (improvement and improvement > 0) else (
                    version_a if (improvement and improvement < 0) else "equal"
                ),
            }

    # ── Query ────────────────────────────────────────────────────────────────

    def get_version(self, model_name: str, version_tag: str) -> dict:
        """Get full version info."""
        with self._lock:
            self._ensure_version_exists(model_name, version_tag)
            return deepcopy(self._registry[model_name][version_tag])

    def get_active(self, model_name: str) -> Optional[dict]:
        """Get the currently active version for a model."""
        with self._lock:
            v = self._find_active(model_name)
            return deepcopy(v) if v else None

    def get_history(self, model_name: str) -> List[dict]:
        """Get all versions for a model, sorted by creation time."""
        with self._lock:
            if model_name not in self._registry:
                return []
            versions = list(self._registry[model_name].values())
            versions.sort(key=lambda v: v.get("created_at", ""))
            return deepcopy(versions)

    def list_models(self) -> List[str]:
        """List all registered model names."""
        with self._lock:
            return list(self._registry.keys())

    def summary(self) -> Dict[str, Any]:
        """Full registry summary."""
        with self._lock:
            result = {}
            for model_name, versions in self._registry.items():
                active = self._find_active(model_name)
                result[model_name] = {
                    "total_versions": len(versions),
                    "active": active["version_tag"] if active else None,
                    "versions": {
                        tag: v["status"] for tag, v in versions.items()
                    },
                }
            return result

    # ── Internal ─────────────────────────────────────────────────────────────

    def _find_active(self, model_name: str) -> Optional[dict]:
        """Find the active version for a model. Returns mutable ref."""
        for v in self._registry.get(model_name, {}).values():
            if v["status"] == VersionStatus.ACTIVE.value:
                return v
        return None

    def _ensure_version_exists(self, model_name: str, version_tag: str):
        if model_name not in self._registry:
            raise ValueError(f"Model {model_name} not found")
        if version_tag not in self._registry[model_name]:
            raise ValueError(f"Version {version_tag} not found for {model_name}")


# ── Singleton ────────────────────────────────────────────────────────────────

_instance: Optional[ModelVersionManager] = None
_instance_lock = threading.Lock()


def get_model_version_manager(registry_dir: Optional[Path] = None) -> ModelVersionManager:
    global _instance
    with _instance_lock:
        if _instance is None:
            _instance = ModelVersionManager(registry_dir)
    return _instance


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    import argparse

    ap = argparse.ArgumentParser(description="Model versioning & rollback")
    sub = ap.add_subparsers(dest="cmd")

    reg = sub.add_parser("register", help="Register a model version")
    reg.add_argument("model")
    reg.add_argument("version")
    reg.add_argument("--model-id", required=True)
    reg.add_argument("--config", default="{}")

    prom = sub.add_parser("promote", help="Promote version to active")
    prom.add_argument("model")
    prom.add_argument("version")

    rb = sub.add_parser("rollback", help="Rollback to previous version")
    rb.add_argument("model")
    rb.add_argument("--target", default=None)

    hist = sub.add_parser("history", help="Show version history")
    hist.add_argument("model")

    sm = sub.add_parser("summary", help="Registry summary")

    cmp = sub.add_parser("compare", help="Compare two versions")
    cmp.add_argument("model")
    cmp.add_argument("version_a")
    cmp.add_argument("version_b")
    cmp.add_argument("--metric", required=True)

    args = ap.parse_args()
    mv = ModelVersionManager()

    if args.cmd == "register":
        v = mv.register(args.model, args.version, args.model_id, json.loads(args.config))
        print(f"Registered {v.model_name} {v.version_tag} (checksum={v.checksum})")
    elif args.cmd == "promote":
        status = mv.promote(args.model, args.version)
        print(f"{args.model} {args.version} → {status}")
    elif args.cmd == "rollback":
        frm, to = mv.rollback(args.model, args.target)
        print(f"Rolled back {args.model}: {frm} → {to}")
    elif args.cmd == "history":
        for v in mv.get_history(args.model):
            print(f"  {v['version_tag']}: {v['status']} (model={v['model_id']}, created={v['created_at']})")
    elif args.cmd == "summary":
        print(json.dumps(mv.summary(), indent=2))
    elif args.cmd == "compare":
        result = mv.compare_versions(args.model, args.version_a, args.version_b, args.metric)
        print(json.dumps(result, indent=2))
    else:
        ap.print_help()


# ── Tests ────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile
    import shutil

    # Use temp directory for isolated tests
    tmp = Path(tempfile.mkdtemp(prefix="model_ver_test_"))
    try:
        mv = ModelVersionManager(registry_dir=tmp)

        # ── Test 1: Register versions ────────────────────────────────────────
        v1 = mv.register("executor", "v1", model_id="nexus-local", config={"temperature": 0.7})
        assert v1.model_name == "executor"
        assert v1.version_tag == "v1"
        assert v1.status == "canary"
        assert v1.checksum != ""
        assert v1.parent_version is None
        print("[PASS] Test 1: Register first version")

        v2 = mv.register("executor", "v2", model_id="nexus-local", config={"temperature": 0.5})
        assert v2.parent_version is None  # no active version yet, so no auto-parent
        print("[PASS] Test 2: Register second version (no active parent yet)")

        # ── Test 3: Promote v1 to active ─────────────────────────────────────
        status = mv.promote("executor", "v1")
        assert status == "active"
        active = mv.get_active("executor")
        assert active is not None
        assert active["version_tag"] == "v1"
        assert active["promoted_at"] is not None
        print("[PASS] Test 3: Promote v1 to active")

        # ── Test 4: Register v3 (should auto-parent to active v1) ───────────
        v3 = mv.register("executor", "v3", model_id="nexus-local", config={"temperature": 0.3})
        assert v3.parent_version == "v1"
        print("[PASS] Test 4: Auto-parent to active version")

        # ── Test 5: Record metrics ───────────────────────────────────────────
        for val in [80.0, 82.5, 85.0, 78.0, 90.0]:
            mv.record_metric("executor", "v1", "quality", val)
        for val in [70.0, 72.0, 68.0, 75.0, 71.0]:
            mv.record_metric("executor", "v1", "latency_ms", val)

        v1_info = mv.get_version("executor", "v1")
        assert v1_info["metrics_summary"]["quality_mean"] == round(statistics.mean([80, 82.5, 85, 78, 90]), 4)
        assert v1_info["metrics_summary"]["quality_latest"] == 90.0
        assert v1_info["metrics_summary"]["quality_count"] == 5
        assert "quality_stdev" in v1_info["metrics_summary"]
        assert "quality_min" in v1_info["metrics_summary"]
        assert "quality_max" in v1_info["metrics_summary"]
        print("[PASS] Test 5: Record and summarize metrics")

        # ── Test 6: Get raw metrics ──────────────────────────────────────────
        raw = mv.get_metrics("executor", "v1")
        assert len(raw) == 10  # 5 quality + 5 latency
        quality_raw = [m for m in raw if m["name"] == "quality"]
        assert len(quality_raw) == 5
        assert quality_raw[-1]["value"] == 90.0
        print("[PASS] Test 6: Get raw metrics")

        # ── Test 7: Promote v3, v1 becomes retired ──────────────────────────
        mv.promote("executor", "v3")
        active = mv.get_active("executor")
        assert active["version_tag"] == "v3"
        v1_after = mv.get_version("executor", "v1")
        assert v1_after["status"] == "retired"
        assert v1_after["retired_at"] is not None
        print("[PASS] Test 7: Promote v3, v1 auto-retired")

        # ── Test 8: Rollback v3 → v1 (parent) ──────────────────────────────
        frm, to = mv.rollback("executor")
        assert frm == "v3"
        assert to == "v1"
        active = mv.get_active("executor")
        assert active["version_tag"] == "v1"
        v3_after = mv.get_version("executor", "v3")
        assert v3_after["status"] == "rolled_back"
        print("[PASS] Test 8: Rollback to parent version")

        # ── Test 9: Explicit rollback target ─────────────────────────────────
        mv.promote("executor", "v2")
        active = mv.get_active("executor")
        assert active["version_tag"] == "v2"
        frm, to = mv.rollback("executor", target_version="v1")
        assert frm == "v2"
        assert to == "v1"
        print("[PASS] Test 9: Explicit rollback target")

        # ── Test 10: Compare versions ────────────────────────────────────────
        for val in [88.0, 91.0, 87.0, 92.0, 89.5]:
            mv.record_metric("executor", "v3", "quality", val)

        cmp = mv.compare_versions("executor", "v1", "v3", "quality")
        assert cmp["model"] == "executor"
        assert cmp["metric"] == "quality"
        assert cmp["v1"]["count"] == 5
        assert cmp["v3"]["count"] == 5
        assert cmp["improvement"] is not None
        v1_mean = statistics.mean([80, 82.5, 85, 78, 90])
        v3_mean = statistics.mean([88, 91, 87, 92, 89.5])
        assert cmp["improvement"] == round(v3_mean - v1_mean, 4)
        assert cmp["better"] == "v3"
        print("[PASS] Test 10: Compare versions")

        # ── Test 11: Auto-rollback on regression ─────────────────────────────
        mv.promote("executor", "v3")
        assert mv.get_active("executor")["version_tag"] == "v3"

        # Record bad metrics for v3 quality (all below threshold of 80)
        mv2 = ModelVersionManager(registry_dir=tmp)  # fresh load
        mv2.register("scorer", "v1", model_id="model-a")
        mv2.promote("scorer", "v1")
        mv2.register("scorer", "v2", model_id="model-b")
        mv2.promote("scorer", "v2")
        for val in [50.0, 55.0, 48.0, 52.0, 60.0]:
            mv2.record_metric("scorer", "v2", "accuracy", val)
        result = mv2.auto_rollback_on_regression("scorer", "v2", "accuracy", threshold=70.0)
        assert result is not None
        frm, to = result
        assert frm == "v2"
        assert to == "v1"
        assert mv2.get_active("scorer")["version_tag"] == "v1"
        print("[PASS] Test 11: Auto-rollback on regression")

        # ── Test 12: No rollback if above threshold ──────────────────────────
        mv2.register("scorer", "v3", model_id="model-c")
        mv2.promote("scorer", "v3")
        for val in [85.0, 88.0, 90.0, 87.0, 86.0]:
            mv2.record_metric("scorer", "v3", "accuracy", val)
        result = mv2.auto_rollback_on_regression("scorer", "v3", "accuracy", threshold=70.0)
        assert result is None
        assert mv2.get_active("scorer")["version_tag"] == "v3"
        print("[PASS] Test 12: No rollback when above threshold")

        # ── Test 13: History ─────────────────────────────────────────────────
        history = mv.get_history("executor")
        assert len(history) == 3
        tags = [v["version_tag"] for v in history]
        assert tags == ["v1", "v2", "v3"]  # sorted by created_at
        print("[PASS] Test 13: Get version history")

        # ── Test 14: List models ─────────────────────────────────────────────
        models = mv.list_models()
        assert "executor" in models
        print("[PASS] Test 14: List models")

        # ── Test 15: Summary ─────────────────────────────────────────────────
        summary = mv.summary()
        assert "executor" in summary
        assert summary["executor"]["total_versions"] == 3
        assert summary["executor"]["active"] is not None
        print("[PASS] Test 15: Summary")

        # ── Test 16: Duplicate registration raises ───────────────────────────
        try:
            mv.register("executor", "v1", model_id="anything")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "already registered" in str(e)
        print("[PASS] Test 16: Duplicate registration rejected")

        # ── Test 17: Rollback nonexistent model raises ───────────────────────
        try:
            mv.rollback("nonexistent")
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "not found" in str(e)
        print("[PASS] Test 17: Rollback nonexistent model raises")

        # ── Test 18: Rollback to same version raises ─────────────────────────
        active_tag = mv.get_active("executor")["version_tag"]
        try:
            mv.rollback("executor", target_version=active_tag)
            assert False, "Should have raised ValueError"
        except ValueError as e:
            assert "same version" in str(e)
        print("[PASS] Test 18: Rollback to same version raises")

        # ── Test 19: Retire manually ─────────────────────────────────────────
        mv.register("executor", "v4", model_id="test-model")
        status = mv.retire("executor", "v4")
        assert status == "retired"
        v4 = mv.get_version("executor", "v4")
        assert v4["status"] == "retired"
        assert v4["retired_at"] is not None
        print("[PASS] Test 19: Manual retire")

        # ── Test 20: Re-promote retired version ──────────────────────────────
        status = mv.promote("executor", "v4")
        assert status == "active"
        assert mv.get_active("executor")["version_tag"] == "v4"
        print("[PASS] Test 20: Re-promote retired version")

        # ── Test 21: Persistence (reload from disk) ──────────────────────────
        mv_reload = ModelVersionManager(registry_dir=tmp)
        assert mv_reload.list_models() == mv.list_models()
        assert mv_reload.get_active("executor")["version_tag"] == "v4"
        history_reloaded = mv_reload.get_history("executor")
        assert len(history_reloaded) == 4
        print("[PASS] Test 21: Persistence across reload")

        # ── Test 22: Audit log written ───────────────────────────────────────
        audit_file = tmp / "audit.jsonl"
        assert audit_file.exists()
        lines = [l for l in audit_file.read_text().splitlines() if l.strip()]
        assert len(lines) > 10  # many operations logged
        first = json.loads(lines[0])
        assert "ts" in first
        assert "action" in first
        assert "model" in first
        print("[PASS] Test 22: Audit log written")

        # ── Test 23: Multi-model isolation ───────────────────────────────────
        mv.register("planner", "v1", model_id="planner-model")
        mv.promote("planner", "v1")
        mv.register("planner", "v2", model_id="planner-model-v2")
        # Rollback executor should not affect planner
        executor_active = mv.get_active("executor")["version_tag"]
        planner_active = mv.get_active("planner")["version_tag"]
        assert planner_active == "v1"
        mv.rollback("executor", target_version="v3")
        assert mv.get_active("planner")["version_tag"] == "v1"  # unchanged
        print("[PASS] Test 23: Multi-model isolation")

        # ── Test 24: Checksum uniqueness ─────────────────────────────────────
        v1_cksum = mv.get_version("executor", "v1")["checksum"]
        v2_cksum = mv.get_version("executor", "v2")["checksum"]
        v3_cksum = mv.get_version("executor", "v3")["checksum"]
        assert v1_cksum != v2_cksum
        assert v2_cksum != v3_cksum
        print("[PASS] Test 24: Checksum uniqueness")

        # ── Test 25: Auto-rollback with insufficient samples ─────────────────
        mv2.register("scorer", "v4", model_id="model-d")
        mv2.promote("scorer", "v4")
        mv2.record_metric("scorer", "v4", "accuracy", 10.0)  # only 1 sample
        result = mv2.auto_rollback_on_regression("scorer", "v4", "accuracy", threshold=70.0, min_samples=5)
        assert result is None  # not enough samples
        print("[PASS] Test 25: Auto-rollback skipped with insufficient samples")

        print("\n" + "=" * 60)
        print("ALL 25 TESTS PASSED")
        print("=" * 60)

    finally:
        shutil.rmtree(tmp, ignore_errors=True)
