#!/usr/bin/env python3
"""
skill_matcher.py — Dynamic skill-to-agent matching engine
==========================================================
Matches task skills/requirements to agent capabilities and finds the best fit.

Features:
  - Exact capability match
  - Fuzzy/semantic similarity matching (token overlap + synonyms)
  - Weighted scoring: exact > synonym > partial
  - Multi-skill tasks: aggregated score across all required skills
  - Fallback ranking when no perfect match exists
  - Load-aware tiebreaking (prefer agents with fewer active tasks)
  - Agent version preference (newer versions score higher)

Usage:
    from scripts.skill_matcher import SkillMatcher
    matcher = SkillMatcher()
    match = matcher.match(["bug_fix", "tdd"])
    print(match.agent_name, match.score)
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple


# ---------------------------------------------------------------------------
# Synonym groups — bidirectional semantic similarity between skill tokens
# ---------------------------------------------------------------------------
SYNONYM_GROUPS: List[Set[str]] = [
    {"code_gen", "code_generation", "coding", "implementation", "code_write"},
    {"bug_fix", "bugfix", "fix", "patch", "hotfix", "debug"},
    {"tdd", "test_driven", "test_gen", "testing", "test", "coverage"},
    {"scaffold", "scaffolding", "boilerplate", "template", "skeleton"},
    {"arch", "architecture", "system_design", "design", "blueprint"},
    {"e2e", "end_to_end", "integration", "full_stack"},
    {"refactor", "refactoring", "restructure", "cleanup", "code_transformation"},
    {"research", "code_search", "search", "explore", "investigate", "context_assembly"},
    {"doc", "doc_gen", "documentation", "docs", "readme", "api_docs", "docstrings", "changelog"},
    {"review", "code_review", "quality_check", "scoring", "audit"},
    {"debug", "debugging", "error_diagnosis", "fix_generation", "troubleshoot"},
    {"plan", "planning", "decomposition", "strategy", "breakdown"},
    {"benchmark", "benchmarking", "scoring", "gap_analysis", "performance"},
    {"deploy", "deployment", "ci_cd", "release"},
    {"security", "auth", "permissions", "access_control"},
    {"frontend", "ui", "ux", "react", "css", "html"},
    {"backend", "api", "server", "database", "rest"},
    {"ml", "ai", "machine_learning", "model", "training", "inference"},
]

# Build a lookup: skill_token -> set of synonyms
_SYNONYM_MAP: Dict[str, Set[str]] = {}
for group in SYNONYM_GROUPS:
    for token in group:
        _SYNONYM_MAP.setdefault(token, set()).update(group - {token})


def _normalize(skill: str) -> str:
    """Lowercase, strip, collapse whitespace, replace hyphens with underscores."""
    return re.sub(r"[\s-]+", "_", skill.strip().lower())


def _tokenize(skill: str) -> Set[str]:
    """Split a skill name into constituent tokens for partial matching."""
    normalized = _normalize(skill)
    tokens = set(normalized.split("_"))
    tokens.add(normalized)  # include the full joined form
    return tokens


def _synonyms_for(skill: str) -> Set[str]:
    """Return all known synonyms for a skill."""
    norm = _normalize(skill)
    result: Set[str] = set()
    result.update(_SYNONYM_MAP.get(norm, set()))
    for token in _tokenize(skill):
        result.update(_SYNONYM_MAP.get(token, set()))
    return result


# ---------------------------------------------------------------------------
# Agent descriptor
# ---------------------------------------------------------------------------
@dataclass
class AgentDescriptor:
    """Describes an agent's capabilities for matching purposes."""
    name: str
    capabilities: List[str]
    version: int = 1
    model: str = "local"
    active_tasks: int = 0
    max_concurrent: int = 8
    benchmark_score: Optional[float] = None

    @property
    def capability_set(self) -> Set[str]:
        return {_normalize(c) for c in self.capabilities}

    @property
    def capability_tokens(self) -> Set[str]:
        tokens: Set[str] = set()
        for cap in self.capabilities:
            tokens.update(_tokenize(cap))
        return tokens

    @property
    def load_ratio(self) -> float:
        if self.max_concurrent <= 0:
            return 1.0
        return self.active_tasks / self.max_concurrent


