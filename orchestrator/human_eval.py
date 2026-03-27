#!/usr/bin/env python3
"""
orchestrator/human_eval.py — Human Evaluation Framework
========================================================
Crowdsource quality evaluation from human raters, collect structured feedback,
compute inter-rater reliability, and aggregate scores into the evaluation pipeline.

Usage:
    python orchestrator/human_eval.py                  # run interactive evaluation session
    python orchestrator/human_eval.py --report         # print aggregated report
    python orchestrator/human_eval.py --export csv     # export ratings to CSV
    python orchestrator/human_eval.py --calibrate      # run calibration round
    python orchestrator/human_eval.py --reliability    # compute inter-rater agreement
"""
import json
import csv
import hashlib
import math
import statistics
import argparse
import io
from pathlib import Path
from datetime import datetime
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple
from enum import Enum
from collections import defaultdict


BASE_DIR = Path(__file__).parent.parent
RATINGS_LOG = BASE_DIR / "reports" / "human_ratings.jsonl"
FEEDBACK_LOG = BASE_DIR / "reports" / "human_feedback.jsonl"
CALIBRATION_LOG = BASE_DIR / "reports" / "human_calibration.jsonl"
AGGREGATE_FILE = BASE_DIR / "reports" / "human_eval_summary.json"
TASKS_FILE = BASE_DIR / "reports" / "eval_tasks.json"

for p in [RATINGS_LOG, FEEDBACK_LOG, CALIBRATION_LOG, AGGREGATE_FILE, TASKS_FILE]:
    p.parent.mkdir(parents=True, exist_ok=True)


# ── Enums & Constants ────────────────────────────────────────────────────────

class EvalDimension(str, Enum):
    CORRECTNESS = "correctness"
    COMPLETENESS = "completeness"
    CLARITY = "clarity"
    HELPFULNESS = "helpfulness"
    SAFETY = "safety"


class TaskStatus(str, Enum):
    PENDING = "pending"
    ASSIGNED = "assigned"
    COMPLETED = "completed"
    CALIBRATION = "calibration"
    DISPUTED = "disputed"


class RaterTier(str, Enum):
    NOVICE = "novice"
    INTERMEDIATE = "intermediate"
    EXPERT = "expert"
    CALIBRATOR = "calibrator"


DIMENSION_WEIGHTS = {
    EvalDimension.CORRECTNESS: 0.30,
    EvalDimension.COMPLETENESS: 0.25,
    EvalDimension.CLARITY: 0.20,
    EvalDimension.HELPFULNESS: 0.15,
    EvalDimension.SAFETY: 0.10,
}

MIN_RATERS_PER_TASK = 3
AGREEMENT_THRESHOLD = 0.7
CALIBRATION_TOLERANCE = 1.0  # max allowed deviation from gold standard


# ── Data Structures ──────────────────────────────────────────────────────────

@dataclass
class EvalTask:
    """A unit of work to be evaluated by human raters."""
    task_id: str
    agent: str
    category: str
    prompt: str
    response: str
    reference_answer: Optional[str] = None
    gold_scores: Optional[Dict[str, float]] = None
    status: str = TaskStatus.PENDING.value
    assigned_raters: List[str] = field(default_factory=list)
    created_at: str = ""
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.created_at:
            self.created_at = datetime.utcnow().isoformat()
        if not self.task_id:
            raw = f"{self.agent}:{self.category}:{self.prompt[:50]}:{self.created_at}"
            self.task_id = hashlib.sha256(raw.encode()).hexdigest()[:12]


@dataclass
class Rating:
    """A single human rating for one eval task."""
    rating_id: str = ""
    task_id: str = ""
    rater_id: str = ""
    dimensions: Dict[str, float] = field(default_factory=dict)
    weighted_score: float = 0.0
    comment: str = ""
    timestamp: str = ""
    duration_s: float = 0.0
    rater_tier: str = RaterTier.NOVICE.value
    flagged: bool = False
    flag_reason: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()
        if not self.rating_id:
            raw = f"{self.task_id}:{self.rater_id}:{self.timestamp}"
            self.rating_id = hashlib.sha256(raw.encode()).hexdigest()[:12]
        if self.dimensions and not self.weighted_score:
            self.weighted_score = self._compute_weighted()

    def _compute_weighted(self) -> float:
        total = 0.0
        for dim, weight in DIMENSION_WEIGHTS.items():
            total += self.dimensions.get(dim.value, 0.0) * weight
        return round(total, 2)


