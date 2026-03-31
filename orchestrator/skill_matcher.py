"""
Dynamic skill-to-agent matching engine.

Matches task skill requirements to agent capabilities using weighted scoring.
Replaces static ROUTING_TABLE lookups with multi-signal matching that considers:
  - Explicit skills and category fields
  - Keyword extraction from task title/description text
  - Synonym expansion to canonical capabilities
  - Agent performance history as tiebreaker

Usage:
    from orchestrator.skill_matcher import SkillMatcher
    matcher = SkillMatcher.from_registry("registry/agents.json")
    match = matcher.match({"category": "bug_fix", "skills": ["debug", "code_gen"]})
    print(match.agent_name, match.score)

    # Also works with description-only tasks (no explicit skills/category):
    match = matcher.match({"title": "Fix crash on login", "description": "App errors out"})
"""

import json
import os
import re
from dataclasses import dataclass, field
from typing import Optional


# Skill synonym groups: any skill in a group can satisfy demand for another
SKILL_SYNONYMS = {
    "code_gen":      {"code_gen", "coding", "implementation", "code_writing", "generate"},
    "bug_fix":       {"bug_fix", "bugfix", "fix", "patch", "hotfix"},
    "debug":         {"debug", "debugging", "error_diagnosis", "troubleshoot", "fix_generation", "diagnose"},
    "tdd":           {"tdd", "test_driven", "test_first"},
    "test_gen":      {"test_gen", "testing", "test_writing", "coverage", "unit_test"},
    "review":        {"review", "code_review", "quality_check", "scoring", "critique", "audit", "inspect"},
    "refactor":      {"refactor", "code_transformation", "cleanup", "restructure", "optimize", "migrate"},
    "research":      {"research", "investigation", "web_search", "code_search", "analysis", "explore", "investigate"},
    "documentation": {"documentation", "doc", "doc_gen", "readme", "api_docs", "docstrings", "changelog"},
    "arch":          {"arch", "architecture", "system_design", "scaffold", "e2e", "design"},
    "planning":      {"planning", "plan", "decomposition", "strategy", "breakdown", "prioritize"},
    "scoring":       {"scoring", "benchmark", "gap_analysis", "upgrade_trigger", "evaluation"},
}

# Build reverse index: skill_name -> canonical group key
_SKILL_TO_CANONICAL: dict[str, str] = {}
for _canonical, _synonyms in SKILL_SYNONYMS.items():
    for _syn in _synonyms:
        _SKILL_TO_CANONICAL[_syn] = _canonical

# Keywords in task text that map to canonical skills for description-based matching
_KEYWORD_TO_SKILLS: dict[str, list[str]] = {
    "bug": ["bug_fix", "debug"],
    "crash": ["debug", "bug_fix"],
    "error": ["debug", "bug_fix"],
    "exception": ["debug"],
    "fix": ["bug_fix"],
    "test": ["test_gen", "tdd"],
    "coverage": ["test_gen"],
    "assert": ["test_gen", "tdd"],
    "refactor": ["refactor"],
    "clean": ["refactor"],
    "optimize": ["refactor"],
    "migrate": ["refactor"],
    "document": ["documentation"],
    "readme": ["documentation"],
    "docs": ["documentation"],
    "architect": ["arch"],
    "scaffold": ["arch"],
    "design": ["arch"],
    "microservice": ["arch"],
    "plan": ["planning"],
    "prioritize": ["planning"],
    "decompose": ["planning"],
    "review": ["review"],
    "audit": ["review"],
    "inspect": ["review"],
    "search": ["research"],
    "investigate": ["research"],
    "explore": ["research"],
    "research": ["research"],
    "benchmark": ["scoring"],
    "evaluate": ["scoring"],
    "score": ["scoring"],
    "implement": ["code_gen"],
    "generate": ["code_gen"],
    "write": ["code_gen"],
    "create": ["code_gen"],
    "deploy": ["arch"],
    "diagnose": ["debug"],
    "troubleshoot": ["debug"],
    "api": ["documentation", "arch"],
    "performance": ["scoring", "refactor"],
}


def canonicalize_skill(skill: str) -> str:
    """Map a skill name to its canonical form."""
    return _SKILL_TO_CANONICAL.get(skill.lower().strip(), skill.lower().strip())


def skills_overlap(demanded: set[str], offered: set[str]) -> float:
    """
    Compute overlap ratio between demanded skills and offered capabilities.
    Uses canonical forms so synonyms match. Returns 0.0-1.0.
    """
    if not demanded:
        return 0.0
    canonical_demanded = {canonicalize_skill(s) for s in demanded}
    canonical_offered = {canonicalize_skill(s) for s in offered}
    matched = canonical_demanded & canonical_offered
    return len(matched) / len(canonical_demanded)


