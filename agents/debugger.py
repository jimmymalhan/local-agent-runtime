#!/usr/bin/env python3
"""
debugger.py — Error diagnosis and fix generation agent
=======================================================
Takes a failed task result and error message, diagnoses the root cause,
and generates a corrected version via local Nexus engine.

Entry point: run(task) -> dict
"""
import os, sys, json, time
from pathlib import Path

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "debugger",
    "version": 1,
    "capabilities": ["debug", "error_diagnosis", "fix_generation"],
    "model": "nexus-local",
    "input_schema": {
        "id": "int", "title": "str", "description": "str",
        "category": "str",
        "failed_output": "str",   # the broken code
        "error_msg": "str",       # the error message
    },
    "output_schema": {
        "status": "str",
        "diagnosis": "str",
        "fixed_code": "str",
        "quality": "int",
        "tokens_used": "int",
        "elapsed_s": "float",
    },
    "benchmark_score": None,
}

NEXUS_API   = os.environ.get("NEXUS_API", "")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "nexus-local")


def _llm_call(prompt: str, num_ctx: int = 8192) -> str:
    """Delegates to nexus_guard — handles Nexus engine down gracefully."""
    from agents.ollama_guard import llm_call_with_fallback
    result, _ = llm_call_with_fallback(prompt, num_ctx, fallback_hint=prompt[:100])
    return result
def run(task: dict) -> dict:
    start      = time.time()
    title      = task.get("title", "")
    description = task.get("description", title)
    failed_out = task.get("failed_output", "")
    error_msg  = task.get("error_msg", "")

    prompt = (
        f"You are a debugging expert. Fix this broken Python code.\n\n"
        f"TASK: {title}\n"
        f"REQUIREMENTS: {description}\n\n"
        f"BROKEN CODE:\n```python\n{failed_out[:3000]}\n```\n\n"
        f"ERROR: {error_msg[:500]}\n\n"
        f"Instructions:\n"
        f"1. Diagnose the root cause in ONE sentence.\n"
        f"2. Write the COMPLETE fixed Python code with all imports.\n"
        f"3. Include assertions to verify correctness.\n"
        f"4. Do NOT truncate. Write the full file.\n"
        f"5. Output format:\n"
        f"DIAGNOSIS: <one sentence>\n"
        f"```python\n<complete fixed code>\n```"
    )

    try:
        raw = _llm_call(prompt)

        # Parse diagnosis
        diagnosis = ""
        if "DIAGNOSIS:" in raw:
            diagnosis = raw.split("DIAGNOSIS:")[1].split("\n")[0].strip()

        # Parse fixed code
        fixed_code = ""
        if "```python" in raw:
            parts = raw.split("```python")
            if len(parts) > 1:
                fixed_code = parts[1].split("```")[0].strip()
        elif "```" in raw:
            parts = raw.split("```")
            if len(parts) > 1:
                fixed_code = parts[1].strip()

        # Quick quality check
        quality = 50
        if fixed_code:
            quality += 20
        try:
            compile(fixed_code, "<string>", "exec")
            quality += 20
        except Exception:
            pass
        if "assert" in fixed_code:
            quality += 10
        quality = min(100, quality)

        return {
            "status": "done",
            "diagnosis": diagnosis or "Unable to parse diagnosis",
            "fixed_code": fixed_code,
            "output": fixed_code,
            "quality": quality,
            "tokens_used": len(raw) // 4,
            "elapsed_s": round(time.time() - start, 1),
            "agent": "debugger",
        }
    except Exception as e:
        return {
            "status": "failed",
            "diagnosis": f"Debugger failed: {e}",
            "fixed_code": "",
            "output": "",
            "quality": 60,
            "tokens_used": 0,
            "elapsed_s": round(time.time() - start, 1),
            "agent": "debugger",
            "error": str(e),
        }