@dataclass
class RaterProfile:
    """Tracks rater reliability and history."""
    rater_id: str
    tier: str = RaterTier.NOVICE.value
    total_ratings: int = 0
    calibration_score: float = 0.0
    agreement_rate: float = 0.0
    avg_duration_s: float = 0.0
    flagged_count: int = 0
    active: bool = True
    joined_at: str = ""

    def __post_init__(self):
        if not self.joined_at:
            self.joined_at = datetime.utcnow().isoformat()


@dataclass
class AggregatedResult:
    """Consensus result for one eval task after multiple ratings."""
    task_id: str
    agent: str
    category: str
    dimension_scores: Dict[str, float] = field(default_factory=dict)
    overall_score: float = 0.0
    num_raters: int = 0
    std_dev: float = 0.0
    agreement: float = 0.0
    ratings: List[Dict] = field(default_factory=list)
    status: str = "incomplete"
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()


# ── Storage Layer ────────────────────────────────────────────────────────────

class EvalStore:
    """Append-only JSONL storage for human evaluation data."""

    def __init__(self, ratings_path: Path = RATINGS_LOG,
                 feedback_path: Path = FEEDBACK_LOG,
                 calibration_path: Path = CALIBRATION_LOG):
        self.ratings_path = ratings_path
        self.feedback_path = feedback_path
        self.calibration_path = calibration_path

    def _append(self, path: Path, record: dict):
        with open(path, "a") as f:
            f.write(json.dumps(record, default=str) + "\n")

    def _read_all(self, path: Path) -> List[dict]:
        if not path.exists():
            return []
        records = []
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
        return records

    def save_rating(self, rating: Rating):
        self._append(self.ratings_path, asdict(rating))

    def save_feedback(self, feedback: dict):
        feedback["timestamp"] = datetime.utcnow().isoformat()
        self._append(self.feedback_path, feedback)

    def save_calibration(self, record: dict):
        record["timestamp"] = datetime.utcnow().isoformat()
        self._append(self.calibration_path, record)

    def load_ratings(self, task_id: Optional[str] = None) -> List[dict]:
        all_ratings = self._read_all(self.ratings_path)
        if task_id:
            return [r for r in all_ratings if r.get("task_id") == task_id]
        return all_ratings

    def load_feedback(self) -> List[dict]:
        return self._read_all(self.feedback_path)

    def load_calibrations(self) -> List[dict]:
        return self._read_all(self.calibration_path)


# ── Task Queue ───────────────────────────────────────────────────────────────

class TaskQueue:
    """Manages evaluation tasks and assignment to raters."""

    def __init__(self, tasks_path: Path = TASKS_FILE):
        self.tasks_path = tasks_path
        self.tasks: Dict[str, EvalTask] = {}
        self._load()

    def _load(self):
        if self.tasks_path.exists():
            data = json.loads(self.tasks_path.read_text())
            for t in data.get("tasks", []):
                task = EvalTask(**t)
                self.tasks[task.task_id] = task

    def _save(self):
        data = {"tasks": [asdict(t) for t in self.tasks.values()],
                "updated_at": datetime.utcnow().isoformat()}
        self.tasks_path.write_text(json.dumps(data, indent=2, default=str))

    def add_task(self, task: EvalTask) -> str:
        self.tasks[task.task_id] = task
        self._save()
        return task.task_id

    def assign_task(self, task_id: str, rater_id: str) -> Optional[EvalTask]:
        task = self.tasks.get(task_id)
        if not task:
            return None
        if rater_id not in task.assigned_raters:
            task.assigned_raters.append(rater_id)
        task.status = TaskStatus.ASSIGNED.value
        self._save()
        return task

    def get_pending(self, rater_id: str, limit: int = 5) -> List[EvalTask]:
        pending = []
        for task in self.tasks.values():
            if task.status in (TaskStatus.PENDING.value, TaskStatus.ASSIGNED.value):
                if rater_id not in task.assigned_raters:
                    if len(task.assigned_raters) < MIN_RATERS_PER_TASK:
                        pending.append(task)
            if len(pending) >= limit:
                break
        return pending

    def mark_completed(self, task_id: str):
        task = self.tasks.get(task_id)
        if task:
            task.status = TaskStatus.COMPLETED.value
            self._save()

    def get_task(self, task_id: str) -> Optional[EvalTask]:
        return self.tasks.get(task_id)


# ── Rater Management ─────────────────────────────────────────────────────────

