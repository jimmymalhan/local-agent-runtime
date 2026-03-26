#!/usr/bin/env python3
"""
frontend_agent.py — React / TypeScript / Dashboard specialist
==============================================================
Owns ALL frontend work for jobs.hil-tad.com and the local-agent dashboard.

Handles categories:
  frontend, react, dashboard, ui, ux, css, html,
  design_system, accessibility, prototype, component,
  state_mgmt, build_tool

Stack awareness:
  - React + TypeScript/JavaScript
  - HTML / CSS (Tailwind, modules, vanilla)
  - State management (Zustand, Redux, Context)
  - Build tools (Vite, Webpack, esbuild)
  - UX: usability testing, design systems, visual hierarchy, a11y

Policy:
  - NEVER escalate to Claude main session.
  - If quality < 60 after 3 retries → write reports/rescue_needed.json
    (cron rescue will upgrade this agent's prompt, NOT call Claude directly).
  - All output written to generated/projects/<project>/ and state.json updated.
"""
import os, sys, time, json
from pathlib import Path

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

AGENT_META = {
    "name": "frontend_agent",
    "version": 1,
    "capabilities": [
        "frontend", "react", "typescript", "dashboard",
        "ui", "ux", "css", "html", "design_system",
        "accessibility", "prototype", "component",
        "state_mgmt", "build_tool",
    ],
    "model": "qwen2.5-coder:7b",
    "project": "jobs.hil-tad.com",
    "claude_rescue": False,   # Never call Claude main — use rescue protocol only
    "input_schema": {
        "id": "int",
        "title": "str",
        "description": "str",
        "category": "str",
        "codebase_path": "str (optional)",
    },
    "output_schema": {
        "status": "str",       # done | failed | blocked
        "output": "str",       # generated code / component
        "quality": "int",      # 0-100
        "tokens_used": "int",
        "iterations": "int",
        "elapsed_s": "float",
    },
    "benchmark_score": None,
}

# System prompt injected for every frontend task
_FRONTEND_SYSTEM = """
You are a senior React / TypeScript engineer working on jobs.hil-tad.com.

Stack:
- React 18+ with functional components and hooks
- TypeScript (strict mode preferred, JS acceptable)
- HTML5 / CSS3 (Tailwind or CSS modules)
- State management: Zustand / Context API / Redux Toolkit
- Build tools: Vite (primary), Webpack fallback
- UX principles: WCAG AA accessibility, design system tokens, visual hierarchy

Rules:
1. Produce working, self-contained code — no placeholders or TODOs.
2. Use semantic HTML and accessible ARIA attributes.
3. Keep components small (<150 lines), single-responsibility.
4. Export a named default component.
5. Include brief inline comments only where logic is non-obvious.
6. Never add backend code to frontend output.
7. Prefer existing design tokens over hardcoded colors/spacing.
""".strip()


def _build_prompt(task: dict) -> str:
    category = task.get("category", "frontend")
    title    = task.get("title", "")
    desc     = task.get("description", "")
    codebase = task.get("codebase_path", "jobs.hil-tad.com codebase")

    return (
        f"[FRONTEND TASK — {category.upper()}]\n"
        f"Project: {codebase}\n"
        f"Title: {title}\n\n"
        f"Requirements:\n{desc}\n\n"
        "Deliver complete, production-ready React/TypeScript code.\n"
        "Start directly with the code — no preamble."
    )


def _single_run(task: dict) -> dict:
    """One Ollama call via agent_runner with frontend system prompt injected."""
    from agent_runner import run_task as _run

    enriched = dict(task)
    enriched.setdefault("system_prompt", _FRONTEND_SYSTEM)
    enriched["prompt"] = _build_prompt(task)

    start = time.time()
    try:
        result = _run(enriched)
        result["elapsed_s"]   = round(time.time() - start, 1)
        result["agent"]       = "frontend_agent"
        if "quality" not in result or result["quality"] is None:
            result["quality"] = result.get("quality_score", 0)
        # Pull file content as output if agent wrote files
        files = result.get("files_written", [])
        if files and not result.get("output"):
            try:
                result["output"] = open(files[0]).read()
            except Exception:
                pass
        # Dynamic re-score via reviewer
        output = result.get("output", "")
        if output and result.get("status") in ("done", "partial"):
            try:
                from agents.reviewer import run as review_run
                review = review_run(dict(task, output=output, code=output))
                result["quality"]   = review.get("quality", result.get("quality", 0))
                result["breakdown"] = review.get("breakdown", {})
                result["verdict"]   = review.get("verdict", "unknown")
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
            "agent": "frontend_agent",
            "error": str(e),
        }


def _trigger_rescue(task: dict, failures: int) -> None:
    """Write rescue_needed.json so the cron rescue upgrades this agent's prompt."""
    rescue_path = Path(BASE_DIR) / "reports" / "rescue_needed.json"
    rescue_path.parent.mkdir(parents=True, exist_ok=True)
    rescue_path.write_text(json.dumps({
        "task_id":    task.get("id", 0),
        "title":      task.get("title", ""),
        "agent":      "frontend_agent",
        "failures":   failures,
        "category":   task.get("category", "frontend"),
        "claude_rescue": False,  # Never direct Claude — upgrade prompt only
    }, indent=2))


def run(task: dict) -> dict:
    """
    Run a frontend task. Retries up to 3× with best-of-n sub-agents.
    On persistent failure, triggers the rescue protocol (prompt upgrade only).
    Never escalates to Claude main session.
    """
    description = task.get("description", "")
    is_complex  = len(description) > 200 or task.get("difficulty") in ("hard", "expert")

    if is_complex:
        try:
            from agents.subagent_pool import SubAgentPool
            result = SubAgentPool.best_of_n(task, _single_run, n=3, agent_name="frontend_agent")
            result["agent"] = "frontend_agent"
            if result.get("quality", 0) < 60:
                _trigger_rescue(task, failures=3)
            return result
        except Exception:
            pass  # fall through to single run

    result = _single_run(task)
    if result.get("quality", 0) < 60:
        _trigger_rescue(task, failures=1)
    return result


if __name__ == "__main__":
    test_task = {
        "id": 0,
        "title": "JobCard component",
        "description": (
            "Create a React TypeScript JobCard component for jobs.hil-tad.com. "
            "Props: title (string), company (string), location (string), salary (string), "
            "tags (string[]). Show a card with apply button. Use Tailwind classes."
        ),
        "category": "component",
    }
    r = run(test_task)
    print(f"Status:  {r['status']}")
    print(f"Quality: {r['quality']}/100")
    print(f"Elapsed: {r['elapsed_s']}s")