# ---------------------------------------------------------------------------
# Match result
# ---------------------------------------------------------------------------
@dataclass
class MatchResult:
    """Result of matching a set of skills to an agent."""
    agent_name: str
    score: float                        # 0.0 - 1.0
    matched_skills: Dict[str, str]      # required_skill -> match_type (exact|synonym|partial|none)
    unmatched_skills: List[str]
    details: Dict[str, float] = field(default_factory=dict)

    @property
    def is_perfect(self) -> bool:
        return len(self.unmatched_skills) == 0 and self.score >= 0.99

    def __repr__(self) -> str:
        return (f"MatchResult(agent={self.agent_name!r}, score={self.score:.3f}, "
                f"matched={len(self.matched_skills)}, unmatched={len(self.unmatched_skills)})")


# ---------------------------------------------------------------------------
# Scoring weights
# ---------------------------------------------------------------------------
EXACT_WEIGHT = 1.0
SYNONYM_WEIGHT = 0.75
PARTIAL_WEIGHT = 0.35
NO_MATCH_WEIGHT = 0.0
VERSION_BONUS = 0.02       # per version above 1
LOAD_PENALTY_MAX = 0.10    # max penalty for fully loaded agent
BENCHMARK_BONUS_MAX = 0.05 # max bonus for high benchmark score


