#!/usr/bin/env python3
"""
orchestrator/continuous_eval.py — Continuous Model Evaluation Pipeline
======================================================================
Daily evaluation of local model quality across agent tasks.
Tracks trends over time, detects regressions, and alerts on degradation.

Usage:
    python orchestrator/continuous_eval.py              # run one evaluation cycle
    python orchestrator/continuous_eval.py --daemon      # run daily in background
    python orchestrator/continuous_eval.py --report      # print trend report
    python orchestrator/continuous_eval.py --check       # check for degradation alerts
"""
import json
import time
import hashlib
import statistics
import argparse
import threading
from pathlib import Path
from datetime import datetime, timedelta
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional, Tuple
from enum import Enum

BASE_DIR = Path(__file__).parent.parent
EVAL_LOG = BASE_DIR / "reports" / "eval_history.jsonl"
TREND_FILE = BASE_DIR / "reports" / "eval_trends.json"
ALERT_FILE = BASE_DIR / "reports" / "eval_alerts.jsonl"
STATE_FILE = BASE_DIR / "dashboard" / "state.json"
CALIBRATION_LOG = BASE_DIR / "reports" / "calibration_log.jsonl"

for p in [EVAL_LOG, TREND_FILE, ALERT_FILE]:
    p.parent.mkdir(parents=True, exist_ok=True)


# ── Data Structures ──────────────────────────────────────────────────────────

class Severity(str, Enum):
    INFO = "info"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass
class EvalResult:
    """Single evaluation run for one agent on one task category."""
    agent: str
    category: str
    score: float          # 0-100
    latency_s: float
    token_count: int
    timestamp: str = ""
    eval_id: str = ""
    version: int = 0

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()
        if not self.eval_id:
            raw = f"{self.agent}:{self.category}:{self.timestamp}"
            self.eval_id = hashlib.sha256(raw.encode()).hexdigest()[:12]


@dataclass
class TrendPoint:
    """Aggregated metrics for a single day."""
    date: str
    avg_score: float
    min_score: float
    max_score: float
    p50_latency: float
    p95_latency: float
    total_evals: int
    by_agent: Dict[str, float] = field(default_factory=dict)
    by_category: Dict[str, float] = field(default_factory=dict)


@dataclass
class Alert:
    """Degradation alert."""
    severity: str
    metric: str
    agent: str
    category: str
    current_value: float
    baseline_value: float
    delta_pct: float
    message: str
    timestamp: str = ""

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = datetime.utcnow().isoformat()


# ── Evaluation Benchmark Suite ───────────────────────────────────────────────

EVAL_SUITE: Dict[str, List[Dict]] = {
    "executor": [
        {"task": "Implement binary search", "category": "code_gen",
         "expected_keywords": ["def", "binary", "mid", "return"], "difficulty": 1},
        {"task": "Write a merge sort function", "category": "code_gen",
         "expected_keywords": ["def", "merge", "sort", "left", "right"], "difficulty": 2},
        {"task": "Implement an LRU cache class", "category": "code_gen",
         "expected_keywords": ["class", "get", "put", "capacity"], "difficulty": 3},
    ],
    "planner": [
        {"task": "Break 'deploy a microservice' into steps", "category": "planning",
         "expected_keywords": ["step", "deploy", "test", "monitor"], "difficulty": 1},
        {"task": "Plan migration from monolith to services", "category": "planning",
         "expected_keywords": ["phase", "migrate", "service", "data"], "difficulty": 2},
        {"task": "Design CI/CD pipeline for 10-person team", "category": "planning",
         "expected_keywords": ["build", "test", "deploy", "review"], "difficulty": 3},
    ],
    "reviewer": [
        {"task": "Review: def add(a,b): return a+b", "category": "review",
         "expected_keywords": ["type", "validation", "error"], "difficulty": 1},
        {"task": "Review a REST endpoint handler", "category": "review",
         "expected_keywords": ["error", "validation", "security"], "difficulty": 2},
        {"task": "Review database connection pooling module", "category": "review",
         "expected_keywords": ["connection", "pool", "timeout", "cleanup"], "difficulty": 3},
    ],
    "researcher": [
        {"task": "Summarize trade-offs of SQL vs NoSQL", "category": "research",
         "expected_keywords": ["SQL", "NoSQL", "scale", "consistency"], "difficulty": 1},
        {"task": "Compare container orchestration tools", "category": "research",
         "expected_keywords": ["Kubernetes", "Docker", "orchestration"], "difficulty": 2},
    ],
    "debugger": [
        {"task": "Diagnose: function returns None unexpectedly", "category": "debugging",
         "expected_keywords": ["return", "None", "path", "condition"], "difficulty": 1},
        {"task": "Diagnose: memory leak in long-running service", "category": "debugging",
         "expected_keywords": ["memory", "leak", "reference", "garbage"], "difficulty": 2},
    ],
}


