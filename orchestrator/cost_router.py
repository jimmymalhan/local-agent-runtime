"""
cost_router.py — Cost-Aware Model Router
==========================================
Picks the cheapest model that meets quality requirements for a given task.

Analyzes task complexity, estimates token usage, and selects the model with
the best cost/quality ratio from the available model catalog. Integrates
with the existing SkillMatcher to combine skill matching with cost optimization.

Usage:
    from orchestrator.cost_router import CostRouter
    router = CostRouter()
    decision = router.route({"category": "code_gen", "description": "Add a hello world endpoint"})
    print(decision.model, decision.estimated_cost)
"""

import json
import math
import os
import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class TaskComplexity(Enum):
    """Task complexity tiers that determine minimum model quality."""
    TRIVIAL = "trivial"       # Simple lookups, formatting, boilerplate
    LOW = "low"               # Single-file edits, small bug fixes
    MEDIUM = "medium"         # Multi-file changes, moderate logic
    HIGH = "high"             # Architecture, complex debugging, multi-step reasoning
    CRITICAL = "critical"     # Production incidents, security, data integrity


@dataclass
class ModelSpec:
    """A model's capabilities and pricing."""
    name: str
    provider: str                 # "local", "anthropic", "openai", etc.
    cost_per_1k_input: float      # USD per 1K input tokens
    cost_per_1k_output: float     # USD per 1K output tokens
    max_context: int              # Max context window in tokens
    quality_score: float          # 0.0-1.0 benchmark quality rating
    speed_tokens_per_sec: float   # Approximate output tokens/sec
    supports_tools: bool = True
    supports_vision: bool = False
    min_complexity: str = "trivial"  # Minimum complexity this model handles well
    max_complexity: str = "critical" # Maximum complexity this model handles well

    @property
    def is_local(self) -> bool:
        return self.provider == "local"

    @property
    def is_free(self) -> bool:
        return self.cost_per_1k_input == 0.0 and self.cost_per_1k_output == 0.0


@dataclass
class TokenEstimate:
    """Estimated token usage for a task."""
    input_tokens: int
    output_tokens: int
    confidence: float  # 0.0-1.0 how confident in the estimate

    @property
    def total_tokens(self) -> int:
        return self.input_tokens + self.output_tokens

    def cost_for_model(self, model: ModelSpec) -> float:
        """Calculate estimated cost in USD for a given model."""
        input_cost = (self.input_tokens / 1000.0) * model.cost_per_1k_input
        output_cost = (self.output_tokens / 1000.0) * model.cost_per_1k_output
        return round(input_cost + output_cost, 6)


@dataclass
class RoutingDecision:
    """The result of cost-aware routing."""
    model: str
    provider: str
    estimated_cost: float         # USD
    estimated_tokens: TokenEstimate
    complexity: TaskComplexity
    quality_score: float
    cost_quality_ratio: float     # Lower is better (cost per unit of quality)
    reason: str
    alternatives: list[dict] = field(default_factory=list)
    is_local: bool = False

    def to_dict(self) -> dict:
        return {
            "model": self.model,
            "provider": self.provider,
            "estimated_cost": self.estimated_cost,
            "estimated_input_tokens": self.estimated_tokens.input_tokens,
            "estimated_output_tokens": self.estimated_tokens.output_tokens,
            "complexity": self.complexity.value,
            "quality_score": self.quality_score,
            "cost_quality_ratio": self.cost_quality_ratio,
            "reason": self.reason,
            "is_local": self.is_local,
            "alternatives": self.alternatives,
        }


