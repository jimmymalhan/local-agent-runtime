#!/usr/bin/env python3
"""
schema_validator.py — Fix Root Causes #2-5
===========================================
Enforce consistent schema across all state writes and reads.

ROOT CAUSE #2: quality_score key mismatch
         #3: Dashboard writer path = reader path
         #4: Required key defaults (never partial state)
         #5: Parser fallbacks (never crash on missing keys)
"""
import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
STATE_FILE = BASE_DIR / "dashboard" / "state.json"

# ROOT CAUSE #4: Define required keys with defaults
REQUIRED_STATE_KEYS = {
    "ts": lambda: datetime.now().isoformat(),
    "quality": lambda: 0,
    "quality_score": lambda: 0,  # Support both variations
    "model": lambda: "local-v1",
    "recent_tasks": lambda: [],
    "changelog": lambda: [],
    "research_feed": lambda: [],
    "task_queue": lambda: {
        "total": 0,
        "completed": 0,
        "in_progress": 0,
        "failed": 0,
        "pending": 0
    },
    "epic_board": lambda: {"epics": [], "operations": {}},
    "board_plan": lambda: {"projects": [], "stages": []},
    "agents": lambda: {},
    "benchmark_scores": lambda: {},
    "token_usage": lambda: {
        "claude_tokens": 0,
        "local_tokens": 0,
        "budget_pct": 0.0,
        "warning": False,
        "hard_limit_hit": False
    },
    "hardware": lambda: {
        "cpu_pct": 0.0,
        "ram_pct": 0.0,
        "disk_pct": 0.0,
        "gpu_pct": None,
        "alert_level": "ok"
    },
    "failures": lambda: [],
    "version_changelog": lambda: {},
}

def normalize_task_status(status):
    """
    ROOT CAUSE #1 FIX: Normalize is_done/done/completed → single format
    """
    if status in ["completed", "done", "is_done", True]:
        return "completed"
    elif status in ["in_progress", "running"]:
        return "in_progress"
    elif status in ["pending", "queued"]:
        return "pending"
    elif status in ["failed", "error"]:
        return "failed"
    elif status in ["blocked"]:
        return "blocked"
    else:
        return "pending"  # Default fallback

def normalize_agent_output(output):
    """
    ROOT CAUSE #2 FIX: Normalize quality/quality_score key variation
    Agents might output "quality" but reader expects "quality_score" (or vice versa)
    """
    if isinstance(output, dict):
        # Support both variations
        if "quality" in output and "quality_score" not in output:
            output["quality_score"] = output["quality"]
        elif "quality_score" in output and "quality" not in output:
            output["quality"] = output["quality_score"]

        # Ensure both are numbers, default to 0
        output["quality_score"] = float(output.get("quality_score", 0))
        output["quality"] = float(output.get("quality", 0))

    return output

def validate_and_repair_state(state):
    """
    ROOT CAUSE #4 FIX: Validate all required keys exist, add defaults if missing
    ROOT CAUSE #5 FIX: Never write partial state — fill in defaults for missing keys
    """
    if not isinstance(state, dict):
        state = {}

    # Ensure all required keys exist
    for key, default_fn in REQUIRED_STATE_KEYS.items():
        if key not in state or state[key] is None:
            state[key] = default_fn()
            print(f"[SCHEMA REPAIR] Added missing key: {key}")

    # Ensure ts is always present and recent
    if "ts" not in state or not state["ts"]:
        state["ts"] = datetime.now().isoformat()

    return state

def write_state_safe(state):
    """
    ROOT CAUSE #3 FIX: Enforce consistent write path
    Always write to BASE_DIR / "dashboard" / "state.json"
    Never write to different paths
    """
    state = validate_and_repair_state(state)

    # Ensure directory exists
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)

    # Write atomically
    tmp_file = STATE_FILE.with_suffix('.tmp')
    with open(tmp_file, 'w') as f:
        json.dump(state, f, indent=2)

    # Atomic replace
    tmp_file.replace(STATE_FILE)

    print(f"[SCHEMA WRITE] Saved to {STATE_FILE}")
    return STATE_FILE

def read_state_safe():
    """
    ROOT CAUSE #5 FIX: Read with fallbacks — never crash on missing keys
    """
    try:
        if STATE_FILE.exists():
            with open(STATE_FILE) as f:
                state = json.load(f)
        else:
            print(f"[SCHEMA READ] {STATE_FILE} not found, using defaults")
            state = {}
    except json.JSONDecodeError as e:
        print(f"[SCHEMA READ] JSON parse error in {STATE_FILE}: {e}")
        print("[SCHEMA READ] Falling back to default state")
        state = {}
    except Exception as e:
        print(f"[SCHEMA READ] Error reading {STATE_FILE}: {e}")
        state = {}

    # Validate and repair
    state = validate_and_repair_state(state)

    return state

def update_task_status(task, new_status):
    """
    Update task status with normalization.
    Handles both "status" and "is_done" formats.
    """
    if isinstance(task, dict):
        new_status = normalize_task_status(new_status)
        task["status"] = new_status

        # For compatibility, also set is_done if status is completed
        if new_status == "completed":
            task["is_done"] = True
        else:
            task["is_done"] = False

    return task

def validate_task(task):
    """
    Validate a task has required fields.
    """
    required_fields = ["id", "title", "status", "agent"]

    for field in required_fields:
        if field not in task:
            print(f"[TASK VALIDATION] Missing required field: {field}")
            if field == "status":
                task["status"] = "pending"
            elif field == "is_done":
                task["is_done"] = False

    # Normalize status
    task["status"] = normalize_task_status(task.get("status", "pending"))

    return task

if __name__ == "__main__":
    # Test the schema validator
    print("Testing schema validator...")

    # Test 1: Read/write safety
    state = read_state_safe()
    print(f"✓ Read state safely (has {len(state)} keys)")

    # Test 2: Normalize task status
    for status_in in ["completed", "done", "is_done", "in_progress", "pending"]:
        normalized = normalize_task_status(status_in)
        print(f"✓ {status_in:15} → {normalized}")

    # Test 3: Normalize agent output
    output = {"quality": 0.75}
    normalized = normalize_agent_output(output)
    print(f"✓ Agent output normalization: quality={normalized['quality']}, quality_score={normalized['quality_score']}")

    # Test 4: State repair
    incomplete_state = {"ts": "2026-03-26"}
    repaired = validate_and_repair_state(incomplete_state)
    print(f"✓ Repaired incomplete state ({len(incomplete_state)} → {len(repaired)} keys)")

    print("\n✅ Schema validator ready")