class RaterManager:
    """Manages rater profiles, calibration, and reliability tracking."""

    def __init__(self):
        self.raters: Dict[str, RaterProfile] = {}

    def register(self, rater_id: str, tier: str = RaterTier.NOVICE.value) -> RaterProfile:
        if rater_id not in self.raters:
            self.raters[rater_id] = RaterProfile(rater_id=rater_id, tier=tier)
        return self.raters[rater_id]

    def get_profile(self, rater_id: str) -> Optional[RaterProfile]:
        return self.raters.get(rater_id)

    def update_stats(self, rater_id: str, rating: Rating):
        profile = self.raters.get(rater_id)
        if not profile:
            profile = self.register(rater_id)
        profile.total_ratings += 1
        if rating.flagged:
            profile.flagged_count += 1
        # running average of duration
        if rating.duration_s > 0:
            n = profile.total_ratings
            profile.avg_duration_s = (
                (profile.avg_duration_s * (n - 1) + rating.duration_s) / n
            )

    def calibrate_rater(self, rater_id: str, gold_task: EvalTask,
                        rater_scores: Dict[str, float]) -> Tuple[bool, float]:
        """Check rater against gold standard scores. Returns (passed, deviation)."""
        if not gold_task.gold_scores:
            return True, 0.0
        deviations = []
        for dim, gold_val in gold_task.gold_scores.items():
            rater_val = rater_scores.get(dim, 0.0)
            deviations.append(abs(gold_val - rater_val))
        avg_deviation = statistics.mean(deviations) if deviations else 0.0
        passed = avg_deviation <= CALIBRATION_TOLERANCE
        profile = self.raters.get(rater_id)
        if profile:
            profile.calibration_score = round(max(0, 5.0 - avg_deviation), 2)
            if passed and profile.total_ratings >= 10:
                profile.tier = RaterTier.INTERMEDIATE.value
            if passed and profile.total_ratings >= 50 and profile.calibration_score >= 4.0:
                profile.tier = RaterTier.EXPERT.value
        return passed, round(avg_deviation, 3)


# ── Inter-Rater Reliability ──────────────────────────────────────────────────

def cohens_kappa(ratings_a: List[float], ratings_b: List[float],
                 num_categories: int = 5) -> float:
    """Compute Cohen's kappa for two raters on ordinal (1-5) scale.
    Discretizes continuous scores into integer buckets."""
    if len(ratings_a) != len(ratings_b) or len(ratings_a) == 0:
        return 0.0
    n = len(ratings_a)
    buckets_a = [min(num_categories, max(1, round(s))) for s in ratings_a]
    buckets_b = [min(num_categories, max(1, round(s))) for s in ratings_b]

    # confusion matrix
    matrix = defaultdict(lambda: defaultdict(int))
    for a, b in zip(buckets_a, buckets_b):
        matrix[a][b] += 1

    # observed agreement
    p_o = sum(matrix[i][i] for i in range(1, num_categories + 1)) / n

    # expected agreement
    p_e = 0.0
    for k in range(1, num_categories + 1):
        row_sum = sum(matrix[k][j] for j in range(1, num_categories + 1))
        col_sum = sum(matrix[i][k] for i in range(1, num_categories + 1))
        p_e += (row_sum / n) * (col_sum / n)

    if p_e >= 1.0:
        return 1.0
    return round((p_o - p_e) / (1.0 - p_e), 4)


def krippendorffs_alpha(ratings_matrix: List[List[Optional[float]]]) -> float:
    """Compute Krippendorff's alpha for multiple raters with possible missing values.
    ratings_matrix: list of raters, each with scores per item (None = missing)."""
    if not ratings_matrix or not ratings_matrix[0]:
        return 0.0

    n_items = len(ratings_matrix[0])
    n_raters = len(ratings_matrix)

    # collect all non-None pairs per item
    pairs_within = []
    all_values = []
    for item_idx in range(n_items):
        item_vals = []
        for rater_idx in range(n_raters):
            v = ratings_matrix[rater_idx][item_idx]
            if v is not None:
                item_vals.append(v)
                all_values.append(v)
        if len(item_vals) >= 2:
            for i in range(len(item_vals)):
                for j in range(i + 1, len(item_vals)):
                    pairs_within.append((item_vals[i] - item_vals[j]) ** 2)

    if not pairs_within or not all_values:
        return 0.0

    # observed disagreement
    d_o = statistics.mean(pairs_within)

    # expected disagreement (all possible cross-item pairs)
    n_vals = len(all_values)
    if n_vals < 2:
        return 0.0
    total_sq_diff = 0.0
    count = 0
    for i in range(n_vals):
        for j in range(i + 1, n_vals):
            total_sq_diff += (all_values[i] - all_values[j]) ** 2
            count += 1
    d_e = total_sq_diff / count if count > 0 else 0.0

    if d_e == 0:
        return 1.0
    return round(1.0 - (d_o / d_e), 4)


# ── Aggregation Engine ───────────────────────────────────────────────────────