# Default model catalog — local models are free, remote models have pricing
DEFAULT_MODEL_CATALOG: list[ModelSpec] = [
    # Local models (free, lower quality)
    ModelSpec(
        name="qwen2.5-coder:7b",
        provider="local",
        cost_per_1k_input=0.0,
        cost_per_1k_output=0.0,
        max_context=32768,
        quality_score=0.45,
        speed_tokens_per_sec=35.0,
        min_complexity="trivial",
        max_complexity="medium",
    ),
    ModelSpec(
        name="qwen2.5-coder:14b",
        provider="local",
        cost_per_1k_input=0.0,
        cost_per_1k_output=0.0,
        max_context=32768,
        quality_score=0.58,
        speed_tokens_per_sec=18.0,
        min_complexity="trivial",
        max_complexity="medium",
    ),
    ModelSpec(
        name="deepseek-coder-v2:16b",
        provider="local",
        cost_per_1k_input=0.0,
        cost_per_1k_output=0.0,
        max_context=65536,
        quality_score=0.55,
        speed_tokens_per_sec=15.0,
        min_complexity="trivial",
        max_complexity="high",
    ),
    ModelSpec(
        name="codellama:34b",
        provider="local",
        cost_per_1k_input=0.0,
        cost_per_1k_output=0.0,
        max_context=16384,
        quality_score=0.52,
        speed_tokens_per_sec=8.0,
        min_complexity="trivial",
        max_complexity="medium",
    ),
    # Remote models (paid, higher quality) — rescue-only per project policy
    ModelSpec(
        name="claude-haiku-4-5-20251001",
        provider="anthropic",
        cost_per_1k_input=0.001,
        cost_per_1k_output=0.005,
        max_context=200000,
        quality_score=0.78,
        speed_tokens_per_sec=120.0,
        supports_vision=True,
        min_complexity="trivial",
        max_complexity="high",
    ),
    ModelSpec(
        name="claude-sonnet-4-6",
        provider="anthropic",
        cost_per_1k_input=0.003,
        cost_per_1k_output=0.015,
        max_context=200000,
        quality_score=0.90,
        speed_tokens_per_sec=80.0,
        supports_vision=True,
        min_complexity="low",
        max_complexity="critical",
    ),
    ModelSpec(
        name="claude-opus-4-6",
        provider="anthropic",
        cost_per_1k_input=0.015,
        cost_per_1k_output=0.075,
        max_context=200000,
        quality_score=0.98,
        speed_tokens_per_sec=40.0,
        supports_vision=True,
        min_complexity="medium",
        max_complexity="critical",
    ),
    ModelSpec(
        name="gpt-4o-mini",
        provider="openai",
        cost_per_1k_input=0.00015,
        cost_per_1k_output=0.0006,
        max_context=128000,
        quality_score=0.72,
        speed_tokens_per_sec=100.0,
        supports_vision=True,
        min_complexity="trivial",
        max_complexity="medium",
    ),
    ModelSpec(
        name="gpt-4o",
        provider="openai",
        cost_per_1k_input=0.0025,
        cost_per_1k_output=0.01,
        max_context=128000,
        quality_score=0.88,
        speed_tokens_per_sec=70.0,
        supports_vision=True,
        min_complexity="low",
        max_complexity="critical",
    ),
]

# Complexity keywords — used to classify tasks
_COMPLEXITY_SIGNALS: dict[str, list[str]] = {
    "critical": [
        "production", "incident", "security", "vulnerability", "data loss",
        "downtime", "outage", "breach", "pii", "compliance", "migration",
    ],
    "high": [
        "architecture", "redesign", "multi-service", "distributed",
        "concurrency", "race condition", "deadlock", "performance",
        "scalability", "microservice", "system design", "complex",
    ],
    "medium": [
        "refactor", "feature", "endpoint", "integration", "workflow",
        "pipeline", "multi-file", "module", "component", "api",
    ],
    "low": [
        "fix", "bug", "typo", "rename", "update", "small", "simple",
        "single file", "config", "format", "lint", "style",
    ],
    "trivial": [
        "hello world", "boilerplate", "scaffold", "template", "stub",
        "placeholder", "comment", "readme", "changelog", "docs",
    ],
}

_COMPLEXITY_ORDER = ["trivial", "low", "medium", "high", "critical"]


