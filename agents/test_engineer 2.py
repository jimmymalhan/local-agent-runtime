#!/usr/bin/env python3
"""
test_engineer.py — Test generation and coverage agent
======================================================
Generates pytest test suites for given code or task specs.
Handles tdd category (write tests first, then verify impl passes them).

Entry point: run(task) -> dict
"""
import os, sys, json, re, time, subprocess
from pathlib import Path

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "test_engineer",
    "version": 1,
    "capabilities": ["test_gen", "coverage", "tdd"],
    "model": "qwen2.5-coder:7b",
    "input_schema": {
        "id": "int", "title": "str", "description": "str",
        "category": "str",
        "code_to_test": "str",  # optional: existing code to write tests for
    },
    "output_schema": {
        "status": "str",
        "test_code": "str",
        "test_count": "int",
        "run_result": "str",    # output of running the tests
        "quality": "int",
        "tokens_used": "int",
        "elapsed_s": "float",
    },
    "benchmark_score": None,
}

OLLAMA_API  = os.environ.get("OLLAMA_API_BASE", "http://127.0.0.1:11434")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen2.5-coder:7b")


def _llm_call(prompt: str, num_ctx: int = 8192) -> str:
    import urllib.request
    payload = json.dumps({
        "model": LOCAL_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": num_ctx, "temperature": 0.1},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_API}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read()).get("response", "")


def _run_tests(test_code: str) -> tuple:
    """Write tests to temp file and run with pytest. Returns (passed, output)."""
    import tempfile
    try:
        with tempfile.NamedTemporaryFile(mode="w", suffix="_test.py",
                                         dir="/tmp", delete=False) as f:
            f.write(test_code)
            tmp_path = f.name
        result = subprocess.run(
            ["python3", "-m", "pytest", tmp_path, "-v", "--tb=short", "-q"],
            capture_output=True, text=True, timeout=30, cwd="/tmp"
        )
        output = (result.stdout + result.stderr)[:1000]
        passed = result.returncode == 0
        return passed, output
    except Exception as e:
        return False, str(e)
    finally:
        try:
            os.unlink(tmp_path)
        except Exception:
            pass


def _run_single_section(task: dict) -> dict:
    """Run one test section sub-task. Used as leaf fn for subagent_pool."""
    return run(task)


def _merge_test_sections(parent_task: dict, results: list) -> dict:
    """Merge multiple test section outputs into one combined test file."""
    import time as _time
    start = _time.time()
    sections = []
    total_tokens = 0
    for r in results:
        code = r.get("test_code") or r.get("output", "")
        if code and "def test_" in code:
            sections.append(code)
        total_tokens += r.get("tokens_used", 0)

    if not sections:
        return {"status": "failed", "quality": 0, "output": "", "test_count": 0,
                "tokens_used": total_tokens, "elapsed_s": 0.0}

    # Deduplicate: collect unique test function names across sections
    seen_tests = set()
    merged_lines = ["import pytest", ""]
    for section in sections:
        for line in section.splitlines():
            if line.strip().startswith("import") or line.strip().startswith("from"):
                if line not in merged_lines[:5]:
                    merged_lines.insert(2, line)
            elif line.strip().startswith("def test_"):
                fn_name = line.strip().split("(")[0].replace("def ", "")
                if fn_name not in seen_tests:
                    seen_tests.add(fn_name)
                    merged_lines.append(line)
            else:
                merged_lines.append(line)

    merged = "\n".join(merged_lines)
    test_count = len(re.findall(r'\bdef test_\w+', merged))
    tests_passed, run_result = _run_tests(merged) if test_count > 0 else (False, "")

    quality = min(100, 20 + (test_count * 5) + (30 if tests_passed else 0))
    return {
        "status": "done",
        "test_code": merged,
        "output": merged,
        "test_count": test_count,
        "run_result": run_result,
        "tests_passed": tests_passed,
        "quality": quality,
        "tokens_used": total_tokens,
        "elapsed_s": round(_time.time() - start, 1),
        "agent": "test_engineer",
        "_subagents_used": len(results),
    }


def run(task: dict) -> dict:
    start        = time.time()
    title        = task.get("title", "")
    description  = task.get("description", title)
    code_to_test = task.get("code_to_test", "")
    category     = task.get("category", "tdd")

    # For complex tasks: spawn sub-agents in parallel, one per test category
    # Skip if this task is already a sub-task (avoid infinite recursion)
    is_complex = len(description) > 300 and not task.get("_sub_idx") and not task.get("_attempt")
    if is_complex:
        try:
            from agents.subagent_pool import SubAgentPool
            sections = [
                "Happy path: normal valid inputs, expected outputs",
                "Edge cases: empty inputs, boundary values, None/null handling",
                "Error cases: invalid types, exceptions, out-of-range values",
                "Integration: end-to-end flow with multiple function calls",
                "Performance: large inputs, repeated calls, timing assertions",
            ]
            result = SubAgentPool.map_reduce(
                task,
                split_fn=lambda t: [
                    {**t, "title": f"{title} — {s}", "description": f"{description}\nFocus: {s}", "_sub_idx": i}
                    for i, s in enumerate(sections)
                ],
                agent_fn=_run_single_section,
                merge_fn=_merge_test_sections,
            )
            result["agent"] = "test_engineer"
            return result
        except Exception:
            pass  # fallback to single run

    if code_to_test:
        prompt = (
            f"Write a comprehensive pytest test suite for this Python code.\n\n"
            f"CODE TO TEST:\n```python\n{code_to_test[:3000]}\n```\n\n"
            f"TASK CONTEXT: {description}\n\n"
            f"Write tests that cover:\n"
            f"1. Happy path (normal inputs)\n"
            f"2. Edge cases (empty, None, boundary values)\n"
            f"3. Error cases (invalid input, exceptions)\n"
            f"4. Type checks\n\n"
            f"Output a single Python test file using pytest.\n"
            f"Import the code being tested correctly.\n"
            f"Do NOT use mocks unless absolutely necessary.\n"
            f"Do NOT truncate."
        )
    else:
        prompt = (
            f"Write a TDD-style test suite for this requirement.\n\n"
            f"REQUIREMENT: {title}\nDETAILS: {description}\n\n"
            f"First write the test file (tests fail because impl doesn't exist yet).\n"
            f"Then write the implementation that makes all tests pass.\n\n"
            f"Output format:\n"
            f"TEST FILE (test_impl.py):\n```python\n<tests>\n```\n\n"
            f"IMPLEMENTATION (impl.py):\n```python\n<implementation>\n```\n\n"
            f"Do NOT truncate. Cover edge cases."
        )

    try:
        raw = _llm_call(prompt)

        # Extract test code
        test_code = ""
        code_blocks = re.findall(r'```python\n(.*?)```', raw, re.DOTALL)
        if code_blocks:
            test_code = code_blocks[0].strip()  # first block = test file

        if not test_code:
            test_code = raw

        # Count test functions
        test_count = len(re.findall(r'\bdef test_\w+', test_code))

        # Try running the tests
        run_result = ""
        tests_passed = False
        if test_count > 0 and "import" in test_code:
            tests_passed, run_result = _run_tests(test_code)

        # Score
        quality = 30
        if test_count >= 3:
            quality += 25
        if test_count >= 6:
            quality += 10
        if tests_passed:
            quality += 25
        if "assert" in test_code:
            quality += 10
        quality = min(100, quality)

        return {
            "status": "done",
            "test_code": test_code,
            "output": test_code,
            "test_count": test_count,
            "run_result": run_result,
            "tests_passed": tests_passed,
            "quality": quality,
            "tokens_used": len(raw) // 4,
            "elapsed_s": round(time.time() - start, 1),
            "agent": "test_engineer",
        }
    except Exception as e:
        return {
            "status": "failed",
            "test_code": "",
            "output": str(e),
            "test_count": 0,
            "run_result": str(e),
            "quality": 0,
            "tokens_used": 0,
            "elapsed_s": round(time.time() - start, 1),
            "agent": "test_engineer",
            "error": str(e),
        }
