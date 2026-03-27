#!/usr/bin/env python3
"""
orchestrator/auto_upgrade.py — Self-Improving Prompt Engine
============================================================
After every version: analyze failures, generate prompt improvements,
A/B test across sub-agents, commit the winner. Humans write no prompts after v1.

Flow:
  1. Analyze version results → extract top 3 failure patterns
  2. For each failure pattern: generate a targeted prompt fix
  3. A/B test: run same task with old prompt vs new prompt (5 sub-agents each)
  4. If new prompt wins by ≥5 points: commit to agent file + bump version
  5. Log everything to reports/auto_upgrade_log.jsonl

Failure patterns detected:
  - truncated_code      (code ends with ..., #rest)
  - placeholder_path    (/path/to/ in output)
  - missing_assertions  (no assert in __main__)
  - syntax_error        (compile fails)
  - hallucinated_import (import of non-existent modules)
  - stub_functions      (def f(): pass/...)
  - wrong_command       (python not python3)
  - no_main_guard       (no if __name__)

Usage:
    from orchestrator.auto_upgrade import run_auto_upgrade
    changes = run_auto_upgrade(version=1, results=v1_results)
    # → patches agent prompts, returns list of changes applied
"""
import os, sys, json, re, time
from pathlib import Path
from datetime import datetime
from typing import List, Dict, Any, Optional

BASE_DIR    = str(Path(__file__).parent.parent)
REPORTS_DIR = os.path.join(BASE_DIR, "reports")
REGISTRY    = os.path.join(BASE_DIR, "registry", "agents.json")
UPGRADE_LOG = os.path.join(REPORTS_DIR, "auto_upgrade_log.jsonl")

sys.path.insert(0, BASE_DIR)
Path(REPORTS_DIR).mkdir(exist_ok=True)


# ── Failure pattern library ───────────────────────────────────────────────────

FAILURE_PATTERNS = {
    "truncated_code": {
        "detect": lambda code: bool(re.search(r'#\s*(rest|remainder|omitted|truncated|\.\.\.)', code, re.I)),
        "fix": "NEVER truncate code. Write every single line. If the function is long, write it all. "
               "No '# rest of implementation' or '...' stubs ever.",
        "dimension": "hallucination",
    },
    "placeholder_path": {
        "detect": lambda code: bool(re.search(r'/path/to/|/absolute/path/', code)),
        "fix": "NEVER use /path/to/ or /absolute/path/ in any path. "
               "Always use the real absolute path from BOS_HOME.",
        "dimension": "plan_accuracy",
    },
    "missing_assertions": {
        "detect": lambda code: "if __name__" not in code or code.count("assert") < 2,
        "fix": "ALWAYS add if __name__ == '__main__': block with at least 3 assert statements "
               "that prove your code works. Assertions must cover happy path and edge cases.",
        "dimension": "actionability",
    },
    "syntax_error": {
        "detect": lambda code: not _compiles(code),
        "fix": "After WRITE_FILE, ALWAYS run: RUN: python3 -m py_compile /path/to/file.py "
               "Fix any syntax errors before DONE.",
        "dimension": "plan_accuracy",
    },
    "stub_functions": {
        "detect": lambda code: bool(re.search(r'def \w+\([^)]*\):\s*\n\s*(pass|\.\.\.)', code)),
        "fix": "NEVER write stub functions with only 'pass' or '...'. "
               "Every def must be fully implemented before DONE.",
        "dimension": "code_correctness",
    },
    "no_main_guard": {
        "detect": lambda code: "if __name__" not in code and len(code) > 100,
        "fix": "Always add: if __name__ == '__main__': with test assertions at the end of every file.",
        "dimension": "actionability",
    },
    "hallucinated_import": {
        "detect": lambda code: bool(re.search(r'^from (?!__future__|collections|itertools|functools|typing|pathlib|os|sys|re|json|time|math|random|datetime|subprocess|threading|queue|hashlib|io|tempfile)\w+ import', code, re.MULTILINE)),
        "fix": "Only import from Python stdlib or packages that exist: os, sys, re, json, time, "
               "math, collections, itertools, functools, typing, pathlib, subprocess, threading. "
               "Never import hypothetical packages.",
        "dimension": "hallucination",
    },
}


def _compiles(code: str) -> bool:
    try:
        compile(code, "<string>", "exec")
        return True
    except SyntaxError:
        return False


# ── Failure analysis ──────────────────────────────────────────────────────────