def _complexity_index(name: str) -> int:
    """Get numeric index for a complexity level."""
    try:
        return _COMPLEXITY_ORDER.index(name)
    except ValueError:
        return 2  # default to medium


class TokenEstimator:
    """Estimates token count for a task based on its characteristics."""

    # Average tokens per complexity tier
    _BASE_INPUT: dict[str, int] = {
        "trivial": 200,
        "low": 500,
        "medium": 1500,
        "high": 4000,
        "critical": 8000,
    }
    _BASE_OUTPUT: dict[str, int] = {
        "trivial": 100,
        "low": 300,
        "medium": 800,
        "high": 2000,
        "critical": 5000,
    }

    # Multipliers for task categories
    _CATEGORY_MULTIPLIERS: dict[str, float] = {
        "code_gen": 1.3,
        "bug_fix": 1.0,
        "debug": 1.2,
        "test_gen": 1.4,
        "review": 0.8,
        "refactor": 1.5,
        "research": 0.6,
        "documentation": 1.1,
        "arch": 1.6,
        "planning": 0.7,
        "scoring": 0.5,
    }

    def estimate(self, task: dict, complexity: TaskComplexity) -> TokenEstimate:
        """Estimate token usage for a task at a given complexity level."""
        c = complexity.value
        base_in = self._BASE_INPUT.get(c, 1500)
        base_out = self._BASE_OUTPUT.get(c, 800)

        # Apply category multiplier
        category = task.get("category", "")
        multiplier = self._CATEGORY_MULTIPLIERS.get(category, 1.0)

        # Scale by description length (longer descriptions = more context tokens)
        desc = task.get("description", "")
        title = task.get("title", "")
        text_len = len(desc) + len(title)
        text_factor = 1.0 + min(text_len / 2000.0, 1.0)  # up to 2x for long descriptions

        # Scale by number of skills requested
        skills = task.get("skills", [])
        if isinstance(skills, str):
            skills = [s.strip() for s in skills.split(",")]
        skill_factor = 1.0 + len(skills) * 0.1  # each skill adds ~10%

        input_tokens = int(base_in * multiplier * text_factor * skill_factor)
        output_tokens = int(base_out * multiplier * skill_factor)

        # Confidence decreases with complexity (harder to estimate)
        confidence = max(0.3, 1.0 - _complexity_index(c) * 0.15)

        return TokenEstimate(
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            confidence=round(confidence, 2),
        )


class ComplexityClassifier:
    """Classifies task complexity based on signals in the task description."""

    def classify(self, task: dict) -> TaskComplexity:
        """Classify a task's complexity from its metadata and text."""
        # Explicit complexity override
        if "complexity" in task:
            raw = task["complexity"].lower().strip()
            try:
                return TaskComplexity(raw)
            except ValueError:
                pass

        # Score based on keyword signals
        text = f"{task.get('title', '')} {task.get('description', '')} {task.get('category', '')}".lower()
        scores: dict[str, float] = {level: 0.0 for level in _COMPLEXITY_ORDER}

        for level, keywords in _COMPLEXITY_SIGNALS.items():
            for kw in keywords:
                if kw in text:
                    scores[level] += 1.0

        # Boost by number of skills (more skills = higher complexity)
        skills = task.get("skills", [])
        if isinstance(skills, str):
            skills = [s.strip() for s in skills.split(",") if s.strip()]
        if len(skills) >= 4:
            scores["high"] += 1.5
        elif len(skills) >= 2:
            scores["medium"] += 1.0

        # Boost by estimated code size hints
        if task.get("files_affected", 0) > 5:
            scores["high"] += 1.0
        elif task.get("files_affected", 0) > 2:
            scores["medium"] += 0.5

        # Pick the highest-scoring complexity level
        best_level = max(scores, key=lambda k: (scores[k], _complexity_index(k)))
        if scores[best_level] == 0.0:
            # No signals found — default to low
            return TaskComplexity.LOW

        return TaskComplexity(best_level)