# ---------------------------------------------------------------------------
# Core matcher
# ---------------------------------------------------------------------------
class SkillMatcher:
    """
    Dynamic skill-to-agent matching engine.

    Registers agent descriptors, then matches required skill sets
    against agent capabilities using exact, synonym, and partial matching.
    """

    def __init__(self) -> None:
        self._agents: Dict[str, AgentDescriptor] = {}

    # -- Registration -------------------------------------------------------

    def register(self, agent: AgentDescriptor) -> None:
        """Register or update an agent descriptor."""
        self._agents[agent.name] = agent

    def register_from_meta(self, meta: dict, active_tasks: int = 0) -> None:
        """Register from an AGENT_META dict (as defined in each agents/*.py)."""
        self.register(AgentDescriptor(
            name=meta.get("name", "unknown"),
            capabilities=meta.get("capabilities", []),
            version=meta.get("version", 1),
            model=meta.get("model", "local"),
            active_tasks=active_tasks,
            benchmark_score=meta.get("benchmark_score"),
        ))

    def unregister(self, name: str) -> None:
        self._agents.pop(name, None)

    @property
    def agents(self) -> Dict[str, AgentDescriptor]:
        return dict(self._agents)

    # -- Single skill scoring -----------------------------------------------

    def _score_skill(self, skill: str, agent: AgentDescriptor) -> Tuple[float, str]:
        """
        Score how well a single skill matches an agent's capabilities.
        Returns (score, match_type).
        """
        norm_skill = _normalize(skill)
        skill_tokens = _tokenize(skill)
        skill_synonyms = _synonyms_for(skill)

        # 1. Exact match
        if norm_skill in agent.capability_set:
            return EXACT_WEIGHT, "exact"

        # 2. Synonym match — any agent capability is a synonym of the skill
        for cap in agent.capability_set:
            if cap in skill_synonyms or norm_skill in _synonyms_for(cap):
                return SYNONYM_WEIGHT, "synonym"

        # 3. Partial token overlap
        agent_tokens = agent.capability_tokens
        overlap = skill_tokens & agent_tokens
        if overlap:
            # Jaccard-like partial score
            jaccard = len(overlap) / len(skill_tokens | agent_tokens)
            return PARTIAL_WEIGHT * min(1.0, jaccard * 3), "partial"

        return NO_MATCH_WEIGHT, "none"

    # -- Multi-skill matching -----------------------------------------------

    def _score_agent(self, required_skills: List[str], agent: AgentDescriptor) -> MatchResult:
        """Score an agent against a full set of required skills."""
        if not required_skills:
            return MatchResult(
                agent_name=agent.name, score=0.5,
                matched_skills={}, unmatched_skills=[],
                details={"reason": "no_skills_required"},
            )

        skill_scores: Dict[str, float] = {}
        match_types: Dict[str, str] = {}
        unmatched: List[str] = []

        for skill in required_skills:
            score, match_type = self._score_skill(skill, agent)
            skill_scores[skill] = score
            match_types[skill] = match_type
            if match_type == "none":
                unmatched.append(skill)

        # Aggregate: geometric mean biased toward worst match (penalizes gaps)
        raw_scores = list(skill_scores.values())
        if all(s == 0.0 for s in raw_scores):
            base_score = 0.0
        else:
            # Use shifted geometric mean to handle zeros gracefully
            epsilon = 0.01
            log_sum = sum(math.log(s + epsilon) for s in raw_scores)
            geo_mean = math.exp(log_sum / len(raw_scores)) - epsilon
            base_score = max(0.0, geo_mean)

        # Bonuses / penalties
        version_bonus = min(0.10, VERSION_BONUS * max(0, agent.version - 1))
        load_penalty = LOAD_PENALTY_MAX * agent.load_ratio
        bench_bonus = 0.0
        if agent.benchmark_score is not None and agent.benchmark_score > 0:
            bench_bonus = BENCHMARK_BONUS_MAX * min(1.0, agent.benchmark_score / 100.0)

        final_score = max(0.0, min(1.0, base_score + version_bonus - load_penalty + bench_bonus))

        return MatchResult(
            agent_name=agent.name,
            score=round(final_score, 4),
            matched_skills=match_types,
            unmatched_skills=unmatched,
            details={
                "base_score": round(base_score, 4),
                "version_bonus": round(version_bonus, 4),
                "load_penalty": round(load_penalty, 4),
                "benchmark_bonus": round(bench_bonus, 4),
                "per_skill": {k: round(v, 4) for k, v in skill_scores.items()},
            },
        )

    # -- Public API ---------------------------------------------------------

    def match(self, required_skills: List[str], top_k: int = 1) -> MatchResult | List[MatchResult]:
        """
        Find the best agent(s) for a set of required skills.

        Args:
            required_skills: List of skill names the task requires.
            top_k: Number of top matches to return. 1 returns a single MatchResult.

        Returns:
            MatchResult (top_k=1) or list of MatchResult (top_k>1), ranked by score desc.
        """
        if not self._agents:
            raise ValueError("No agents registered. Call register() first.")

        results = [
            self._score_agent(required_skills, agent)
            for agent in self._agents.values()
        ]
        results.sort(key=lambda r: r.score, reverse=True)

        if top_k == 1:
            return results[0]
        return results[:top_k]

    def match_task(self, task: dict, top_k: int = 1) -> MatchResult | List[MatchResult]:
        """
        Match a task dict (with 'category' and/or 'skills' keys) to agents.

        Extracts skills from:
          - task["skills"] (list of strings)
          - task["category"] (single string, used as a skill)
          - task["tags"] (list of strings, each treated as a skill)
        """
        skills: List[str] = []
        if "skills" in task:
            skills.extend(task["skills"] if isinstance(task["skills"], list) else [task["skills"]])
        if "category" in task:
            skills.append(task["category"])
        if "tags" in task:
            skills.extend(task["tags"] if isinstance(task["tags"], list) else [task["tags"]])
        # Deduplicate while preserving order
        seen: Set[str] = set()
        unique: List[str] = []
        for s in skills:
            n = _normalize(s)
            if n not in seen:
                seen.add(n)
                unique.append(s)
        return self.match(unique, top_k=top_k)

    def auto_register_from_routing_table(
        self, routing_table: Dict[str, str], meta_loader=None
    ) -> int:
        """
        Bulk-register agents from a routing table like agents.ROUTING_TABLE.
        Infers capabilities by inverting the table (agent_name -> [categories]).
        Optionally loads AGENT_META via meta_loader(agent_name) -> dict.

        Returns number of agents registered.
        """
        # Invert: agent_name -> set of categories
        inverted: Dict[str, Set[str]] = {}
        for category, agent_name in routing_table.items():
            inverted.setdefault(agent_name, set()).add(category)

        count = 0
        for agent_name, caps in inverted.items():
            meta = {}
            if meta_loader:
                try:
                    meta = meta_loader(agent_name) or {}
                except Exception:
                    meta = {}
            # Merge inferred capabilities with declared ones
            declared = set(meta.get("capabilities", []))
            all_caps = list(declared | caps)
            self.register(AgentDescriptor(
                name=agent_name,
                capabilities=all_caps,
                version=meta.get("version", 1),
                model=meta.get("model", "local"),
                benchmark_score=meta.get("benchmark_score"),
            ))
            count += 1
        return count


