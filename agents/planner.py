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
    "model": "nexus-local",
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

NEXUS_API  = os.environ.get("NEXUS_API", "")
LOCAL_MODEL = os.environ.get("LOCAL_MODEL", "nexus-local")

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


def _llm_call(prompt: str, num_ctx: int = 8192) -> str:
    """Delegates to nexus_guard — handles Nexus engine down gracefully."""
    from agents.ollama_guard import llm_call_with_fallback
    result, _ = llm_call_with_fallback(prompt, num_ctx, fallback_hint=prompt[:100])
    return result
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