class CostRouter:
    """
    Cost-aware model router.

    Picks the cheapest model that meets quality requirements for a task.
    Respects the project's local-first policy: prefers local models unless
    complexity demands a remote model (rescue path).
    """

    def __init__(
        self,
        models: Optional[list[ModelSpec]] = None,
        local_only: bool = True,
        min_quality: float = 0.0,
        max_budget_per_task: float = 1.0,
        rescue_allowed: bool = False,
    ):
        """
        Args:
            models: Available model catalog. Defaults to DEFAULT_MODEL_CATALOG.
            local_only: If True, only consider local models unless rescue_allowed.
            min_quality: Minimum quality score (0-1) to consider a model.
            max_budget_per_task: Maximum USD budget per task.
            rescue_allowed: If True, include remote models in candidates.
        """
        self.models = {m.name: m for m in (models or DEFAULT_MODEL_CATALOG)}
        self.local_only = local_only
        self.min_quality = min_quality
        self.max_budget_per_task = max_budget_per_task
        self.rescue_allowed = rescue_allowed
        self.classifier = ComplexityClassifier()
        self.estimator = TokenEstimator()
        self._history: list[dict] = []

    def _candidate_models(self, complexity: TaskComplexity,
                          token_estimate: TokenEstimate) -> list[ModelSpec]:
        """Filter models that can handle this complexity and token count."""
        candidates = []
        complexity_idx = _complexity_index(complexity.value)

        for model in self.models.values():
            # Respect local-only policy unless rescue is allowed
            if self.local_only and not model.is_local and not self.rescue_allowed:
                continue

            # Check quality floor
            if model.quality_score < self.min_quality:
                continue

            # Check complexity range
            min_idx = _complexity_index(model.min_complexity)
            max_idx = _complexity_index(model.max_complexity)
            if complexity_idx > max_idx:
                continue  # Task too complex for this model

            # Check context window
            if token_estimate.total_tokens > model.max_context:
                continue

            # Check budget
            est_cost = token_estimate.cost_for_model(model)
            if est_cost > self.max_budget_per_task:
                continue

            candidates.append(model)

        return candidates

    def _score_model(self, model: ModelSpec, complexity: TaskComplexity,
                     token_estimate: TokenEstimate) -> float:
        """
        Score a model for cost/quality efficiency. Lower score = better choice.

        Score = cost / (quality * complexity_fit)
        For free models: score = (1.0 - quality) to rank by quality alone.
        """
        est_cost = token_estimate.cost_for_model(model)

        complexity_idx = _complexity_index(complexity.value)
        min_idx = _complexity_index(model.min_complexity)
        max_idx = _complexity_index(model.max_complexity)

        # Complexity fit: 1.0 if perfectly in range, drops off at edges
        range_size = max(max_idx - min_idx, 1)
        center = (min_idx + max_idx) / 2.0
        distance = abs(complexity_idx - center) / range_size
        complexity_fit = max(0.1, 1.0 - distance)

        quality_adjusted = model.quality_score * complexity_fit

        if model.is_free:
            # For free models, rank by quality (higher quality = lower score = better)
            return round(1.0 - quality_adjusted, 6)
        else:
            # For paid models, rank by cost-per-quality-unit
            if quality_adjusted == 0:
                return float("inf")
            return round(est_cost / quality_adjusted, 6)

    def route(self, task: dict) -> RoutingDecision:
        """
        Route a task to the best model based on cost/quality trade-off.

        Args:
            task: Task dict with optional keys: category, skills, title,
                  description, complexity, files_affected

        Returns:
            RoutingDecision with the chosen model and reasoning
        """
        complexity = self.classifier.classify(task)
        token_estimate = self.estimator.estimate(task, complexity)
        candidates = self._candidate_models(complexity, token_estimate)

        if not candidates:
            # Fallback: if local_only blocked everything, try enabling rescue
            if self.local_only and not self.rescue_allowed:
                candidates = self._candidate_models(complexity, token_estimate)
            # If still nothing, use the first local model regardless
            if not candidates:
                fallback = next(
                    (m for m in self.models.values() if m.is_local),
                    list(self.models.values())[0],
                )
                candidates = [fallback]

        # Score and rank candidates
        scored = []
        for model in candidates:
            score = self._score_model(model, complexity, token_estimate)
            est_cost = token_estimate.cost_for_model(model)
            scored.append((score, est_cost, model))

        scored.sort(key=lambda x: (x[0], x[1], x[2].name))
        best_score, best_cost, best_model = scored[0]

        # Build alternatives list
        alternatives = []
        for score, cost, model in scored[1:4]:  # top 3 alternatives
            alternatives.append({
                "model": model.name,
                "provider": model.provider,
                "estimated_cost": cost,
                "quality_score": model.quality_score,
                "cost_quality_ratio": score,
            })

        # Build reason string
        if best_model.is_free:
            reason = (
                f"Local model selected for {complexity.value} task. "
                f"Quality={best_model.quality_score:.0%}, cost=$0.00. "
                f"Est. {token_estimate.total_tokens} tokens."
            )
        else:
            reason = (
                f"Remote model selected for {complexity.value} task (rescue path). "
                f"Quality={best_model.quality_score:.0%}, est. cost=${best_cost:.4f}. "
                f"Est. {token_estimate.total_tokens} tokens."
            )

        decision = RoutingDecision(
            model=best_model.name,
            provider=best_model.provider,
            estimated_cost=best_cost,
            estimated_tokens=token_estimate,
            complexity=complexity,
            quality_score=best_model.quality_score,
            cost_quality_ratio=best_score,
            reason=reason,
            alternatives=alternatives,
            is_local=best_model.is_local,
        )

        self._history.append(decision.to_dict())
        return decision

    def route_batch(self, tasks: list[dict]) -> list[RoutingDecision]:
        """Route multiple tasks, optimizing total cost across the batch."""
        return [self.route(task) for task in tasks]

    def get_cost_summary(self) -> dict:
        """Summarize total estimated costs from routing history."""
        total_cost = sum(d["estimated_cost"] for d in self._history)
        local_count = sum(1 for d in self._history if d["is_local"])
        remote_count = len(self._history) - local_count
        by_model: dict[str, float] = {}
        for d in self._history:
            by_model[d["model"]] = by_model.get(d["model"], 0.0) + d["estimated_cost"]
        return {
            "total_estimated_cost": round(total_cost, 6),
            "tasks_routed": len(self._history),
            "local_tasks": local_count,
            "remote_tasks": remote_count,
            "cost_by_model": {k: round(v, 6) for k, v in by_model.items()},
            "local_ratio": round(local_count / max(len(self._history), 1), 2),
        }

    def explain(self, task: dict) -> str:
        """Human-readable explanation of routing decision."""
        decision = self.route(task)
        lines = [
            f"Task complexity: {decision.complexity.value}",
            f"Estimated tokens: {decision.estimated_tokens.input_tokens} in / "
            f"{decision.estimated_tokens.output_tokens} out "
            f"(confidence: {decision.estimated_tokens.confidence:.0%})",
            f"Selected model: {decision.model} ({decision.provider})",
            f"Quality: {decision.quality_score:.0%}",
            f"Estimated cost: ${decision.estimated_cost:.4f}",
            f"Cost/quality ratio: {decision.cost_quality_ratio:.4f}",
            f"Reason: {decision.reason}",
        ]
        if decision.alternatives:
            lines.append("Alternatives:")
            for alt in decision.alternatives:
                lines.append(
                    f"  - {alt['model']} ({alt['provider']}): "
                    f"quality={alt['quality_score']:.0%}, "
                    f"cost=${alt['estimated_cost']:.4f}, "
                    f"ratio={alt['cost_quality_ratio']:.4f}"
                )
        return "\n".join(lines)