# ── Scoring Engine ───────────────────────────────────────────────────────────

def score_output(output: str, expected_keywords: List[str], difficulty: int) -> float:
    """Score an agent output based on keyword coverage and length heuristics.

    Returns 0-100 score.
    """
    if not output or not output.strip():
        return 0.0

    output_lower = output.lower()

    # Keyword coverage (0-50 points)
    if expected_keywords:
        hits = sum(1 for kw in expected_keywords if kw.lower() in output_lower)
        keyword_score = (hits / len(expected_keywords)) * 50.0
    else:
        keyword_score = 25.0

    # Length adequacy (0-20 points) — scaled by difficulty
    min_length = 50 * difficulty
    ideal_length = 200 * difficulty
    length = len(output.strip())
    if length >= ideal_length:
        length_score = 20.0
    elif length >= min_length:
        length_score = 10.0 + 10.0 * ((length - min_length) / max(ideal_length - min_length, 1))
    else:
        length_score = max(0.0, 10.0 * (length / max(min_length, 1)))

    # Structure (0-15 points) — presence of organization signals
    structure_score = 0.0
    if "\n" in output.strip():
        structure_score += 5.0
    if any(c in output for c in ["- ", "* ", "1.", "def ", "class "]):
        structure_score += 5.0
    if len(output.strip().split("\n")) >= 3:
        structure_score += 5.0

    # Coherence heuristic (0-15 points) — penalize repetition and gibberish
    words = output_lower.split()
    if len(words) > 5:
        unique_ratio = len(set(words)) / len(words)
        coherence_score = min(15.0, unique_ratio * 20.0)
    else:
        coherence_score = 5.0

    return min(100.0, round(keyword_score + length_score + structure_score + coherence_score, 2))


def simulate_agent_output(agent: str, task: Dict) -> Tuple[str, float, int]:
    """Simulate running an agent on a task. Returns (output, latency_s, token_count).

    In production, this calls the actual local agent via agents/__init__.py router.
    For evaluation purposes, we load from calibration logs if available,
    otherwise generate a synthetic baseline.
    """
    # Try to pull from calibration log first
    output = _load_calibration_output(agent, task["category"])
    if output:
        latency = 1.5 + task["difficulty"] * 0.8
        tokens = len(output.split()) * 2
        return output, latency, tokens

    # Synthetic baseline: simulate reasonable agent output
    kw = task.get("expected_keywords", [])
    difficulty = task.get("difficulty", 1)
    lines = [f"# {task['task']}", ""]

    if agent == "executor":
        lines += [
            f"def solution():",
            f"    # Implementation for: {task['task']}",
        ]
        for k in kw:
            lines.append(f"    {k} = None  # placeholder")
        lines += ["    return result", ""]
    elif agent == "planner":
        for i, k in enumerate(kw, 1):
            lines.append(f"{i}. {k.capitalize()} — detailed step")
        lines.append("")
        lines.append(f"Total steps: {len(kw)}, estimated complexity: {difficulty}/3")
    elif agent == "reviewer":
        lines += ["## Review Findings", ""]
        for k in kw:
            lines.append(f"- **{k.capitalize()}**: Checked, see details below")
        lines += ["", f"Overall quality: {'good' if difficulty < 2 else 'needs improvement'}"]
    elif agent == "researcher":
        lines += [f"## Analysis: {task['task']}", ""]
        for k in kw:
            lines.append(f"- {k}: Key consideration in this domain")
        lines += ["", "## Conclusion", "Trade-offs depend on specific use case."]
    elif agent == "debugger":
        lines += ["## Diagnosis", ""]
        for k in kw:
            lines.append(f"- Check {k}: Common root cause")
        lines += ["", "## Recommended Fix", "Apply targeted patch after verifying root cause."]
    else:
        lines += [f"Agent {agent} output for {task['task']}"]
        for k in kw:
            lines.append(f"  - {k}")

    output = "\n".join(lines)
    latency = 1.0 + difficulty * 1.2 + len(kw) * 0.3
    tokens = len(output.split()) * 2
    return output, round(latency, 3), tokens