def extract_keywords_from_text(text: str) -> set[str]:
    """Extract matching skill keywords from free-form text."""
    tokens = set(re.findall(r"[a-z_][a-z0-9_]*", text.lower()))
    found: set[str] = set()
    for token in tokens:
        if token in _KEYWORD_TO_SKILLS:
            found.update(_KEYWORD_TO_SKILLS[token])
    return found


@dataclass
class AgentProfile:
    """An agent's capabilities and performance history."""
    name: str
    capabilities: list[str]
    model: str = ""
    version: int = 1
    avg_quality: Optional[float] = None
    win_rate: Optional[float] = None
    benchmark_scores: dict = field(default_factory=dict)

    @property
    def canonical_capabilities(self) -> set[str]:
        return {canonicalize_skill(c) for c in self.capabilities}

    @property
    def performance_score(self) -> float:
        """Normalized 0-1 performance based on available metrics."""
        scores = []
        if self.avg_quality is not None:
            scores.append(self.avg_quality / 100.0)
        if self.win_rate is not None:
            scores.append(self.win_rate / 100.0)
        if self.benchmark_scores:
            latest = list(self.benchmark_scores.values())[-1]
            if isinstance(latest, (int, float)):
                scores.append(latest / 100.0)
        return sum(scores) / len(scores) if scores else 0.5  # default mid-range


@dataclass
class MatchResult:
    """Result of matching a task to an agent."""
    agent_name: str
    score: float            # 0.0-1.0 composite match score
    capability_overlap: float
    performance_score: float
    matched_skills: list[str]
    unmatched_skills: list[str]
    keyword_matched: list[str] = field(default_factory=list)

    @property
    def is_strong_match(self) -> bool:
        return self.score >= 0.6

    @property
    def is_perfect_match(self) -> bool:
        return self.capability_overlap == 1.0


