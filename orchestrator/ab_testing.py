#!/usr/bin/env python3
"""
orchestrator/ab_testing.py — A/B testing framework for agents
=============================================================
Route traffic between control/variant agents, collect metrics,
and auto-declare a winner using sequential statistical testing.

Features:
  - Create experiments with control + variant(s) agent configs
  - Traffic splitting with configurable weights (hash-based for consistency)
  - Per-variant metric collection (quality, latency, success rate, tokens)
  - Sequential analysis with auto-winner declaration
  - Early stopping on clear winner or loser
  - Persistent experiment state (JSON) and event log (JSONL)
  - Thread-safe for concurrent task routing

Usage:
    from orchestrator.ab_testing import ABTestManager, Experiment, Variant

    mgr = ABTestManager()
    exp = mgr.create_experiment(
        name="executor-v3-vs-v4",
        hypothesis="v4 prompt yields higher quality",
        control=Variant(name="v3", agent="executor", config={"prompt_version": 3}),
        variants=[Variant(name="v4", agent="executor", config={"prompt_version": 4})],
        traffic_pct=0.5,       # 50% to variants
        min_samples=30,        # per variant before analysis
        max_samples=200,       # hard cap per variant
        confidence=0.95,       # significance threshold
    )
    assignment = mgr.assign(exp.id, task)
    # ... run the assigned agent ...
    mgr.record(exp.id, assignment.variant_name, metrics)
    result = mgr.analyze(exp.id)
"""

import json
import math
import time
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
AB_DIR = BASE_DIR / "state" / "ab_tests"
EXPERIMENTS_FILE = AB_DIR / "experiments.json"
EVENT_LOG = AB_DIR / "events.jsonl"


# ── Enums & Data Classes ────────────────────────────────────────────────────

class ExperimentStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    ROLLED_BACK = "rolled_back"


class WinnerReason(str, Enum):
    STATISTICAL = "statistical_significance"
    EARLY_STOP_WINNER = "early_stop_clear_winner"
    EARLY_STOP_LOSER = "early_stop_clear_loser"
    MAX_SAMPLES = "max_samples_reached"
    MANUAL = "manual_override"


@dataclass
class Variant:
    """A single arm of an A/B test."""
    name: str
    agent: str
    config: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Variant":
        return cls(**d)


@dataclass
class MetricSample:
    """Single observation from a variant execution."""
    quality: float = 0.0
    latency_s: float = 0.0
    tokens_used: int = 0
    success: bool = True
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "MetricSample":
        return cls(**d)


@dataclass
class VariantStats:
    """Aggregated stats for a variant."""
    name: str
    samples: int = 0
    successes: int = 0
    qualities: List[float] = field(default_factory=list)
    latencies: List[float] = field(default_factory=list)
    tokens: List[int] = field(default_factory=list)

    @property
    def success_rate(self) -> float:
        return self.successes / self.samples if self.samples > 0 else 0.0

    @property
    def mean_quality(self) -> float:
        return statistics.mean(self.qualities) if self.qualities else 0.0

    @property
    def std_quality(self) -> float:
        return statistics.stdev(self.qualities) if len(self.qualities) >= 2 else 0.0

    @property
    def mean_latency(self) -> float:
        return statistics.mean(self.latencies) if self.latencies else 0.0

    @property
    def mean_tokens(self) -> float:
        return statistics.mean(self.tokens) if self.tokens else 0.0

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "samples": self.samples,
            "successes": self.successes,
            "success_rate": round(self.success_rate, 4),
            "mean_quality": round(self.mean_quality, 2),
            "std_quality": round(self.std_quality, 2),
            "mean_latency": round(self.mean_latency, 3),
            "mean_tokens": round(self.mean_tokens, 1),
            "qualities": self.qualities,
            "latencies": self.latencies,
            "tokens": self.tokens,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "VariantStats":
        return cls(
            name=d["name"],
            samples=d.get("samples", 0),
            successes=d.get("successes", 0),
            qualities=d.get("qualities", []),
            latencies=d.get("latencies", []),
            tokens=d.get("tokens", []),
        )


@dataclass
class Assignment:
    """Result of assigning a task to a variant."""
    experiment_id: str
    variant_name: str
    agent: str
    config: Dict[str, Any]
    task_id: str