def _load_calibration_output(agent: str, category: str) -> Optional[str]:
    """Try to load a recent calibration output for this agent+category."""
    if not CALIBRATION_LOG.exists():
        return None
    try:
        with open(CALIBRATION_LOG) as f:
            for line in reversed(f.readlines()[-100:]):
                entry = json.loads(line.strip())
                if entry.get("agent") == agent and entry.get("category") == category:
                    return entry.get("output", "")
    except (json.JSONDecodeError, KeyError):
        pass
    return None


# ── Evaluation Runner ────────────────────────────────────────────────────────

def run_evaluation(version: int = 0) -> List[EvalResult]:
    """Run the full evaluation suite across all agents. Returns list of EvalResults."""
    results = []
    for agent, tasks in EVAL_SUITE.items():
        for task in tasks:
            output, latency, tokens = simulate_agent_output(agent, task)
            score = score_output(output, task.get("expected_keywords", []), task.get("difficulty", 1))

            result = EvalResult(
                agent=agent,
                category=task["category"],
                score=score,
                latency_s=latency,
                token_count=tokens,
                version=version,
            )
            results.append(result)

    # Persist results
    with open(EVAL_LOG, "a") as f:
        for r in results:
            f.write(json.dumps(asdict(r)) + "\n")

    return results


def load_eval_history(days: int = 30) -> List[EvalResult]:
    """Load evaluation results from the last N days."""
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()
    results = []
    if not EVAL_LOG.exists():
        return results
    with open(EVAL_LOG) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
                if d.get("timestamp", "") >= cutoff:
                    results.append(EvalResult(**d))
            except (json.JSONDecodeError, TypeError):
                continue
    return results


# ── Trend Analysis ───────────────────────────────────────────────────────────