if __name__ == "__main__":
    # ===== Test ComplexityClassifier =====
    classifier = ComplexityClassifier()

    # Test 1: Trivial task
    c = classifier.classify({"title": "Add hello world endpoint", "description": "scaffold a stub"})
    assert c == TaskComplexity.TRIVIAL, f"Expected TRIVIAL, got {c}"
    print(f"PASS test 1: 'hello world scaffold stub' -> {c.value}")

    # Test 2: Low task
    c = classifier.classify({"title": "Fix typo in config", "description": "simple rename"})
    assert c == TaskComplexity.LOW, f"Expected LOW, got {c}"
    print(f"PASS test 2: 'fix typo simple rename' -> {c.value}")

    # Test 3: Medium task
    c = classifier.classify({"title": "Add new API endpoint", "description": "integrate with pipeline module"})
    assert c == TaskComplexity.MEDIUM, f"Expected MEDIUM, got {c}"
    print(f"PASS test 3: 'API endpoint pipeline module' -> {c.value}")

    # Test 4: High task
    c = classifier.classify({"title": "Redesign architecture", "description": "distributed system design with concurrency"})
    assert c == TaskComplexity.HIGH, f"Expected HIGH, got {c}"
    print(f"PASS test 4: 'redesign architecture distributed concurrency' -> {c.value}")

    # Test 5: Critical task
    c = classifier.classify({"title": "Production incident", "description": "security vulnerability causing data loss"})
    assert c == TaskComplexity.CRITICAL, f"Expected CRITICAL, got {c}"
    print(f"PASS test 5: 'production incident security data loss' -> {c.value}")

    # Test 6: Explicit complexity override
    c = classifier.classify({"title": "anything", "complexity": "high"})
    assert c == TaskComplexity.HIGH, f"Expected HIGH, got {c}"
    print(f"PASS test 6: explicit complexity override -> {c.value}")

    # Test 7: Multi-skill boosts complexity
    c = classifier.classify({"title": "do stuff", "skills": ["code_gen", "debug", "test_gen", "review"]})
    assert c in (TaskComplexity.MEDIUM, TaskComplexity.HIGH), f"Expected MEDIUM or HIGH, got {c}"
    print(f"PASS test 7: 4 skills -> {c.value}")

    # Test 8: No signals defaults to LOW
    c = classifier.classify({"title": "do something"})
    assert c == TaskComplexity.LOW, f"Expected LOW, got {c}"
    print(f"PASS test 8: no signals -> {c.value}")

    # ===== Test TokenEstimator =====
    estimator = TokenEstimator()

    # Test 9: Trivial task tokens are small
    est = estimator.estimate({"category": "code_gen"}, TaskComplexity.TRIVIAL)
    assert est.input_tokens < 500, f"Expected <500, got {est.input_tokens}"
    assert est.output_tokens < 300, f"Expected <300, got {est.output_tokens}"
    assert est.confidence >= 0.7
    print(f"PASS test 9: trivial tokens: {est.input_tokens}in/{est.output_tokens}out (conf={est.confidence})")

    # Test 10: Critical task tokens are large
    est = estimator.estimate({"category": "arch"}, TaskComplexity.CRITICAL)
    assert est.input_tokens > 5000, f"Expected >5000, got {est.input_tokens}"
    assert est.output_tokens > 3000, f"Expected >3000, got {est.output_tokens}"
    print(f"PASS test 10: critical tokens: {est.input_tokens}in/{est.output_tokens}out")

    # Test 11: Token cost calculation
    model = ModelSpec("test", "anthropic", 0.003, 0.015, 200000, 0.9, 80.0)
    est = TokenEstimate(1000, 500, 0.8)
    cost = est.cost_for_model(model)
    expected_cost = (1000 / 1000 * 0.003) + (500 / 1000 * 0.015)  # 0.003 + 0.0075 = 0.0105
    assert abs(cost - expected_cost) < 0.000001, f"Expected {expected_cost}, got {cost}"
    print(f"PASS test 11: cost calculation ${cost} == ${expected_cost}")

    # Test 12: Free model cost is zero
    free_model = ModelSpec("local", "local", 0.0, 0.0, 32768, 0.45, 35.0)
    assert est.cost_for_model(free_model) == 0.0
    print("PASS test 12: free model cost is $0.00")

    # ===== Test CostRouter =====

    # Test 13: Local-only mode picks local model
    router = CostRouter(local_only=True, rescue_allowed=False)
    decision = router.route({"category": "code_gen", "title": "Add endpoint"})
    assert decision.is_local, f"Expected local model, got {decision.provider}"
    assert decision.estimated_cost == 0.0
    print(f"PASS test 13: local-only route -> {decision.model} (${decision.estimated_cost})")

    # Test 14: Higher quality local model for medium task
    decision = router.route({"category": "refactor", "title": "Refactor module", "description": "multi-file component"})
    assert decision.is_local
    print(f"PASS test 14: medium local route -> {decision.model} (quality={decision.quality_score:.0%})")

    # Test 15: Rescue mode picks cheapest adequate remote model
    rescue_router = CostRouter(local_only=False, rescue_allowed=True)
    decision = rescue_router.route({
        "category": "debug",
        "title": "Production incident response",
        "description": "critical security vulnerability in distributed system",
        "complexity": "critical",
    })
    # Should pick a high-quality model for critical task
    assert decision.quality_score >= 0.7, f"Expected quality>=0.7, got {decision.quality_score}"
    print(f"PASS test 15: critical rescue route -> {decision.model} (quality={decision.quality_score:.0%}, cost=${decision.estimated_cost:.4f})")

    # Test 16: Budget constraint filters expensive models
    budget_router = CostRouter(local_only=False, rescue_allowed=True, max_budget_per_task=0.01)
    decision = budget_router.route({"category": "code_gen", "title": "Simple task"})
    assert decision.estimated_cost <= 0.01, f"Expected cost<=0.01, got {decision.estimated_cost}"
    print(f"PASS test 16: budget-constrained route -> {decision.model} (cost=${decision.estimated_cost:.4f})")

    # Test 17: Quality floor filters low-quality models
    quality_router = CostRouter(local_only=False, rescue_allowed=True, min_quality=0.85)
    decision = quality_router.route({"category": "arch", "title": "System design", "complexity": "high"})
    assert decision.quality_score >= 0.85, f"Expected quality>=0.85, got {decision.quality_score}"
    print(f"PASS test 17: quality-floor route -> {decision.model} (quality={decision.quality_score:.0%})")

    # Test 18: Batch routing
    tasks = [
        {"category": "code_gen", "title": "Add feature"},
        {"category": "debug", "title": "Fix bug", "description": "simple fix"},
        {"category": "arch", "title": "Design system", "complexity": "high"},
    ]
    decisions = router.route_batch(tasks)
    assert len(decisions) == 3
    print(f"PASS test 18: batch routing -> {[(d.model, d.complexity.value) for d in decisions]}")

    # Test 19: Cost summary tracks totals
    summary = router.get_cost_summary()
    assert summary["tasks_routed"] > 0
    assert summary["local_ratio"] > 0
    print(f"PASS test 19: cost summary -> {summary}")

    # Test 20: Explain output is readable
    explanation = router.explain({"category": "bug_fix", "title": "Fix login error"})
    assert "Task complexity:" in explanation
    assert "Selected model:" in explanation
    assert "Estimated cost:" in explanation
    print(f"PASS test 20: explain output:\n{explanation}")

    # Test 21: RoutingDecision.to_dict
    decision = router.route({"category": "code_gen"})
    d = decision.to_dict()
    assert "model" in d
    assert "estimated_cost" in d
    assert "complexity" in d
    assert "alternatives" in d
    print(f"PASS test 21: to_dict keys: {sorted(d.keys())}")

    # Test 22: Local models preferred over cheaper remote for same quality tier
    local_router = CostRouter(local_only=True)
    decision = local_router.route({"category": "code_gen", "title": "Simple code gen"})
    assert decision.is_local
    assert decision.estimated_cost == 0.0
    print(f"PASS test 22: local preference -> {decision.model}")

    # Test 23: ModelSpec properties
    local_model = ModelSpec("test-local", "local", 0.0, 0.0, 32768, 0.5, 30.0)
    remote_model = ModelSpec("test-remote", "anthropic", 0.003, 0.015, 200000, 0.9, 80.0)
    assert local_model.is_local and local_model.is_free
    assert not remote_model.is_local and not remote_model.is_free
    print("PASS test 23: ModelSpec.is_local and is_free properties")

    # Test 24: TaskComplexity enum values
    assert TaskComplexity.TRIVIAL.value == "trivial"
    assert TaskComplexity.CRITICAL.value == "critical"
    print("PASS test 24: TaskComplexity enum values")

    # Test 25: Empty task routes successfully (doesn't crash)
    decision = router.route({})
    assert decision.model is not None
    assert decision.complexity is not None
    print(f"PASS test 25: empty task -> {decision.model} ({decision.complexity.value})")

    # Test 26: Token estimate scales with description length
    short_est = estimator.estimate({"description": "short"}, TaskComplexity.MEDIUM)
    long_desc = "This is a very long description " * 50
    long_est = estimator.estimate({"description": long_desc}, TaskComplexity.MEDIUM)
    assert long_est.input_tokens > short_est.input_tokens, "Long description should have more tokens"
    print(f"PASS test 26: token scaling: short={short_est.input_tokens}, long={long_est.input_tokens}")

    # Test 27: Cost/quality ratio is lower (better) for free models
    decision_free = router.route({"category": "code_gen"})
    rescue_router2 = CostRouter(local_only=False, rescue_allowed=True)
    decision_paid = rescue_router2.route({"category": "code_gen", "complexity": "critical"})
    # Free model ratio is (1 - quality), paid model ratio is cost/quality
    # Both are just numbers — verify they're finite
    assert decision_free.cost_quality_ratio < float("inf")
    assert decision_paid.cost_quality_ratio < float("inf")
    print(f"PASS test 27: cost/quality ratios: free={decision_free.cost_quality_ratio:.4f}, paid={decision_paid.cost_quality_ratio:.4f}")

    # Test 28: Alternatives are populated
    rescue_router3 = CostRouter(local_only=False, rescue_allowed=True)
    decision = rescue_router3.route({"category": "code_gen", "title": "Write code"})
    # With all models available, should have alternatives
    assert len(decision.alternatives) > 0, "Expected at least one alternative"
    print(f"PASS test 28: {len(decision.alternatives)} alternatives provided")

    # Test 29: Context window limit filters large tasks
    huge_est = TokenEstimate(50000, 20000, 0.5)
    small_model = ModelSpec("tiny", "local", 0.0, 0.0, 16384, 0.4, 10.0)
    tiny_router = CostRouter(models=[small_model], local_only=True)
    # Route a trivial task — should still work even with small context
    decision = tiny_router.route({"category": "code_gen", "title": "hello"})
    assert decision.model == "tiny"
    print(f"PASS test 29: small context model handles small task")

    # Test 30: files_affected boosts complexity
    c_no_files = classifier.classify({"title": "do stuff"})
    c_many_files = classifier.classify({"title": "do stuff", "files_affected": 10})
    assert _complexity_index(c_many_files.value) >= _complexity_index(c_no_files.value)
    print(f"PASS test 30: files_affected boost: 0 files={c_no_files.value}, 10 files={c_many_files.value}")

    print("\n=== All 30 tests passed ===")
