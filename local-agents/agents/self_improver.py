"""
self_improver.py — Self-improving agent system.

After N completed tasks, analyzes success/failure patterns and improves
agent prompts. Tracks quality delta per prompt version. A/B tests improvements.

The path to beating Opus 4.6: systematic learning from every task.

Usage:
    from agents.self_improver import SelfImprover
    improver = SelfImprover()
    improver.analyze_and_improve(min_samples=20)
"""
import json
import argparse
import uuid
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Optional

# ---------------------------------------------------------------------------
# Paths
# ---------------------------------------------------------------------------
_BASE = Path(__file__).parent.parent  # local-agents/
REPORTS_DIR = _BASE / "reports"
SKILLS_DIR = _BASE.parent / ".claude" / "skills"

EPISODIC_GLOB = "*.jsonl"
AB_TESTS_FILE = REPORTS_DIR / "ab_tests.json"
IMPROVEMENTS_FILE = REPORTS_DIR / "improvements.jsonl"

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _load_tasks(last_n: int = 100) -> list[dict]:
    """
    Read up to last_n task records from all *.jsonl files in reports/.
    Each record is expected to have at minimum: category, quality.
    """
    records: list[dict] = []
    for jl in sorted(REPORTS_DIR.glob(EPISODIC_GLOB)):
        try:
            lines = jl.read_text().splitlines()
            for line in lines:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                    # Only keep records that look like task results
                    # (must have both 'category' and a quality field)
                    if "category" not in rec:
                        continue
                    if rec.get("quality") is None and rec.get("quality_score") is None:
                        continue
                    records.append(rec)
                except json.JSONDecodeError:
                    continue
        except OSError:
            continue
    # newest-first, then cap
    records.sort(key=lambda r: r.get("ts", ""), reverse=True)
    return records[:last_n]


def _skill_file_for(agent_name: str) -> Optional[Path]:
    """Return the first matching skill file, or None."""
    candidates = list(SKILLS_DIR.glob(f"{agent_name}*.md"))
    if candidates:
        return candidates[0]
    # fallback: quality-rubric is the general skill
    generic = SKILLS_DIR / "quality-rubric.md"
    return generic if generic.exists() else None


def _load_ab_tests() -> dict:
    if AB_TESTS_FILE.exists():
        try:
            return json.loads(AB_TESTS_FILE.read_text())
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def _save_ab_tests(data: dict) -> None:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    AB_TESTS_FILE.write_text(json.dumps(data, indent=2))


# ---------------------------------------------------------------------------
# Main class
# ---------------------------------------------------------------------------

