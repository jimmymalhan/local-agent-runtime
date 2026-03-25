#!/usr/bin/env python3
"""
executor.py — Primary code execution agent
===========================================
Wraps agent_runner.py's run_task() with the standard agent contract.
Handles: code_gen, bug_fix, tdd categories.

Entry point: run(task) -> dict
"""
import os, sys, time
from pathlib import Path

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "executor",
    "version": 4,
    "capabilities": ["code_gen", "bug_fix", "tdd"],
    "model": "qwen2.5-coder:7b",
    "input_schema": {
        "id": "int",
        "title": "str",
        "description": "str",
        "category": "str",
    },
    "output_schema": {
        "status": "str",       # done | failed | blocked
        "output": "str",       # code or result text
        "quality": "int",      # 0-100
        "tokens_used": "int",
        "iterations": "int",
        "elapsed_s": "float",
    },
    "benchmark_score": None,
}


def _single_run(task: dict) -> dict:
    """One Ollama call. Used as the leaf agent_fn for sub-agent pools."""
    from agent_runner import run_task
    start = time.time()
    try:
        result = run_task(task)
        result["tokens_used"] = result.get("tokens_used", 0)
        result["elapsed_s"]   = round(time.time() - start, 1)
        result["agent"]       = "executor"
        # Normalize quality_score → quality (agent_runner uses quality_score)
        if "quality" not in result or result["quality"] is None:
            result["quality"] = result.get("quality_score", 0)
        # Extract written file content as output for dynamic scoring
        files = result.get("files_written", [])
        if files and not result.get("output"):
            try:
                result["output"] = open(files[0]).read()
            except Exception:
                pass
        # Dynamic quality re-score using reviewer (execution-based)
        output = result.get("output", "")
        if output and result.get("status") in ("done", "partial"):
            try:
                from agents.reviewer import run as review_run
                review_task = dict(task, output=output, code=output)
                review = review_run(review_task)
                result["quality"]  = review.get("quality", result.get("quality", 0))
                result["breakdown"] = review.get("breakdown", {})
                result["verdict"]  = review.get("verdict", "unknown")
            except Exception:
                pass
        return result
    except Exception as e:
        return {
            "status": "failed",
            "output": str(e),
            "quality": 0,
            "tokens_used": 0,
            "elapsed_s": round(time.time() - start, 1),
            "agent": "executor",
            "error": str(e),
        }


def run(task: dict) -> dict:
    """
    Run a code task via local Ollama agents.

    Simple tasks (description <= 200 chars): single run.
    Complex tasks (description > 200 chars): best-of-3 parallel sub-agents.
    Sub-agents are all local Ollama — zero Claude budget used.
    """
    description = task.get("description", "")
    is_complex = len(description) > 200 or task.get("difficulty") in ("hard", "expert")

    if is_complex:
        try:
            from agents.subagent_pool import SubAgentPool
            result = SubAgentPool.best_of_n(task, _single_run, n=3)
            result["agent"] = "executor"
            return result
        except Exception:
            pass  # fallback to single run if pool fails

    return _single_run(task)


if __name__ == "__main__":
    # Quick smoke test
    test_task = {
        "id": 0,
        "title": "Write binary_search function",
        "description": "Write a Python function binary_search(arr, target) -> int that returns the index of target in sorted arr, or -1 if not found. Include assertions.",
        "category": "code_gen",
    }
    result = run(test_task)
    print(f"Status:  {result['status']}")
    print(f"Quality: {result['quality']}/100")
    print(f"Elapsed: {result['elapsed_s']}s")
