"""
Agent performance profiler & self-optimizer.

Profiles agent execution, identifies slow paths and low-quality agents,
and auto-generates optimization recommendations that can be applied to
routing weights, prompt tuning, token budgets, and concurrency limits.

Usage:
    from orchestrator.performance_profiler import AgentProfiler
    profiler = AgentProfiler(stats_dir="state")
    profiler.record_execution("executor", task_id="t-001", elapsed_s=12.3,
                              quality=72, tokens_used=350, category="bug_fix")
    report = profiler.analyze()
    optimizations = profiler.optimize()
    budget_actions = profiler.optimize_budgets()  # token budget reallocation
    concurrency_actions = profiler.optimize_concurrency()  # concurrency tuning
    summary = profiler.run_full_optimization()  # all optimizations + bottlenecks

Integration with existing runtime:
    Wraps agent run() calls via profile_agent_call() or @profile_execution
    decorator to automatically capture timing, quality, and token data per
    invocation.
"""

import cProfile
import functools
import io
import json
import math
import os
import pstats
import statistics
import time
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Any, Callable, Optional


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Trend detection
TREND_WINDOW = 20           # samples per half-window
TREND_THRESHOLD = 0.10      # 10% change triggers trend

# Token budget bounds
MIN_TOKEN_BUDGET = 200
MAX_TOKEN_BUDGET = 5000
BUDGET_STEP = 100

# Concurrency bounds
MIN_CONCURRENCY = 1
MAX_CONCURRENCY = 4

# Routing weight bounds
MIN_ROUTING_WEIGHT = 0.1
MAX_ROUTING_WEIGHT = 2.0


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

@dataclass
class ExecutionRecord:
    """Single agent execution record."""
    agent: str
    task_id: str
    elapsed_s: float
    quality: float
    tokens_used: int
    category: str
    timestamp: float = field(default_factory=time.time)
    success: bool = True
    error: Optional[str] = None


@dataclass
class AgentProfile:
    """Aggregated performance profile for one agent."""
    agent: str
    total_executions: int = 0
    success_count: int = 0
    failure_count: int = 0
    total_tokens: int = 0
    elapsed_times: list = field(default_factory=list)
    quality_scores: list = field(default_factory=list)
    categories: dict = field(default_factory=lambda: defaultdict(int))

    @property
    def success_rate(self) -> float:
        return self.success_count / max(self.total_executions, 1)

    @property
    def avg_quality(self) -> float:
        return statistics.mean(self.quality_scores) if self.quality_scores else 0.0

    @property
    def median_elapsed(self) -> float:
        return statistics.median(self.elapsed_times) if self.elapsed_times else 0.0

    @property
    def p95_elapsed(self) -> float:
        if not self.elapsed_times:
            return 0.0
        sorted_t = sorted(self.elapsed_times)
        idx = int(math.ceil(0.95 * len(sorted_t))) - 1
        return sorted_t[max(idx, 0)]

    @property
    def p99_elapsed(self) -> float:
        if not self.elapsed_times:
            return 0.0
        sorted_t = sorted(self.elapsed_times)
        idx = int(math.ceil(0.99 * len(sorted_t))) - 1
        return sorted_t[max(idx, 0)]

    @property
    def tokens_per_task(self) -> float:
        return self.total_tokens / max(self.total_executions, 1)

    @property
    def quality_per_token(self) -> float:
        """Quality points earned per token spent — higher is better."""
        return self.avg_quality / max(self.tokens_per_task, 1) * 100

    @property
    def trend(self) -> str:
        """Detect improving/degrading/stable trend from recent vs older samples."""
        if len(self.quality_scores) < TREND_WINDOW * 2:
            return "stable"
        recent = self.quality_scores[-TREND_WINDOW:]
        older = self.quality_scores[-TREND_WINDOW * 2:-TREND_WINDOW]
        recent_avg = statistics.mean(recent)
        older_avg = statistics.mean(older)
        if older_avg == 0:
            return "stable"
        delta = (recent_avg - older_avg) / max(older_avg, 1)
        if delta > TREND_THRESHOLD:
            return "improving"
        elif delta < -TREND_THRESHOLD:
            return "degrading"
        return "stable"

    def to_dict(self) -> dict:
        return {
            "agent": self.agent,
            "total_executions": self.total_executions,
            "success_rate": round(self.success_rate, 4),
            "avg_quality": round(self.avg_quality, 2),
            "median_elapsed_s": round(self.median_elapsed, 3),
            "p95_elapsed_s": round(self.p95_elapsed, 3),
            "p99_elapsed_s": round(self.p99_elapsed, 3),
            "tokens_per_task": round(self.tokens_per_task, 1),
            "quality_per_token": round(self.quality_per_token, 4),
            "trend": self.trend,
            "top_categories": dict(sorted(
                self.categories.items(), key=lambda x: -x[1]
            )[:5]),
        }


@dataclass
class SlowPath:
    """A detected slow execution path."""
    agent: str
    category: str
    median_elapsed_s: float
    p95_elapsed_s: float
    sample_count: int
    severity: str  # "critical", "warning", "info"