class AggregationEngine:
    """Aggregates multiple human ratings into consensus scores."""

    def __init__(self, store: EvalStore):
        self.store = store

    def aggregate_task(self, task_id: str, task: EvalTask) -> AggregatedResult:
        raw_ratings = self.store.load_ratings(task_id)
        if not raw_ratings:
            return AggregatedResult(
                task_id=task_id, agent=task.agent, category=task.category,
                status="no_ratings"
            )

        # filter out flagged ratings
        valid = [r for r in raw_ratings if not r.get("flagged", False)]
        if not valid:
            return AggregatedResult(
                task_id=task_id, agent=task.agent, category=task.category,
                status="all_flagged"
            )

        # per-dimension averages
        dim_scores: Dict[str, List[float]] = defaultdict(list)
        weighted_scores = []
        for r in valid:
            dims = r.get("dimensions", {})
            for dim_name, val in dims.items():
                dim_scores[dim_name].append(val)
            weighted_scores.append(r.get("weighted_score", 0.0))

        avg_dims = {d: round(statistics.mean(vals), 2) for d, vals in dim_scores.items()}
        overall = round(statistics.mean(weighted_scores), 2) if weighted_scores else 0.0
        std = round(statistics.stdev(weighted_scores), 2) if len(weighted_scores) > 1 else 0.0

        # inter-rater agreement using weighted scores
        agreement = 0.0
        if len(weighted_scores) >= 2:
            max_possible_range = 5.0
            mean_dev = statistics.mean(
                [abs(s - overall) for s in weighted_scores]
            )
            agreement = round(max(0, 1.0 - (mean_dev / max_possible_range)), 3)

        status = "completed" if len(valid) >= MIN_RATERS_PER_TASK else "incomplete"

        return AggregatedResult(
            task_id=task_id,
            agent=task.agent,
            category=task.category,
            dimension_scores=avg_dims,
            overall_score=overall,
            num_raters=len(valid),
            std_dev=std,
            agreement=agreement,
            ratings=valid,
            status=status,
        )

    def aggregate_all(self, queue: TaskQueue) -> Dict[str, AggregatedResult]:
        results = {}
        for task_id, task in queue.tasks.items():
            results[task_id] = self.aggregate_task(task_id, task)
        return results

    def generate_summary(self, queue: TaskQueue) -> dict:
        results = self.aggregate_all(queue)
        by_agent: Dict[str, List[float]] = defaultdict(list)
        by_category: Dict[str, List[float]] = defaultdict(list)
        all_scores = []
        completed = 0
        total = len(results)

        for r in results.values():
            if r.status == "completed":
                completed += 1
                all_scores.append(r.overall_score)
                by_agent[r.agent].append(r.overall_score)
                by_category[r.category].append(r.overall_score)

        summary = {
            "timestamp": datetime.utcnow().isoformat(),
            "total_tasks": total,
            "completed_tasks": completed,
            "avg_score": round(statistics.mean(all_scores), 2) if all_scores else 0.0,
            "min_score": round(min(all_scores), 2) if all_scores else 0.0,
            "max_score": round(max(all_scores), 2) if all_scores else 0.0,
            "std_dev": round(statistics.stdev(all_scores), 2) if len(all_scores) > 1 else 0.0,
            "by_agent": {a: round(statistics.mean(s), 2) for a, s in by_agent.items()},
            "by_category": {c: round(statistics.mean(s), 2) for c, s in by_category.items()},
            "dimension_averages": {},
            "tasks": {tid: asdict(r) for tid, r in results.items()},
        }

        # global dimension averages
        dim_all: Dict[str, List[float]] = defaultdict(list)
        for r in results.values():
            if r.status == "completed":
                for d, v in r.dimension_scores.items():
                    dim_all[d].append(v)
        summary["dimension_averages"] = {
            d: round(statistics.mean(vals), 2) for d, vals in dim_all.items()
        }

        return summary

    def export_csv(self, queue: TaskQueue) -> str:
        results = self.aggregate_all(queue)
        output = io.StringIO()
        writer = csv.writer(output)
        dims = [d.value for d in EvalDimension]
        header = ["task_id", "agent", "category", "rater_id", "weighted_score",
                  "comment", "flagged"] + dims
        writer.writerow(header)

        for task_id, agg in results.items():
            for r in agg.ratings:
                row = [
                    task_id, agg.agent, agg.category,
                    r.get("rater_id", ""), r.get("weighted_score", 0),
                    r.get("comment", ""), r.get("flagged", False),
                ]
                for d in dims:
                    row.append(r.get("dimensions", {}).get(d, ""))
                writer.writerow(row)

        return output.getvalue()


# ── Feedback Collector ───────────────────────────────────────────────────────