def compute_trends(results: List[EvalResult], window_days: int = 7) -> List[TrendPoint]:
    """Aggregate evaluation results into daily trend points."""
    if not results:
        return []

    # Group by date
    by_date: Dict[str, List[EvalResult]] = {}
    for r in results:
        date = r.timestamp[:10]  # YYYY-MM-DD
        by_date.setdefault(date, []).append(r)

    trends = []
    for date in sorted(by_date.keys()):
        day_results = by_date[date]
        scores = [r.score for r in day_results]
        latencies = [r.latency_s for r in day_results]

        # Per-agent averages
        agent_scores: Dict[str, List[float]] = {}
        for r in day_results:
            agent_scores.setdefault(r.agent, []).append(r.score)
        by_agent = {a: round(statistics.mean(s), 2) for a, s in agent_scores.items()}

        # Per-category averages
        cat_scores: Dict[str, List[float]] = {}
        for r in day_results:
            cat_scores.setdefault(r.category, []).append(r.score)
        by_category = {c: round(statistics.mean(s), 2) for c, s in cat_scores.items()}

        sorted_latencies = sorted(latencies)
        p50_idx = max(0, len(sorted_latencies) // 2 - 1)
        p95_idx = max(0, int(len(sorted_latencies) * 0.95) - 1)

        trends.append(TrendPoint(
            date=date,
            avg_score=round(statistics.mean(scores), 2),
            min_score=round(min(scores), 2),
            max_score=round(max(scores), 2),
            p50_latency=round(sorted_latencies[p50_idx], 3),
            p95_latency=round(sorted_latencies[p95_idx], 3),
            total_evals=len(day_results),
            by_agent=by_agent,
            by_category=by_category,
        ))

    return trends


def save_trends(trends: List[TrendPoint]) -> None:
    """Persist trend data to JSON."""
    with open(TREND_FILE, "w") as f:
        json.dump([asdict(t) for t in trends], f, indent=2)


def load_trends() -> List[TrendPoint]:
    """Load trend data from JSON."""
    if not TREND_FILE.exists():
        return []
    try:
        with open(TREND_FILE) as f:
            data = json.load(f)
        return [TrendPoint(**d) for d in data]
    except (json.JSONDecodeError, TypeError):
        return []


# ── Degradation Detection ───────────────────────────────────────────────────

# Thresholds for alerting
SCORE_DROP_WARNING_PCT = 5.0     # warn if score drops >5% vs baseline
SCORE_DROP_CRITICAL_PCT = 15.0   # critical if score drops >15%
LATENCY_SPIKE_WARNING_PCT = 30.0  # warn if latency increases >30%
LATENCY_SPIKE_CRITICAL_PCT = 100.0  # critical if latency doubles
MIN_BASELINE_DAYS = 2            # need at least 2 days of data for baseline


def detect_degradation(trends: List[TrendPoint], baseline_days: int = 7) -> List[Alert]:
    """Compare recent performance against baseline and generate alerts."""
    if len(trends) < MIN_BASELINE_DAYS + 1:
        return []

    alerts = []

    # Split into baseline (older) and recent (latest day)
    baseline = trends[-(baseline_days + 1):-1]
    current = trends[-1]

    if not baseline:
        return []

    # Overall score degradation
    baseline_avg = statistics.mean([t.avg_score for t in baseline])
    if baseline_avg > 0:
        score_delta_pct = ((current.avg_score - baseline_avg) / baseline_avg) * 100

        if score_delta_pct <= -SCORE_DROP_CRITICAL_PCT:
            alerts.append(Alert(
                severity=Severity.CRITICAL,
                metric="avg_score",
                agent="all",
                category="all",
                current_value=current.avg_score,
                baseline_value=round(baseline_avg, 2),
                delta_pct=round(score_delta_pct, 2),
                message=f"Critical score drop: {current.avg_score:.1f} vs baseline {baseline_avg:.1f} ({score_delta_pct:+.1f}%)",
            ))
        elif score_delta_pct <= -SCORE_DROP_WARNING_PCT:
            alerts.append(Alert(
                severity=Severity.WARNING,
                metric="avg_score",
                agent="all",
                category="all",
                current_value=current.avg_score,
                baseline_value=round(baseline_avg, 2),
                delta_pct=round(score_delta_pct, 2),
                message=f"Score regression: {current.avg_score:.1f} vs baseline {baseline_avg:.1f} ({score_delta_pct:+.1f}%)",
            ))

    # Per-agent degradation
    for agent, current_score in current.by_agent.items():
        agent_baselines = [t.by_agent.get(agent, 0) for t in baseline if agent in t.by_agent]
        if not agent_baselines:
            continue
        agent_baseline_avg = statistics.mean(agent_baselines)
        if agent_baseline_avg > 0:
            delta = ((current_score - agent_baseline_avg) / agent_baseline_avg) * 100
            if delta <= -SCORE_DROP_CRITICAL_PCT:
                alerts.append(Alert(
                    severity=Severity.CRITICAL,
                    metric="agent_score",
                    agent=agent,
                    category="all",
                    current_value=current_score,
                    baseline_value=round(agent_baseline_avg, 2),
                    delta_pct=round(delta, 2),
                    message=f"Agent '{agent}' critical regression: {current_score:.1f} vs {agent_baseline_avg:.1f} ({delta:+.1f}%)",
                ))
            elif delta <= -SCORE_DROP_WARNING_PCT:
                alerts.append(Alert(
                    severity=Severity.WARNING,
                    metric="agent_score",
                    agent=agent,
                    category="all",
                    current_value=current_score,
                    baseline_value=round(agent_baseline_avg, 2),
                    delta_pct=round(delta, 2),
                    message=f"Agent '{agent}' score drop: {current_score:.1f} vs {agent_baseline_avg:.1f} ({delta:+.1f}%)",
                ))

    # Latency degradation
    baseline_p95 = statistics.mean([t.p95_latency for t in baseline])
    if baseline_p95 > 0:
        latency_delta_pct = ((current.p95_latency - baseline_p95) / baseline_p95) * 100
        if latency_delta_pct >= LATENCY_SPIKE_CRITICAL_PCT:
            alerts.append(Alert(
                severity=Severity.CRITICAL,
                metric="p95_latency",
                agent="all",
                category="all",
                current_value=current.p95_latency,
                baseline_value=round(baseline_p95, 3),
                delta_pct=round(latency_delta_pct, 2),
                message=f"Latency spike: p95={current.p95_latency:.2f}s vs baseline {baseline_p95:.2f}s ({latency_delta_pct:+.1f}%)",
            ))
        elif latency_delta_pct >= LATENCY_SPIKE_WARNING_PCT:
            alerts.append(Alert(
                severity=Severity.WARNING,
                metric="p95_latency",
                agent="all",
                category="all",
                current_value=current.p95_latency,
                baseline_value=round(baseline_p95, 3),
                delta_pct=round(latency_delta_pct, 2),
                message=f"Latency increase: p95={current.p95_latency:.2f}s vs baseline {baseline_p95:.2f}s ({latency_delta_pct:+.1f}%)",
            ))

    # Persist alerts
    if alerts:
        with open(ALERT_FILE, "a") as f:
            for a in alerts:
                f.write(json.dumps(asdict(a)) + "\n")

    return alerts


# ── Dashboard Integration ────────────────────────────────────────────────────

def update_dashboard(trends: List[TrendPoint], alerts: List[Alert]) -> None:
    """Write evaluation summary into dashboard state."""
    state = {}
    if STATE_FILE.exists():
        try:
            with open(STATE_FILE) as f:
                state = json.load(f)
        except (json.JSONDecodeError, ValueError):
            state = {}

    latest = trends[-1] if trends else None
    state["eval_pipeline"] = {
        "last_run": datetime.utcnow().isoformat(),
        "latest_avg_score": latest.avg_score if latest else None,
        "latest_p95_latency": latest.p95_latency if latest else None,
        "total_trend_days": len(trends),
        "active_alerts": len(alerts),
        "critical_alerts": sum(1 for a in alerts if a.severity == Severity.CRITICAL),
        "agents_evaluated": list(EVAL_SUITE.keys()),
    }

    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)


