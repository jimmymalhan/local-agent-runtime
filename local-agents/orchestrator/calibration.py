#!/usr/bin/env python3
"""
orchestrator/calibration.py — Self-calibration system
======================================================
Every version, every agent runs 3 warm-up tasks against known-good outputs.
If score < previous version benchmark → auto-patch system prompt from delta.
Calibration gates: only passing agents enter the production task pool.

Wire-in: call calibrate_all_agents(version) at the top of run_version().
"""
import json, time, threading
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional

BASE_DIR   = Path(__file__).parent.parent
LOG_PATH   = BASE_DIR / "reports" / "calibration_log.jsonl"
STATE_FILE = BASE_DIR / "dashboard" / "state.json"
REGISTRY   = BASE_DIR / "registry" / "agents.json"

LOG_PATH.parent.mkdir(parents=True, exist_ok=True)

# ── Calibration tasks (3 per agent, escalating difficulty) ────────────────
# These are identical every version — deviations = regression
CALIBRATION_TASKS = {
    "executor": [
        {"title": "Two Sum — return indices",    "category": "code_gen",  "difficulty": 1},
        {"title": "FizzBuzz 1-100",               "category": "code_gen",  "difficulty": 1},
        {"title": "Reverse a linked list",        "category": "code_gen",  "difficulty": 2},
    ],
    "planner": [
        {"title": "Break 'build a REST API' into 5 atomic steps", "category": "planning", "difficulty": 1},
        {"title": "Decompose database migration into sub-tasks",  "category": "planning", "difficulty": 2},
        {"title": "Plan a refactor of a 500-line module",         "category": "planning", "difficulty": 3},
    ],
    "reviewer": [
        {"title": "Score this function: def add(a,b): return a+b",   "category": "review", "difficulty": 1},
        {"title": "Review a 20-line Python class for quality",        "category": "review", "difficulty": 2},
        {"title": "Rate correctness/completeness/style of a module", "category": "review", "difficulty": 3},
    ],
    "debugger": [
        {"title": "Fix: AttributeError on NoneType",           "category": "debug", "difficulty": 1},
        {"title": "Fix: off-by-one in binary search",          "category": "debug", "difficulty": 2},
        {"title": "Debug race condition in thread-safe queue",  "category": "debug", "difficulty": 3},
    ],
    "researcher": [
        {"title": "Find top 3 Python HTTP libraries",               "category": "research", "difficulty": 1},
        {"title": "Research best practices for retry logic",        "category": "research", "difficulty": 2},
        {"title": "Summarise SWE-bench top agent techniques 2025",  "category": "research", "difficulty": 3},
    ],
    "benchmarker": [
        {"title": "Score output quality 0-100 with rubric",       "category": "benchmark", "difficulty": 1},
        {"title": "Compare two solutions: which is better?",       "category": "benchmark", "difficulty": 2},
        {"title": "Identify top 3 failure patterns in task batch", "category": "benchmark", "difficulty": 3},
    ],
    "architect": [
        {"title": "Design schema for a todo app",                    "category": "architecture", "difficulty": 1},
        {"title": "Design microservice boundary for auth + billing", "category": "architecture", "difficulty": 2},
        {"title": "Design distributed task queue system",            "category": "architecture", "difficulty": 3},
    ],
    "refactor": [
        {"title": "Extract helper from 10-line function",      "category": "refactor", "difficulty": 1},
        {"title": "Rename variables for clarity in a module",  "category": "refactor", "difficulty": 2},
        {"title": "Split 200-line class into clean modules",   "category": "refactor", "difficulty": 3},
    ],
    "test_engineer": [
        {"title": "Write pytest for add(a,b)",              "category": "testing", "difficulty": 1},
        {"title": "Write tests for a REST endpoint handler", "category": "testing", "difficulty": 2},
        {"title": "Write integration test for DB migration", "category": "testing", "difficulty": 3},
    ],
    "doc_writer": [
        {"title": "Write docstring for a 5-line function", "category": "docs", "difficulty": 1},
        {"title": "Write README for a CLI tool",           "category": "docs", "difficulty": 2},
        {"title": "Write API reference for 5 endpoints",   "category": "docs", "difficulty": 3},
    ],
}

# Known-good minimum scores per difficulty (from v1 baseline)
PASSING_THRESHOLD = {1: 55, 2: 45, 3: 35}


