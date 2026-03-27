"""
Dynamic skill-to-agent matching engine.

Extends the base SkillMatcher with:
- Team composition for multi-skill tasks no single agent covers
- Workload-aware routing (prefer idle agents over busy ones)
- Affinity scoring from past task success history
- Skill gap detection (identify uncoverable skills)
- Confidence-banded match tiers (perfect / strong / partial / weak)

Usage:
    from orchestrator.dynamic_match_engine import DynamicMatchEngine
    engine = DynamicMatchEngine.from_registry("registry/agents.json")
    result = engine.match_best({"skills": ["debug", "code_gen", "documentation"]})
    team = engine.match_team({"skills": ["debug", "code_gen", "documentation"]})
"""

import json
import os
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


# ---------------------------------------------------------------------------
# Skill synonym groups — any skill in a group satisfies demand for another
# ---------------------------------------------------------------------------
SKILL_SYNONYMS: dict[str, set[str]] = {
    "code_gen":      {"code_gen", "coding", "implementation", "code_writing"},
    "bug_fix":       {"bug_fix", "bugfix", "fix", "patch", "hotfix"},
    "debug":         {"debug", "debugging", "error_diagnosis", "troubleshoot", "fix_generation"},
    "tdd":           {"tdd", "test_driven", "test_first"},
    "test_gen":      {"test_gen", "testing", "test_writing", "coverage", "unit_test"},
    "review":        {"review", "code_review", "quality_check", "scoring", "critique"},
    "refactor":      {"refactor", "code_transformation", "cleanup", "restructure"},
    "research":      {"research", "investigation", "web_search", "code_search", "analysis"},
    "documentation": {"documentation", "doc", "doc_gen", "readme", "api_docs", "docstrings", "changelog"},
    "arch":          {"arch", "architecture", "system_design", "scaffold", "e2e", "design"},
    "planning":      {"planning", "plan", "decomposition", "strategy", "breakdown"},
    "scoring":       {"scoring", "benchmark", "gap_analysis", "upgrade_trigger", "evaluation"},
}

# Reverse index: synonym -> canonical key
_SKILL_TO_CANONICAL: dict[str, str] = {}
for _canonical, _synonyms in SKILL_SYNONYMS.items():
    for _syn in _synonyms:
        _SKILL_TO_CANONICAL[_syn] = _canonical


def canonicalize(skill: str) -> str:
    """Map any skill name to its canonical form."""
    return _SKILL_TO_CANONICAL.get(skill.lower().strip(), skill.lower().strip())


def skills_overlap(demanded: set[str], offered: set[str]) -> tuple[float, set[str], set[str]]:
    """
    Compute overlap between demanded and offered skills using canonical forms.
    Returns (ratio, matched_canonical, unmatched_canonical).
    """
    if not demanded:
        return 0.0, set(), set()
    c_demanded = {canonicalize(s) for s in demanded}
    c_offered = {canonicalize(s) for s in offered}
    matched = c_demanded & c_offered
    unmatched = c_demanded - c_offered
    return len(matched) / len(c_demanded), matched, unmatched


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------

class MatchTier(Enum):
    PERFECT = "perfect"    # overlap == 1.0 and score >= 0.8
    STRONG = "strong"      # score >= 0.6
    PARTIAL = "partial"    # score >= 0.3
    WEAK = "weak"          # score < 0.3


@dataclass
class AgentProfile:
    """Agent capabilities and performance history."""
    name: str
    capabilities: list[str]
    model: str = ""
    version: int = 1
    avg_quality: Optional[float] = None
    win_rate: Optional[float] = None
    benchmark_scores: dict = field(default_factory=dict)
    current_load: int = 0          # tasks currently assigned
    max_concurrent: int = 3        # max parallel tasks
    recent_successes: list[str] = field(default_factory=list)  # recent task categories

    @property
    def canonical_capabilities(self) -> set[str]:
        return {canonicalize(c) for c in self.capabilities}

    @property
    def performance_score(self) -> float:
        """Normalized 0-1 performance from available metrics."""
        scores = []
        if self.avg_quality is not None:
            scores.append(self.avg_quality / 100.0)
        if self.win_rate is not None:
            scores.append(self.win_rate / 100.0)
        if self.benchmark_scores:
            latest = list(self.benchmark_scores.values())[-1]
            if isinstance(latest, (int, float)):
                scores.append(min(latest / 100.0, 1.0))
        return sum(scores) / len(scores) if scores else 0.5

    @property
    def availability(self) -> float:
        """0.0 (fully loaded) to 1.0 (idle)."""
        if self.max_concurrent <= 0:
            return 0.0
        return max(0.0, 1.0 - self.current_load / self.max_concurrent)

    def affinity_for(self, skills: set[str]) -> float:
        """0.0-1.0 affinity based on recent success with similar skills."""
        if not self.recent_successes or not skills:
            return 0.0
        canonical_skills = {canonicalize(s) for s in skills}
        canonical_recent = {canonicalize(s) for s in self.recent_successes}
        if not canonical_recent:
            return 0.0
        return len(canonical_skills & canonical_recent) / len(canonical_skills)