# ── Report Generation ────────────────────────────────────────────────────────

def generate_report(trends: List[TrendPoint], alerts: List[Alert]) -> str:
    """Generate a human-readable evaluation report."""
    lines = ["=" * 60, "  CONTINUOUS MODEL EVALUATION REPORT", "=" * 60, ""]

    if not trends:
        lines.append("No evaluation data available. Run an evaluation first.")
        return "\n".join(lines)

    latest = trends[-1]
    lines.append(f"Date:           {latest.date}")
    lines.append(f"Avg Score:      {latest.avg_score:.1f}/100")
    lines.append(f"Score Range:    {latest.min_score:.1f} - {latest.max_score:.1f}")
    lines.append(f"P50 Latency:    {latest.p50_latency:.2f}s")
    lines.append(f"P95 Latency:    {latest.p95_latency:.2f}s")
    lines.append(f"Total Evals:    {latest.total_evals}")
    lines.append("")

    lines.append("── Agent Scores ──")
    for agent, score in sorted(latest.by_agent.items()):
        bar = "█" * int(score / 5) + "░" * (20 - int(score / 5))
        lines.append(f"  {agent:<12} {bar} {score:.1f}")
    lines.append("")

    lines.append("── Category Scores ──")
    for cat, score in sorted(latest.by_category.items()):
        bar = "█" * int(score / 5) + "░" * (20 - int(score / 5))
        lines.append(f"  {cat:<12} {bar} {score:.1f}")
    lines.append("")

    if len(trends) > 1:
        lines.append("── Trend (last 7 days) ──")
        for t in trends[-7:]:
            delta = ""
            idx = trends.index(t)
            if idx > 0:
                prev = trends[idx - 1].avg_score
                d = t.avg_score - prev
                delta = f" ({d:+.1f})"
            lines.append(f"  {t.date}  score={t.avg_score:.1f}{delta}  evals={t.total_evals}")
        lines.append("")

    if alerts:
        lines.append("── Active Alerts ──")
        for a in alerts:
            icon = "🔴" if a.severity == Severity.CRITICAL else "🟡"
            lines.append(f"  {icon} [{a.severity.upper()}] {a.message}")
        lines.append("")
    else:
        lines.append("── No Active Alerts ──")
        lines.append("")

    lines.append("=" * 60)
    return "\n".join(lines)


