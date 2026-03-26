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


import logging
import os
import sys

logger = logging.getLogger(__name__)

# Make local-agents/ importable so memory package can be found
_AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCAL_AGENTS_DIR = os.path.dirname(_AGENTS_DIR)
if _LOCAL_AGENTS_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENTS_DIR)

# ---------------------------------------------------------------------------
# Memory integration (optional -- gracefully disabled if unavailable)
# ---------------------------------------------------------------------------
try:
    from memory import get_store as _get_memory_store
    from memory.context_builder import ContextBuilder as _ContextBuilder
    _memory_enabled = True
except Exception as _mem_err:
    logger.debug("Memory system unavailable: %s", _mem_err)
    _memory_enabled = False

\1 → agent module mapping (single source of truth)
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
    "documentation": "doc_writer",
    "review":        "reviewer",
    "debug":         "debugger",
    "plan":          "planner",
    "benchmark":     "benchmarker",
    # Dependency graph + blast radius
    "blast_radius":  "code_graph",
    "conventions":   "code_graph",
    "graph":         "code_graph",
    # Context window / token budget
    "context":       "context_optimizer",
    "token_budget":  "context_optimizer",
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
    # --- Pre-task: inject memory context ---
    augmented_task = task
    if _memory_enabled:
        try:
            store = _get_memory_store()
            builder = _ContextBuilder(store)
            augmented_task = builder.inject(task, max_tokens=2000)
        except Exception as _e:
            logger.debug("Memory context injection failed: %s", _e)
            augmented_task = task

    agent_name = route(augmented_task)
    agent = get_agent(agent_name)
    result = agent.run(augmented_task)
    result.setdefault("agent_name", agent_name)

    # --- Post-task: persist result in episodic memory ---
    if _memory_enabled:
        try:
            quality = result.get("quality", 0)
            _get_memory_store().remember_task(task, result, quality)
        except Exception as _e:
            logger.debug("Memory store failed: %s", _e)

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
