#!/usr/bin/env python3
"""
planner.py — Task decomposition and strategy agent
====================================================
Takes a high-level task and breaks it into subtasks with execution order,
file targets, and complexity estimate. Used by orchestrator before handing
to executor/architect.

Entry point: run(task) -> dict
"""
import os, sys, json, time
from pathlib import Path

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "planner",
    "version": 1,
    "capabilities": ["planning", "decomposition", "strategy"],
    "model": "qwen2.5-coder:7b",
    "input_schema": {"id": "int", "title": "str", "description": "str", "category": "str"},
    "output_schema": {
        "status": "str",
        "plan": "list",      # [{step, description, agent, file_targets}]
        "complexity": "str", # simple | medium | hard | ultra
        "quality": "int",
        "tokens_used": "int",
        "elapsed_s": "float",
    },
    "benchmark_score": None,
}

OLLAMA_API = os.environ.get("OLLAMA_API_BASE", "http://127.0.0.1:11434")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "qwen2.5-coder:7b")

_COMPLEXITY_KEYWORDS = {
    "ultra": {"distributed", "consensus", "raft", "actor model", "jit compiler", "bytecode"},
    "hard":  {"async", "multithread", "pipeline", "scaffold", "architecture", "e2e", "system design"},
    "medium": {"class", "api", "database", "test", "refactor", "optimize"},
}


def _estimate_complexity(title: str, description: str) -> str:
    text = (title + " " + description).lower()
    for level, keywords in _COMPLEXITY_KEYWORDS.items():
        if any(k in text for k in keywords):
            return level
    return "simple"


def _llm_call(prompt: str) -> str:
    import urllib.request
    payload = json.dumps({
        "model": LOCAL_MODEL,
        "prompt": prompt,
        "stream": False,
        "options": {"num_ctx": 4096, "temperature": 0.1},
    }).encode()
    req = urllib.request.Request(
        f"{OLLAMA_API}/api/generate",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.loads(r.read()).get("response", "")


def run(task: dict) -> dict:
    start = time.time()
    title = task.get("title", "")
    description = task.get("description", title)
    category = task.get("category", "code_gen")

    complexity = _estimate_complexity(title, description)

    prompt = (
        f"You are a software project planner. Break this task into clear steps.\n\n"
        f"TASK: {title}\nDETAILS: {description}\nCATEGORY: {category}\n\n"
        f"Output a numbered list of steps. Each step: what to do, which file to create/edit, "
        f"and which agent should handle it (executor/architect/test_engineer/reviewer).\n"
        f"Be concrete and brief. Max 6 steps."
    )

    try:
        raw = _llm_call(prompt)
        lines = [l.strip() for l in raw.splitlines() if l.strip()]
        plan = []
        for i, line in enumerate(lines[:6]):
            plan.append({
                "step": i + 1,
                "description": line,
                "agent": "executor" if category in ("code_gen", "bug_fix", "tdd") else "architect",
                "file_targets": [],
            })

        return {
            "status": "done",
            "plan": plan,
            "complexity": complexity,
            "quality": 75,
            "tokens_used": len(raw) // 4,
            "elapsed_s": round(time.time() - start, 1),
            "agent": "planner",
        }
    except Exception as e:
        # Fallback: generate a minimal plan without LLM
        plan = [
            {"step": 1, "description": f"Implement: {title}", "agent": "executor", "file_targets": []},
            {"step": 2, "description": "Write tests", "agent": "test_engineer", "file_targets": []},
            {"step": 3, "description": "Review output quality", "agent": "reviewer", "file_targets": []},
        ]
        return {
            "status": "done",
            "plan": plan,
            "complexity": complexity,
            "quality": 50,
            "tokens_used": 0,
            "elapsed_s": round(time.time() - start, 1),
            "agent": "planner",
            "fallback": True,
        }