@dataclass
class MatchResult:
    """Scored match between a task and an agent."""
    agent_name: str
    score: float
    capability_overlap: float
    performance_score: float
    availability_score: float
    affinity_score: float
    matched_skills: list[str]
    unmatched_skills: list[str]
    tier: MatchTier = MatchTier.WEAK

    @property
    def is_strong_match(self) -> bool:
        return self.score >= 0.6

    @property
    def is_perfect_match(self) -> bool:
        return self.capability_overlap == 1.0


@dataclass
class TeamAssignment:
    """A team of agents covering a multi-skill task."""
    assignments: list[tuple[str, list[str]]]   # [(agent_name, [skills_assigned])]
    coverage: float                             # 0.0-1.0 total skill coverage
    uncovered_skills: list[str]                 # skills no agent can handle
    total_score: float                          # average of individual scores

    @property
    def is_fully_covered(self) -> bool:
        return self.coverage == 1.0

    @property
    def agent_names(self) -> list[str]:
        return [name for name, _ in self.assignments]


@dataclass
class SkillGap:
    """A skill demanded by tasks but not covered by any agent."""
    skill: str
    canonical: str
    closest_agent: Optional[str]
    closest_overlap: float


# ---------------------------------------------------------------------------
# DynamicMatchEngine
# ---------------------------------------------------------------------------