class FeedbackCollector:
    """Collects structured and freeform feedback from evaluators."""

    def __init__(self, store: EvalStore):
        self.store = store

    def submit_feedback(self, rater_id: str, task_id: str,
                        feedback_type: str, content: str,
                        severity: str = "info") -> dict:
        record = {
            "rater_id": rater_id,
            "task_id": task_id,
            "type": feedback_type,
            "content": content,
            "severity": severity,
        }
        self.store.save_feedback(record)
        return record

    def submit_dispute(self, rater_id: str, task_id: str,
                       reason: str) -> dict:
        return self.submit_feedback(
            rater_id, task_id, "dispute", reason, severity="warning"
        )

    def get_feedback_summary(self) -> dict:
        all_fb = self.store.load_feedback()
        by_type: Dict[str, int] = defaultdict(int)
        by_severity: Dict[str, int] = defaultdict(int)
        by_task: Dict[str, int] = defaultdict(int)
        for fb in all_fb:
            by_type[fb.get("type", "unknown")] += 1
            by_severity[fb.get("severity", "info")] += 1
            by_task[fb.get("task_id", "unknown")] += 1

        return {
            "total": len(all_fb),
            "by_type": dict(by_type),
            "by_severity": dict(by_severity),
            "top_tasks": dict(sorted(by_task.items(), key=lambda x: -x[1])[:10]),
        }


# ── Human Eval Session ───────────────────────────────────────────────────────

class HumanEvalSession:
    """Orchestrates a complete human evaluation session."""

    def __init__(self, store: Optional[EvalStore] = None,
                 queue: Optional[TaskQueue] = None):
        self.store = store or EvalStore()
        self.queue = queue or TaskQueue()
        self.rater_mgr = RaterManager()
        self.aggregator = AggregationEngine(self.store)
        self.feedback = FeedbackCollector(self.store)

    def create_eval_task(self, agent: str, category: str,
                         prompt: str, response: str,
                         reference: Optional[str] = None,
                         gold_scores: Optional[Dict[str, float]] = None) -> str:
        task = EvalTask(
            task_id="",
            agent=agent,
            category=category,
            prompt=prompt,
            response=response,
            reference_answer=reference,
            gold_scores=gold_scores,
        )
        return self.queue.add_task(task)

    def submit_rating(self, task_id: str, rater_id: str,
                      scores: Dict[str, float],
                      comment: str = "",
                      duration_s: float = 0.0,
                      flagged: bool = False,
                      flag_reason: str = "") -> Rating:
        # validate scores
        for dim in scores:
            if scores[dim] < 1.0 or scores[dim] > 5.0:
                raise ValueError(f"Score for {dim} must be between 1.0 and 5.0, got {scores[dim]}")

        # ensure rater is registered
        self.rater_mgr.register(rater_id)

        # assign task to rater if not already
        self.queue.assign_task(task_id, rater_id)

        rating = Rating(
            task_id=task_id,
            rater_id=rater_id,
            dimensions=scores,
            comment=comment,
            duration_s=duration_s,
            flagged=flagged,
            flag_reason=flag_reason,
            rater_tier=self.rater_mgr.get_profile(rater_id).tier,
        )

        self.store.save_rating(rating)
        self.rater_mgr.update_stats(rater_id, rating)

        # check if task has enough ratings
        task_ratings = self.store.load_ratings(task_id)
        valid_count = sum(1 for r in task_ratings if not r.get("flagged", False))
        if valid_count >= MIN_RATERS_PER_TASK:
            self.queue.mark_completed(task_id)

        return rating

    def run_calibration(self, rater_id: str, gold_task: EvalTask,
                        rater_scores: Dict[str, float]) -> Tuple[bool, float]:
        passed, deviation = self.rater_mgr.calibrate_rater(
            rater_id, gold_task, rater_scores
        )
        self.store.save_calibration({
            "rater_id": rater_id,
            "task_id": gold_task.task_id,
            "rater_scores": rater_scores,
            "gold_scores": gold_task.gold_scores,
            "deviation": deviation,
            "passed": passed,
        })
        return passed, deviation

    def get_report(self) -> dict:
        summary = self.aggregator.generate_summary(self.queue)
        feedback_summary = self.feedback.get_feedback_summary()
        summary["feedback"] = feedback_summary
        summary["raters"] = {
            rid: asdict(rp) for rid, rp in self.rater_mgr.raters.items()
        }
        return summary

    def compute_reliability(self) -> dict:
        """Compute inter-rater reliability across all completed tasks."""
        all_ratings = self.store.load_ratings()
        tasks_ratings: Dict[str, Dict[str, float]] = defaultdict(dict)
        for r in all_ratings:
            if not r.get("flagged", False):
                tid = r["task_id"]
                rid = r["rater_id"]
                tasks_ratings[tid][rid] = r.get("weighted_score", 0.0)

        # find tasks with 2+ raters
        multi_rated = {t: rs for t, rs in tasks_ratings.items() if len(rs) >= 2}
        if not multi_rated:
            return {"kappa": None, "alpha": None, "n_tasks": 0,
                    "msg": "Need at least 2 raters on same tasks"}

        # all raters who participated
        all_raters = sorted(set(
            rid for rs in multi_rated.values() for rid in rs
        ))

        # build matrix for Krippendorff: raters x items
        items = sorted(multi_rated.keys())
        matrix = []
        for rater in all_raters:
            row = []
            for item in items:
                row.append(multi_rated[item].get(rater))
            matrix.append(row)

        alpha = krippendorffs_alpha(matrix)

        # pairwise kappa for first two raters with overlap
        kappa = None
        rater_pairs = []
        for i in range(len(all_raters)):
            for j in range(i + 1, len(all_raters)):
                r_a, r_b = all_raters[i], all_raters[j]
                scores_a, scores_b = [], []
                for item in items:
                    va = multi_rated[item].get(r_a)
                    vb = multi_rated[item].get(r_b)
                    if va is not None and vb is not None:
                        scores_a.append(va)
                        scores_b.append(vb)
                if len(scores_a) >= 2:
                    k = cohens_kappa(scores_a, scores_b)
                    rater_pairs.append({
                        "raters": [r_a, r_b],
                        "kappa": k,
                        "n_items": len(scores_a),
                    })
                    if kappa is None:
                        kappa = k

        return {
            "krippendorffs_alpha": alpha,
            "cohens_kappa_pairs": rater_pairs,
            "n_tasks": len(items),
            "n_raters": len(all_raters),
        }