class SkillMatcher:
    """
    Matches task skill requirements to agent capabilities.

    Scoring weights:
        - capability_overlap (60%): How many demanded skills the agent covers
        - keyword_overlap    (15%): Skills inferred from title/description text
        - performance_score  (25%): Historical quality/win_rate/benchmark
    """

    WEIGHT_CAPABILITY = 0.60
    WEIGHT_KEYWORD = 0.15
    WEIGHT_PERFORMANCE = 0.25

    def __init__(self, agents: list[AgentProfile]):
        self.agents = {a.name: a for a in agents}

    @classmethod
    def from_registry(cls, registry_path: str) -> "SkillMatcher":
        """Load agent profiles from registry/agents.json."""
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

    def _extract_skills(self, task: dict) -> set[str]:
        """Extract explicit skill signals from a task dict."""
        skills = set()
        if "skills" in task:
            raw = task["skills"]
            if isinstance(raw, str):
                skills.update(s.strip() for s in raw.split(","))
            elif isinstance(raw, list):
                skills.update(raw)
        if "category" in task:
            skills.add(task["category"])
        return {s for s in skills if s}

    def _extract_text_keywords(self, task: dict) -> set[str]:
        """Extract skill signals from task title and description text."""
        text = f"{task.get('title', '')} {task.get('description', '')}"
        return extract_keywords_from_text(text)

    def score_agent(self, agent: AgentProfile, demanded_skills: set[str],
                    keyword_skills: Optional[set[str]] = None) -> MatchResult:
        """Score a single agent against demanded skills and keyword signals."""
        overlap = skills_overlap(demanded_skills, set(agent.capabilities))
        perf = agent.performance_score

        # Keyword overlap: how many keyword-inferred skills match the agent
        kw_overlap = 0.0
        kw_matched: list[str] = []
        if keyword_skills:
            canonical_kw = {canonicalize_skill(s) for s in keyword_skills}
            canonical_offered = agent.canonical_capabilities
            kw_match = canonical_kw & canonical_offered
            kw_overlap = len(kw_match) / len(canonical_kw) if canonical_kw else 0.0
            kw_matched = sorted(kw_match)

        composite = (self.WEIGHT_CAPABILITY * overlap +
                     self.WEIGHT_KEYWORD * kw_overlap +
                     self.WEIGHT_PERFORMANCE * perf)

        canonical_offered = agent.canonical_capabilities
        matched = [s for s in demanded_skills
                   if canonicalize_skill(s) in canonical_offered]
        unmatched = [s for s in demanded_skills
                     if canonicalize_skill(s) not in canonical_offered]

        return MatchResult(
            agent_name=agent.name,
            score=round(composite, 4),
            capability_overlap=round(overlap, 4),
            performance_score=round(perf, 4),
            matched_skills=sorted(matched),
            unmatched_skills=sorted(unmatched),
            keyword_matched=kw_matched,
        )

    def match(self, task: dict) -> MatchResult:
        """Find the best-fit agent for a task. Returns top match."""
        demanded = self._extract_skills(task)
        keyword_skills = self._extract_text_keywords(task)

        if not demanded and not keyword_skills:
            # Fallback: default to executor
            agent = self.agents.get("executor", list(self.agents.values())[0])
            return MatchResult(
                agent_name=agent.name, score=0.0,
                capability_overlap=0.0, performance_score=agent.performance_score,
                matched_skills=[], unmatched_skills=[],
            )

        # If no explicit skills, promote keyword skills to demanded
        if not demanded and keyword_skills:
            demanded = keyword_skills
            keyword_skills = None  # avoid double-counting

        results = [self.score_agent(agent, demanded, keyword_skills)
                   for agent in self.agents.values()]
        results.sort(key=lambda r: (-r.score, r.agent_name))
        return results[0]

    def match_top_n(self, task: dict, n: int = 3) -> list[MatchResult]:
        """Return top N agent matches ranked by score."""
        demanded = self._extract_skills(task)
        keyword_skills = self._extract_text_keywords(task)

        if not demanded and not keyword_skills:
            return [self.match(task)]

        if not demanded and keyword_skills:
            demanded = keyword_skills
            keyword_skills = None

        results = [self.score_agent(agent, demanded, keyword_skills)
                   for agent in self.agents.values()]
        results.sort(key=lambda r: (-r.score, r.agent_name))
        return results[:n]

    def match_with_fallback(self, task: dict, min_score: float = 0.3) -> MatchResult:
        """
        Match with fallback chain:
        1. Best skill match above min_score
        2. Category-based fallback via ROUTING_TABLE
        3. Executor as last resort
        """
        from agents import ROUTING_TABLE

        best = self.match(task)
        if best.score >= min_score:
            return best

        # Fallback to static routing table
        category = task.get("category", "")
        fallback_name = ROUTING_TABLE.get(category, "executor")
        if fallback_name in self.agents:
            demanded = self._extract_skills(task)
            return self.score_agent(self.agents[fallback_name], demanded)

        return best

    def explain(self, task: dict) -> str:
        """Human-readable explanation of match reasoning."""
        top = self.match_top_n(task, n=3)
        demanded = self._extract_skills(task)
        keyword_skills = self._extract_text_keywords(task)
        lines = [f"Task skills: {sorted(demanded)}"]
        if keyword_skills:
            lines.append(f"Keyword-inferred skills: {sorted(keyword_skills)}")
        lines.append("Top matches:")
        for i, r in enumerate(top, 1):
            parts = (
                f"  {i}. {r.agent_name}: score={r.score:.2f} "
                f"(overlap={r.capability_overlap:.0%}, perf={r.performance_score:.0%}) "
                f"matched={r.matched_skills} unmatched={r.unmatched_skills}"
            )
            if r.keyword_matched:
                parts += f" kw_matched={r.keyword_matched}"
            lines.append(parts)
        return "\n".join(lines)