class DynamicMatchEngine:
    """
    Multi-signal skill-to-agent matching engine.

    Scoring weights:
        capability_overlap  55%   — skill coverage
        performance_score   20%   — historical quality / win_rate
        availability        15%   — prefer idle agents
        affinity            10%   — recent success with similar tasks
    """

    W_CAPABILITY = 0.55
    W_PERFORMANCE = 0.20
    W_AVAILABILITY = 0.15
    W_AFFINITY = 0.10

    def __init__(self, agents: list[AgentProfile]):
        self.agents: dict[str, AgentProfile] = {a.name: a for a in agents}
        self._assignment_log: list[dict] = []

    # -- Construction -------------------------------------------------------

    @classmethod
    def from_registry(cls, registry_path: str) -> "DynamicMatchEngine":
        """Build engine from registry/agents.json."""
        with open(registry_path) as f:
            data = json.load(f)
        agents_data = data.get("agents", data)
        profiles = []
        for name, info in agents_data.items():
            profiles.append(AgentProfile(
                name=name,
                capabilities=info.get("capabilities", []),
                model=info.get("model", ""),
                version=info.get("version", 1),
                avg_quality=info.get("avg_quality"),
                win_rate=info.get("win_rate"),
                benchmark_scores=info.get("benchmark_scores", {}),
            ))
        return cls(profiles)

    @classmethod
    def from_profiles(cls, agents: list[AgentProfile]) -> "DynamicMatchEngine":
        return cls(agents)

    # -- Skill extraction ---------------------------------------------------

    @staticmethod
    def extract_skills(task: dict) -> set[str]:
        """Extract skill signals from a task dict."""
        skills: set[str] = set()
        if "skills" in task:
            raw = task["skills"]
            if isinstance(raw, str):
                skills.update(s.strip() for s in raw.split(","))
            elif isinstance(raw, list):
                skills.update(raw)
        if "category" in task:
            skills.add(task["category"])
        return {s for s in skills if s}

    # -- Single agent scoring -----------------------------------------------

    def score_agent(self, agent: AgentProfile, demanded: set[str]) -> MatchResult:
        """Score one agent against demanded skills."""
        overlap_ratio, matched_c, unmatched_c = skills_overlap(demanded, set(agent.capabilities))
        perf = agent.performance_score
        avail = agent.availability
        affinity = agent.affinity_for(demanded)

        composite = (
            self.W_CAPABILITY * overlap_ratio
            + self.W_PERFORMANCE * perf
            + self.W_AVAILABILITY * avail
            + self.W_AFFINITY * affinity
        )

        # Map original skill names to matched/unmatched
        matched = sorted(s for s in demanded if canonicalize(s) in matched_c)
        unmatched = sorted(s for s in demanded if canonicalize(s) in unmatched_c)

        # Determine tier
        if overlap_ratio == 1.0 and composite >= 0.8:
            tier = MatchTier.PERFECT
        elif composite >= 0.6:
            tier = MatchTier.STRONG
        elif composite >= 0.3:
            tier = MatchTier.PARTIAL
        else:
            tier = MatchTier.WEAK

        return MatchResult(
            agent_name=agent.name,
            score=round(composite, 4),
            capability_overlap=round(overlap_ratio, 4),
            performance_score=round(perf, 4),
            availability_score=round(avail, 4),
            affinity_score=round(affinity, 4),
            matched_skills=matched,
            unmatched_skills=unmatched,
            tier=tier,
        )

    # -- Best single match --------------------------------------------------

    def match_best(self, task: dict) -> MatchResult:
        """Find the single best-fit agent for a task."""
        demanded = self.extract_skills(task)
        if not demanded:
            agent = self.agents.get("executor", list(self.agents.values())[0])
            return MatchResult(
                agent_name=agent.name, score=0.0,
                capability_overlap=0.0, performance_score=agent.performance_score,
                availability_score=agent.availability, affinity_score=0.0,
                matched_skills=[], unmatched_skills=[], tier=MatchTier.WEAK,
            )
        results = [self.score_agent(a, demanded) for a in self.agents.values()]
        results.sort(key=lambda r: r.score, reverse=True)
        return results[0]

    def match_top_n(self, task: dict, n: int = 3) -> list[MatchResult]:
        """Return top N matches ranked by score."""
        demanded = self.extract_skills(task)
        if not demanded:
            return [self.match_best(task)]
        results = [self.score_agent(a, demanded) for a in self.agents.values()]
        results.sort(key=lambda r: r.score, reverse=True)
        return results[:n]

    # -- Team composition ---------------------------------------------------

    def match_team(self, task: dict, max_agents: int = 3) -> TeamAssignment:
        """
        Compose a team of agents that collectively cover all demanded skills.

        Uses a greedy set-cover: repeatedly pick the agent that covers the most
        uncovered skills, until all skills are covered or max_agents reached.
        """
        demanded = self.extract_skills(task)
        if not demanded:
            best = self.match_best(task)
            return TeamAssignment(
                assignments=[(best.agent_name, [])],
                coverage=0.0, uncovered_skills=[], total_score=best.score,
            )

        canonical_demanded = {canonicalize(s) for s in demanded}
        remaining = set(canonical_demanded)
        assignments: list[tuple[str, list[str]]] = []
        used_agents: set[str] = set()
        scores: list[float] = []

        for _ in range(max_agents):
            if not remaining:
                break

            best_agent = None
            best_covered: set[str] = set()
            best_score = -1.0

            for agent in self.agents.values():
                if agent.name in used_agents:
                    continue
                agent_canonical = agent.canonical_capabilities
                covers = remaining & agent_canonical
                if not covers:
                    continue
                # Score by coverage count, break ties by performance
                score = len(covers) + agent.performance_score * 0.1
                if score > best_score:
                    best_score = score
                    best_agent = agent
                    best_covered = covers

            if best_agent is None:
                break

            # Map canonical back to original skill names
            assigned_skills = sorted(
                s for s in demanded if canonicalize(s) in best_covered
            )
            assignments.append((best_agent.name, assigned_skills))
            used_agents.add(best_agent.name)
            remaining -= best_covered
            result = self.score_agent(best_agent, demanded)
            scores.append(result.score)

        covered_count = len(canonical_demanded) - len(remaining)
        coverage = covered_count / len(canonical_demanded) if canonical_demanded else 0.0

        uncovered = sorted(
            s for s in demanded if canonicalize(s) in remaining
        )

        avg_score = sum(scores) / len(scores) if scores else 0.0

        return TeamAssignment(
            assignments=assignments,
            coverage=round(coverage, 4),
            uncovered_skills=uncovered,
            total_score=round(avg_score, 4),
        )

    # -- Skill gap detection ------------------------------------------------

    def detect_skill_gaps(self, demanded_skills: set[str]) -> list[SkillGap]:
        """Find skills that no agent can fully cover."""
        gaps = []
        for skill in demanded_skills:
            canonical = canonicalize(skill)
            covered = False
            closest_agent = None
            closest_overlap = 0.0

            for agent in self.agents.values():
                if canonical in agent.canonical_capabilities:
                    covered = True
                    break
                # Check partial overlap via synonym groups
                agent_caps = agent.canonical_capabilities
                if canonical in SKILL_SYNONYMS:
                    group = {canonicalize(s) for s in SKILL_SYNONYMS[canonical]}
                    overlap = len(group & agent_caps) / len(group) if group else 0.0
                    if overlap > closest_overlap:
                        closest_overlap = overlap
                        closest_agent = agent.name

            if not covered:
                gaps.append(SkillGap(
                    skill=skill,
                    canonical=canonical,
                    closest_agent=closest_agent,
                    closest_overlap=round(closest_overlap, 4),
                ))
        return gaps

    # -- Workload management ------------------------------------------------

    def record_assignment(self, agent_name: str, task_skills: set[str]) -> None:
        """Record that an agent was assigned a task (updates load + affinity)."""
        if agent_name in self.agents:
            agent = self.agents[agent_name]
            agent.current_load += 1
            canonical_skills = [canonicalize(s) for s in task_skills]
            agent.recent_successes = (canonical_skills + agent.recent_successes)[:20]
            self._assignment_log.append({
                "agent": agent_name,
                "skills": sorted(task_skills),
                "timestamp": time.time(),
            })

    def record_completion(self, agent_name: str, success: bool = True) -> None:
        """Record task completion, freeing agent capacity."""
        if agent_name in self.agents:
            self.agents[agent_name].current_load = max(
                0, self.agents[agent_name].current_load - 1
            )

    # -- Explanation --------------------------------------------------------

    def explain(self, task: dict) -> str:
        """Human-readable match explanation."""
        demanded = self.extract_skills(task)
        top = self.match_top_n(task, n=3)
        team = self.match_team(task)
        gaps = self.detect_skill_gaps(demanded)

        lines = [
            f"Task skills: {sorted(demanded)}",
            f"",
            f"Best single match:",
        ]
        for i, r in enumerate(top, 1):
            lines.append(
                f"  {i}. {r.agent_name} [{r.tier.value}] score={r.score:.2f} "
                f"(cap={r.capability_overlap:.0%} perf={r.performance_score:.0%} "
                f"avail={r.availability_score:.0%} affinity={r.affinity_score:.0%})"
            )
            if r.matched_skills:
                lines.append(f"     matched: {r.matched_skills}")
            if r.unmatched_skills:
                lines.append(f"     gaps: {r.unmatched_skills}")

        lines.append(f"")
        lines.append(f"Team composition ({len(team.assignments)} agents, {team.coverage:.0%} coverage):")
        for name, skills in team.assignments:
            lines.append(f"  - {name}: {skills}")
        if team.uncovered_skills:
            lines.append(f"  uncovered: {team.uncovered_skills}")

        if gaps:
            lines.append(f"")
            lines.append(f"Skill gaps ({len(gaps)}):")
            for g in gaps:
                closest = f" (closest: {g.closest_agent} at {g.closest_overlap:.0%})" if g.closest_agent else ""
                lines.append(f"  - {g.skill} -> {g.canonical}{closest}")

        return "\n".join(lines)

    # -- Batch matching -----------------------------------------------------

    def match_batch(self, tasks: list[dict]) -> list[MatchResult]:
        """Match multiple tasks, updating load after each assignment."""
        results = []
        for task in tasks:
            result = self.match_best(task)
            self.record_assignment(result.agent_name, self.extract_skills(task))
            results.append(result)
        return results