# ── Main ─────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import tempfile
    import os

    # Use temp directory for test isolation
    tmp = tempfile.mkdtemp()
    test_ratings = Path(tmp) / "ratings.jsonl"
    test_feedback = Path(tmp) / "feedback.jsonl"
    test_calibration = Path(tmp) / "calibration.jsonl"
    test_tasks = Path(tmp) / "tasks.json"

    store = EvalStore(
        ratings_path=test_ratings,
        feedback_path=test_feedback,
        calibration_path=test_calibration,
    )
    queue = TaskQueue(tasks_path=test_tasks)
    session = HumanEvalSession(store=store, queue=queue)

    # ── Test 1: Create eval tasks ──
    t1 = session.create_eval_task(
        agent="executor",
        category="code_gen",
        prompt="Write a Python function to sort a list",
        response="def sort_list(lst): return sorted(lst)",
        reference="def sort_list(lst): return sorted(lst)",
    )
    t2 = session.create_eval_task(
        agent="planner",
        category="planning",
        prompt="Plan a migration from SQLite to PostgreSQL",
        response="1. Export data\n2. Create schema\n3. Import data\n4. Validate",
    )
    assert t1, "Task 1 should have an ID"
    assert t2, "Task 2 should have an ID"
    assert t1 != t2, "Task IDs must be unique"
    assert queue.get_task(t1) is not None
    assert queue.get_task(t2) is not None
    print("[PASS] Task creation")

    # ── Test 2: Submit ratings from multiple raters ──
    raters = ["rater_alice", "rater_bob", "rater_carol"]
    base_scores = {
        "correctness": 4.5, "completeness": 4.0,
        "clarity": 3.5, "helpfulness": 4.0, "safety": 5.0,
    }

    for i, rater in enumerate(raters):
        scores = {k: min(5.0, max(1.0, v + (i * 0.2 - 0.2)))
                  for k, v in base_scores.items()}
        rating = session.submit_rating(
            task_id=t1, rater_id=rater, scores=scores,
            comment=f"Evaluation by {rater}", duration_s=45.0 + i * 10,
        )
        assert rating.rating_id, f"Rating from {rater} should have ID"
        assert rating.weighted_score > 0, f"Weighted score should be positive"
        assert 1.0 <= rating.weighted_score <= 5.0, "Weighted score in range"

    # Verify task marked completed after 3 ratings
    task1 = queue.get_task(t1)
    assert task1.status == TaskStatus.COMPLETED.value, \
        f"Task should be completed after {MIN_RATERS_PER_TASK} ratings, got {task1.status}"
    print("[PASS] Rating submission and task completion")

    # ── Test 3: Validate score range enforcement ──
    try:
        session.submit_rating(t2, "rater_bad", {"correctness": 6.0}, "")
        assert False, "Should have raised ValueError for score > 5"
    except ValueError:
        pass

    try:
        session.submit_rating(t2, "rater_bad", {"correctness": 0.5}, "")
        assert False, "Should have raised ValueError for score < 1"
    except ValueError:
        pass
    print("[PASS] Score validation")

    # ── Test 4: Aggregation ──
    agg = session.aggregator.aggregate_task(t1, queue.get_task(t1))
    assert agg.status == "completed"
    assert agg.num_raters == 3
    assert agg.overall_score > 0
    assert agg.std_dev >= 0
    assert agg.agreement > 0
    assert "correctness" in agg.dimension_scores
    assert "completeness" in agg.dimension_scores
    assert "clarity" in agg.dimension_scores
    print(f"[PASS] Aggregation: score={agg.overall_score}, "
          f"agreement={agg.agreement}, std_dev={agg.std_dev}")

    # ── Test 5: Weighted scoring ──
    rating_manual = Rating(
        task_id="test", rater_id="test",
        dimensions={
            "correctness": 5.0,    # weight 0.30
            "completeness": 4.0,   # weight 0.25
            "clarity": 3.0,        # weight 0.20
            "helpfulness": 2.0,    # weight 0.15
            "safety": 1.0,         # weight 0.10
        }
    )
    expected = 5.0*0.30 + 4.0*0.25 + 3.0*0.20 + 2.0*0.15 + 1.0*0.10
    assert abs(rating_manual.weighted_score - round(expected, 2)) < 0.01, \
        f"Weighted score mismatch: {rating_manual.weighted_score} != {expected}"
    print(f"[PASS] Weighted scoring: {rating_manual.weighted_score} == {round(expected, 2)}")

    # ── Test 6: Feedback collection ──
    fb = session.feedback.submit_feedback(
        "rater_alice", t1, "quality_issue",
        "Response is too terse", severity="warning"
    )
    assert fb["type"] == "quality_issue"

    dispute = session.feedback.submit_dispute(
        "rater_bob", t1, "Gold answer seems wrong"
    )
    assert dispute["type"] == "dispute"
    assert dispute["severity"] == "warning"

    fb_summary = session.feedback.get_feedback_summary()
    assert fb_summary["total"] == 2
    assert fb_summary["by_type"]["quality_issue"] == 1
    assert fb_summary["by_type"]["dispute"] == 1
    print("[PASS] Feedback collection")

    # ── Test 7: Calibration ──
    gold_task = EvalTask(
        task_id="gold_1", agent="executor", category="code_gen",
        prompt="test", response="test",
        gold_scores={"correctness": 4.0, "completeness": 3.5, "clarity": 4.0},
        status=TaskStatus.CALIBRATION.value,
    )

    # Good rater: close to gold
    passed, dev = session.run_calibration(
        "rater_alice", gold_task,
        {"correctness": 4.2, "completeness": 3.3, "clarity": 3.8}
    )
    assert passed, f"Alice should pass calibration (dev={dev})"
    assert dev < CALIBRATION_TOLERANCE

    # Bad rater: far from gold
    passed_bad, dev_bad = session.run_calibration(
        "rater_bad_cal", gold_task,
        {"correctness": 1.0, "completeness": 1.0, "clarity": 1.0}
    )
    assert not passed_bad, f"Bad rater should fail calibration (dev={dev_bad})"
    print(f"[PASS] Calibration: alice_dev={dev}, bad_dev={dev_bad}")

    # ── Test 8: Inter-rater reliability ──
    # Submit ratings for t2 from multiple raters
    for rater in raters:
        scores = {k: min(5.0, max(1.0, v)) for k, v in base_scores.items()}
        session.submit_rating(t2, rater, scores, comment="t2 eval", duration_s=30.0)

    reliability = session.compute_reliability()
    assert reliability["n_tasks"] >= 2, f"Should have 2+ multi-rated tasks, got {reliability['n_tasks']}"
    assert reliability["n_raters"] >= 3
    alpha = reliability["krippendorffs_alpha"]
    assert alpha is not None, "Alpha should be computed"
    assert -1.0 <= alpha <= 1.0, f"Alpha out of range: {alpha}"
    print(f"[PASS] Inter-rater reliability: alpha={alpha}, "
          f"pairs={len(reliability['cohens_kappa_pairs'])}")

    # ── Test 9: Cohen's kappa edge cases ──
    # Perfect agreement
    k_perfect = cohens_kappa([4.0, 3.0, 5.0, 2.0], [4.0, 3.0, 5.0, 2.0])
    assert k_perfect == 1.0, f"Perfect agreement kappa should be 1.0, got {k_perfect}"

    # Empty input
    k_empty = cohens_kappa([], [])
    assert k_empty == 0.0

    # Mismatched length
    k_mismatch = cohens_kappa([1.0], [1.0, 2.0])
    assert k_mismatch == 0.0
    print("[PASS] Cohen's kappa edge cases")

    # ── Test 10: Krippendorff's alpha edge cases ──
    # Perfect agreement (3 raters, 4 items)
    alpha_perfect = krippendorffs_alpha([
        [4.0, 3.0, 5.0, 2.0],
        [4.0, 3.0, 5.0, 2.0],
        [4.0, 3.0, 5.0, 2.0],
    ])
    assert alpha_perfect == 1.0, f"Perfect alpha should be 1.0, got {alpha_perfect}"

    # With missing values
    alpha_missing = krippendorffs_alpha([
        [4.0, None, 5.0, 2.0],
        [4.0, 3.0, None, 2.0],
        [None, 3.0, 5.0, 2.0],
    ])
    assert alpha_missing is not None
    assert -1.0 <= alpha_missing <= 1.0
    print(f"[PASS] Krippendorff's alpha: perfect={alpha_perfect}, missing={alpha_missing}")

    # ── Test 11: Report generation ──
    report = session.get_report()
    assert "total_tasks" in report
    assert "completed_tasks" in report
    assert report["completed_tasks"] == 2
    assert report["avg_score"] > 0
    assert "by_agent" in report
    assert "executor" in report["by_agent"]
    assert "planner" in report["by_agent"]
    assert "feedback" in report
    assert report["feedback"]["total"] == 2
    assert "dimension_averages" in report
    print(f"[PASS] Report: avg_score={report['avg_score']}, "
          f"agents={list(report['by_agent'].keys())}")

    # ── Test 12: CSV export ──
    csv_output = session.aggregator.export_csv(queue)
    assert csv_output, "CSV should not be empty"
    lines = csv_output.strip().split("\n")
    assert len(lines) >= 7, f"CSV should have header + 6 ratings, got {len(lines)} lines"
    header = lines[0]
    assert "task_id" in header
    assert "correctness" in header
    assert "weighted_score" in header
    print(f"[PASS] CSV export: {len(lines)} lines")

    # ── Test 13: Rater management ──
    profile = session.rater_mgr.get_profile("rater_alice")
    assert profile is not None
    assert profile.total_ratings >= 2  # rated t1 and t2
    assert profile.avg_duration_s > 0
    assert profile.calibration_score > 0  # calibrated above
    print(f"[PASS] Rater profile: {profile.rater_id}, ratings={profile.total_ratings}, "
          f"tier={profile.tier}, cal_score={profile.calibration_score}")

    # ── Test 14: Task queue management ──
    t3 = session.create_eval_task(
        agent="debugger", category="debugging",
        prompt="Fix null pointer", response="Check for null before access",
    )
    pending = queue.get_pending("new_rater", limit=10)
    pending_ids = [t.task_id for t in pending]
    assert t3 in pending_ids, "New task should be in pending queue"
    # t1 and t2 are completed, should not appear
    assert t1 not in pending_ids, "Completed task should not be pending"
    assert t2 not in pending_ids, "Completed task should not be pending"
    print("[PASS] Task queue pending/completed filtering")

    # ── Test 15: Flagged rating handling ──
    flagged_rating = session.submit_rating(
        task_id=t3, rater_id="rater_flaggy",
        scores={"correctness": 1.0, "completeness": 1.0,
                "clarity": 1.0, "helpfulness": 1.0, "safety": 1.0},
        comment="Spam",
        flagged=True, flag_reason="Suspected spam",
    )
    assert flagged_rating.flagged
    # Flagged ratings should not count toward completion
    agg3 = session.aggregator.aggregate_task(t3, queue.get_task(t3))
    assert agg3.status != "completed", "Task with only flagged ratings should not be completed"
    print("[PASS] Flagged rating excluded from aggregation")

    # ── Test 16: Dimension weights sum to 1.0 ──
    weight_sum = sum(DIMENSION_WEIGHTS.values())
    assert abs(weight_sum - 1.0) < 0.001, f"Weights must sum to 1.0, got {weight_sum}"
    print("[PASS] Dimension weights sum to 1.0")

    # ── Test 17: Store persistence ──
    all_stored = store.load_ratings()
    assert len(all_stored) >= 7, f"Should have 7+ stored ratings, got {len(all_stored)}"
    cals = store.load_calibrations()
    assert len(cals) == 2, f"Should have 2 calibration records, got {len(cals)}"
    print(f"[PASS] Store persistence: {len(all_stored)} ratings, {len(cals)} calibrations")

    # Cleanup
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)

    print("\n" + "=" * 60)
    print("ALL 17 TESTS PASSED — Human Evaluation Framework verified")
    print("=" * 60)
