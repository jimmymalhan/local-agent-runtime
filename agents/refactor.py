#!/usr/bin/env python3
"""
refactor.py — Code transformation and cleanup agent
====================================================
Takes existing code and applies refactoring: extract functions, rename
variables, improve readability, reduce duplication, apply design patterns.

Entry point: run(task) -> dict
"""
import os, sys, json, re, time
from pathlib import Path

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "refactor",
    "version": 1,
    "capabilities": ["refactor", "code_transformation", "cleanup"],
    "model": "nexus-local",
    "input_schema": {
        "id": "int", "title": "str", "description": "str",
        "category": "str",
        "original_code": "str",  # optional: code to refactor
    },
    "output_schema": {
        "status": "str",
        "refactored_code": "str",
        "changes_summary": "list",
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
    start         = time.time()
    title         = task.get("title", "")
    description   = task.get("description", title)
    original_code = task.get("original_code", "")

    if original_code:
        prompt = (
            f"You are a refactoring expert. Improve this Python code.\n\n"
            f"TASK: {title}\nGOAL: {description}\n\n"
            f"ORIGINAL CODE:\n```python\n{original_code[:4000]}\n```\n\n"
            f"Refactor by:\n"
            f"1. Extracting repeated logic into helper functions\n"
            f"2. Improving variable names for clarity\n"
            f"3. Adding type hints\n"
            f"4. Reducing complexity (cyclomatic complexity)\n"
            f"5. Applying appropriate design patterns\n\n"
            f"Output:\n"
            f"CHANGES:\n- <bullet list of changes>\n\n"
            f"```python\n<complete refactored code>\n```\n\n"
            f"Do NOT truncate. Preserve all functionality."
        )
    else:
        prompt = (
            f"You are a refactoring expert. Implement this refactoring task.\n\n"
            f"TASK: {title}\nDETAILS: {description}\n\n"
            f"Write complete Python code that demonstrates the refactoring.\n"
            f"Show BEFORE and AFTER versions with clear comments.\n"
            f"Include assertions proving behavior is preserved.\n"
            f"Do NOT truncate."
        )

    try:
        raw = _llm_call(prompt)

        # Parse changes summary
        changes = []
        if "CHANGES:" in raw:
            changes_section = raw.split("CHANGES:")[1].split("```")[0]
            changes = [l.strip("- ").strip() for l in changes_section.splitlines()
                      if l.strip().startswith("-")]

        # Parse refactored code
        refactored = ""
        if "```python" in raw:
            blocks = re.findall(r'```python\n(.*?)```', raw, re.DOTALL)
            if blocks:
                refactored = blocks[-1].strip()  # take last block (the final version)
        elif "```" in raw:
            blocks = re.findall(r'```\n(.*?)```', raw, re.DOTALL)
            if blocks:
                refactored = blocks[-1].strip()

        if not refactored:
            refactored = raw  # fallback: full output

        # Score quality
        quality = 40
        if refactored and len(refactored) > 100:
            quality += 20
        if changes:
            quality += 15
        try:
            compile(refactored, "<string>", "exec")
            quality += 15
        except Exception:
            pass
        if "def " in refactored:
            quality += 10
        quality = min(100, quality)

        return {
            "status": "done",
            "refactored_code": refactored,
            "output": refactored,
            "changes_summary": changes,
            "quality": quality,
            "tokens_used": len(raw) // 4,
            "elapsed_s": round(time.time() - start, 1),
            "agent": "refactor",
        }
    except Exception as e:
        return {
            "status": "failed",
            "refactored_code": "",
            "output": str(e),
            "changes_summary": [],
            "quality": 60,
            "tokens_used": 0,
            "elapsed_s": round(time.time() - start, 1),
            "agent": "refactor",
            "error": str(e),
        }