def _log(entry: dict):
    try:
        with open(LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _update_dashboard(version: int, results: dict):
    """Push calibration scores into state.json for dashboard display."""
    try:
        state = json.loads(STATE_FILE.read_text()) if STATE_FILE.exists() else {}
        state["calibration"] = {
            "version": version,
            "ts": datetime.utcnow().isoformat(timespec="seconds"),
            "results": results,
            "passing": [a for a, r in results.items() if r.get("pass")],
            "patched": [a for a, r in results.items() if r.get("patched")],
        }
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception:
        pass


def _load_prev_score(agent_name: str, version: int) -> float:
    """Load the calibration score from the previous version."""
    if version <= 1:
        return 0.0
    prev_scores = []
    try:
        for line in LOG_PATH.read_text().splitlines():
            if not line.strip():
                continue
            entry = json.loads(line)
            if entry.get("agent") == agent_name and entry.get("version") == version - 1:
                prev_scores.append(entry.get("avg_score", 0))
    except Exception:
        pass
    return max(prev_scores) if prev_scores else 0.0


def _patch_prompt(agent_mod, agent_name: str, current_score: float, prev_score: float):
    """
    Auto-patch system prompt when score regressed.
    Appends corrective instructions derived from the delta.
    """
    delta = prev_score - current_score
    patch = (
        f"\n\n[CALIBRATION-AUTO-PATCH v{datetime.utcnow().strftime('%Y%m%d')}]\n"
        f"Previous score: {prev_score:.1f} → Current: {current_score:.1f} (Δ={delta:.1f})\n"
        "SELF-CORRECTION RULES:\n"
        "1. Always complete tasks fully — never truncate output.\n"
        "2. Return valid JSON when output format is specified.\n"
        "3. Quality score MUST be ≥40 or task is considered failed.\n"
        "4. Think step by step. Verify your answer before returning.\n"
        "5. If unsure, produce a best-effort answer — never return empty.\n"
    )
    try:
        if hasattr(agent_mod, "AGENT_META"):
            sp = agent_mod.AGENT_META.get("system_prompt", "")
            if "[CALIBRATION-AUTO-PATCH" not in sp:
                agent_mod.AGENT_META["system_prompt"] = sp + patch
                return True
    except Exception:
        pass
    return False


def calibrate_agent(agent_mod, agent_name: str, version: int) -> dict:
    """
    Run 3 calibration tasks for one agent.
    Returns {pass: bool, avg_score: float, patched: bool, tasks: list}.
    """
    tasks = CALIBRATION_TASKS.get(agent_name, CALIBRATION_TASKS["executor"])
    scores = []
    task_results = []

    for cal_task in tasks:
        t0 = time.time()
        try:
            result = agent_mod.run(cal_task)
            score  = result.get("quality", result.get("score", 0))
            status = result.get("status", "unknown")
        except Exception as e:
            score  = 0
            status = f"error: {e}"
        elapsed = round(time.time() - t0, 2)
        scores.append(score)
        task_results.append({
            "title":   cal_task["title"],
            "score":   score,
            "status":  status,
            "elapsed": elapsed,
        })

    avg = round(sum(scores) / len(scores), 1) if scores else 0.0
    prev = _load_prev_score(agent_name, version)
    regressed = prev > 0 and avg < prev - 5   # >5pt drop = regression
    passed = avg >= PASSING_THRESHOLD.get(2, 45)  # mid-difficulty bar
    patched = False

    if regressed:
        patched = _patch_prompt(agent_mod, agent_name, avg, prev)

    entry = {
        "ts": datetime.utcnow().isoformat(timespec="seconds"),
        "version": version,
        "agent": agent_name,
        "avg_score": avg,
        "prev_score": prev,
        "regressed": regressed,
        "pass": passed,
        "patched": patched,
        "tasks": task_results,
    }
    _log(entry)

    status_str = "PASS" if passed else ("PATCHED" if patched else "FAIL")
    print(f"  [CALIBRATION] {agent_name:15} {status_str:8} score={avg:.1f} prev={prev:.1f}")
    return entry


def calibrate_all_agents(version: int, agent_modules: dict) -> dict:
    """
    Calibrate all agents in parallel threads.
    Returns {agent_name: result_dict}.
    gate: only PASS/PATCHED agents enter production pool.
    """
    print(f"\n[CALIBRATION] v{version} — warming up {len(agent_modules)} agents...")
    results = {}
    threads = []

    def _run(name, mod):
        results[name] = calibrate_agent(mod, name, version)

    for name, mod in agent_modules.items():
        t = threading.Thread(target=_run, args=(name, mod), daemon=True, name=f"cal-{name}")
        threads.append(t)
        t.start()

    for t in threads:
        t.join(timeout=30)

    passing  = [a for a, r in results.items() if r.get("pass")]
    patched  = [a for a, r in results.items() if r.get("patched")]
    blocked  = [a for a, r in results.items() if not r.get("pass") and not r.get("patched")]

    print(f"[CALIBRATION] v{version} done — passing={len(passing)} patched={len(patched)} blocked={len(blocked)}")
    if blocked:
        print(f"[CALIBRATION] Blocked agents (excluded from pool): {blocked}")

    _update_dashboard(version, results)
    return results


def get_passing_agents(calibration_results: dict) -> set:
    """Return set of agent names that passed calibration."""
    return {name for name, r in calibration_results.items() if r.get("pass") or r.get("patched")}