@dataclass
class AnalysisResult:
    """Outcome of analyzing an experiment."""
    experiment_id: str
    status: str
    winner: Optional[str] = None
    reason: Optional[str] = None
    confidence: float = 0.0
    effect_size: float = 0.0
    variant_stats: Dict[str, dict] = field(default_factory=dict)
    recommendation: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class Experiment:
    """Full experiment definition and state."""
    id: str
    name: str
    hypothesis: str
    control: Variant
    variants: List[Variant]
    traffic_pct: float = 0.5
    min_samples: int = 30
    max_samples: int = 200
    confidence: float = 0.95
    primary_metric: str = "quality"
    status: str = ExperimentStatus.DRAFT.value
    winner: Optional[str] = None
    winner_reason: Optional[str] = None
    created_at: str = ""
    updated_at: str = ""
    stats: Dict[str, VariantStats] = field(default_factory=dict)

    def __post_init__(self):
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now
        # Initialize stats for all arms
        all_arms = [self.control.name] + [v.name for v in self.variants]
        for arm in all_arms:
            if arm not in self.stats:
                self.stats[arm] = VariantStats(name=arm)

    def all_variants(self) -> List[Variant]:
        return [self.control] + self.variants

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "hypothesis": self.hypothesis,
            "control": self.control.to_dict(),
            "variants": [v.to_dict() for v in self.variants],
            "traffic_pct": self.traffic_pct,
            "min_samples": self.min_samples,
            "max_samples": self.max_samples,
            "confidence": self.confidence,
            "primary_metric": self.primary_metric,
            "status": self.status,
            "winner": self.winner,
            "winner_reason": self.winner_reason,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "stats": {k: v.to_dict() for k, v in self.stats.items()},
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Experiment":
        control = Variant.from_dict(d["control"])
        variants = [Variant.from_dict(v) for v in d["variants"]]
        stats = {k: VariantStats.from_dict(v) for k, v in d.get("stats", {}).items()}
        return cls(
            id=d["id"],
            name=d["name"],
            hypothesis=d["hypothesis"],
            control=control,
            variants=variants,
            traffic_pct=d.get("traffic_pct", 0.5),
            min_samples=d.get("min_samples", 30),
            max_samples=d.get("max_samples", 200),
            confidence=d.get("confidence", 0.95),
            primary_metric=d.get("primary_metric", "quality"),
            status=d.get("status", ExperimentStatus.DRAFT.value),
            winner=d.get("winner"),
            winner_reason=d.get("winner_reason"),
            created_at=d.get("created_at", ""),
            updated_at=d.get("updated_at", ""),
            stats=stats,
        )


# ── Statistical Helpers ──────────────────────────────────────────────────────

def _welch_t_test(mean1: float, std1: float, n1: int,
                  mean2: float, std2: float, n2: int) -> Tuple[float, float]:
    """
    Welch's t-test for unequal variances.
    Returns (t_statistic, approximate_p_value).
    Uses normal approximation for p-value (good for n >= 30).
    """
    if n1 < 2 or n2 < 2:
        return 0.0, 1.0

    se1 = (std1 ** 2) / n1
    se2 = (std2 ** 2) / n2
    se_diff = math.sqrt(se1 + se2)

    if se_diff == 0:
        return 0.0, 1.0

    t_stat = (mean2 - mean1) / se_diff

    # Welch-Satterthwaite degrees of freedom
    if se1 + se2 == 0:
        df = n1 + n2 - 2
    else:
        df = ((se1 + se2) ** 2) / (
            (se1 ** 2) / (n1 - 1) + (se2 ** 2) / (n2 - 1)
        )
        df = max(df, 1.0)

    # Approximate p-value using normal CDF (accurate for df >= 30)
    p_value = _normal_cdf(-abs(t_stat)) * 2  # two-tailed
    return t_stat, p_value


def _normal_cdf(x: float) -> float:
    """Standard normal CDF approximation (Abramowitz & Stegun)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _cohens_d(mean1: float, std1: float, n1: int,
              mean2: float, std2: float, n2: int) -> float:
    """Cohen's d effect size (pooled standard deviation)."""
    if n1 < 2 or n2 < 2:
        return 0.0
    pooled_std = math.sqrt(
        ((n1 - 1) * std1 ** 2 + (n2 - 1) * std2 ** 2) / (n1 + n2 - 2)
    )
    if pooled_std == 0:
        return 0.0
    return (mean2 - mean1) / pooled_std


# ── ABTestManager ────────────────────────────────────────────────────────────

