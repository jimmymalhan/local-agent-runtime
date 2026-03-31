#!/usr/bin/env python3
"""
reviewer.py — Code review and quality scoring agent
====================================================
Reviews code output from executor/architect. Scores 0-100 across:
  correctness, completeness, style, error handling, testability.

Entry point: run(task) -> dict
"""
import os, sys, json, re, time
from pathlib import Path

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "reviewer",
    "version": 1,
    "capabilities": ["review", "quality_check", "scoring"],
    "model": "nexus-local",
    "input_schema": {
        "id": "int", "title": "str", "description": "str",
        "category": "str", "code": "str",  # code to review
    },
    "output_schema": {
        "status": "str",
        "score": "int",        # 0-100
        "breakdown": "dict",   # {correctness, completeness, style, error_handling, testability}
        "issues": "list",
        "verdict": "str",      # pass | fail | needs_work
        "quality": "int",
        "tokens_used": "int",
        "elapsed_s": "float",
    },
    "benchmark_score": None,
}

NEXUS_API   = os.environ.get("NEXUS_API", "")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "nexus-local")


def _static_score(code: str, task_title: str) -> dict:
    """
    Composite quality scoring using benchmark-against-quality-v2 rubric.

    Dimensions and weights (from benchmark-against-quality-v2.md):
      plan_accuracy    (30%) — correct paths, real imports, no placeholders
      code_correctness (25%) — syntax valid, functions implemented, correct logic
      hallucination    (25%) — no fabricated paths, no TODO stubs, no "..."
      actionability    (20%) — runnable, has __main__, assertions prove correctness

    composite = (plan*0.30) + (code*0.25) + (hallucination*0.25) + (actionability*0.20)
    """
    issues = []

    if not code or len(code) < 30:
        issues.append("Output is empty or too short")
        return {"score": 0, "breakdown": {}, "issues": issues}

    # ── Dimension 1: Plan Accuracy (30%) ─────────────────────────────────────
    no_placeholder_paths = "/path/to/" not in code and "path/to/file" not in code
    no_syntax_err = True
    try:
        compile(code, "<string>", "exec")
    except SyntaxError as e:
        no_syntax_err = False
        issues.append(f"SyntaxError: {e}")
    has_real_imports = bool(re.search(r'^(import|from)\s+\w', code, re.MULTILINE))
    covers_task = any(kw in code.lower() for kw in task_title.lower().split()[:3])

    plan_score = (
        35 * int(no_placeholder_paths) +
        35 * int(no_syntax_err) +
        15 * int(has_real_imports) +
        15 * int(covers_task)
    )

    # ── Dimension 2: Code Correctness (25%) ───────────────────────────────────
    has_def     = bool(re.search(r'\bdef \w+', code))
    has_return  = "return" in code
    func_count  = len(re.findall(r'\bdef \w+', code))
    has_logic   = bool(re.search(r'\bif\b|\bfor\b|\bwhile\b', code))
    no_stubs    = "pass" not in code or func_count > 1  # single pass is usually ok in loop body

    code_score = (
        25 * int(has_def) +
        20 * int(has_return) +
        20 * int(no_syntax_err) +
        20 * int(has_logic) +
        15 * int(no_stubs)
    )

    # ── Dimension 3: Hallucination Rate (25%) ─────────────────────────────────
    has_todos     = bool(re.search(r'#\s*TODO|\.\.\.', code))
    has_fake_refs = bool(re.search(r'/path/to/|fake_|mock_path|example\.com', code))
    has_truncation = bool(re.search(r'#\s*(rest|remainder|omitted|truncated)', code, re.I))
    stub_funcs    = len(re.findall(r'def \w+\([^)]*\):\s*\n\s*(pass|\.\.\.)', code))

    halluc_score = 100
    if has_todos:
        halluc_score -= 30
        issues.append("Contains TODO stubs")
    if has_fake_refs:
        halluc_score -= 40
        issues.append("Contains placeholder/fake paths")
    if has_truncation:
        halluc_score -= 30
        issues.append("Code appears truncated")
    if stub_funcs > 0:
        halluc_score -= min(40, stub_funcs * 20)
        issues.append(f"{stub_funcs} stub function(s) with only pass/...")
    halluc_score = max(0, halluc_score)

    # ── Dimension 4: Actionability (20%) ──────────────────────────────────────
    has_main_guard  = 'if __name__' in code
    has_assertions  = bool(re.search(r'\bassert\b', code))
    assert_count    = len(re.findall(r'\bassert\b', code))
    has_type_hints  = bool(re.search(r'->\s*\w+|:\s*(int|str|float|bool|list|dict)', code))
    has_docstring   = '"""' in code or "'''" in code

    action_score = (
        30 * int(has_main_guard) +
        30 * int(has_assertions) +
        min(20, assert_count * 5) +
        10 * int(has_type_hints) +
        10 * int(has_docstring)
    )

    # ── Composite ─────────────────────────────────────────────────────────────
    composite = round(
        plan_score * 0.30 +
        code_score * 0.25 +
        halluc_score * 0.25 +
        action_score * 0.20
    )

    breakdown = {
        "plan_accuracy":   round(plan_score),
        "code_correctness": round(code_score),
        "hallucination":   round(halluc_score),
        "actionability":   round(action_score),
        "composite":       composite,
    }

    # Threshold flags
    for dim, val in breakdown.items():
        if dim != "composite" and val < 50:
            issues.append(f"WEAK {dim}: {val}/100 (threshold: 60)")

    return {"score": composite, "breakdown": breakdown, "issues": issues}