# ---------------------------------------------------------------------------
# Convenience: load from live agents package
# ---------------------------------------------------------------------------
def create_matcher_from_agents() -> SkillMatcher:
    """
    Create a SkillMatcher pre-loaded with all agents from agents/ package.
    Works when run from the repo root (agents/ importable).
    """
    import sys
    from pathlib import Path
    repo_root = str(Path(__file__).parent.parent)
    if repo_root not in sys.path:
        sys.path.insert(0, repo_root)

    try:
        import agents as agents_pkg
        matcher = SkillMatcher()
        matcher.auto_register_from_routing_table(
            agents_pkg.ROUTING_TABLE,
            meta_loader=lambda name: agents_pkg.agent_meta(name),
        )
        return matcher
    except ImportError:
        raise ImportError("Cannot import agents package. Run from repo root.")


# ---------------------------------------------------------------------------
# __main__ — assertions that verify correctness
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    print("=== SkillMatcher self-test ===\n")

    # -- Setup: register agents matching the real codebase --
    matcher = SkillMatcher()

    agents_meta = [
        {"name": "executor",      "version": 4, "capabilities": ["code_gen", "bug_fix", "tdd"],        "model": "nexus-local"},
        {"name": "planner",       "version": 1, "capabilities": ["planning", "decomposition", "strategy"]},
        {"name": "architect",     "version": 1, "capabilities": ["arch", "scaffold", "e2e", "system_design"]},
        {"name": "test_engineer", "version": 1, "capabilities": ["test_gen", "coverage", "tdd"]},
        {"name": "reviewer",      "version": 1, "capabilities": ["review", "quality_check", "scoring"]},
        {"name": "refactor",      "version": 1, "capabilities": ["refactor", "code_transformation", "cleanup"]},
        {"name": "debugger",      "version": 1, "capabilities": ["debug", "error_diagnosis", "fix_generation"]},
        {"name": "doc_writer",    "version": 2, "capabilities": ["documentation", "readme", "api_docs", "docstrings", "changelog"]},
        {"name": "researcher",    "version": 1, "capabilities": ["research", "code_search", "context_assembly"]},
        {"name": "benchmarker",   "version": 1, "capabilities": ["scoring", "gap_analysis", "upgrade_trigger"]},
    ]
    for meta in agents_meta:
        matcher.register_from_meta(meta)

    print(f"Registered {len(matcher.agents)} agents\n")

    # ---- Test 1: Exact match ----
    result = matcher.match(["code_gen"])
    print(f"Test 1 (exact 'code_gen'): {result}")
    assert result.agent_name == "executor", f"Expected executor, got {result.agent_name}"
    assert result.matched_skills["code_gen"] == "exact"
    assert result.score > 0.9
    print("  PASS\n")

    # ---- Test 2: Exact match for documentation ----
    result = matcher.match(["documentation"])
    print(f"Test 2 (exact 'documentation'): {result}")
    assert result.agent_name == "doc_writer", f"Expected doc_writer, got {result.agent_name}"
    assert result.matched_skills["documentation"] == "exact"
    print("  PASS\n")

    # ---- Test 3: Synonym match — "testing" should match test_engineer (via tdd synonym) ----
    result = matcher.match(["testing"])
    print(f"Test 3 (synonym 'testing'): {result}")
    assert result.matched_skills["testing"] in ("exact", "synonym"), \
        f"Expected synonym match, got {result.matched_skills['testing']}"
    assert result.agent_name in ("test_engineer", "executor"), f"Unexpected agent: {result.agent_name}"
    print("  PASS\n")

    # ---- Test 4: Multi-skill — "bug_fix" + "tdd" should favor executor ----
    result = matcher.match(["bug_fix", "tdd"])
    print(f"Test 4 (multi 'bug_fix'+'tdd'): {result}")
    assert result.agent_name == "executor", f"Expected executor, got {result.agent_name}"
    assert result.score > 0.8
    print("  PASS\n")

    # ---- Test 5: Partial match — "code_review" should match reviewer (partial on 'review') ----
    result = matcher.match(["code_review"])
    print(f"Test 5 (partial 'code_review'): {result}")
    # Should match reviewer via synonym or partial
    assert result.agent_name == "reviewer", f"Expected reviewer, got {result.agent_name}"
    assert result.matched_skills["code_review"] in ("synonym", "partial", "exact")
    print("  PASS\n")

    # ---- Test 6: No match — totally unrelated skill ----
    result = matcher.match(["quantum_entanglement"])
    print(f"Test 6 (no match 'quantum_entanglement'): {result}")
    assert result.score < 0.3, f"Score too high for unmatched: {result.score}"
    assert len(result.unmatched_skills) > 0
    print("  PASS\n")

    # ---- Test 7: top_k returns ranked list ----
    results = matcher.match(["debug", "fix"], top_k=3)
    print(f"Test 7 (top_k=3 for 'debug'+'fix'):")
    assert isinstance(results, list)
    assert len(results) == 3
    for r in results:
        print(f"  {r}")
    # Scores must be descending
    for i in range(len(results) - 1):
        assert results[i].score >= results[i + 1].score, "Results not sorted by score"
    # debugger or executor should be top (both have debug/fix capabilities)
    assert results[0].agent_name in ("debugger", "executor")
    print("  PASS\n")

    # ---- Test 8: Version bonus — executor (v4) should beat others at equal match ----
    result = matcher.match(["code_gen"])
    print(f"Test 8 (version bonus): executor v4 score={result.score}")
    assert result.details["version_bonus"] > 0, "Version bonus should be positive for v4"
    print("  PASS\n")

    # ---- Test 9: Load penalty — busy agent ranks lower ----
    matcher_load = SkillMatcher()
    matcher_load.register(AgentDescriptor(
        name="agent_a", capabilities=["code_gen"], version=1, active_tasks=0, max_concurrent=8
    ))
    matcher_load.register(AgentDescriptor(
        name="agent_b", capabilities=["code_gen"], version=1, active_tasks=7, max_concurrent=8
    ))
    result = matcher_load.match(["code_gen"])
    print(f"Test 9 (load penalty): best={result.agent_name}")
    assert result.agent_name == "agent_a", f"Idle agent should win, got {result.agent_name}"
    print("  PASS\n")

    # ---- Test 10: match_task with task dict ----
    task = {"category": "refactor", "skills": ["cleanup"], "tags": ["code_transformation"]}
    result = matcher.match_task(task)
    print(f"Test 10 (match_task): {result}")
    assert result.agent_name == "refactor", f"Expected refactor, got {result.agent_name}"
    print("  PASS\n")

    # ---- Test 11: auto_register_from_routing_table ----
    routing_table = {
        "code_gen": "executor",
        "bug_fix": "executor",
        "tdd": "test_engineer",
        "scaffold": "architect",
        "refactor": "refactor",
        "doc": "doc_writer",
        "review": "reviewer",
        "debug": "debugger",
        "plan": "planner",
        "benchmark": "benchmarker",
    }
    auto_matcher = SkillMatcher()
    count = auto_matcher.auto_register_from_routing_table(routing_table)
    print(f"Test 11 (auto_register): registered {count} agents from routing table")
    assert count == len(set(routing_table.values())), f"Expected {len(set(routing_table.values()))} unique agents, got {count}"
    result = auto_matcher.match(["code_gen"])
    assert result.agent_name == "executor"
    print("  PASS\n")

    # ---- Test 12: Synonym "docs" → doc_writer ----
    result = matcher.match(["docs"])
    print(f"Test 12 (synonym 'docs'): {result}")
    assert result.agent_name == "doc_writer", f"Expected doc_writer, got {result.agent_name}"
    print("  PASS\n")

    # ---- Test 13: Synonym "architecture" → architect ----
    result = matcher.match(["architecture"])
    print(f"Test 13 (synonym 'architecture'): {result}")
    assert result.agent_name == "architect", f"Expected architect, got {result.agent_name}"
    print("  PASS\n")

    # ---- Test 14: is_perfect property ----
    result = matcher.match(["code_gen", "bug_fix", "tdd"])
    print(f"Test 14 (is_perfect): {result}, perfect={result.is_perfect}")
    assert result.agent_name == "executor"
    assert result.is_perfect, "All 3 skills are exact matches for executor"
    print("  PASS\n")

    # ---- Test 15: Empty skills returns 0.5 baseline ----
    result = matcher.match([])
    print(f"Test 15 (empty skills): {result}")
    assert result.score == 0.5
    print("  PASS\n")

    # ---- Test 16: No agents raises ValueError ----
    empty_matcher = SkillMatcher()
    try:
        empty_matcher.match(["anything"])
        assert False, "Should have raised ValueError"
    except ValueError:
        print("Test 16 (no agents): ValueError raised correctly")
    print("  PASS\n")

    print("=" * 50)
    print("ALL 16 TESTS PASSED")
    print("=" * 50)
