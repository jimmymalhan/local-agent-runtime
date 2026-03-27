#!/usr/bin/env python3
"""
dashboard_schema.py — Strict TypedDict for dashboard state
===========================================================
Defines the complete dashboard state structure with:
  - All required fields
  - Default values (never empty/null)
  - Type safety
  - Validation before write

This ensures state.json is always valid and usable.

Usage:
  from state.dashboard_schema import DashboardState, create_default_state, validate_and_fix_state

  # Create fresh state with defaults
  state = create_default_state()

  # Fix incoming state, filling gaps with defaults
  state = validate_and_fix_state(incoming_state)
"""

from typing import TypedDict, Optional, Any
from datetime import datetime


class VersionInfo(TypedDict):
    """Version tracking for the system."""
    current: int
    total: int
    pct_complete: float
    label: str


class SubAgent(TypedDict):
    """Sub-agent worker state."""
    id: int
    status: str  # running | done | idle | failed
    task: str
    model: str
    elapsed_s: float
    quality: float


class AgentState(TypedDict):
    """Individual agent state."""
    status: str  # idle | planning | executing | reviewing | blocked | restarting | upgrading
    task: str
    task_id: Optional[int]
    quality: float
    elapsed_s: float
    last_activity: str  # ISO timestamp
    sub_agents: list[SubAgent]
    worker_count: int


class TaskQueue(TypedDict):
    """Task queue statistics."""
    total: int
    completed: int
    in_progress: int
    failed: int
    pending: int


class TokenUsage(TypedDict):
    """Token usage tracking."""
    claude_tokens: int
    local_tokens: int
    budget_pct: float
    warning: bool
    hard_limit_hit: bool


class Hardware(TypedDict):
    """Hardware resource state."""
    cpu_pct: float
    ram_pct: float
    disk_pct: float
    gpu_pct: Optional[float]
    alert_level: str  # ok | warning | critical


class Failure(TypedDict):
    """Failure record."""
    task_id: str
    error: str
    strategy: str
    timestamp: str
    retry_count: int


class ResearchItem(TypedDict):
    """Research feed item."""
    task_id: str
    finding: str
    confidence: float
    timestamp: str
    agent: str


class DashboardState(TypedDict):
    """Complete dashboard state with all fields."""
    ts: str  # ISO timestamp
    version: VersionInfo
    agents: dict[str, AgentState]
    task_queue: TaskQueue
    benchmark_scores: dict[str, float]
    token_usage: TokenUsage
    hardware: Hardware
    failures: list[Failure]
    research_feed: list[ResearchItem]
    version_changelog: dict[str, Any]


def create_default_state() -> DashboardState:
    """
    Create a fresh dashboard state with all defaults.

    Returns:
        Valid DashboardState with sensible defaults.
    """
    now = datetime.now().isoformat()

    return {
        "ts": now,
        "version": {
            "current": 0,
            "total": 100,
            "pct_complete": 0.0,
            "label": "v0 → v100",
        },
        "agents": {},
        "task_queue": {
            "total": 100,
            "completed": 0,
            "in_progress": 0,
            "failed": 0,
            "pending": 100,
        },
        "benchmark_scores": {},
        "token_usage": {
            "claude_tokens": 0,
            "local_tokens": 0,
            "budget_pct": 0.0,
            "warning": False,
            "hard_limit_hit": False,
        },
        "hardware": {
            "cpu_pct": 0.0,
            "ram_pct": 0.0,
            "disk_pct": 0.0,
            "gpu_pct": None,
            "alert_level": "ok",
        },
        "failures": [],
        "research_feed": [],
        "version_changelog": {},
    }


def validate_and_fix_state(state: dict[str, Any]) -> DashboardState:
    """
    Validate incoming state and fill missing fields with defaults.

    Never returns empty or null values. Always returns valid state.

    Args:
        state: Incoming state dict (may be incomplete or invalid)

    Returns:
        Valid DashboardState with all fields populated
    """
    defaults = create_default_state()

    # Deep merge: keep existing values, fill gaps with defaults
    result = _deep_merge(state, defaults)

    # Ensure timestamp is current
    result["ts"] = datetime.now().isoformat()

    return result


def _deep_merge(source: dict, defaults: dict) -> dict:
    """
    Recursively merge source dict with defaults, preserving source values
    but filling in missing keys from defaults.

    Args:
        source: Incoming data (may have missing keys)
        defaults: Default values for missing keys

    Returns:
        Merged dict with all keys from defaults, values from source where present
    """
    result = dict(defaults)

    for key, value in source.items():
        if key not in result:
            # New key not in defaults, keep it
            result[key] = value
        elif isinstance(value, dict) and isinstance(defaults.get(key), dict):
            # Recursive merge for nested dicts
            result[key] = _deep_merge(value, defaults[key])
        elif value is None or value == "":
            # Reject null/empty values, use default
            pass
        else:
            # Use source value
            result[key] = value

    return result


def create_agent_state(
    name: str,
    status: str = "idle",
    task: str = "",
    task_id: Optional[int] = None,
    quality: float = 0.0,
    elapsed_s: float = 0.0,
) -> AgentState:
    """
    Create a valid AgentState with defaults.

    Args:
        name: Agent name
        status: Current status
        task: Current task description
        task_id: Current task ID
        quality: Quality score (0-100)
        elapsed_s: Elapsed time in seconds

    Returns:
        Valid AgentState
    """
    return {
        "status": status,
        "task": task[:100] if task else "",  # Cap at 100 chars
        "task_id": task_id,
        "quality": max(0.0, min(100.0, quality)),  # Clamp to [0, 100]
        "elapsed_s": max(0.0, elapsed_s),  # Never negative
        "last_activity": datetime.now().isoformat(),
        "sub_agents": [],
        "worker_count": 0,
    }


def is_valid_state(state: dict) -> bool:
    """
    Check if state is valid (all required fields present and non-empty).

    Args:
        state: State dict to validate

    Returns:
        True if state is valid, False otherwise
    """
    required_keys = {
        "ts", "version", "agents", "task_queue",
        "benchmark_scores", "token_usage", "hardware",
        "failures", "research_feed", "version_changelog"
    }

    # Check required keys exist
    if not all(key in state for key in required_keys):
        return False

    # Check no critical fields are empty
    if not state.get("ts") or state["ts"] == "":
        return False

    if not isinstance(state.get("version"), dict):
        return False

    if not isinstance(state.get("task_queue"), dict):
        return False

    # If we got here, state is valid
    return True


if __name__ == "__main__":
    # Quick test
    print("[TEST] Creating default state...")
    default = create_default_state()
    assert is_valid_state(default), "Default state is invalid!"
    print("[TEST] ✓ Default state is valid")

    print("[TEST] Testing validation with empty input...")
    invalid = {"version": {"current": 0}}  # Missing most fields
    fixed = validate_and_fix_state(invalid)
    assert is_valid_state(fixed), "Fixed state is invalid!"
    print("[TEST] ✓ Fixed state is valid after validation")

    print("[TEST] All tests passed ✓")