def _dynamic_score(code: str) -> dict:
    """
    Run the code and score based on actual execution.
    Returns {exec_score, issues, assertions_passed, ran_ok}
    """
    import subprocess, tempfile, os as _os
    if not code or len(code) < 30:
        return {"exec_score": 0, "ran_ok": False, "assertions_passed": 0, "issues": []}

    issues = []
    exec_score = 0

    # Write to temp file and execute
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(code)
        tmp_path = f.name

    try:
        # 1. Compile check (+20)
        cr = subprocess.run(
            ["python3", "-m", "py_compile", tmp_path],
            capture_output=True, text=True, timeout=10
        )
        if cr.returncode == 0:
            exec_score += 20
        else:
            issues.append(f"compile error: {cr.stderr[:100]}")
            return {"exec_score": exec_score, "ran_ok": False, "assertions_passed": 0, "issues": issues}

        # 2. Execute (+40 if passes, partial credit for assertion errors)
        run_result = subprocess.run(
            ["python3", tmp_path],
            capture_output=True, text=True, timeout=15
        )
        output = (run_result.stdout + run_result.stderr).lower()

        if run_result.returncode == 0:
            exec_score += 40
            ran_ok = True
        elif "assertionerror" in output:
            exec_score += 10   # ran but assertions failed
            issues.append("assertion failed")
            ran_ok = False
        else:
            issues.append(f"runtime error: {run_result.stderr[:100]}")
            ran_ok = False

        # 3. Count assertions passed in stdout (+up to 30)
        assertion_lines = [l for l in run_result.stdout.splitlines()
                          if any(w in l.lower() for w in ("assert", "pass", "ok", "test"))]
        assertions_passed = len(assertion_lines)
        exec_score += min(30, assertions_passed * 5)

        return {
            "exec_score": min(90, exec_score),
            "ran_ok": ran_ok,
            "assertions_passed": assertions_passed,
            "issues": issues,
        }
    except subprocess.TimeoutExpired:
        issues.append("execution timeout (>15s)")
        return {"exec_score": 10, "ran_ok": False, "assertions_passed": 0, "issues": issues}
    except Exception as e:
        return {"exec_score": 0, "ran_ok": False, "assertions_passed": 0, "issues": [str(e)]}
    finally:
        try:
            _os.unlink(tmp_path)
        except Exception:
            pass


def run(task: dict) -> dict:
    start = time.time()
    code  = task.get("code", task.get("output", ""))
    title = task.get("title", "")

    static  = _static_score(code, title)
    dynamic = _dynamic_score(code)

    # Composite: 50% static analysis + 50% dynamic execution
    static_s  = static["score"]
    dynamic_s = dynamic["exec_score"]
    score = round(static_s * 0.50 + dynamic_s * 0.50)

    # Boost: ran perfectly → floor at 65
    if dynamic.get("ran_ok") and score < 65:
        score = 65

    all_issues = static["issues"] + dynamic["issues"]

    if score >= 70:
        verdict = "pass"
    elif score >= 40:
        verdict = "needs_work"
    else:
        verdict = "fail"

    breakdown = dict(static["breakdown"])
    breakdown["exec_score"]         = dynamic_s
    breakdown["ran_ok"]             = dynamic.get("ran_ok", False)
    breakdown["assertions_passed"]  = dynamic.get("assertions_passed", 0)

    return {
        "status": "done",
        "score": score,
        "breakdown": breakdown,
        "issues": all_issues,
        "verdict": verdict,
        "quality": score,
        "tokens_used": 0,
        "elapsed_s": round(time.time() - start, 2),
        "agent": "reviewer",
    }