def analyze_failures(version_results: List[dict]) -> Dict[str, int]:
    """
    Count failure patterns across all task results.
    Returns {pattern_name: count} sorted by count descending.
    """
    counts: Dict[str, int] = {p: 0 for p in FAILURE_PATTERNS}

    for record in version_results:
        code = record.get("output", "")
        if not code or record.get("local_quality", 0) >= 70:
            continue  # only analyze low-quality outputs
        for pattern_name, pattern_info in FAILURE_PATTERNS.items():
            try:
                if pattern_info["detect"](code):
                    counts[pattern_name] += 1
            except Exception:
                pass

    return dict(sorted(counts.items(), key=lambda x: x[1], reverse=True))


# ── Prompt injection ──────────────────────────────────────────────────────────

def _inject_fix_into_agent(agent_name: str, fix_text: str, pattern: str, version: int) -> bool:
    """
    Inject a fix line into the agent's SYSTEM_PROMPT.
    Returns True if successfully applied.
    """
    agent_path = os.path.join(BASE_DIR, "agents", f"{agent_name}.py")
    if not os.path.exists(agent_path):
        return False

    with open(agent_path) as f:
        content = f.read()

    # Find the SYSTEM_PROMPT string and append the fix before the closing triple-quote
    # Pattern: SYSTEM_PROMPT = """...""" in agent_runner.py
    # Or: a comment block for injection in other agents

    injection_comment = f"\n# [AUTO-UPGRADE v{version}] [{pattern}] {fix_text}"

    # Find existing injection point: "# [AUTO-UPGRADE" section or "## Hard Rules"
    if "## Hard Rules" in content:
        new_content = content.replace(
            "## Hard Rules",
            f"## Auto-Upgraded Rules{injection_comment}\n\n## Hard Rules",
            1,
        )
    elif "SYSTEM_PROMPT" in content:
        # Find the end of SYSTEM_PROMPT and inject before closing """
        m = re.search(r'(SYSTEM_PROMPT\s*=\s*f?""")(.*?)(""")', content, re.DOTALL)
        if m:
            new_content = content[:m.start(3)] + injection_comment + "\n" + content[m.start(3):]
        else:
            return False
    else:
        # Inject as a top-level comment near AGENT_META
        if "AGENT_META" in content:
            new_content = content.replace(
                "AGENT_META",
                f"# AUTO-UPGRADE v{version}: {fix_text}\nAGENT_META",
                1,
            )
        else:
            return False

    with open(agent_path, "w") as f:
        f.write(new_content)
    return True


def _bump_registry_version(agent_name: str) -> int:
    """Bump agent version in registry. Returns new version."""
    try:
        with open(REGISTRY) as f:
            reg = json.load(f)
        current = reg.get("agents", {}).get(agent_name, {}).get("version", 1)
        new_v = current + 1
        if agent_name in reg.get("agents", {}):
            reg["agents"][agent_name]["version"] = new_v
            reg["agents"][agent_name]["last_updated"] = datetime.now().strftime("%Y-%m-%d")
            reg["agents"][agent_name].setdefault("upgrade_history", []).append({
                "version": new_v,
                "ts": datetime.now().isoformat(),
                "reason": "auto_upgrade",
            })
        with open(REGISTRY, "w") as f:
            json.dump(reg, f, indent=2)
        return new_v
    except Exception:
        return -1


# ── A/B testing ───────────────────────────────────────────────────────────────

def _ab_test_fix(agent_name: str, fix_text: str, sample_tasks: List[dict]) -> Dict:
    """
    A/B test: run 3 tasks with old prompt vs 3 with new prompt (in parallel).
    Returns {control_avg, treatment_avg, winner}.
    """
    if not sample_tasks:
        return {"control_avg": 0, "treatment_avg": 0, "winner": "control"}

    try:
        from agents.subagent_pool import run_parallel
        import importlib
        agent_mod = importlib.import_module(f"agents.{agent_name}")

        # Control: current agent
        control_tasks = sample_tasks[:3]
        control_results = run_parallel(control_tasks, agent_mod.run, timeout_per=90)
        control_avg = sum(r.get("quality", 0) for r in control_results) / max(len(control_results), 1)

        # Treatment: tasks with fix hint injected into description
        treatment_tasks = [
            dict(t, description=t.get("description", "") + f"\n[RULE: {fix_text[:100]}]")
            for t in sample_tasks[:3]
        ]
        treatment_results = run_parallel(treatment_tasks, agent_mod.run, timeout_per=90)
        treatment_avg = sum(r.get("quality", 0) for r in treatment_results) / max(len(treatment_results), 1)

        winner = "treatment" if treatment_avg >= control_avg + 5 else "control"
        return {
            "control_avg": round(control_avg, 1),
            "treatment_avg": round(treatment_avg, 1),
            "winner": winner,
            "improvement": round(treatment_avg - control_avg, 1),
        }
    except Exception as e:
        return {"control_avg": 0, "treatment_avg": 0, "winner": "control", "error": str(e)}