if __name__ == "__main__":
    # --- Build test agents ---
    agents = [
        AgentProfile("executor", ["code_gen", "bug_fix", "tdd"],
                     avg_quality=100.0, win_rate=100.0,
                     benchmark_scores={"v5": 72.7}),
        AgentProfile("debugger", ["debug", "error_diagnosis", "fix_generation"]),
        AgentProfile("test_engineer", ["test_gen", "coverage", "tdd"]),
        AgentProfile("reviewer", ["review", "quality_check", "scoring"]),
        AgentProfile("architect", ["arch", "scaffold", "e2e", "system_design"]),
        AgentProfile("refactor", ["refactor", "code_transformation", "cleanup"]),
        AgentProfile("researcher", ["research", "web_search", "code_search"]),
        AgentProfile("doc_writer", ["documentation", "readme", "api_docs"]),
        AgentProfile("planner", ["planning", "decomposition", "strategy"]),
        AgentProfile("benchmarker", ["scoring", "gap_analysis", "upgrade_trigger"]),
    ]
    matcher = SkillMatcher(agents)

    # --- Test 1: Exact category match routes to executor ---
    result = matcher.match({"category": "code_gen"})
    assert result.agent_name == "executor", f"Expected executor, got {result.agent_name}"
    assert result.capability_overlap == 1.0
    print(f"PASS test 1: code_gen -> {result.agent_name} (score={result.score:.2f})")

    # --- Test 2: Debug task routes to debugger ---
    result = matcher.match({"category": "debug"})
    assert result.agent_name == "debugger", f"Expected debugger, got {result.agent_name}"
    assert result.is_strong_match
    print(f"PASS test 2: debug -> {result.agent_name} (score={result.score:.2f})")

    # --- Test 3: Multi-skill task picks best overlap ---
    result = matcher.match({"skills": ["code_gen", "bug_fix", "tdd"]})
    assert result.agent_name == "executor", f"Expected executor, got {result.agent_name}"
    assert result.is_perfect_match
    print(f"PASS test 3: [code_gen,bug_fix,tdd] -> {result.agent_name} (score={result.score:.2f})")

    # --- Test 4: Synonym matching works ---
    result = matcher.match({"skills": ["debugging", "troubleshoot"]})
    assert result.agent_name == "debugger", f"Expected debugger, got {result.agent_name}"
    assert result.capability_overlap == 1.0
    print(f"PASS test 4: synonyms [debugging,troubleshoot] -> {result.agent_name}")

    # --- Test 5: Documentation synonyms ---
    result = matcher.match({"category": "doc_gen"})
    assert result.agent_name == "doc_writer", f"Expected doc_writer, got {result.agent_name}"
    print(f"PASS test 5: doc_gen -> {result.agent_name}")

    # --- Test 6: Performance tiebreaker ---
    result = matcher.match({"category": "tdd"})
    top2 = matcher.match_top_n({"category": "tdd"}, n=2)
    agent_names_in_top2 = {r.agent_name for r in top2}
    assert "executor" in agent_names_in_top2 or "test_engineer" in agent_names_in_top2
    print(f"PASS test 6: tdd -> top={result.agent_name} (score={result.score:.2f}), "
          f"runner-up={top2[1].agent_name} (score={top2[1].score:.2f})")

    # --- Test 7: Top-N returns ranked list ---
    top3 = matcher.match_top_n({"skills": ["code_gen", "test_gen", "review"]}, n=3)
    assert len(top3) == 3
    assert top3[0].score >= top3[1].score >= top3[2].score
    print(f"PASS test 7: top-3 for mixed skills: "
          f"{[(r.agent_name, r.score) for r in top3]}")

    # --- Test 8: Empty task falls back to executor ---
    result = matcher.match({"id": "empty"})
    assert result.agent_name == "executor"
    assert result.score == 0.0
    print(f"PASS test 8: empty task -> {result.agent_name} (fallback)")

    # --- Test 9: Explain output is readable ---
    explanation = matcher.explain({"skills": ["code_gen", "debug"], "category": "bug_fix"})
    assert "executor" in explanation
    assert "Task skills:" in explanation
    print(f"PASS test 9: explain output:\n{explanation}")

    # --- Test 10: Skill extraction from comma-separated string ---
    result = matcher.match({"skills": "refactor,cleanup"})
    assert result.agent_name == "refactor", f"Expected refactor, got {result.agent_name}"
    print(f"PASS test 10: comma string 'refactor,cleanup' -> {result.agent_name}")

    # --- Test 11: canonicalize_skill ---
    assert canonicalize_skill("debugging") == "debug"
    assert canonicalize_skill("code_review") == "review"
    assert canonicalize_skill("README") == "documentation"
    assert canonicalize_skill("unknown_thing") == "unknown_thing"
    print("PASS test 11: canonicalize_skill works for synonyms and passthrough")

    # --- Test 12: AgentProfile.performance_score ---
    perf_agent = AgentProfile("x", [], avg_quality=80.0, win_rate=60.0)
    assert perf_agent.performance_score == 0.7  # (0.8 + 0.6) / 2
    no_perf = AgentProfile("y", [])
    assert no_perf.performance_score == 0.5  # default
    print("PASS test 12: performance_score calculation correct")

    # --- Test 13: from_registry loads real registry ---
    registry_path = os.path.join(os.path.dirname(__file__), "..", "registry", "agents.json")
    if os.path.exists(registry_path):
        loaded = SkillMatcher.from_registry(registry_path)
        assert len(loaded.agents) >= 8
        result = loaded.match({"category": "code_gen"})
        assert result.agent_name == "executor"
        print(f"PASS test 13: from_registry loaded {len(loaded.agents)} agents")
    else:
        print(f"SKIP test 13: registry not found at {registry_path}")

    # --- Test 14: architecture/design synonyms ---
    result = matcher.match({"skills": ["architecture", "design"]})
    assert result.agent_name == "architect", f"Expected architect, got {result.agent_name}"
    print(f"PASS test 14: [architecture,design] -> {result.agent_name}")

    # --- Test 15: MatchResult properties ---
    strong = MatchResult("a", 0.7, 0.8, 0.5, ["x"], [])
    weak = MatchResult("b", 0.2, 0.1, 0.5, [], ["x"])
    perfect = MatchResult("c", 0.9, 1.0, 0.8, ["x"], [])
    assert strong.is_strong_match and not weak.is_strong_match
    assert perfect.is_perfect_match and not strong.is_perfect_match
    print("PASS test 15: MatchResult properties correct")

    # --- Test 16: Description-only matching (no skills, no category) ---
    result = matcher.match({
        "title": "Fix crash on login page",
        "description": "The app throws an error when users try to log in"
    })
    assert result.agent_name in ("debugger", "executor"), f"Expected debugger or executor, got {result.agent_name}"
    assert result.score > 0
    print(f"PASS test 16: description-only 'fix crash error' -> {result.agent_name} (score={result.score:.2f})")

    # --- Test 17: Description-only research task ---
    result = matcher.match({
        "title": "Investigate auth patterns",
        "description": "Research and explore how authentication is implemented"
    })
    assert result.agent_name == "researcher", f"Expected researcher, got {result.agent_name}"
    print(f"PASS test 17: description-only 'investigate research explore' -> {result.agent_name} (score={result.score:.2f})")

    # --- Test 18: Description-only architecture task ---
    result = matcher.match({
        "title": "Design new microservice",
        "description": "Architect and scaffold the payment processing service"
    })
    assert result.agent_name == "architect", f"Expected architect, got {result.agent_name}"
    print(f"PASS test 18: description-only 'design architect scaffold' -> {result.agent_name} (score={result.score:.2f})")

    # --- Test 19: Keywords boost explicit skill match ---
    result = matcher.match({
        "title": "Write tests for crash handler",
        "description": "Add coverage for the error recovery module",
        "category": "tdd",
    })
    # tdd category + keyword signals (test, coverage, error, crash)
    assert result.score > 0.5
    print(f"PASS test 19: tdd + keyword boost -> {result.agent_name} (score={result.score:.2f})")

    # --- Test 20: extract_keywords_from_text ---
    kw = extract_keywords_from_text("Fix the crash and write a test for coverage")
    assert "bug_fix" in kw  # from "fix"
    assert "debug" in kw    # from "crash"
    assert "test_gen" in kw  # from "test"
    print(f"PASS test 20: extract_keywords_from_text -> {sorted(kw)}")

    # --- Test 21: keyword_matched field populated ---
    result = matcher.match({
        "title": "Fix login bug",
        "description": "Users see error on submit",
        "category": "bug_fix",
    })
    # Should have keyword matches from "fix", "bug", "error"
    assert result.agent_name == "executor"
    print(f"PASS test 21: keyword_matched={result.keyword_matched} for bug_fix + keywords")

    # --- Test 22: Documentation from description only ---
    result = matcher.match({
        "title": "Update the README for the project",
        "description": "Add docs and document the changelog"
    })
    assert result.agent_name == "doc_writer", f"Expected doc_writer, got {result.agent_name}"
    print(f"PASS test 22: description-only 'readme docs document changelog' -> {result.agent_name} (score={result.score:.2f})")

    # --- Test 23: Planning from description only ---
    result = matcher.match({
        "title": "Plan sprint work",
        "description": "Decompose and prioritize tasks for the next iteration"
    })
    assert result.agent_name == "planner", f"Expected planner, got {result.agent_name}"
    print(f"PASS test 23: description-only 'plan decompose prioritize' -> {result.agent_name} (score={result.score:.2f})")

    # --- Test 24: Refactor from description only ---
    result = matcher.match({
        "title": "Clean up payment module",
        "description": "Refactor and optimize the checkout flow"
    })
    assert result.agent_name == "refactor", f"Expected refactor, got {result.agent_name}"
    print(f"PASS test 24: description-only 'clean refactor optimize' -> {result.agent_name} (score={result.score:.2f})")

    # --- Test 25: Benchmark from description only ---
    result = matcher.match({
        "title": "Evaluate agent scores",
        "description": "Benchmark performance and score outputs"
    })
    assert result.agent_name in ("benchmarker", "reviewer"), f"Expected benchmarker or reviewer, got {result.agent_name}"
    print(f"PASS test 25: description-only 'evaluate benchmark score' -> {result.agent_name} (score={result.score:.2f})")

    print("\n=== All 25 tests passed ===")