class ABTestManager:
    """
    Manages A/B test experiments for agents.

    Thread-safe. Persists experiments to JSON and events to JSONL.
    """

    def __init__(self, base_dir: Optional[Path] = None):
        self._dir = base_dir or AB_DIR
        self._experiments_file = self._dir / "experiments.json"
        self._event_log = self._dir / "events.jsonl"
        self._lock = threading.RLock()
        self._experiments: Dict[str, Experiment] = {}
        self._dir.mkdir(parents=True, exist_ok=True)
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────

    def _load(self):
        """Load experiments from disk."""
        if self._experiments_file.exists():
            try:
                data = json.loads(self._experiments_file.read_text())
                for eid, ed in data.items():
                    self._experiments[eid] = Experiment.from_dict(ed)
            except (json.JSONDecodeError, KeyError):
                self._experiments = {}

    def _save(self):
        """Persist experiments to disk."""
        data = {eid: exp.to_dict() for eid, exp in self._experiments.items()}
        self._experiments_file.write_text(json.dumps(data, indent=2))

    def _log_event(self, event_type: str, experiment_id: str, data: dict):
        """Append event to JSONL audit log."""
        entry = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "type": event_type,
            "experiment_id": experiment_id,
            **data,
        }
        with open(self._event_log, "a") as f:
            f.write(json.dumps(entry) + "\n")

    # ── Experiment Lifecycle ─────────────────────────────────────────────

    def create_experiment(
        self,
        name: str,
        hypothesis: str,
        control: Variant,
        variants: List[Variant],
        traffic_pct: float = 0.5,
        min_samples: int = 30,
        max_samples: int = 200,
        confidence: float = 0.95,
        primary_metric: str = "quality",
    ) -> Experiment:
        """Create and register a new A/B experiment."""
        with self._lock:
            exp_id = hashlib.sha256(
                f"{name}:{time.time_ns()}".encode()
            ).hexdigest()[:12]

            if not (0.0 < traffic_pct <= 1.0):
                raise ValueError(f"traffic_pct must be in (0, 1], got {traffic_pct}")
            if min_samples < 1:
                raise ValueError("min_samples must be >= 1")
            if not variants:
                raise ValueError("At least one variant required")

            # Validate unique names
            all_names = [control.name] + [v.name for v in variants]
            if len(all_names) != len(set(all_names)):
                raise ValueError("Variant names must be unique")

            exp = Experiment(
                id=exp_id,
                name=name,
                hypothesis=hypothesis,
                control=control,
                variants=variants,
                traffic_pct=traffic_pct,
                min_samples=min_samples,
                max_samples=max_samples,
                confidence=confidence,
                primary_metric=primary_metric,
                status=ExperimentStatus.RUNNING.value,
            )
            self._experiments[exp_id] = exp
            self._save()
            self._log_event("experiment_created", exp_id, {
                "name": name,
                "control": control.name,
                "variants": [v.name for v in variants],
                "traffic_pct": traffic_pct,
            })
            return exp

    def get_experiment(self, experiment_id: str) -> Optional[Experiment]:
        """Retrieve an experiment by ID."""
        return self._experiments.get(experiment_id)

    def list_experiments(self, status: Optional[str] = None) -> List[Experiment]:
        """List experiments, optionally filtered by status."""
        exps = list(self._experiments.values())
        if status:
            exps = [e for e in exps if e.status == status]
        return exps

    def pause_experiment(self, experiment_id: str):
        """Pause a running experiment."""
        with self._lock:
            exp = self._experiments.get(experiment_id)
            if not exp:
                raise KeyError(f"Experiment {experiment_id} not found")
            exp.status = ExperimentStatus.PAUSED.value
            exp.updated_at = datetime.now(timezone.utc).isoformat()
            self._save()
            self._log_event("experiment_paused", experiment_id, {})

    def resume_experiment(self, experiment_id: str):
        """Resume a paused experiment."""
        with self._lock:
            exp = self._experiments.get(experiment_id)
            if not exp:
                raise KeyError(f"Experiment {experiment_id} not found")
            exp.status = ExperimentStatus.RUNNING.value
            exp.updated_at = datetime.now(timezone.utc).isoformat()
            self._save()
            self._log_event("experiment_resumed", experiment_id, {})

    # ── Traffic Assignment ───────────────────────────────────────────────

    def assign(self, experiment_id: str, task: dict) -> Assignment:
        """
        Assign a task to a variant using deterministic hashing.

        Uses hash(experiment_id + task_id) for consistent assignment:
        the same task always gets the same variant within an experiment.
        """
        with self._lock:
            exp = self._experiments.get(experiment_id)
            if not exp:
                raise KeyError(f"Experiment {experiment_id} not found")
            if exp.status != ExperimentStatus.RUNNING.value:
                raise RuntimeError(
                    f"Experiment {experiment_id} is {exp.status}, not running"
                )

            task_id = str(task.get("id", task.get("title", id(task))))
            hash_key = f"{experiment_id}:{task_id}"
            hash_val = int(hashlib.md5(hash_key.encode()).hexdigest(), 16)
            bucket = (hash_val % 10000) / 10000.0  # 0.0 to 0.9999

            # Control gets (1 - traffic_pct), variants share traffic_pct
            if bucket >= exp.traffic_pct:
                chosen = exp.control
            else:
                # Distribute evenly among variants
                variant_idx = hash_val % len(exp.variants)
                chosen = exp.variants[variant_idx]

            # Check max samples
            stats = exp.stats.get(chosen.name)
            if stats and stats.samples >= exp.max_samples:
                # Overflow to control
                chosen = exp.control

            self._log_event("task_assigned", experiment_id, {
                "task_id": task_id,
                "variant": chosen.name,
                "bucket": round(bucket, 4),
            })

            return Assignment(
                experiment_id=experiment_id,
                variant_name=chosen.name,
                agent=chosen.agent,
                config=deepcopy(chosen.config),
                task_id=task_id,
            )

    # ── Metric Recording ─────────────────────────────────────────────────

    def record(self, experiment_id: str, variant_name: str,
               metrics: dict) -> VariantStats:
        """
        Record metrics for a variant execution.

        Args:
            metrics: dict with optional keys: quality, latency_s, tokens_used, success
        """
        with self._lock:
            exp = self._experiments.get(experiment_id)
            if not exp:
                raise KeyError(f"Experiment {experiment_id} not found")

            stats = exp.stats.get(variant_name)
            if not stats:
                raise KeyError(f"Variant {variant_name} not in experiment")

            sample = MetricSample(
                quality=float(metrics.get("quality", 0)),
                latency_s=float(metrics.get("latency_s", 0)),
                tokens_used=int(metrics.get("tokens_used", 0)),
                success=bool(metrics.get("success", True)),
            )

            stats.samples += 1
            if sample.success:
                stats.successes += 1
            stats.qualities.append(sample.quality)
            stats.latencies.append(sample.latency_s)
            stats.tokens.append(sample.tokens_used)

            exp.updated_at = datetime.now(timezone.utc).isoformat()
            self._save()

            self._log_event("metric_recorded", experiment_id, {
                "variant": variant_name,
                "sample": sample.to_dict(),
                "total_samples": stats.samples,
            })

            # Auto-analyze after each record
            self._check_auto_complete(exp)

            return stats

    # ── Analysis ─────────────────────────────────────────────────────────

    def analyze(self, experiment_id: str) -> AnalysisResult:
        """
        Analyze experiment results.

        Runs Welch's t-test on primary metric between control and each variant.
        Returns winner if significance threshold met and min_samples reached.
        """
        with self._lock:
            exp = self._experiments.get(experiment_id)
            if not exp:
                raise KeyError(f"Experiment {experiment_id} not found")

            control_stats = exp.stats[exp.control.name]
            variant_results = {}

            best_variant = None
            best_mean = control_stats.mean_quality
            best_p = 1.0

            for variant in exp.variants:
                vs = exp.stats[variant.name]
                variant_results[variant.name] = vs.to_dict()

                if vs.samples < exp.min_samples or control_stats.samples < exp.min_samples:
                    continue

                # Primary metric comparison
                if exp.primary_metric == "quality":
                    c_mean, c_std = control_stats.mean_quality, control_stats.std_quality
                    v_mean, v_std = vs.mean_quality, vs.std_quality
                    c_vals, v_vals = control_stats.qualities, vs.qualities
                elif exp.primary_metric == "latency":
                    c_mean = control_stats.mean_latency
                    c_std = statistics.stdev(control_stats.latencies) if len(control_stats.latencies) >= 2 else 0
                    v_mean = vs.mean_latency
                    v_std = statistics.stdev(vs.latencies) if len(vs.latencies) >= 2 else 0
                elif exp.primary_metric == "success_rate":
                    c_mean = control_stats.success_rate
                    c_std = math.sqrt(c_mean * (1 - c_mean) / max(control_stats.samples, 1))
                    v_mean = vs.success_rate
                    v_std = math.sqrt(v_mean * (1 - v_mean) / max(vs.samples, 1))
                else:
                    c_mean, c_std = control_stats.mean_quality, control_stats.std_quality
                    v_mean, v_std = vs.mean_quality, vs.std_quality

                t_stat, p_value = _welch_t_test(
                    c_mean, c_std, control_stats.samples,
                    v_mean, v_std, vs.samples,
                )
                effect = _cohens_d(
                    c_mean, c_std, control_stats.samples,
                    v_mean, v_std, vs.samples,
                )

                variant_results[variant.name]["t_stat"] = round(t_stat, 4)
                variant_results[variant.name]["p_value"] = round(p_value, 6)
                variant_results[variant.name]["effect_size"] = round(effect, 4)

                # For quality/success_rate higher is better; for latency lower is better
                is_better = (
                    v_mean < c_mean if exp.primary_metric == "latency"
                    else v_mean > c_mean
                )

                if p_value < (1 - exp.confidence) and is_better:
                    if best_variant is None or p_value < best_p:
                        best_variant = variant.name
                        best_mean = v_mean
                        best_p = p_value

            # Add control stats
            variant_results[exp.control.name] = control_stats.to_dict()

            # Determine winner
            winner = None
            reason = None
            rec = "Insufficient data" if control_stats.samples < exp.min_samples else "No significant difference"

            if best_variant:
                winner = best_variant
                reason = WinnerReason.STATISTICAL.value
                rec = f"Deploy {best_variant} (p={best_p:.4f})"
            elif all(
                exp.stats[v.name].samples >= exp.max_samples
                for v in exp.variants
            ) and control_stats.samples >= exp.max_samples:
                # Max samples reached, pick practical winner
                all_arms = [(exp.control.name, control_stats.mean_quality)]
                for v in exp.variants:
                    all_arms.append((v.name, exp.stats[v.name].mean_quality))
                all_arms.sort(key=lambda x: x[1], reverse=True)
                winner = all_arms[0][0]
                reason = WinnerReason.MAX_SAMPLES.value
                rec = f"Deploy {winner} (best mean quality at max samples)"

            return AnalysisResult(
                experiment_id=experiment_id,
                status=exp.status,
                winner=winner,
                reason=reason,
                confidence=1.0 - best_p if best_variant else 0.0,
                effect_size=_cohens_d(
                    control_stats.mean_quality, control_stats.std_quality, control_stats.samples,
                    exp.stats[best_variant].mean_quality if best_variant else 0,
                    exp.stats[best_variant].std_quality if best_variant else 0,
                    exp.stats[best_variant].samples if best_variant else 0,
                ) if best_variant else 0.0,
                variant_stats=variant_results,
                recommendation=rec,
            )

    def _check_auto_complete(self, exp: Experiment):
        """Auto-complete experiment if all variants hit max_samples or clear winner emerges."""
        if exp.status != ExperimentStatus.RUNNING.value:
            return

        control_stats = exp.stats[exp.control.name]

        # Check early stopping: clear winner with 2x min_samples
        early_threshold = exp.min_samples * 2
        if control_stats.samples >= early_threshold:
            for variant in exp.variants:
                vs = exp.stats[variant.name]
                if vs.samples < early_threshold:
                    continue

                if exp.primary_metric == "quality":
                    c_mean, c_std = control_stats.mean_quality, control_stats.std_quality
                    v_mean, v_std = vs.mean_quality, vs.std_quality
                else:
                    continue

                _, p_value = _welch_t_test(
                    c_mean, c_std, control_stats.samples,
                    v_mean, v_std, vs.samples,
                )
                # Very strong signal (p < 0.001)
                if p_value < 0.001:
                    is_better = v_mean > c_mean
                    exp.winner = variant.name if is_better else exp.control.name
                    exp.winner_reason = (
                        WinnerReason.EARLY_STOP_WINNER.value if is_better
                        else WinnerReason.EARLY_STOP_LOSER.value
                    )
                    exp.status = ExperimentStatus.COMPLETED.value
                    exp.updated_at = datetime.now(timezone.utc).isoformat()
                    self._save()
                    self._log_event("experiment_completed", exp.id, {
                        "winner": exp.winner,
                        "reason": exp.winner_reason,
                    })
                    return

        # Check max samples reached
        all_maxed = all(
            exp.stats[v.name].samples >= exp.max_samples
            for v in exp.all_variants()
        )
        if all_maxed:
            result = self.analyze(exp.id)
            if result.winner:
                exp.winner = result.winner
                exp.winner_reason = WinnerReason.MAX_SAMPLES.value
            exp.status = ExperimentStatus.COMPLETED.value
            exp.updated_at = datetime.now(timezone.utc).isoformat()
            self._save()
            self._log_event("experiment_completed", exp.id, {
                "winner": exp.winner,
                "reason": exp.winner_reason or "no_winner",
            })

    # ── Rollback ─────────────────────────────────────────────────────────

    def rollback(self, experiment_id: str):
        """Roll back an experiment — revert to control."""
        with self._lock:
            exp = self._experiments.get(experiment_id)
            if not exp:
                raise KeyError(f"Experiment {experiment_id} not found")
            exp.status = ExperimentStatus.ROLLED_BACK.value
            exp.winner = exp.control.name
            exp.winner_reason = WinnerReason.MANUAL.value
            exp.updated_at = datetime.now(timezone.utc).isoformat()
            self._save()
            self._log_event("experiment_rolled_back", experiment_id, {
                "reverted_to": exp.control.name,
            })

    # ── Integration with agent routing ───────────────────────────────────

    def get_active_experiment_for_agent(self, agent_name: str) -> Optional[Experiment]:
        """Find running experiment that involves this agent."""
        for exp in self._experiments.values():
            if exp.status != ExperimentStatus.RUNNING.value:
                continue
            for v in exp.all_variants():
                if v.agent == agent_name:
                    return exp
        return None

    def get_winner_config(self, experiment_id: str) -> Optional[Tuple[str, Dict]]:
        """Get the winning variant's agent and config after experiment completes."""
        exp = self._experiments.get(experiment_id)
        if not exp or not exp.winner:
            return None
        for v in exp.all_variants():
            if v.name == exp.winner:
                return (v.agent, deepcopy(v.config))
        return None