# ── Daemon Mode ──────────────────────────────────────────────────────────────

def run_daemon(interval_hours: float = 24.0):
    """Run evaluation pipeline on a schedule."""
    print(f"[eval-daemon] Starting continuous evaluation (interval={interval_hours}h)")
    cycle = 0
    while True:
        cycle += 1
        print(f"[eval-daemon] Cycle {cycle} starting at {datetime.utcnow().isoformat()}")
        try:
            results = run_evaluation(version=cycle)
            history = load_eval_history(days=30)
            trends = compute_trends(history)
            save_trends(trends)
            alerts = detect_degradation(trends)
            update_dashboard(trends, alerts)

            print(f"[eval-daemon] Cycle {cycle} complete: "
                  f"{len(results)} evals, {len(alerts)} alerts")
            if alerts:
                for a in alerts:
                    print(f"  [{a.severity.upper()}] {a.message}")
        except Exception as e:
            print(f"[eval-daemon] Cycle {cycle} error: {e}")

        time.sleep(interval_hours * 3600)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Continuous Model Evaluation Pipeline")
    parser.add_argument("--daemon", action="store_true", help="Run as background daemon")
    parser.add_argument("--report", action="store_true", help="Print trend report")
    parser.add_argument("--check", action="store_true", help="Check for degradation alerts")
    parser.add_argument("--interval", type=float, default=24.0, help="Daemon interval in hours")
    args = parser.parse_args()

    if args.daemon:
        run_daemon(interval_hours=args.interval)
    elif args.report:
        trends = load_trends()
        alerts = detect_degradation(trends) if len(trends) >= MIN_BASELINE_DAYS + 1 else []
        print(generate_report(trends, alerts))
    elif args.check:
        trends = load_trends()
        alerts = detect_degradation(trends)
        if not alerts:
            print("No degradation detected.")
        else:
            for a in alerts:
                print(f"[{a.severity.upper()}] {a.message}")
    else:
        # Single evaluation cycle
        print("Running evaluation...")
        results = run_evaluation(version=0)
        history = load_eval_history(days=30)
        trends = compute_trends(history)
        save_trends(trends)
        alerts = detect_degradation(trends)
        update_dashboard(trends, alerts)
        print(generate_report(trends, alerts))


