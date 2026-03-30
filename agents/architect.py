#!/usr/bin/env python3
"""
architect.py — System design and project scaffold agent
========================================================
Handles arch, scaffold, e2e categories.
Generates directory structures, file skeletons, and schema designs
using the local Ollama model.

Entry point: run(task) -> dict
"""
import os, sys, json, time
from pathlib import Path

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "architect",
    "version": 1,
    "capabilities": ["arch", "scaffold", "e2e", "system_design"],
    "model": "qwen2.5-coder:7b",
    "input_schema": {"id": "int", "title": "str", "description": "str", "category": "str"},
    "output_schema": {
        "status": "str",
        "output": "str",        # design doc or scaffold code
        "files_created": "list",
        "quality": "int",
        "tokens_used": "int",
        "elapsed_s": "float",
    },
    "benchmark_score": None,
}

OLLAMA_API  = os.environ.get("OLLAMA_API_BASE", "http://127.0.0.1:11434")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen2.5-coder:7b")
BOS         = os.environ.get("BOS_HOME", os.path.expanduser("~/local-agents-os"))


def _llm_call(prompt: str, num_ctx: int = 8192) -> str:
    """Delegates to ollama_guard — handles Ollama down gracefully."""
    from agents.ollama_guard import llm_call_with_fallback
    result, _ = llm_call_with_fallback(prompt, num_ctx, fallback_hint=prompt[:100])
    return result
def run(task: dict) -> dict:
    start       = time.time()
    title       = task.get("title", "")
    description = task.get("description", title)
    category    = task.get("category", "arch")

    if category == "scaffold":
        prompt = (
            f"You are a software architect. Generate a complete project scaffold.\n\n"
            f"PROJECT: {title}\nREQUIREMENTS: {description}\n\n"
            f"Output:\n"
            f"1. Directory structure (tree format)\n"
            f"2. Each file's purpose (1 sentence)\n"
            f"3. main.py or app.py with working skeleton code\n"
            f"4. requirements.txt\n\n"
            f"Write complete, working Python code. Do NOT truncate. Include all imports."
        )
    elif category == "e2e":
        prompt = (
            f"You are a systems engineer. Build this end-to-end pipeline.\n\n"
            f"PIPELINE: {title}\nREQUIREMENTS: {description}\n\n"
            f"Write a single Python file that implements the full pipeline:\n"
            f"- Input validation\n- Processing stages\n- Output/result\n- Error handling\n"
            f"- A main() function that runs the pipeline\n"
            f"Include assertions and a smoke test at the end.\n"
            f"Do NOT truncate. Write complete code."
        )
    else:  # arch
        prompt = (
            f"You are a software architect. Design this system.\n\n"
            f"SYSTEM: {title}\nREQUIREMENTS: {description}\n\n"
            f"Provide:\n"
            f"1. Architecture overview (components and their roles)\n"
            f"2. Data flow diagram (text format)\n"
            f"3. Key interfaces / APIs (Python dataclasses or TypedDicts)\n"
            f"4. A working Python skeleton with all classes and method signatures\n"
            f"5. Scalability notes\n"
            f"Write complete code. Do NOT truncate."
        )

    try:
        raw = _llm_call(prompt)

        # Score output quality
        quality = 40
        if "def " in raw or "class " in raw:
            quality += 25
        if "import" in raw:
            quality += 10
        if len(raw) > 500:
            quality += 15
        try:
            # Try to extract and compile code blocks
            import re
            code_blocks = re.findall(r'```python\n(.*?)```', raw, re.DOTALL)
            for block in code_blocks:
                compile(block, "<string>", "exec")
            if code_blocks:
                quality += 10
        except Exception:
            pass
        quality = min(100, quality)

        return {
            "status": "done",
            "output": raw,
            "files_created": [],
            "quality": quality,
            "tokens_used": len(raw) // 4,
            "elapsed_s": round(time.time() - start, 1),
            "agent": "architect",
        }
    except Exception as e:
        return {
            "status": "failed",
            "output": str(e),
            "files_created": [],
            "quality": 60,
            "tokens_used": 0,
            "elapsed_s": round(time.time() - start, 1),
            "agent": "architect",
            "error": str(e),
        }
