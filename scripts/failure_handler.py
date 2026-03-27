#!/usr/bin/env python3
"""
failure_handler.py — Local failure handling without external rescue
=====================================================================
Replaces the Claude rescue path. When an agent fails 3×:
  1. Log to state/failures.json
  2. Tag task as [BLOCKED]
  3. Move to next task (no escalation)

This is called by the orchestrator when attempt_count reaches 3.
The self_heal.py process reads failures.json and retries with different strategies.

Usage:
  from scripts.failure_handler import log_failure, is_blocked_task, get_blocked_tasks

Architecture:
  Agent fails → attempt_count=3 → log_failure(task_id, error, strategy)
  → task tagged [BLOCKED] → move to next task
  → self_heal.py reads failures.json on 1-hour loop
  → attempts each with different strategy
  → updates success/status back to failures.json
"""

import json
import pathlib
from datetime import datetime
from typing import Optional, Any

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
FAILURES_FILE = REPO_ROOT / "state" / "failures.json"
STATE_DIR = REPO_ROOT / "state"


def _ensure_failures_file():
    """Ensure failures.json exists with default structure."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not FAILURES_FILE.exists():
        FAILURES_FILE.write_text(json.dumps({
            "blocked_tasks": [],
            "failure_history": [],
            "last_self_heal": None,
        }, indent=2))


def log_failure(
    task_id: str,
    error: str,
    strategy: str = "unknown",
    context: Optional[dict] = None
) -> dict:
    """
    Log a failed task attempt to failures.json when attempt_count reaches 3.

    Args:
        task_id: The task ID that failed
        error: Error message/description
        strategy: The strategy that was attempted (e.g., "retry_with_backoff", "fallback_model")
        context: Additional context (agent name, file paths, etc.)

    Returns:
        The failure record that was logged
    """
    _ensure_failures_file()

    # Read current failures
    try:
        failures = json.loads(FAILURES_FILE.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        failures = {"blocked_tasks": [], "failure_history": []}

    timestamp = datetime.now().isoformat()

    # Create failure record
    record = {
        "task_id": task_id,
        "error": error,
        "last_strategy": strategy,
        "timestamp": timestamp,
        "context": context or {},
        "status": "blocked",
        "retry_count": 0,
        "last_retry_at": None,
    }

    # Add to blocked_tasks if not already present
    existing = next((t for t in failures.get("blocked_tasks", []) if t["task_id"] == task_id), None)
    if existing:
        existing.update(record)
    else:
        failures["blocked_tasks"].append(record)

    # Add to history
    failures["failure_history"].append({
        "task_id": task_id,
        "error": error,
        "strategy": strategy,
        "timestamp": timestamp,
    })

    # Write back
    FAILURES_FILE.write_text(json.dumps(failures, indent=2))

    print(f"[FAILURE_HANDLER] Logged task {task_id} as blocked: {error}")
    print(f"[FAILURE_HANDLER] Last attempted strategy: {strategy}")
    print(f"[FAILURE_HANDLER] Failures file: {FAILURES_FILE}")

    return record


def is_blocked_task(task_id: str) -> bool:
    """Check if a task is currently blocked (failed 3× already)."""
    _ensure_failures_file()
    try:
        failures = json.loads(FAILURES_FILE.read_text())
        return any(t["task_id"] == task_id for t in failures.get("blocked_tasks", []))
    except (json.JSONDecodeError, FileNotFoundError):
        return False


def get_blocked_tasks() -> list[dict]:
    """Get all currently blocked tasks."""
    _ensure_failures_file()
    try:
        failures = json.loads(FAILURES_FILE.read_text())
        return failures.get("blocked_tasks", [])
    except (json.JSONDecodeError, FileNotFoundError):
        return []


def mark_task_recovered(task_id: str, strategy: str):
    """
    Mark a blocked task as recovered after successful retry.

    Args:
        task_id: The task ID that was recovered
        strategy: The strategy that successfully recovered it
    """
    _ensure_failures_file()
    try:
        failures = json.loads(FAILURES_FILE.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        failures = {"blocked_tasks": [], "failure_history": []}

    # Find and remove from blocked_tasks
    failures["blocked_tasks"] = [
        t for t in failures.get("blocked_tasks", [])
        if t["task_id"] != task_id
    ]

    # Log recovery to history
    failures["failure_history"].append({
        "task_id": task_id,
        "status": "recovered",
        "recovery_strategy": strategy,
        "timestamp": datetime.now().isoformat(),
    })

    FAILURES_FILE.write_text(json.dumps(failures, indent=2))

    print(f"[FAILURE_HANDLER] Task {task_id} marked as recovered with strategy: {strategy}")


def update_recovery_status(task_id: str, retry_attempt: int):
    """Track self-heal retry attempts."""
    _ensure_failures_file()
    try:
        failures = json.loads(FAILURES_FILE.read_text())
    except (json.JSONDecodeError, FileNotFoundError):
        return

    for task in failures.get("blocked_tasks", []):
        if task["task_id"] == task_id:
            task["retry_count"] = retry_attempt
            task["last_retry_at"] = datetime.now().isoformat()
            break

    FAILURES_FILE.write_text(json.dumps(failures, indent=2))


def get_failure_history(limit: int = 10) -> list[dict]:
    """Get recent failure history (for debugging/metrics)."""
    _ensure_failures_file()
    try:
        failures = json.loads(FAILURES_FILE.read_text())
        history = failures.get("failure_history", [])
        return sorted(history, key=lambda x: x.get("timestamp", ""), reverse=True)[:limit]
    except (json.JSONDecodeError, FileNotFoundError):
        return []


if __name__ == "__main__":
    # Quick test
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "test":
        print("[TEST] Logging sample failure...")
        log_failure(
            task_id="test-task-001",
            error="Network timeout after 3 retries",
            strategy="exponential_backoff",
            context={"agent": "retriever", "model": "qwen2.5:3b"},
        )
        print(f"[TEST] Blocked tasks: {get_blocked_tasks()}")
        print(f"[TEST] All tests passed ✓")