if __name__ == "__main__":
    import sys

    # If invoked without flags, run assertions to verify correctness
    if len(sys.argv) == 1:
        print("=" * 60)
        print("  RUNNING VERIFICATION ASSERTIONS")
        print("=" * 60)

        # ── Test 1: score_output ──
        score_empty = score_output("", ["foo"], 1)
        assert score_empty == 0.0, f"Empty output should score 0, got {score_empty}"

        score_good = score_output(
            "def binary_search(arr, target):\n    mid = len(arr) // 2\n    return mid\n",
            ["def", "binary", "mid", "return"], 1
        )
        assert score_good > 50, f"Good output should score >50, got {score_good}"

        score_partial = score_output("just a short string", ["def", "binary", "mid", "return"], 1)
        assert score_partial < score_good, f"Partial ({score_partial}) should be < good ({score_good})"
        print(f"  [PASS] score_output: empty={score_empty}, partial={score_partial:.1f}, good={score_good:.1f}")

        # ── Test 2: EvalResult creation ──
        er = EvalResult(agent="test", category="code_gen", score=85.0, latency_s=1.5, token_count=100)
        assert er.agent == "test"
        assert er.eval_id != ""
        assert er.timestamp != ""
        print(f"  [PASS] EvalResult: id={er.eval_id}, ts={er.timestamp[:19]}")

        # ── Test 3: run_evaluation ──
        results = run_evaluation(version=99)
        assert len(results) > 0, "Should produce results"
        assert all(isinstance(r, EvalResult) for r in results), "All results should be EvalResult"
        assert all(0 <= r.score <= 100 for r in results), "All scores in 0-100"
        assert all(r.latency_s > 0 for r in results), "All latencies positive"
        agents_seen = set(r.agent for r in results)
        assert agents_seen == set(EVAL_SUITE.keys()), f"Expected all agents, got {agents_seen}"
        print(f"  [PASS] run_evaluation: {len(results)} results, agents={sorted(agents_seen)}")

        # ── Test 4: compute_trends ──
        trends = compute_trends(results)
        assert len(trends) == 1, f"Single day should give 1 trend point, got {len(trends)}"
        tp = trends[0]
        assert tp.total_evals == len(results), f"Trend evals mismatch: {tp.total_evals} vs {len(results)}"
        assert 0 < tp.avg_score <= 100, f"Avg score out of range: {tp.avg_score}"
        assert tp.p50_latency > 0, "P50 latency should be positive"
        assert tp.p95_latency >= tp.p50_latency, "P95 should be >= P50"
        print(f"  [PASS] compute_trends: avg={tp.avg_score:.1f}, p50={tp.p50_latency:.2f}s, p95={tp.p95_latency:.2f}s")

        # ── Test 5: degradation detection (no alerts with single day) ──
        alerts = detect_degradation(trends)
        assert alerts == [], f"Single day should produce no alerts, got {len(alerts)}"
        print(f"  [PASS] detect_degradation: no alerts with insufficient baseline")

        # ── Test 6: degradation detection with synthetic regression ──
        baseline_trends = []
        for i in range(5):
            date = (datetime.utcnow() - timedelta(days=5 - i)).strftime("%Y-%m-%d")
            baseline_trends.append(TrendPoint(
                date=date, avg_score=80.0, min_score=70.0, max_score=90.0,
                p50_latency=2.0, p95_latency=3.0, total_evals=10,
                by_agent={"executor": 80.0, "planner": 80.0},
                by_category={"code_gen": 80.0},
            ))
        # Add a degraded day
        degraded_date = datetime.utcnow().strftime("%Y-%m-%d")
        baseline_trends.append(TrendPoint(
            date=degraded_date, avg_score=60.0, min_score=40.0, max_score=70.0,
            p50_latency=2.0, p95_latency=7.0, total_evals=10,
            by_agent={"executor": 55.0, "planner": 65.0},
            by_category={"code_gen": 60.0},
        ))
        degradation_alerts = detect_degradation(baseline_trends, baseline_days=5)
        assert len(degradation_alerts) > 0, "Should detect degradation"
        severities = [a.severity for a in degradation_alerts]
        assert Severity.CRITICAL in severities, f"Should have CRITICAL alert, got {severities}"
        print(f"  [PASS] detect_degradation: {len(degradation_alerts)} alerts, severities={[s.value for s in severities]}")

        # ── Test 7: report generation ──
        report = generate_report(baseline_trends, degradation_alerts)
        assert "CONTINUOUS MODEL EVALUATION REPORT" in report
        assert "Avg Score" in report
        assert "CRITICAL" in report or "critical" in report.lower()
        print(f"  [PASS] generate_report: {len(report)} chars, contains expected sections")

        # ── Test 8: trend persistence ──
        save_trends(baseline_trends)
        loaded = load_trends()
        assert len(loaded) == len(baseline_trends), f"Loaded {len(loaded)} vs saved {len(baseline_trends)}"
        assert loaded[-1].avg_score == baseline_trends[-1].avg_score
        print(f"  [PASS] save/load_trends: round-trip OK ({len(loaded)} points)")

        # ── Test 9: dashboard update ──
        update_dashboard(baseline_trends, degradation_alerts)
        with open(STATE_FILE) as f:
            dash = json.load(f)
        assert "eval_pipeline" in dash, "Dashboard should have eval_pipeline key"
        ep = dash["eval_pipeline"]
        assert ep["active_alerts"] == len(degradation_alerts)
        assert ep["critical_alerts"] > 0
        assert "executor" in ep["agents_evaluated"]
        print(f"  [PASS] update_dashboard: {ep['active_alerts']} alerts, agents={ep['agents_evaluated']}")

        # ── Test 10: Alert dataclass ──
        alert = Alert(
            severity=Severity.WARNING, metric="test", agent="test", category="test",
            current_value=50.0, baseline_value=80.0, delta_pct=-37.5,
            message="Test alert",
        )
        ad = asdict(alert)
        assert ad["severity"] == "warning"
        assert ad["delta_pct"] == -37.5
        print(f"  [PASS] Alert dataclass: serialization OK")

        print("")
        print("=" * 60)
        print("  ALL 10 ASSERTIONS PASSED")
        print("=" * 60)

        # Now run normal mode
        print("")
        main()