class SelfImprover:
    """
    Analyzes task results across all agents, identifies what works and what
    doesn't, then surgically updates .claude/skills/ files with learned
    patterns so future runs benefit from that knowledge.
    """

    def __init__(self, reports_dir: Path = REPORTS_DIR, skills_dir: Path = SKILLS_DIR):
        self.reports_dir = reports_dir
        self.skills_dir = skills_dir

    # ------------------------------------------------------------------
    # 1. Failure analysis
    # ------------------------------------------------------------------

    def analyze_failures(self, category: str = None) -> dict:
        """
        Read last 100 tasks, find quality < 60, group by category.

        Returns:
            {
                category: {
                    failure_count: int,
                    common_issues: list[str],
                    suggested_fixes: list[str],
                }
            }
        """
        tasks = _load_tasks(100)
        failures: dict[str, list[dict]] = defaultdict(list)

        for t in tasks:
            q = t.get("quality") or t.get("quality_score") or 0
            try:
                q = int(q)
            except (TypeError, ValueError):
                q = 0
            cat = t.get("category", "unknown")
            if category and cat != category:
                continue
            if q < 60:
                failures[cat].append(t)

        result = {}
        for cat, records in failures.items():
            # Collect clues from status/error fields
            error_types: dict[str, int] = defaultdict(int)
            for r in records:
                status = r.get("status", "")
                if status and status != "done":
                    error_types[status] += 1
                err = r.get("error") or r.get("error_type") or ""
                if err:
                    error_types[str(err)[:80]] += 1

            common_issues = [
                f"status={k} occurred {v}x" for k, v in
                sorted(error_types.items(), key=lambda x: -x[1])
            ] or ["output quality scored below threshold (quality < 60)"]

            avg_q = sum(
                int(r.get("quality") or r.get("quality_score") or 0)
                for r in records
            ) / max(len(records), 1)

            suggested_fixes = [
                f"Average quality was {avg_q:.1f}/100 — add explicit output format instructions",
                "Include worked example in prompt for this category",
                "Add verification step: assert output satisfies task description",
                "Increase context window usage: pass full description, not summary",
            ]

            result[cat] = {
                "failure_count": len(records),
                "common_issues": common_issues,
                "suggested_fixes": suggested_fixes,
            }

        return result

    # ------------------------------------------------------------------
    # 2. Success analysis
    # ------------------------------------------------------------------

    def analyze_successes(self, category: str = None) -> dict:
        """
        Find tasks with quality >= 85, extract winning prompt patterns.

        Returns:
            {
                category: {
                    success_count: int,
                    winning_patterns: list[str],
                }
            }
        """
        tasks = _load_tasks(100)
        successes: dict[str, list[dict]] = defaultdict(list)

        for t in tasks:
            q = t.get("quality") or t.get("quality_score") or 0
            try:
                q = int(q)
            except (TypeError, ValueError):
                q = 0
            cat = t.get("category", "unknown")
            if category and cat != category:
                continue
            if q >= 85:
                successes[cat].append(t)

        result = {}
        for cat, records in successes.items():
            avg_q = sum(
                int(r.get("quality") or r.get("quality_score") or 0)
                for r in records
            ) / max(len(records), 1)

            # Look for fast tasks (good signal: model was confident)
            fast = [r for r in records if float(r.get("elapsed_s", 999)) < 30]
            slow = [r for r in records if float(r.get("elapsed_s", 999)) >= 30]

            patterns = [
                f"Average quality {avg_q:.1f}/100 across {len(records)} tasks",
            ]
            if fast:
                patterns.append(
                    f"{len(fast)}/{len(records)} tasks completed in <30s "
                    f"— concise, well-scoped prompts correlate with speed+quality"
                )
            if slow:
                patterns.append(
                    f"{len(slow)} tasks needed >30s — consider breaking into subtasks"
                )
            if len(records) >= 5:
                patterns.append(
                    "High volume of successes: this category is well-handled; "
                    "prioritize similar prompt structure for edge cases"
                )

            result[cat] = {
                "success_count": len(records),
                "winning_patterns": patterns,
            }

        return result

    # ------------------------------------------------------------------
    # 3. Generate prompt improvement text
    # ------------------------------------------------------------------

    def generate_prompt_improvement(self, agent_name: str, analysis: dict) -> str:
        """
        Given combined failure+success analysis keyed by category, produce
        a markdown block to append/update in the agent's skill file.

        analysis expected shape:
            {
                category: {
                    failure_count, common_issues, suggested_fixes,   # from failures
                    success_count, winning_patterns,                  # from successes
                }
            }
        """
        today = str(date.today())
        lines = [
            f"## Learned Patterns (auto-updated {today})",
            "",
        ]

        for cat, data in sorted(analysis.items()):
            lines.append(f"### Category: {cat}")
            lines.append("")

            wins = data.get("winning_patterns", [])
            if wins:
                lines.append(f"#### What works for {cat}:")
                for w in wins:
                    lines.append(f"- {w}")
                lines.append("")

            issues = data.get("common_issues", [])
            if issues:
                lines.append("#### Common pitfalls to avoid:")
                for i in issues:
                    lines.append(f"- {i}")
                lines.append("")

            fixes = data.get("suggested_fixes", [])
            if fixes:
                lines.append("#### Context that helps:")
                for f_ in fixes:
                    lines.append(f"- {f_}")
                lines.append("")

        return "\n".join(lines)

    # ------------------------------------------------------------------
    # 4. Update skill file
    # ------------------------------------------------------------------

    def update_skill_file(self, agent_name: str, improvement: str) -> None:
        """
        Append (or replace) the '## Learned Patterns' section in the
        agent's skill file.  Creates a generic learned-patterns file if
        no matching skill exists.
        """
        skill_path = _skill_file_for(agent_name)
        if skill_path is None:
            # Create a minimal learned-patterns file under skills/
            skill_path = self.skills_dir / f"{agent_name}-learned.md"
            skill_path.write_text(f"# {agent_name} — Learned Patterns\n\n")

        content = skill_path.read_text()
        marker = "## Learned Patterns"

        if marker in content:
            # Replace everything from marker to end-of-file
            idx = content.index(marker)
            content = content[:idx] + improvement + "\n"
        else:
            # Append with separator
            content = content.rstrip("\n") + "\n\n" + improvement + "\n"

        skill_path.write_text(content)
        print(f"  Updated skill: {skill_path.relative_to(self.skills_dir.parent.parent)}")

    # ------------------------------------------------------------------
    # 5. A/B test setup
    # ------------------------------------------------------------------

    def ab_test_setup(self, agent_name: str, variant_prompt: str) -> str:
        """
        Register a new A/B test.  A = current skill file content,
        B = variant_prompt.  Returns test_id.
        """
        tests = _load_ab_tests()
        test_id = str(uuid.uuid4())[:8]

        skill_path = _skill_file_for(agent_name)
        current_content = skill_path.read_text() if skill_path else ""

        tests[test_id] = {
            "agent": agent_name,
            "A": current_content,
            "B": variant_prompt,
            "A_results": [],  # list of quality scores
            "B_results": [],
            "status": "running",
        }
        _save_ab_tests(tests)
        print(f"  A/B test registered: id={test_id} agent={agent_name}")
        return test_id

    # ------------------------------------------------------------------
    # 6. A/B test evaluation
    # ------------------------------------------------------------------

    def ab_test_evaluate(self, test_id: str) -> dict:
        """
        Compare A vs B quality scores after min 20 tasks each.

        Returns:
            {winner, quality_delta, confidence, recommendation}
        """
        tests = _load_ab_tests()
        if test_id not in tests:
            return {"error": f"test_id {test_id!r} not found"}

        t = tests[test_id]
        a_scores = [float(x) for x in t.get("A_results", [])]
        b_scores = [float(x) for x in t.get("B_results", [])]

        if len(a_scores) < 20 or len(b_scores) < 20:
            return {
                "winner": None,
                "quality_delta": None,
                "confidence": 0.0,
                "recommendation": (
                    f"Not enough data yet — "
                    f"A has {len(a_scores)} tasks, B has {len(b_scores)} tasks "
                    f"(need 20 each)"
                ),
            }

        avg_a = sum(a_scores) / len(a_scores)
        avg_b = sum(b_scores) / len(b_scores)
        delta = avg_b - avg_a

        # Simple confidence proxy: |delta| / pooled_std, capped at [0,1]
        all_vals = a_scores + b_scores
        mean_all = sum(all_vals) / len(all_vals)
        variance = sum((x - mean_all) ** 2 for x in all_vals) / len(all_vals)
        std = variance ** 0.5 or 1.0
        confidence = min(abs(delta) / std, 1.0)

        winner = "B" if delta > 0 else "A"
        recommendation = (
            f"Variant {'B' if winner == 'B' else 'A'} wins by {abs(delta):.1f} quality points "
            f"(confidence={confidence:.2f}). "
            + (
                "Promote B with promote_winner()."
                if winner == "B" and confidence > 0.7
                else "Delta too small or confidence too low — keep A."
            )
        )

        return {
            "winner": winner,
            "quality_delta": round(delta, 2),
            "confidence": round(confidence, 3),
            "recommendation": recommendation,
        }

    # ------------------------------------------------------------------
    # 7. Promote winning variant
    # ------------------------------------------------------------------

    def promote_winner(self, test_id: str) -> None:
        """
        If B wins with confidence > 0.7, replace skill file with B variant
        and log to improvements.jsonl.
        """
        evaluation = self.ab_test_evaluate(test_id)
        tests = _load_ab_tests()

        if test_id not in tests:
            print(f"  [skip] test_id {test_id!r} not found")
            return

        t = tests[test_id]
        agent_name = t["agent"]

        if evaluation.get("winner") != "B":
            print(f"  [skip] A is still better or inconclusive for {agent_name}")
            return

        if evaluation.get("confidence", 0.0) <= 0.7:
            print(
                f"  [skip] Confidence {evaluation['confidence']:.2f} <= 0.7 "
                f"— not promoting yet"
            )
            return

        # Write B to skill file
        skill_path = _skill_file_for(agent_name)
        if skill_path is None:
            skill_path = self.skills_dir / f"{agent_name}-learned.md"

        skill_path.write_text(t["B"])
        print(f"  Promoted B → {skill_path.name}")

        # Mark test as done
        tests[test_id]["status"] = "promoted"
        _save_ab_tests(tests)

        # Log to improvements.jsonl
        REPORTS_DIR.mkdir(parents=True, exist_ok=True)
        record = {
            "ts": str(date.today()),
            "test_id": test_id,
            "agent": agent_name,
            "winner": "B",
            "quality_delta": evaluation.get("quality_delta"),
            "confidence": evaluation.get("confidence"),
        }
        with IMPROVEMENTS_FILE.open("a") as fh:
            fh.write(json.dumps(record) + "\n")
        print(f"  Logged to {IMPROVEMENTS_FILE.name}")

    # ------------------------------------------------------------------
    # 8. High-level entry point
    # ------------------------------------------------------------------

    def run(self, min_samples: int = 20) -> None:
        """
        Main entry: analyze all agents, generate improvements, update skill files.
        Prints a human-readable summary.
        """
        tasks = _load_tasks(100)
        print(f"Self-improvement analysis")
        print(f"  Tasks loaded: {len(tasks)}")

        if len(tasks) < min_samples:
            print(
                f"  [skip] Only {len(tasks)} task records found; "
                f"need at least {min_samples}. Run more tasks first."
            )
            return

        failures = self.analyze_failures()
        successes = self.analyze_successes()

        # Merge by category
        all_categories = set(failures) | set(successes)
        if not all_categories:
            print("  No actionable data found.")
            return

        # Group categories by the agent that handles them
        category_to_agent: dict[str, str] = {}
        try:
            # Try to import the routing table from the package (__init__.py)
            import importlib
            _rt_mod = importlib.import_module("agents")
            category_to_agent = getattr(_rt_mod, "ROUTING_TABLE", {})
        except Exception:
            pass
        if not category_to_agent:
            # Inline fallback — mirrors agents/__init__.py ROUTING_TABLE
            category_to_agent = {
                "code_gen": "executor", "bug_fix": "executor", "tdd": "test_engineer",
                "scaffold": "architect", "e2e": "architect", "arch": "architect",
                "refactor": "refactor", "research": "researcher", "doc": "doc_writer",
                "documentation": "doc_writer", "review": "reviewer", "debug": "debugger",
                "plan": "planner", "benchmark": "benchmarker",
            }

        # Build per-agent combined analysis
        agent_analysis: dict[str, dict] = defaultdict(dict)
        for cat in all_categories:
            agent = category_to_agent.get(cat, "executor")
            merged: dict = {}
            if cat in failures:
                merged.update(failures[cat])
            if cat in successes:
                merged.update(successes[cat])
            agent_analysis[agent][cat] = merged

        print(f"  Agents to update: {sorted(agent_analysis.keys())}")
        print()

        updated = []
        for agent_name, analysis in agent_analysis.items():
            total_failures = sum(
                v.get("failure_count", 0) for v in analysis.values()
            )
            total_successes = sum(
                v.get("success_count", 0) for v in analysis.values()
            )
            improvement_text = self.generate_prompt_improvement(agent_name, analysis)
            self.update_skill_file(agent_name, improvement_text)
            updated.append(
                f"  {agent_name}: {total_successes} successes, {total_failures} failures"
            )

        print("\nSummary of changes:")
        for line in updated:
            print(line)
        print(f"\nDone. Check .claude/skills/ for updates.")


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the self-improvement analysis cycle."
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=20,
        help="Minimum number of task records required before improving (default: 20)",
    )
    args = parser.parse_args()

    improver = SelfImprover()
    improver.run(min_samples=args.min_samples)


if __name__ == "__main__":
    main()