@dataclass
class Optimization:
    """A recommended optimization action."""
    agent: str
    action: str        # "reduce_routing_weight", "increase_routing_weight",
                       # "flag_for_prompt_tuning", "reassign_category", "retire",
                       # "budget_increase", "budget_decrease",
                       # "concurrency_increase", "concurrency_decrease"
    reason: str
    priority: int      # 1 = highest
    params: dict = field(default_factory=dict)


# ---------------------------------------------------------------------------
# Core profiler
# ---------------------------------------------------------------------------

class AgentProfiler:
    """Profiles agent performance and generates self-optimization actions."""

    # Thresholds (configurable)
    SLOW_P95_THRESHOLD_S = 30.0       # p95 latency above this = slow
    SLOW_MEDIAN_THRESHOLD_S = 15.0    # median latency above this = warning
    LOW_QUALITY_THRESHOLD = 40.0      # avg quality below this = flag
    LOW_SUCCESS_THRESHOLD = 0.25      # success rate below this = flag
    HIGH_TOKEN_THRESHOLD = 800        # tokens/task above this = wasteful
    MIN_SAMPLES = 3                   # need at least this many samples

    def __init__(self, stats_dir: str = "state", profile_log: str = None):
        self.stats_dir = stats_dir
        self.profile_log = profile_log or os.path.join(stats_dir, "agent_profile_log.jsonl")
        self._records: list[ExecutionRecord] = []
        self._profiles: dict[str, AgentProfile] = {}
        self._load_existing_records()

    # ------------------------------------------------------------------
    # Record collection
    # ------------------------------------------------------------------

    def record_execution(self, agent: str, task_id: str, elapsed_s: float,
                         quality: float, tokens_used: int, category: str,
                         success: bool = True, error: str = None) -> ExecutionRecord:
        """Record a single agent execution."""
        rec = ExecutionRecord(
            agent=agent, task_id=task_id, elapsed_s=elapsed_s,
            quality=quality, tokens_used=tokens_used, category=category,
            success=success, error=error,
        )
        self._records.append(rec)
        self._update_profile(rec)
        self._persist_record(rec)
        return rec

    def profile_agent_call(self, agent_name: str, run_fn: Callable,
                           task: dict) -> dict:
        """Wrap an agent run() call with profiling.

        Returns the agent result dict, augmented with profiling metadata.
        """
        task_id = task.get("id", f"anon-{int(time.time())}")
        category = task.get("category", "unknown")

        start = time.monotonic()
        error_msg = None
        success = True
        result = {}

        try:
            result = run_fn(task)
        except Exception as e:
            error_msg = str(e)
            success = False
            result = {"status": "failed", "output": error_msg, "quality": 0,
                      "quality_score": 0, "tokens_used": 0}

        elapsed = time.monotonic() - start
        quality = float(result.get("quality", result.get("quality_score", 0)))
        tokens = int(result.get("tokens_used", 0))

        self.record_execution(
            agent=agent_name, task_id=str(task_id), elapsed_s=elapsed,
            quality=quality, tokens_used=tokens, category=category,
            success=success, error=error_msg,
        )

        result["_profiling"] = {
            "elapsed_s": round(elapsed, 4),
            "agent": agent_name,
            "category": category,
        }
        return result

    # ------------------------------------------------------------------
    # Analysis
    # ------------------------------------------------------------------

    def analyze(self) -> dict[str, dict]:
        """Return per-agent performance profiles as dicts."""
        return {name: prof.to_dict() for name, prof in self._profiles.items()}

    def detect_slow_paths(self) -> list[SlowPath]:
        """Identify agent+category combos with high latency."""
        # Group records by (agent, category)
        groups: dict[tuple, list[float]] = defaultdict(list)
        for rec in self._records:
            groups[(rec.agent, rec.category)].append(rec.elapsed_s)

        slow_paths = []
        for (agent, cat), times in groups.items():
            if len(times) < self.MIN_SAMPLES:
                continue
            med = statistics.median(times)
            sorted_t = sorted(times)
            p95_idx = int(math.ceil(0.95 * len(sorted_t))) - 1
            p95 = sorted_t[max(p95_idx, 0)]

            if p95 >= self.SLOW_P95_THRESHOLD_S:
                severity = "critical"
            elif med >= self.SLOW_MEDIAN_THRESHOLD_S:
                severity = "warning"
            else:
                continue

            slow_paths.append(SlowPath(
                agent=agent, category=cat, median_elapsed_s=round(med, 3),
                p95_elapsed_s=round(p95, 3), sample_count=len(times),
                severity=severity,
            ))

        slow_paths.sort(key=lambda s: (-{"critical": 2, "warning": 1}[s.severity],
                                        -s.p95_elapsed_s))
        return slow_paths

    def rank_agents(self) -> list[dict]:
        """Rank agents by composite score (quality × success_rate / latency)."""
        rankings = []
        for name, prof in self._profiles.items():
            if prof.total_executions < self.MIN_SAMPLES:
                continue
            # Composite: high quality + high success + low latency = good
            latency_factor = 1.0 / max(prof.median_elapsed, 0.01)
            composite = (prof.avg_quality * prof.success_rate * latency_factor)
            rankings.append({
                "agent": name,
                "composite_score": round(composite, 4),
                "avg_quality": round(prof.avg_quality, 2),
                "success_rate": round(prof.success_rate, 4),
                "median_elapsed_s": round(prof.median_elapsed, 3),
                "total_executions": prof.total_executions,
            })
        rankings.sort(key=lambda r: -r["composite_score"])
        return rankings

    # ------------------------------------------------------------------
    # Self-optimization
    # ------------------------------------------------------------------

    def optimize(self) -> list[Optimization]:
        """Generate optimization recommendations based on profiling data."""
        opts: list[Optimization] = []

        for name, prof in self._profiles.items():
            if prof.total_executions < self.MIN_SAMPLES:
                continue

            # 1) Low success rate → reduce routing weight or retire
            if prof.success_rate < self.LOW_SUCCESS_THRESHOLD:
                if prof.success_rate < 0.05:
                    opts.append(Optimization(
                        agent=name, action="retire",
                        reason=f"Success rate {prof.success_rate:.1%} is critically low",
                        priority=1,
                        params={"current_success_rate": prof.success_rate},
                    ))
                else:
                    opts.append(Optimization(
                        agent=name, action="reduce_routing_weight",
                        reason=f"Success rate {prof.success_rate:.1%} below threshold {self.LOW_SUCCESS_THRESHOLD:.0%}",
                        priority=2,
                        params={"suggested_weight": max(0.1, prof.success_rate)},
                    ))

            # 2) Low quality → flag for prompt tuning
            if prof.avg_quality < self.LOW_QUALITY_THRESHOLD:
                opts.append(Optimization(
                    agent=name, action="flag_for_prompt_tuning",
                    reason=f"Avg quality {prof.avg_quality:.1f} below threshold {self.LOW_QUALITY_THRESHOLD}",
                    priority=2,
                    params={"avg_quality": prof.avg_quality,
                            "worst_categories": self._worst_categories(name)},
                ))

            # 3) High token usage → optimize prompt or switch model
            if prof.tokens_per_task > self.HIGH_TOKEN_THRESHOLD:
                opts.append(Optimization(
                    agent=name, action="reduce_token_usage",
                    reason=f"Tokens/task {prof.tokens_per_task:.0f} exceeds {self.HIGH_TOKEN_THRESHOLD}",
                    priority=3,
                    params={"tokens_per_task": prof.tokens_per_task,
                            "quality_per_token": prof.quality_per_token},
                ))

            # 4) High quality + high success → increase routing weight
            if prof.success_rate > 0.8 and prof.avg_quality > 70:
                opts.append(Optimization(
                    agent=name, action="increase_routing_weight",
                    reason=f"Strong performer: {prof.success_rate:.0%} success, {prof.avg_quality:.0f} quality",
                    priority=4,
                    params={"suggested_weight": min(1.0, prof.success_rate * 1.2)},
                ))

        # 5) Category reassignment — find categories where an agent underperforms
        #    and another agent excels
        reassignments = self._find_reassignments()
        opts.extend(reassignments)

        # Sort by priority
        opts.sort(key=lambda o: o.priority)
        return opts

    def apply_optimizations(self, opts: list[Optimization],
                            registry_path: str = "registry/agents.json") -> dict:
        """Apply optimization actions to the agent registry.

        Returns a summary of what was changed.
        """
        changes = {"applied": [], "skipped": []}

        if not os.path.exists(registry_path):
            return {"applied": [], "skipped": [o.action for o in opts],
                    "reason": "registry not found"}

        with open(registry_path, "r") as f:
            registry = json.load(f)

        for opt in opts:
            agent_entry = registry.get(opt.agent)
            if not agent_entry:
                changes["skipped"].append({
                    "agent": opt.agent, "action": opt.action,
                    "reason": "agent not in registry"})
                continue

            if opt.action == "reduce_routing_weight":
                old_weight = agent_entry.get("routing_weight", 1.0)
                new_weight = opt.params.get("suggested_weight", old_weight * 0.5)
                agent_entry["routing_weight"] = round(new_weight, 3)
                changes["applied"].append({
                    "agent": opt.agent, "action": opt.action,
                    "old": old_weight, "new": new_weight})

            elif opt.action == "increase_routing_weight":
                old_weight = agent_entry.get("routing_weight", 1.0)
                new_weight = opt.params.get("suggested_weight", min(old_weight * 1.2, 1.0))
                agent_entry["routing_weight"] = round(new_weight, 3)
                changes["applied"].append({
                    "agent": opt.agent, "action": opt.action,
                    "old": old_weight, "new": new_weight})

            elif opt.action == "flag_for_prompt_tuning":
                agent_entry.setdefault("flags", [])
                if "needs_prompt_tuning" not in agent_entry["flags"]:
                    agent_entry["flags"].append("needs_prompt_tuning")
                agent_entry["prompt_tuning_reason"] = opt.reason
                changes["applied"].append({
                    "agent": opt.agent, "action": opt.action,
                    "reason": opt.reason})

            elif opt.action == "retire":
                agent_entry["retired"] = True
                agent_entry["retire_reason"] = opt.reason
                changes["applied"].append({
                    "agent": opt.agent, "action": opt.action})

            elif opt.action == "reduce_token_usage":
                agent_entry.setdefault("flags", [])
                if "high_token_usage" not in agent_entry["flags"]:
                    agent_entry["flags"].append("high_token_usage")
                changes["applied"].append({
                    "agent": opt.agent, "action": opt.action,
                    "tokens_per_task": opt.params.get("tokens_per_task")})

            elif opt.action == "reassign_category":
                changes["applied"].append({
                    "agent": opt.agent, "action": opt.action,
                    "params": opt.params})
            else:
                changes["skipped"].append({
                    "agent": opt.agent, "action": opt.action,
                    "reason": "unknown action"})

        with open(registry_path, "w") as f:
            json.dump(registry, f, indent=2)

        return changes

    # ------------------------------------------------------------------
    # cProfile integration
    # ------------------------------------------------------------------

    def cprofile_agent_call(self, agent_name: str, run_fn: Callable,
                            task: dict, top_n: int = 10) -> tuple[dict, list[dict]]:
        """Run an agent call under cProfile and return (result, bottlenecks).

        Useful for deep profiling during development/benchmarking.
        """
        prof = cProfile.Profile()
        task_id = task.get("id", f"anon-{int(time.time())}")
        category = task.get("category", "unknown")

        start = time.monotonic()
        try:
            prof.enable()
            result = run_fn(task)
            prof.disable()
        except Exception as e:
            prof.disable()
            result = {"status": "failed", "output": str(e), "quality": 0,
                      "quality_score": 0, "tokens_used": 0}

        elapsed = time.monotonic() - start

        # Extract top bottlenecks
        stream = io.StringIO()
        ps = pstats.Stats(prof, stream=stream)
        ps.sort_stats("cumulative")
        ps.print_stats(top_n)
        raw_stats = stream.getvalue()

        bottlenecks = []
        for func_key, (cc, nc, tt, ct, callers) in ps.stats.items():
            bottlenecks.append({
                "file": func_key[0],
                "line": func_key[1],
                "function": func_key[2],
                "cumulative_s": round(ct, 6),
                "total_s": round(tt, 6),
                "calls": nc,
            })
        bottlenecks.sort(key=lambda b: -b["cumulative_s"])
        bottlenecks = bottlenecks[:top_n]

        quality = float(result.get("quality", result.get("quality_score", 0)))
        tokens = int(result.get("tokens_used", 0))
        self.record_execution(
            agent=agent_name, task_id=str(task_id), elapsed_s=elapsed,
            quality=quality, tokens_used=tokens, category=category,
        )

        return result, bottlenecks

    # ------------------------------------------------------------------
    # Snapshot export
    # ------------------------------------------------------------------

    def export_snapshot(self, path: str = None) -> str:
        """Export full profiling snapshot to JSON file."""
        path = path or os.path.join(self.stats_dir, "performance_snapshot.json")
        snapshot = {
            "timestamp": time.time(),
            "profiles": self.analyze(),
            "rankings": self.rank_agents(),
            "slow_paths": [asdict(sp) for sp in self.detect_slow_paths()],
            "optimizations": [asdict(o) for o in self.optimize()],
            "total_records": len(self._records),
        }
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        with open(path, "w") as f:
            json.dump(snapshot, f, indent=2)
        return path

    # ------------------------------------------------------------------
    # Token budget self-optimization
    # ------------------------------------------------------------------

    def optimize_budgets(self, budgets: Optional[dict] = None) -> list[Optimization]:
        """Reallocate token budgets based on per-agent efficiency.

        Args:
            budgets: dict of agent_name→current_budget. If None, loads from
                     state/agent_budgets.json.

        Returns:
            List of budget optimization actions (applied in-place to budgets dict).
        """
        if budgets is None:
            budgets_path = os.path.join(self.stats_dir, "agent_budgets.json")
            if os.path.exists(budgets_path):
                with open(budgets_path) as f:
                    budgets = json.load(f)
            else:
                budgets = {}

        actions = []
        for name, prof in self._profiles.items():
            if prof.total_executions < self.MIN_SAMPLES:
                continue
            current = budgets.get(name, 1000)

            if prof.success_rate >= 0.8 and prof.quality_per_token > 5.0:
                new_budget = min(current + BUDGET_STEP, MAX_TOKEN_BUDGET)
                if new_budget != current:
                    actions.append(Optimization(
                        agent=name, action="budget_increase",
                        reason=f"High efficiency ({prof.quality_per_token:.2f} q/tok, "
                               f"{prof.success_rate:.0%} success) — reward with more tokens",
                        priority=4,
                        params={"old_budget": current, "new_budget": new_budget},
                    ))
                    budgets[name] = new_budget

            elif prof.success_rate < 0.25:
                new_budget = max(current - BUDGET_STEP * 2, MIN_TOKEN_BUDGET)
                if new_budget != current:
                    actions.append(Optimization(
                        agent=name, action="budget_decrease",
                        reason=f"Low success ({prof.success_rate:.0%}) — reduce token waste",
                        priority=2,
                        params={"old_budget": current, "new_budget": new_budget},
                    ))
                    budgets[name] = new_budget

            elif prof.success_rate < 0.5 and prof.quality_per_token < 3.0:
                new_budget = max(current - BUDGET_STEP, MIN_TOKEN_BUDGET)
                if new_budget != current:
                    actions.append(Optimization(
                        agent=name, action="budget_decrease",
                        reason=f"Below-average efficiency ({prof.quality_per_token:.2f} q/tok)",
                        priority=3,
                        params={"old_budget": current, "new_budget": new_budget},
                    ))
                    budgets[name] = new_budget

        # Persist updated budgets
        if actions:
            budgets_path = os.path.join(self.stats_dir, "agent_budgets.json")
            os.makedirs(os.path.dirname(budgets_path) or ".", exist_ok=True)
            with open(budgets_path, "w") as f:
                json.dump(budgets, f, indent=2)

        return actions

    # ------------------------------------------------------------------
    # Concurrency tuning
    # ------------------------------------------------------------------

    def optimize_concurrency(self, limits: Optional[dict] = None) -> list[Optimization]:
        """Tune max concurrency per agent based on throughput and latency.

        Args:
            limits: dict of agent_name→current_max_concurrent. Defaults to 1 each.

        Returns:
            List of concurrency optimization actions.
        """
        if limits is None:
            limits = {}

        actions = []
        for name, prof in self._profiles.items():
            if prof.total_executions < self.MIN_SAMPLES * 3:
                continue

            old_limit = limits.get(name, 1)

            if prof.p95_elapsed < 5.0 and prof.success_rate > 0.8:
                new_limit = min(old_limit + 1, MAX_CONCURRENCY)
            elif prof.p95_elapsed > self.SLOW_P95_THRESHOLD_S or prof.success_rate < 0.25:
                new_limit = max(old_limit - 1, MIN_CONCURRENCY)
            else:
                new_limit = old_limit

            if new_limit != old_limit:
                actions.append(Optimization(
                    agent=name, action="concurrency_increase" if new_limit > old_limit else "concurrency_decrease",
                    reason=f"p95={prof.p95_elapsed:.1f}s, success={prof.success_rate:.0%}",
                    priority=3,
                    params={"old_limit": old_limit, "new_limit": new_limit},
                ))
                limits[name] = new_limit

        return actions

    # ------------------------------------------------------------------
    # Full optimization pass
    # ------------------------------------------------------------------

    def run_full_optimization(self, budgets: Optional[dict] = None,
                              concurrency_limits: Optional[dict] = None) -> dict:
        """Run all optimization passes and return a combined summary.

        Returns dict with keys: routing_actions, budget_actions,
        concurrency_actions, slow_paths, rankings, total_actions.
        """
        routing_actions = self.optimize()
        budget_actions = self.optimize_budgets(budgets)
        concurrency_actions = self.optimize_concurrency(concurrency_limits)
        slow_paths = self.detect_slow_paths()
        rankings = self.rank_agents()

        return {
            "routing_actions": [asdict(a) for a in routing_actions],
            "budget_actions": [asdict(a) for a in budget_actions],
            "concurrency_actions": [asdict(a) for a in concurrency_actions],
            "slow_paths": [asdict(s) for s in slow_paths],
            "rankings": rankings,
            "total_actions": len(routing_actions) + len(budget_actions) + len(concurrency_actions),
            "total_slow_paths": len(slow_paths),
        }

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    def _update_profile(self, rec: ExecutionRecord):
        if rec.agent not in self._profiles:
            self._profiles[rec.agent] = AgentProfile(agent=rec.agent)
        prof = self._profiles[rec.agent]
        prof.total_executions += 1
        if rec.success:
            prof.success_count += 1
        else:
            prof.failure_count += 1
        prof.total_tokens += rec.tokens_used
        prof.elapsed_times.append(rec.elapsed_s)
        prof.quality_scores.append(rec.quality)
        prof.categories[rec.category] += 1

    def _persist_record(self, rec: ExecutionRecord):
        os.makedirs(os.path.dirname(self.profile_log) or ".", exist_ok=True)
        with open(self.profile_log, "a") as f:
            f.write(json.dumps(asdict(rec)) + "\n")

    def _load_existing_records(self):
        """Load previously persisted records from the profile log."""
        if not os.path.exists(self.profile_log):
            return
        with open(self.profile_log, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    rec = ExecutionRecord(**data)
                    self._records.append(rec)
                    self._update_profile(rec)
                except (json.JSONDecodeError, TypeError):
                    continue

    def _worst_categories(self, agent_name: str, top_n: int = 3) -> list[dict]:
        """Find categories where this agent performs worst."""
        cat_scores: dict[str, list[float]] = defaultdict(list)
        for rec in self._records:
            if rec.agent == agent_name:
                cat_scores[rec.category].append(rec.quality)

        worst = []
        for cat, scores in cat_scores.items():
            if len(scores) >= 2:
                worst.append({"category": cat, "avg_quality": round(statistics.mean(scores), 2),
                              "count": len(scores)})
        worst.sort(key=lambda w: w["avg_quality"])
        return worst[:top_n]

    def _find_reassignments(self) -> list[Optimization]:
        """Find categories that should be reassigned from underperformer to better agent."""
        cat_agent_quality: dict[str, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
        for rec in self._records:
            cat_agent_quality[rec.category][rec.agent].append(rec.quality)

        reassignments = []
        for cat, agents in cat_agent_quality.items():
            if len(agents) < 2:
                continue

            agent_avgs = {}
            for ag, scores in agents.items():
                if len(scores) >= self.MIN_SAMPLES:
                    agent_avgs[ag] = statistics.mean(scores)

            if len(agent_avgs) < 2:
                continue

            best_agent = max(agent_avgs, key=agent_avgs.get)
            worst_agent = min(agent_avgs, key=agent_avgs.get)
            gap = agent_avgs[best_agent] - agent_avgs[worst_agent]

            if gap >= 15:  # meaningful quality gap
                reassignments.append(Optimization(
                    agent=worst_agent, action="reassign_category",
                    reason=(f"Category '{cat}': {worst_agent} avg {agent_avgs[worst_agent]:.0f} "
                            f"vs {best_agent} avg {agent_avgs[best_agent]:.0f} (gap={gap:.0f})"),
                    priority=2,
                    params={"category": cat, "from_agent": worst_agent,
                            "to_agent": best_agent, "quality_gap": round(gap, 2)},
                ))

        return reassignments


# ---------------------------------------------------------------------------
# Convenience: wrap any agent's run function with profiling
# ---------------------------------------------------------------------------

def make_profiled_runner(profiler: AgentProfiler, agent_name: str,
                         run_fn: Callable) -> Callable:
    """Return a wrapped version of run_fn that auto-profiles every call."""
    def profiled_run(task: dict) -> dict:
        return profiler.profile_agent_call(agent_name, run_fn, task)
    return profiled_run


def profile_execution(profiler: AgentProfiler, agent_name: str):
    """Decorator that auto-records execution samples for a function.

    Usage:
        @profile_execution(profiler, "executor")
        def run(task):
            ...
            return {"status": "completed", "quality": 85, "tokens_used": 200}
    """
    def decorator(func):
        @functools.wraps(func)
        def wrapper(task, *args, **kwargs):
            return profiler.profile_agent_call(agent_name, lambda t: func(t, *args, **kwargs), task)
        return wrapper
    return decorator


# ---------------------------------------------------------------------------
# __main__: self-test with assertions
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    import tempfile
    import shutil

    tmp_dir = tempfile.mkdtemp(prefix="profiler_test_")
    try:
        # ---------------------------------------------------------------
        # 1. Create profiler with temp directory
        # ---------------------------------------------------------------
        profiler = AgentProfiler(stats_dir=tmp_dir)
        assert len(profiler._records) == 0, "Should start empty"
        assert len(profiler._profiles) == 0, "Should start with no profiles"

        # ---------------------------------------------------------------
        # 2. Record executions for multiple agents
        # ---------------------------------------------------------------

        # executor: many tasks, low success, low quality
        for i in range(20):
            profiler.record_execution(
                agent="executor", task_id=f"t-exec-{i}",
                elapsed_s=8.0 + i * 0.5, quality=30 + (i % 5),
                tokens_used=400 + i * 10, category="bug_fix",
                success=(i % 5 != 0),  # 80% success
            )

        # architect: few tasks, high success, high quality
        for i in range(10):
            profiler.record_execution(
                agent="architect", task_id=f"t-arch-{i}",
                elapsed_s=3.0 + i * 0.2, quality=85 + (i % 10),
                tokens_used=200 + i * 5, category="arch",
                success=True,
            )

        # debugger: slow, medium quality
        for i in range(8):
            profiler.record_execution(
                agent="debugger", task_id=f"t-dbg-{i}",
                elapsed_s=20.0 + i * 5, quality=50 + (i % 8),
                tokens_used=600 + i * 50, category="debug",
                success=(i % 3 != 0),
            )

        # researcher: high token usage, decent quality
        for i in range(6):
            profiler.record_execution(
                agent="researcher", task_id=f"t-res-{i}",
                elapsed_s=5.0 + i, quality=65 + i,
                tokens_used=900 + i * 100, category="research",
                success=True,
            )

        # bad_agent: terrible at everything
        for i in range(5):
            profiler.record_execution(
                agent="bad_agent", task_id=f"t-bad-{i}",
                elapsed_s=25.0, quality=10 + i,
                tokens_used=500, category="code_gen",
                success=(i == 4),  # 20% success
            )

        total_records = 20 + 10 + 8 + 6 + 5
        assert len(profiler._records) == total_records, \
            f"Expected {total_records} records, got {len(profiler._records)}"

        # ---------------------------------------------------------------
        # 3. Verify per-agent profiles
        # ---------------------------------------------------------------
        profiles = profiler.analyze()
        assert "executor" in profiles
        assert "architect" in profiles
        assert "debugger" in profiles
        assert "researcher" in profiles
        assert "bad_agent" in profiles

        # executor: 20 tasks, 16 successes (i%5!=0 for i=0..19 → 4 failures)
        exec_prof = profiles["executor"]
        assert exec_prof["total_executions"] == 20
        assert exec_prof["success_rate"] == 0.8
        assert 30 <= exec_prof["avg_quality"] <= 35, \
            f"executor avg_quality {exec_prof['avg_quality']} unexpected"

        # architect: 10 tasks, all success, high quality
        arch_prof = profiles["architect"]
        assert arch_prof["total_executions"] == 10
        assert arch_prof["success_rate"] == 1.0
        assert arch_prof["avg_quality"] >= 85

        # bad_agent: 5 tasks, 1 success
        bad_prof = profiles["bad_agent"]
        assert bad_prof["success_rate"] == 0.2
        assert bad_prof["avg_quality"] < 20

        print("[PASS] Agent profiles computed correctly")

        # ---------------------------------------------------------------
        # 4. Detect slow paths
        # ---------------------------------------------------------------
        slow = profiler.detect_slow_paths()
        slow_agents = {s.agent for s in slow}
        # debugger has p95 > 30s (times range from 20 to 55)
        assert "debugger" in slow_agents, \
            f"Expected debugger in slow paths, got {slow_agents}"
        # bad_agent has constant 25s < 30s threshold so shouldn't be critical
        # but median=25 > SLOW_MEDIAN_THRESHOLD=15, so it should be warning
        assert "bad_agent" in slow_agents, \
            f"Expected bad_agent as slow warning, got {slow_agents}"

        dbg_slow = [s for s in slow if s.agent == "debugger"][0]
        assert dbg_slow.severity == "critical", \
            f"debugger should be critical, got {dbg_slow.severity}"

        print("[PASS] Slow path detection works")

        # ---------------------------------------------------------------
        # 5. Rank agents
        # ---------------------------------------------------------------
        rankings = profiler.rank_agents()
        assert len(rankings) >= 4, f"Expected at least 4 ranked agents, got {len(rankings)}"

        # architect should rank highest (high quality, 100% success, low latency)
        assert rankings[0]["agent"] == "architect", \
            f"Expected architect at top, got {rankings[0]['agent']}"
        # bad_agent should rank lowest
        assert rankings[-1]["agent"] == "bad_agent", \
            f"Expected bad_agent at bottom, got {rankings[-1]['agent']}"

        print("[PASS] Agent ranking works correctly")

        # ---------------------------------------------------------------
        # 6. Generate optimizations
        # ---------------------------------------------------------------
        opts = profiler.optimize()
        assert len(opts) > 0, "Should generate at least one optimization"

        opt_actions = [(o.agent, o.action) for o in opts]

        # bad_agent should be flagged for retirement or reduced weight
        bad_opts = [o for o in opts if o.agent == "bad_agent"]
        assert len(bad_opts) > 0, "bad_agent should have optimization recommendations"
        bad_actions = {o.action for o in bad_opts}
        assert "retire" in bad_actions or "reduce_routing_weight" in bad_actions, \
            f"bad_agent should be retired or reduced, got {bad_actions}"

        # bad_agent has avg quality ~12 → should be flagged for prompt tuning
        assert "flag_for_prompt_tuning" in bad_actions, \
            f"bad_agent should be flagged for prompt tuning, got {bad_actions}"

        # researcher has tokens_per_task > 800 → should flag high token usage
        res_opts = [o for o in opts if o.agent == "researcher"]
        res_actions = {o.action for o in res_opts}
        assert "reduce_token_usage" in res_actions, \
            f"researcher should have reduce_token_usage, got {res_actions}"

        # architect should get increase_routing_weight
        arch_opts = [o for o in opts if o.agent == "architect"]
        arch_actions = {o.action for o in arch_opts}
        assert "increase_routing_weight" in arch_actions, \
            f"architect should get increase_routing_weight, got {arch_actions}"

        # optimizations should be sorted by priority
        for i in range(len(opts) - 1):
            assert opts[i].priority <= opts[i + 1].priority, \
                f"Optimizations not sorted by priority at index {i}"

        print("[PASS] Optimization generation works correctly")

        # ---------------------------------------------------------------
        # 7. Test profiled runner wrapper
        # ---------------------------------------------------------------
        call_count = [0]

        def mock_agent_run(task):
            call_count[0] += 1
            time.sleep(0.01)  # simulate work
            return {"status": "completed", "output": "done", "quality": 77,
                    "quality_score": 77, "tokens_used": 150}

        profiled_fn = make_profiled_runner(profiler, "mock_agent", mock_agent_run)
        result = profiled_fn({"id": "wrap-1", "category": "test", "title": "test"})
        assert call_count[0] == 1, "Wrapped function should be called once"
        assert result["status"] == "completed"
        assert "_profiling" in result
        assert result["_profiling"]["agent"] == "mock_agent"
        assert result["_profiling"]["elapsed_s"] >= 0.01

        # Verify mock_agent was recorded
        assert "mock_agent" in profiler._profiles
        assert profiler._profiles["mock_agent"].total_executions == 1

        print("[PASS] Profiled runner wrapper works")

        # ---------------------------------------------------------------
        # 8. Test cProfile integration
        # ---------------------------------------------------------------
        def slow_mock_run(task):
            total = sum(range(10000))  # some CPU work
            return {"status": "completed", "output": str(total),
                    "quality": 60, "quality_score": 60, "tokens_used": 100}

        result2, bottlenecks = profiler.cprofile_agent_call(
            "cprof_agent", slow_mock_run,
            {"id": "cp-1", "category": "test"}, top_n=5
        )
        assert result2["status"] == "completed"
        assert len(bottlenecks) > 0, "Should detect at least one bottleneck"
        assert "function" in bottlenecks[0], "Bottleneck should have function key"
        assert "cumulative_s" in bottlenecks[0], "Bottleneck should have cumulative_s"

        print("[PASS] cProfile integration works")

        # ---------------------------------------------------------------
        # 9. Test snapshot export
        # ---------------------------------------------------------------
        snap_path = profiler.export_snapshot()
        assert os.path.exists(snap_path), f"Snapshot file should exist at {snap_path}"
        with open(snap_path) as f:
            snap = json.load(f)
        assert "profiles" in snap
        assert "rankings" in snap
        assert "slow_paths" in snap
        assert "optimizations" in snap
        assert snap["total_records"] == total_records + 2  # +mock +cprof

        print("[PASS] Snapshot export works")

        # ---------------------------------------------------------------
        # 10. Test persistence and reload
        # ---------------------------------------------------------------
        log_path = profiler.profile_log
        assert os.path.exists(log_path), "Profile log should exist"

        # Create new profiler from same directory — should reload records
        profiler2 = AgentProfiler(stats_dir=tmp_dir)
        assert len(profiler2._records) == len(profiler._records), \
            f"Reloaded {len(profiler2._records)} records, expected {len(profiler._records)}"

        profiles2 = profiler2.analyze()
        assert profiles2["executor"]["total_executions"] == 20
        assert profiles2["architect"]["success_rate"] == 1.0

        print("[PASS] Persistence and reload works")

        # ---------------------------------------------------------------
        # 11. Test apply_optimizations with mock registry
        # ---------------------------------------------------------------
        mock_registry = {
            "bad_agent": {"name": "bad_agent", "routing_weight": 1.0},
            "architect": {"name": "architect", "routing_weight": 0.8},
            "researcher": {"name": "researcher", "routing_weight": 1.0},
        }
        reg_path = os.path.join(tmp_dir, "agents.json")
        with open(reg_path, "w") as f:
            json.dump(mock_registry, f)

        changes = profiler.apply_optimizations(opts, registry_path=reg_path)
        assert len(changes["applied"]) > 0, "Should apply at least one optimization"

        # Reload and verify
        with open(reg_path) as f:
            updated_reg = json.load(f)

        # bad_agent should be retired or have reduced routing weight
        bad_retired = updated_reg["bad_agent"].get("retired", False)
        bad_weight_reduced = updated_reg["bad_agent"].get("routing_weight", 1.0) < 1.0
        bad_flagged = "needs_prompt_tuning" in updated_reg["bad_agent"].get("flags", [])
        assert bad_retired or bad_weight_reduced or bad_flagged, \
            "bad_agent should be retired, weight-reduced, or flagged"

        # architect routing weight should increase
        assert updated_reg["architect"]["routing_weight"] >= 0.8, \
            "architect weight should not decrease"

        print("[PASS] Apply optimizations works")

        # ---------------------------------------------------------------
        # 12. Test category reassignment detection
        # ---------------------------------------------------------------
        profiler3 = AgentProfiler(
            stats_dir=tmp_dir,
            profile_log=os.path.join(tmp_dir, "reassign_test.jsonl")
        )
        # Agent A is bad at code_gen, Agent B is good
        for i in range(5):
            profiler3.record_execution("agent_a", f"ra-{i}", 5.0, 25, 200, "code_gen")
            profiler3.record_execution("agent_b", f"rb-{i}", 5.0, 80, 200, "code_gen")

        opts3 = profiler3.optimize()
        reassign_opts = [o for o in opts3 if o.action == "reassign_category"]
        assert len(reassign_opts) > 0, "Should detect category reassignment opportunity"
        assert reassign_opts[0].params["from_agent"] == "agent_a"
        assert reassign_opts[0].params["to_agent"] == "agent_b"
        assert reassign_opts[0].params["quality_gap"] >= 50

        print("[PASS] Category reassignment detection works")

        # ---------------------------------------------------------------
        # 13. Edge cases
        # ---------------------------------------------------------------
        # Empty profiler
        empty_profiler = AgentProfiler(
            stats_dir=tmp_dir,
            profile_log=os.path.join(tmp_dir, "empty_test.jsonl")
        )
        assert empty_profiler.analyze() == {}
        assert empty_profiler.detect_slow_paths() == []
        assert empty_profiler.rank_agents() == []
        assert empty_profiler.optimize() == []

        # Agent with too few samples (below MIN_SAMPLES)
        empty_profiler.record_execution("solo", "s-1", 5.0, 50, 100, "test")
        assert empty_profiler.rank_agents() == [], \
            "Should not rank agents with < MIN_SAMPLES executions"
        assert empty_profiler.optimize() == [], \
            "Should not optimize agents with < MIN_SAMPLES executions"

        print("[PASS] Edge cases handled correctly")

        # ---------------------------------------------------------------
        # Summary
        # ---------------------------------------------------------------
        print()
        print("=" * 60)
        print("ALL 13 TEST GROUPS PASSED")
        print("=" * 60)
        print()
        print("Profiler capabilities verified:")
        print("  - Execution recording and aggregation")
        print("  - Per-agent profile computation")
        print("  - Slow path detection (critical/warning)")
        print("  - Agent ranking by composite score")
        print("  - Self-optimization recommendations")
        print("  - Profiled runner wrapper")
        print("  - cProfile deep profiling integration")
        print("  - JSON snapshot export")
        print("  - Persistence and reload from disk")
        print("  - Registry optimization application")
        print("  - Category reassignment detection")
        print("  - Edge case handling")

    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
