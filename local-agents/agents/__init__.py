"""
local-agents/agents — Production-grade specialized agent package.

Each agent is:
  - Independently importable: from agents.executor import run
  - Deployable to any project: python3 deploy.py executor --to /path/to/project
  - Self-contained: zero deps on other agents (subagent_pool is optional)
  - Hardware-aware: scales workers to available RAM/CPU
  - Claude-free by default: 90% local Ollama, Claude only on 10% rescue

Quick start:
    from agents.executor import run as code_run
    result = code_run({"id": 1, "title": "Binary search", "description": "...", "category": "code_gen"})
    print(result["quality"])   # 0-100

Agent router:
    from agents import route, run_task
    result = run_task({"category": "tdd", "title": "...", "description": "..."})
"""
import importlib
from typing import Optional

# Category → agent module mapping (single source of truth)
ROUTING_TABLE = {
    "code_gen":      "executor",
    "bug_fix":       "executor",
    "tdd":           "test_engineer",
    "scaffold":      "architect",
    "e2e":           "architect",
    "arch":          "architect",
    "refactor":      "refactor",
    "research":      "researcher",
    "doc":           "doc_writer",
    "doc_gen":       "doc_writer",
    "documentation": "doc_writer",
    "review":        "reviewer",
    "debug":         "debugger",
    "plan":          "planner",
    "benchmark":     "benchmarker",
}

_cache: dict = {}


def route(task: dict) -> str:
    """Return the agent name for this task's category."""
    return ROUTING_TABLE.get(task.get("category", "code_gen"), "executor")


def get_agent(name: str):
    """Lazy-load and cache an agent module by name."""
    if name not in _cache:
        _cache[name] = importlib.import_module(f"agents.{name}")
    return _cache[name]


def run_task(task: dict) -> dict:
    """
    Route and run a task through the correct specialized agent.
    This is the single callable entry point for all agent work.

    Args:
        task: dict with keys: id, title, description, category, [codebase_path]

    Returns:
        dict with keys: status, output, quality (0-100), tokens_used, elapsed_s, agent
    """
    agent_name = route(task)
    agent = get_agent(agent_name)
    result = agent.run(task)
    result.setdefault("agent_name", agent_name)
    return result


def list_agents() -> list:
    """Return all available agent names."""
    return sorted(set(ROUTING_TABLE.values()))


def agent_meta(name: str) -> dict:
    """Return AGENT_META for the named agent."""
    try:
        return get_agent(name).AGENT_META
    except AttributeError:
        return {"name": name, "version": 0, "capabilities": [], "benchmark_score": None}