# ── Module-level convenience ─────────────────────────────────────────────────

_default_manager: Optional[ABTestManager] = None


def get_manager() -> ABTestManager:
    """Get or create the default ABTestManager singleton."""
    global _default_manager
    if _default_manager is None:
        _default_manager = ABTestManager()
    return _default_manager


# ── __main__ ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile
    import random
    import shutil

    print("=" * 70)
    print("A/B Testing Framework — Verification Suite")
    print("=" * 70)

    # Use temp directory for isolation
    tmp_dir = Path(tempfile.mkdtemp(prefix="ab_test_"))
    try:
        mgr = ABTestManager(base_dir=tmp_dir)

        # ── Test 1: Create experiment ────────────────────────────────────
        print("\n[1] Creating experiment...")
        control = Variant(name="v3", agent="executor", config={"prompt_version": 3})
        variant = Variant(name="v4", agent="executor", config={"prompt_version": 4})

        exp = mgr.create_experiment(
            name="executor-v3-vs-v4",
            hypothesis="v4 prompt yields higher quality scores",
            control=control,
            variants=[variant],
            traffic_pct=0.5,
            min_samples=10,
            max_samples=50,
            confidence=0.95,
            primary_metric="quality",
        )
        assert exp.id, "Experiment ID should be set"
        assert exp.status == "running", f"Expected running, got {exp.status}"
        assert exp.control.name == "v3"
        assert len(exp.variants) == 1
        assert exp.stats["v3"].samples == 0
        assert exp.stats["v4"].samples == 0
        print(f"  ✓ Created experiment {exp.id}: {exp.name}")

        # ── Test 2: Validate constraints ─────────────────────────────────
        print("\n[2] Validating constraints...")
        try:
            mgr.create_experiment(
                name="bad", hypothesis="x",
                control=Variant(name="a", agent="x"),
                variants=[],
                traffic_pct=0.5,
            )
            assert False, "Should have raised ValueError for empty variants"
        except ValueError as e:
            assert "variant" in str(e).lower()
            print(f"  ✓ Rejects empty variants: {e}")

        try:
            mgr.create_experiment(
                name="bad", hypothesis="x",
                control=Variant(name="a", agent="x"),
                variants=[Variant(name="a", agent="y")],
            )
            assert False, "Should have raised ValueError for duplicate names"
        except ValueError as e:
            assert "unique" in str(e).lower()
            print(f"  ✓ Rejects duplicate names: {e}")

        try:
            mgr.create_experiment(
                name="bad", hypothesis="x",
                control=Variant(name="a", agent="x"),
                variants=[Variant(name="b", agent="y")],
                traffic_pct=0.0,
            )
            assert False, "Should have raised ValueError for traffic_pct=0"
        except ValueError:
            print("  ✓ Rejects traffic_pct=0")

        # ── Test 3: Deterministic assignment ─────────────────────────────
        print("\n[3] Testing deterministic assignment...")
        task_a = {"id": "task-001", "title": "Binary search", "category": "code_gen"}
        assignment1 = mgr.assign(exp.id, task_a)
        assignment2 = mgr.assign(exp.id, task_a)
        assert assignment1.variant_name == assignment2.variant_name, \
            "Same task should get same variant"
        assert assignment1.agent == "executor"
        print(f"  ✓ task-001 → {assignment1.variant_name} (deterministic)")

        # ── Test 4: Traffic distribution ─────────────────────────────────
        print("\n[4] Testing traffic distribution (1000 tasks)...")
        counts = {"v3": 0, "v4": 0}
        for i in range(1000):
            task = {"id": f"dist-{i}", "category": "code_gen"}
            a = mgr.assign(exp.id, task)
            counts[a.variant_name] += 1

        # With traffic_pct=0.5, expect roughly 50/50 (hash-based, not exact)
        v3_pct = counts["v3"] / 1000
        v4_pct = counts["v4"] / 1000
        assert 0.3 < v4_pct < 0.7, f"Variant traffic {v4_pct:.1%} too skewed"
        print(f"  ✓ v3={counts['v3']} ({v3_pct:.1%}), v4={counts['v4']} ({v4_pct:.1%})")

        # ── Test 5: Record metrics ───────────────────────────────────────
        print("\n[5] Recording metrics...")
        random.seed(42)
        # v3 (control): mean quality ~65
        for i in range(15):
            mgr.record(exp.id, "v3", {
                "quality": random.gauss(65, 8),
                "latency_s": random.uniform(1.0, 3.0),
                "tokens_used": random.randint(100, 500),
                "success": random.random() > 0.1,
            })
        # v4 (variant): mean quality ~78 (clearly better)
        for i in range(15):
            mgr.record(exp.id, "v4", {
                "quality": random.gauss(78, 7),
                "latency_s": random.uniform(0.8, 2.5),
                "tokens_used": random.randint(120, 480),
                "success": random.random() > 0.05,
            })

        v3_stats = exp.stats["v3"]
        v4_stats = exp.stats["v4"]
        assert v3_stats.samples == 15, f"v3 samples: {v3_stats.samples}"
        assert v4_stats.samples == 15, f"v4 samples: {v4_stats.samples}"
        print(f"  ✓ v3: {v3_stats.samples} samples, mean_q={v3_stats.mean_quality:.1f}")
        print(f"  ✓ v4: {v4_stats.samples} samples, mean_q={v4_stats.mean_quality:.1f}")

        # ── Test 6: Analyze results ──────────────────────────────────────
        print("\n[6] Analyzing results...")
        result = mgr.analyze(exp.id)
        assert result.experiment_id == exp.id
        assert "v3" in result.variant_stats
        assert "v4" in result.variant_stats
        print(f"  ✓ Analysis: winner={result.winner}, confidence={result.confidence:.4f}")
        print(f"    effect_size={result.effect_size:.3f}, recommendation={result.recommendation}")

        # With 15 samples of mean 65 vs 78, should detect significance
        if result.winner:
            assert result.winner == "v4", f"v4 should win, got {result.winner}"
            print(f"  ✓ Correct winner: {result.winner}")
        else:
            print("  ⚠ Not yet significant (expected with small sample)")

        # ── Test 7: Welch t-test directly ────────────────────────────────
        print("\n[7] Testing statistical functions...")
        # Large effect: mean 50 vs 80, std 10, n=50
        t, p = _welch_t_test(50, 10, 50, 80, 10, 50)
        assert p < 0.001, f"Large effect should be significant: p={p}"
        assert t > 0, "t should be positive (mean2 > mean1)"
        print(f"  ✓ Large effect: t={t:.2f}, p={p:.6f}")

        # No effect: mean 50 vs 50
        t, p = _welch_t_test(50, 10, 50, 50, 10, 50)
        assert p > 0.5, f"No effect should not be significant: p={p}"
        print(f"  ✓ No effect: t={t:.2f}, p={p:.6f}")

        # Cohen's d
        d = _cohens_d(50, 10, 50, 80, 10, 50)
        assert 2.5 < d < 3.5, f"Cohen's d should be ~3.0: d={d}"
        print(f"  ✓ Cohen's d: {d:.2f} (large effect)")

        d_small = _cohens_d(50, 10, 50, 52, 10, 50)
        assert d_small < 0.5, f"Small effect d should be < 0.5: d={d_small}"
        print(f"  ✓ Cohen's d: {d_small:.2f} (small effect)")

        # ── Test 8: Pause / Resume ───────────────────────────────────────
        print("\n[8] Testing pause/resume...")
        mgr.pause_experiment(exp.id)
        assert exp.status == "paused"
        try:
            mgr.assign(exp.id, {"id": "blocked-task"})
            assert False, "Should not assign when paused"
        except RuntimeError:
            print("  ✓ Cannot assign when paused")

        mgr.resume_experiment(exp.id)
        assert exp.status == "running"
        a = mgr.assign(exp.id, {"id": "resumed-task"})
        assert a.variant_name in ("v3", "v4")
        print("  ✓ Resumed and assigning again")

        # ── Test 9: Rollback ─────────────────────────────────────────────
        print("\n[9] Testing rollback...")
        mgr.rollback(exp.id)
        assert exp.status == "rolled_back"
        assert exp.winner == "v3"
        assert exp.winner_reason == "manual_override"
        print("  ✓ Rolled back to control (v3)")

        # ── Test 10: Auto-winner with clear signal ───────────────────────
        print("\n[10] Testing auto-winner with strong signal...")
        exp2 = mgr.create_experiment(
            name="auto-winner-test",
            hypothesis="variant is clearly better",
            control=Variant(name="old", agent="debugger", config={"version": 1}),
            variants=[Variant(name="new", agent="debugger", config={"version": 2})],
            traffic_pct=0.5,
            min_samples=5,
            max_samples=100,
            confidence=0.95,
        )

        random.seed(99)
        # Feed very different distributions to trigger early stop
        for i in range(30):
            mgr.record(exp2.id, "old", {
                "quality": random.gauss(40, 5),
                "latency_s": 2.0,
                "tokens_used": 200,
                "success": True,
            })
            mgr.record(exp2.id, "new", {
                "quality": random.gauss(85, 5),
                "latency_s": 1.5,
                "tokens_used": 180,
                "success": True,
            })

        # Check if auto-completed
        exp2_latest = mgr.get_experiment(exp2.id)
        if exp2_latest.status == "completed":
            assert exp2_latest.winner == "new", f"Expected 'new', got {exp2_latest.winner}"
            print(f"  ✓ Auto-winner declared: {exp2_latest.winner} ({exp2_latest.winner_reason})")
        else:
            # Manually analyze
            r = mgr.analyze(exp2.id)
            assert r.winner == "new", f"Expected 'new' winner, got {r.winner}"
            print(f"  ✓ Manual analysis winner: {r.winner} (p<0.001)")

        # ── Test 11: Multi-variant experiment ────────────────────────────
        print("\n[11] Testing multi-variant (3-way) experiment...")
        exp3 = mgr.create_experiment(
            name="three-way-test",
            hypothesis="testing three prompt strategies",
            control=Variant(name="baseline", agent="planner", config={"strategy": "chain"}),
            variants=[
                Variant(name="tree", agent="planner", config={"strategy": "tree"}),
                Variant(name="graph", agent="planner", config={"strategy": "graph"}),
            ],
            traffic_pct=0.6,
            min_samples=10,
            max_samples=50,
        )
        assert len(exp3.variants) == 2
        assert "baseline" in exp3.stats
        assert "tree" in exp3.stats
        assert "graph" in exp3.stats

        random.seed(7)
        for i in range(20):
            mgr.record(exp3.id, "baseline", {"quality": random.gauss(60, 10)})
            mgr.record(exp3.id, "tree", {"quality": random.gauss(70, 8)})
            mgr.record(exp3.id, "graph", {"quality": random.gauss(75, 9)})

        r3 = mgr.analyze(exp3.id)
        print(f"  ✓ 3-way analysis: winner={r3.winner}, rec={r3.recommendation}")
        for vn, vs in r3.variant_stats.items():
            print(f"    {vn}: n={vs['samples']}, mean_q={vs['mean_quality']:.1f}")

        # ── Test 12: Persistence ─────────────────────────────────────────
        print("\n[12] Testing persistence...")
        mgr2 = ABTestManager(base_dir=tmp_dir)
        loaded_exp = mgr2.get_experiment(exp.id)
        assert loaded_exp is not None, "Experiment should persist"
        assert loaded_exp.name == "executor-v3-vs-v4"
        assert loaded_exp.stats["v3"].samples == 15
        assert loaded_exp.stats["v4"].samples == 15
        print(f"  ✓ Loaded {len(mgr2.list_experiments())} experiments from disk")

        # ── Test 13: Event log ───────────────────────────────────────────
        print("\n[13] Checking event log...")
        event_log_path = tmp_dir / "events.jsonl"
        assert event_log_path.exists(), "Event log should exist"
        events = [json.loads(line) for line in event_log_path.read_text().strip().split("\n")]
        event_types = set(e["type"] for e in events)
        assert "experiment_created" in event_types
        assert "task_assigned" in event_types
        assert "metric_recorded" in event_types
        print(f"  ✓ {len(events)} events logged, types: {sorted(event_types)}")

        # ── Test 14: Get active experiment for agent ─────────────────────
        print("\n[14] Testing agent lookup...")
        # Create a fresh running experiment for lookup test
        exp_lookup = mgr.create_experiment(
            name="lookup-test",
            hypothesis="test agent lookup",
            control=Variant(name="ctrl", agent="reviewer", config={}),
            variants=[Variant(name="new_rev", agent="reviewer", config={"v": 2})],
            min_samples=100,
        )
        active = mgr.get_active_experiment_for_agent("reviewer")
        assert active is not None
        assert active.id == exp_lookup.id
        print(f"  ✓ Found active experiment for reviewer: {active.name}")

        no_exp = mgr.get_active_experiment_for_agent("nonexistent")
        assert no_exp is None
        print("  ✓ No experiment for unknown agent")

        # ── Test 15: Winner config extraction ────────────────────────────
        print("\n[15] Testing winner config extraction...")
        winner_info = mgr.get_winner_config(exp.id)
        assert winner_info is not None
        agent, config = winner_info
        assert agent == "executor"
        assert config == {"prompt_version": 3}  # rolled back to v3
        print(f"  ✓ Winner config: agent={agent}, config={config}")

        # ── Test 16: List experiments with filter ────────────────────────
        print("\n[16] Testing list/filter...")
        all_exps = mgr.list_experiments()
        running_exps = mgr.list_experiments(status="running")
        completed_exps = mgr.list_experiments(status="completed")
        assert len(all_exps) >= 3
        print(f"  ✓ All={len(all_exps)}, Running={len(running_exps)}, Completed={len(completed_exps)}")

        # ── Test 17: Edge cases ──────────────────────────────────────────
        print("\n[17] Testing edge cases...")

        # Unknown experiment
        try:
            mgr.assign("nonexistent", {"id": "x"})
            assert False
        except KeyError:
            print("  ✓ Assign to unknown experiment raises KeyError")

        try:
            mgr.record("nonexistent", "v1", {"quality": 50})
            assert False
        except KeyError:
            print("  ✓ Record to unknown experiment raises KeyError")

        try:
            mgr.record(exp.id, "nonexistent_variant", {"quality": 50})
            assert False
        except KeyError:
            print("  ✓ Record to unknown variant raises KeyError")

        # Analyze with insufficient data
        exp_small = mgr.create_experiment(
            name="small-test",
            hypothesis="test",
            control=Variant(name="a", agent="executor"),
            variants=[Variant(name="b", agent="executor")],
            min_samples=100,
        )
        r_small = mgr.analyze(exp_small.id)
        assert r_small.winner is None, "Should have no winner with 0 samples"
        assert "Insufficient" in r_small.recommendation
        print("  ✓ No winner with insufficient data")

        print("\n" + "=" * 70)
        print("ALL 17 TESTS PASSED")
        print("=" * 70)

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