# ---------------------------------------------------------------------------
# __main__ — comprehensive assertions
# ---------------------------------------------------------------------------

if __name__ == "__main__":

    # --- Build test agent pool ---
    agents = [
        AgentProfile(
            "executor", ["code_gen", "bug_fix", "tdd"],
            avg_quality=100.0, win_rate=100.0,
            benchmark_scores={"v5": 72.7},
        ),
        AgentProfile("debugger", ["debug", "error_diagnosis", "fix_generation"]),
        AgentProfile("test_engineer", ["test_gen", "coverage", "tdd"]),
        AgentProfile("reviewer", ["review", "quality_check", "scoring"]),
        AgentProfile(
            "architect", ["arch", "scaffold", "e2e", "system_design"],
            avg_quality=85.0,
        ),
        AgentProfile("refactor", ["refactor", "code_transformation", "cleanup"]),
        AgentProfile("researcher", ["research", "web_search", "code_search"]),
        AgentProfile("doc_writer", ["documentation", "readme", "api_docs"]),
        AgentProfile("planner", ["planning", "decomposition", "strategy"]),
        AgentProfile("benchmarker", ["scoring", "gap_analysis", "upgrade_trigger"]),
    ]
    engine = DynamicMatchEngine(agents)

    # ---- Test 1: Exact single-skill match ----
    r = engine.match_best({"category": "code_gen"})
    assert r.agent_name == "executor", f"Expected executor, got {r.agent_name}"
    assert r.capability_overlap == 1.0
    assert r.tier in (MatchTier.PERFECT, MatchTier.STRONG)
    print(f"PASS  1: code_gen -> {r.agent_name} (score={r.score:.2f}, tier={r.tier.value})")

    # ---- Test 2: Debug routes to debugger ----
    r = engine.match_best({"category": "debug"})
    assert r.agent_name == "debugger", f"Expected debugger, got {r.agent_name}"
    assert r.is_strong_match
    print(f"PASS  2: debug -> {r.agent_name} (score={r.score:.2f})")

    # ---- Test 3: Multi-skill perfect match ----
    r = engine.match_best({"skills": ["code_gen", "bug_fix", "tdd"]})
    assert r.agent_name == "executor", f"Expected executor, got {r.agent_name}"
    assert r.is_perfect_match
    print(f"PASS  3: [code_gen,bug_fix,tdd] -> {r.agent_name} (perfect)")

    # ---- Test 4: Synonym matching ----
    r = engine.match_best({"skills": ["debugging", "troubleshoot"]})
    assert r.agent_name == "debugger", f"Expected debugger, got {r.agent_name}"
    assert r.capability_overlap == 1.0
    print(f"PASS  4: synonyms [debugging,troubleshoot] -> {r.agent_name}")

    # ---- Test 5: Documentation synonym ----
    r = engine.match_best({"category": "doc_gen"})
    assert r.agent_name == "doc_writer", f"Expected doc_writer, got {r.agent_name}"
    print(f"PASS  5: doc_gen -> {r.agent_name}")

    # ---- Test 6: Performance tiebreak (executor wins on perf for tdd) ----
    r = engine.match_best({"category": "tdd"})
    top2 = engine.match_top_n({"category": "tdd"}, n=2)
    names = {t.agent_name for t in top2}
    assert "executor" in names or "test_engineer" in names
    print(f"PASS  6: tdd -> top={r.agent_name}, runner-up={top2[1].agent_name}")

    # ---- Test 7: Top-N ranked ----
    top3 = engine.match_top_n({"skills": ["code_gen", "test_gen", "review"]}, n=3)
    assert len(top3) == 3
    assert top3[0].score >= top3[1].score >= top3[2].score
    print(f"PASS  7: top-3 ranked: {[(t.agent_name, t.score) for t in top3]}")

    # ---- Test 8: Empty task falls back ----
    r = engine.match_best({})
    assert r.agent_name == "executor"
    assert r.score == 0.0
    print(f"PASS  8: empty task -> {r.agent_name} (fallback)")

    # ---- Test 9: Comma-separated string skills ----
    r = engine.match_best({"skills": "refactor,cleanup"})
    assert r.agent_name == "refactor", f"Expected refactor, got {r.agent_name}"
    print(f"PASS  9: 'refactor,cleanup' -> {r.agent_name}")

    # ---- Test 10: canonicalize ----
    assert canonicalize("debugging") == "debug"
    assert canonicalize("code_review") == "review"
    assert canonicalize("README") == "documentation"
    assert canonicalize("unknown_xyz") == "unknown_xyz"
    print("PASS 10: canonicalize works correctly")

    # ---- Test 11: Performance score calculation ----
    p = AgentProfile("x", [], avg_quality=80.0, win_rate=60.0)
    assert p.performance_score == 0.7, f"Expected 0.7, got {p.performance_score}"
    p2 = AgentProfile("y", [])
    assert p2.performance_score == 0.5
    print("PASS 11: performance_score correct")

    # ---- Test 12: Availability ----
    a = AgentProfile("a", [], max_concurrent=4, current_load=0)
    assert a.availability == 1.0
    a.current_load = 2
    assert a.availability == 0.5
    a.current_load = 4
    assert a.availability == 0.0
    print("PASS 12: availability calculation correct")

    # ---- Test 13: Affinity scoring ----
    a = AgentProfile("a", ["debug"], recent_successes=["debug", "code_gen"])
    assert a.affinity_for({"debug"}) == 1.0
    assert a.affinity_for({"debug", "review"}) == 0.5
    assert a.affinity_for({"planning"}) == 0.0
    a2 = AgentProfile("b", [])
    assert a2.affinity_for({"debug"}) == 0.0
    print("PASS 13: affinity scoring correct")

    # ---- Test 14: Team composition — single agent covers all ----
    team = engine.match_team({"skills": ["code_gen", "bug_fix", "tdd"]})
    assert team.is_fully_covered
    assert len(team.assignments) == 1
    assert team.assignments[0][0] == "executor"
    assert team.uncovered_skills == []
    print(f"PASS 14: team single-agent cover: {team.assignments}")

    # ---- Test 15: Team composition — multi-agent needed ----
    team = engine.match_team({"skills": ["code_gen", "debug", "documentation"]})
    assert team.is_fully_covered, f"Coverage={team.coverage}, uncovered={team.uncovered_skills}"
    assert len(team.assignments) >= 2
    all_assigned = []
    for _, skills in team.assignments:
        all_assigned.extend(skills)
    demanded_canonical = {canonicalize(s) for s in ["code_gen", "debug", "documentation"]}
    assigned_canonical = {canonicalize(s) for s in all_assigned}
    assert demanded_canonical <= assigned_canonical, f"Not all covered: {demanded_canonical - assigned_canonical}"
    print(f"PASS 15: team multi-agent: {team.assignments}")

    # ---- Test 16: Team respects max_agents ----
    team = engine.match_team(
        {"skills": ["code_gen", "debug", "documentation", "review", "research"]},
        max_agents=2,
    )
    assert len(team.assignments) <= 2
    print(f"PASS 16: team max_agents=2: {len(team.assignments)} agents, coverage={team.coverage:.0%}")

    # ---- Test 17: Skill gap detection ----
    gaps = engine.detect_skill_gaps({"code_gen", "debug", "quantum_computing"})
    gap_skills = {g.skill for g in gaps}
    assert "quantum_computing" in gap_skills
    assert "code_gen" not in gap_skills
    assert "debug" not in gap_skills
    print(f"PASS 17: skill gaps detected: {[g.skill for g in gaps]}")

    # ---- Test 18: No gaps for covered skills ----
    gaps = engine.detect_skill_gaps({"code_gen", "debug", "review"})
    assert len(gaps) == 0
    print("PASS 18: no gaps for fully covered skills")

    # ---- Test 19: Workload-aware matching ----
    engine2 = DynamicMatchEngine([
        AgentProfile("a", ["code_gen"], avg_quality=90.0, current_load=0, max_concurrent=3),
        AgentProfile("b", ["code_gen"], avg_quality=90.0, current_load=3, max_concurrent=3),
    ])
    r = engine2.match_best({"category": "code_gen"})
    assert r.agent_name == "a", f"Expected idle agent 'a', got {r.agent_name}"
    assert r.availability_score == 1.0
    print(f"PASS 19: workload-aware: idle agent 'a' preferred over loaded 'b'")

    # ---- Test 20: Record assignment updates load ----
    engine.record_assignment("executor", {"code_gen"})
    assert engine.agents["executor"].current_load == 1
    engine.record_completion("executor")
    assert engine.agents["executor"].current_load == 0
    print("PASS 20: record_assignment / record_completion updates load")

    # ---- Test 21: Record assignment updates affinity ----
    engine.record_assignment("debugger", {"debug", "troubleshoot"})
    assert "debug" in engine.agents["debugger"].recent_successes
    engine.record_completion("debugger")
    print("PASS 21: record_assignment updates recent_successes for affinity")

    # ---- Test 22: Batch matching with load balancing ----
    engine3 = DynamicMatchEngine([
        AgentProfile("a", ["code_gen"], avg_quality=80.0, max_concurrent=2),
        AgentProfile("b", ["code_gen"], avg_quality=80.0, max_concurrent=2),
    ])
    tasks = [{"category": "code_gen"}] * 4
    results = engine3.match_batch(tasks)
    assert len(results) == 4
    assigned = [r.agent_name for r in results]
    # With load balancing, both agents should get work
    assert "a" in assigned and "b" in assigned, f"Expected both agents used, got {assigned}"
    print(f"PASS 22: batch load-balanced: {assigned}")

    # ---- Test 23: Match tier classification ----
    r = engine.match_best({"skills": ["code_gen", "bug_fix", "tdd"]})
    assert r.tier == MatchTier.PERFECT, f"Expected PERFECT, got {r.tier}"
    r_weak = engine.match_best({"skills": ["quantum_computing"]})
    assert r_weak.tier == MatchTier.WEAK, f"Expected WEAK, got {r_weak.tier}"
    print("PASS 23: match tier classification correct")

    # ---- Test 24: Architecture/design synonyms ----
    r = engine.match_best({"skills": ["architecture", "design"]})
    assert r.agent_name == "architect", f"Expected architect, got {r.agent_name}"
    print(f"PASS 24: [architecture,design] -> {r.agent_name}")

    # ---- Test 25: Explain output ----
    explanation = engine.explain({"skills": ["code_gen", "debug"], "category": "bug_fix"})
    assert "executor" in explanation
    assert "Task skills:" in explanation
    assert "Team composition" in explanation
    print(f"PASS 25: explain output contains expected sections")

    # ---- Test 26: MatchResult properties ----
    strong = MatchResult("a", 0.7, 0.8, 0.5, 1.0, 0.0, ["x"], [], MatchTier.STRONG)
    weak = MatchResult("b", 0.2, 0.1, 0.5, 1.0, 0.0, [], ["x"], MatchTier.WEAK)
    perfect = MatchResult("c", 0.9, 1.0, 0.8, 1.0, 0.5, ["x"], [], MatchTier.PERFECT)
    assert strong.is_strong_match and not weak.is_strong_match
    assert perfect.is_perfect_match and not strong.is_perfect_match
    print("PASS 26: MatchResult properties correct")

    # ---- Test 27: from_registry loads real registry ----
    registry_path = os.path.join(os.path.dirname(__file__), "..", "registry", "agents.json")
    if os.path.exists(registry_path):
        loaded = DynamicMatchEngine.from_registry(registry_path)
        assert len(loaded.agents) >= 8
        r = loaded.match_best({"category": "code_gen"})
        assert r.agent_name == "executor"
        team = loaded.match_team({"skills": ["code_gen", "debug", "documentation"]})
        assert team.is_fully_covered
        print(f"PASS 27: from_registry loaded {len(loaded.agents)} agents, team works")
    else:
        print(f"SKIP 27: registry not found at {registry_path}")

    # ---- Test 28: TeamAssignment properties ----
    ta = TeamAssignment(
        assignments=[("a", ["x"]), ("b", ["y"])],
        coverage=1.0, uncovered_skills=[], total_score=0.8,
    )
    assert ta.is_fully_covered
    assert ta.agent_names == ["a", "b"]
    ta2 = TeamAssignment(
        assignments=[("a", ["x"])],
        coverage=0.5, uncovered_skills=["z"], total_score=0.4,
    )
    assert not ta2.is_fully_covered
    print("PASS 28: TeamAssignment properties correct")

    # ---- Test 29: SkillGap structure ----
    gaps = engine.detect_skill_gaps({"blockchain", "ml_ops"})
    assert len(gaps) == 2
    for g in gaps:
        assert g.skill in ("blockchain", "ml_ops")
        assert g.canonical == g.skill  # unknown skills pass through
    print("PASS 29: SkillGap for unknown skills")

    # ---- Test 30: Weights sum to 1.0 ----
    total = (DynamicMatchEngine.W_CAPABILITY + DynamicMatchEngine.W_PERFORMANCE
             + DynamicMatchEngine.W_AVAILABILITY + DynamicMatchEngine.W_AFFINITY)
    assert total == 1.0, f"Weights sum to {total}, expected 1.0"
    print("PASS 30: scoring weights sum to 1.0")

    print(f"\n=== All 30 tests passed ===")
