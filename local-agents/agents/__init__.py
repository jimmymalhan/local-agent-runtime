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

Project-aware task pulling:
    from agents import next_project_task, run_project_task
    item = next_project_task()   # highest-priority pending task from projects.json
    if item:
        result = run_project_task(item)
"""
import importlib
import logging
import sys
import os
from typing import Optional

logger = logging.getLogger(__name__)

# Make the projects package importable from wherever agents is imported
_AGENTS_DIR = os.path.dirname(os.path.abspath(__file__))
_LOCAL_AGENTS_DIR = os.path.dirname(_AGENTS_DIR)
if _LOCAL_AGENTS_DIR not in sys.path:
    sys.path.insert(0, _LOCAL_AGENTS_DIR)

try:
    from projects.project_manager import ProjectManager as _ProjectManager
    _pm: Optional[_ProjectManager] = _ProjectManager()
except Exception:  # pragma: no cover
    _pm = None

# ---------------------------------------------------------------------------
# Memory integration (optional — gracefully disabled if unavailable)
# ---------------------------------------------------------------------------
try:
    from memory import get_store as _get_memory_store
    from memory.context_builder import ContextBuilder as _ContextBuilder
    _memory_enabled = True
except Exception as _mem_err:  # noqa: BLE001
    logger.debug("Memory system unavailable: %s", _mem_err)
    _memory_enabled = False

# Category → agent module mapping (single source of truth)
ROUTING_TABLE = {
    "code_gen":      "executor",
    "bug_fix":       "executor",
    "tdd":           "test_engineer",
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
    # Codebase understanding
    "analyze":       "codebase_analyzer",
    "onboard":       "codebase_analyzer",
    # Scaffolding (scaffolder agent, to be built)
    "scaffold":      "scaffolder",
    # Research
    "web_research":  "researcher",
    # Security
    "security":      "reviewer",
    # Documentation generation
    "doc_gen":       "doc_writer",
    # Test generation
    "test_gen":      "test_engineer",
    # Multi-file edits and migrations
    "multi_edit":    "executor",
    "migrate":       "executor",
    "deploy":        "executor",
    # Architecture and design
    "api_design":    "architect",
    "db":            "architect",
    "infra":         "architect",
    # Performance and monitoring
    "perf":          "debugger",
    "monitor":       "debugger",
    # Git and GitHub operations
    "git":           "git_agent",
    "branch":        "git_agent",
    "pr":            "git_agent",
    "ci":            "git_agent",
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


# ---------------------------------------------------------------------------
# Project-aware task pulling
# ---------------------------------------------------------------------------

def next_project_task() -> Optional[dict]:
    """
    Pull the highest-priority pending task from projects.json.

    Returns a dict with keys: project_id, project_name, epic_id, epic_title, task
    or None if no pending tasks exist or projects package is unavailable.
    """
    if _pm is None:
        return None
    return _pm.next_task()


def run_project_task(item: dict) -> dict:
    """
    Run a task returned by next_project_task() through the correct agent,
    then mark it complete in ProjectManager.

    Args:
        item: dict from next_project_task() with keys project_id, epic_id, task

    Returns:
        Agent result dict augmented with project_id, epic_id, task_id.
    """
    task = item["task"]
    result = run_task(task)
    quality = result.get("quality", 0)
    if _pm is not None:
        _pm.complete_task(
            project_id=item["project_id"],
            epic_id=item["epic_id"],
            task_id=task["id"],
            result=result,
            quality=quality,
        )
    result["project_id"] = item["project_id"]
    result["epic_id"] = item["epic_id"]
    result["task_id"] = task["id"]
    return result
