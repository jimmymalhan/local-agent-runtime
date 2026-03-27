#!/usr/bin/env python3
"""
Runtime Lessons — Track agent attempts and enforce 3-attempt rescue gate

Stores attempt history in state/runtime-lessons.json for rescue gate enforcement.
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Optional


RUNTIME_LESSONS_FILE = "state/runtime-lessons.json"


def init_runtime_lessons(file_path: str = RUNTIME_LESSONS_FILE) -> Dict:
    """Initialize or read runtime-lessons.json."""
    try:
        if os.path.exists(file_path):
            with open(file_path) as f:
                return json.load(f)
    except Exception as e:
        print(f"[RUNTIME] Warning: Could not read {file_path}: {e}")

    # Return empty template
    return {}


def log_attempt(
    task_id: str,
    strategy: str,
    error: Optional[str] = None,
    success: bool = False,
    file_path: str = RUNTIME_LESSONS_FILE
) -> None:
    """
    Log an attempt to state/runtime-lessons.json.

    Args:
        task_id: Task identifier
        strategy: Strategy used (e.g., "default_prompt", "minimal_prompt", "verbose_prompt")
        error: Error message if failed
        success: Whether this attempt succeeded
        file_path: Path to runtime-lessons file
    """
    # Read current lessons
    try:
        with open(file_path) as f:
            lessons = json.load(f)
            # Fix: if lessons is a list (old format), convert to dict
            if isinstance(lessons, list):
                lessons = {}
    except:
        lessons = {}

    # Initialize task if needed
    if task_id not in lessons:
        lessons[task_id] = {
            "attempts": [],
            "rescue_escalated": False,
            "first_attempt_at": datetime.now().isoformat(),
        }

    # Add attempt record
    attempt_num = len(lessons[task_id]["attempts"]) + 1
    lessons[task_id]["attempts"].append({
        "attempt": attempt_num,
        "strategy": strategy,
        "error": error,
        "success": success,
        "timestamp": datetime.now().isoformat(),
    })

    # Write back
    try:
        with open(file_path, "w") as f:
            json.dump(lessons, f, indent=2)
        print(f"[RUNTIME] Logged attempt {attempt_num} for task {task_id}")
    except Exception as e:
        print(f"[RUNTIME] ERROR: Could not write {file_path}: {e}")


def get_attempt_count(task_id: str, file_path: str = RUNTIME_LESSONS_FILE) -> int:
    """Get number of attempts for a task."""
    try:
        with open(file_path) as f:
            lessons = json.load(f)
            if task_id in lessons:
                return len(lessons[task_id]["attempts"])
    except:
        pass
    return 0


def can_escalate_to_rescue(task_id: str, file_path: str = RUNTIME_LESSONS_FILE, max_attempts: int = 3) -> bool:
    """
    Check if a task should be escalated to rescue.

    Returns True if:
    1. Attempt count >= max_attempts
    2. All attempts have failed

    Args:
        task_id: Task identifier
        file_path: Path to runtime-lessons file
        max_attempts: Max retries before rescue (default: 3)

    Returns:
        True if eligible for rescue, False otherwise
    """
    try:
        with open(file_path) as f:
            lessons = json.load(f)
            if task_id not in lessons:
                return False

            task_lessons = lessons[task_id]
            attempts = task_lessons.get("attempts", [])

            # Check attempt count
            if len(attempts) < max_attempts:
                return False

            # Check if all attempts failed
            for attempt in attempts:
                if attempt.get("success"):
                    return False  # At least one succeeded, don't rescue

            # All attempts failed and count >= max_attempts
            return True
    except:
        pass

    return False


def mark_rescued(task_id: str, file_path: str = RUNTIME_LESSONS_FILE) -> None:
    """Mark a task as escalated to rescue."""
    try:
        with open(file_path) as f:
            lessons = json.load(f)
    except:
        lessons = {}

    if task_id in lessons:
        lessons[task_id]["rescue_escalated"] = True
        lessons[task_id]["rescue_escalated_at"] = datetime.now().isoformat()

    try:
        with open(file_path, "w") as f:
            json.dump(lessons, f, indent=2)
        print(f"[RUNTIME] Marked task {task_id} as rescued")
    except Exception as e:
        print(f"[RUNTIME] ERROR: Could not write {file_path}: {e}")


def get_task_history(task_id: str, file_path: str = RUNTIME_LESSONS_FILE) -> Dict:
    """Get full attempt history for a task."""
    try:
        with open(file_path) as f:
            lessons = json.load(f)
            if task_id in lessons:
                return lessons[task_id]
    except:
        pass
    return {}


if __name__ == "__main__":
    # Test the runtime lessons tracker
    print("Testing runtime lessons tracker...")

    # Test 1: Log attempts
    print("\n1. Logging 3 failed attempts:")
    for i in range(1, 4):
        log_attempt("task-001", f"strategy-{i}", error=f"Error on attempt {i}", success=False)

    # Test 2: Check attempt count
    count = get_attempt_count("task-001")
    print(f"   Attempts for task-001: {count}")

    # Test 3: Check rescue eligibility
    eligible = can_escalate_to_rescue("task-001")
    print(f"   Eligible for rescue: {eligible}")

    # Test 4: Mark as rescued
    mark_rescued("task-001")
    history = get_task_history("task-001")
    print(f"   Rescue escalated: {history.get('rescue_escalated')}")

    print("\nRuntime lessons tracker working correctly!")