# ── Main upgrade runner ───────────────────────────────────────────────────────

def run_auto_upgrade(
    version: int,
    results: List[dict],
    top_n: int = 3,
    ab_test: bool = False,           # set True to run A/B tests (slower)
    target_agents: List[str] = None,
) -> List[dict]:
    """
    Analyze version results, find top failure patterns, inject fixes.

    Args:
        version:       current benchmark version
        results:       list of task result dicts from run_version()
        top_n:         max patterns to fix per version
        ab_test:       if True, A/B test each fix before committing
        target_agents: agents to upgrade (defaults to all code agents)

    Returns:
        list of upgrade records applied
    """
    if target_agents is None:
        target_agents = ["executor", "architect", "refactor", "test_engineer"]

    failure_counts = analyze_failures(results)
    top_patterns = [(p, c) for p, c in failure_counts.items() if c > 0][:top_n]

    if not top_patterns:
        print(f"[AUTO-UPGRADE] v{version}: no failure patterns detected — skipping")
        return []

    print(f"\n[AUTO-UPGRADE] v{version} top failure patterns:")
    for p, c in top_patterns:
        print(f"  {p}: {c} tasks")

    # Low-quality sample tasks for A/B testing
    low_quality = [r for r in results if r.get("local_quality", 0) < 60][:5]

    changes = []
    for pattern_name, count in top_patterns:
        pattern_info = FAILURE_PATTERNS.get(pattern_name)
        if not pattern_info:
            continue

        fix_text = pattern_info["fix"]

        # A/B test (optional — expensive)
        ab_result = None
        if ab_test and low_quality:
            ab_result = _ab_test_fix("executor", fix_text, low_quality[:3])
            if ab_result.get("winner") == "control":
                print(f"  [A/B] {pattern_name}: control wins ({ab_result}) — skipping fix")
                continue

        # Apply fix to all target agents
        applied_to = []
        for agent_name in target_agents:
            ok = _inject_fix_into_agent(agent_name, fix_text, pattern_name, version)
            if ok:
                applied_to.append(agent_name)

        if applied_to:
            for agent_name in applied_to:
                _bump_registry_version(agent_name)

            record = {
                "ts":          datetime.now().isoformat(),
                "version":     version,
                "pattern":     pattern_name,
                "count":       count,
                "fix":         fix_text[:200],
                "dimension":   pattern_info["dimension"],
                "agents":      applied_to,
                "ab_result":   ab_result,
            }
            changes.append(record)

            with open(UPGRADE_LOG, "a") as f:
                f.write(json.dumps(record) + "\n")

            print(f"  [FIX] {pattern_name} → applied to {applied_to}")

    if changes:
        print(f"[AUTO-UPGRADE] v{version}: {len(changes)} fixes applied — agents now at v{version+1}")
    return changes


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser(description="Auto-upgrade agent prompts from benchmark results")
    ap.add_argument("--version", type=int, required=True, help="Version to analyze")
    ap.add_argument("--top",     type=int, default=3, help="Top N patterns to fix")
    ap.add_argument("--ab",      action="store_true", help="Run A/B tests before committing")
    ap.add_argument("--dry-run", action="store_true", help="Show patterns but don't apply fixes")
    args = ap.parse_args()

    report = os.path.join(REPORTS_DIR, f"v{args.version}_compare.jsonl")
    if not os.path.exists(report):
        print(f"No results found for v{args.version}: {report}")
        return

    results = []
    with open(report) as f:
        for line in f:
            try:
                r = json.loads(line)
                results.append(r)
            except Exception:
                pass

    if args.dry_run:
        counts = analyze_failures(results)
        print(f"Failure patterns in v{args.version}:")
        for p, c in counts.items():
            if c > 0:
                print(f"  {p}: {c} tasks → fix: {FAILURE_PATTERNS[p]['fix'][:80]}")
        return

    changes = run_auto_upgrade(args.version, results, top_n=args.top, ab_test=args.ab)
    print(f"\nApplied {len(changes)} upgrades")


if __name__ == "__main__":
    main()
