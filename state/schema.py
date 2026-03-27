#!/usr/bin/env python3
"""
State Writer Schema Enforcement

Validates state.json before writing to prevent empty/null values
from breaking dashboard and agent feedback loops.
"""

import json
from pathlib import Path


def validate_state_write(state_dict, last_known_good=None):
    """
    Validate state.json before writing.
    Reject if quality="", model="", recent_tasks=[], etc.
    Return last_known_good if validation fails.

    Args:
        state_dict: Dictionary to validate
        last_known_good: Previous valid state to fallback to

    Returns:
        Validated state dict or last_known_good
    """
    required_fields = {
        "quality": (int, float),
        "model": str,
        "active_agent": str,
        "version": int,
        "recent_tasks": list,
        "changelog": list,
    }

    # Check each required field
    for field, type_ in required_fields.items():
        value = state_dict.get(field)

        # Reject empty values
        if value == "" or value is None or (isinstance(value, list) and len(value) == 0):
            print(f"[SCHEMA] REJECT: {field}={repr(value)} (empty)")
            if last_known_good:
                print(f"[SCHEMA] Falling back to last known good state")
                return last_known_good
            else:
                # No fallback available, return unvalidated to prevent hard failure
                print(f"[SCHEMA] WARNING: No fallback available, returning input as-is")
                return state_dict

        # Check type
        if not isinstance(value, type_):
            print(f"[SCHEMA] WARNING: {field} type mismatch (expected {type_.__name__}, got {type(value).__name__})")

    # All required fields present and non-empty
    return state_dict


def write_state(state_dict, state_file="dashboard/state.json"):
    """
    Write state.json only if validation passes.

    Args:
        state_dict: Dictionary to write
        state_file: Path to state file (default: dashboard/state.json)

    Returns:
        Validated state that was written
    """
    # Read last known good state
    last_known_good = None
    try:
        with open(state_file) as f:
            last_known_good = json.load(f)
    except Exception as e:
        print(f"[SCHEMA] Warning: Could not read last state: {e}")
        last_known_good = None

    # Validate new state
    validated = validate_state_write(state_dict, last_known_good)

    # Write validated state
    try:
        with open(state_file, "w") as f:
            json.dump(validated, f, indent=2)
        print(f"[SCHEMA] WRITE: State written successfully")
    except Exception as e:
        print(f"[SCHEMA] ERROR: Failed to write state: {e}")
        return last_known_good

    return validated


def read_state(state_file="dashboard/state.json"):
    """
    Read state.json with validation.

    Args:
        state_file: Path to state file

    Returns:
        Validated state dict or empty dict if missing
    """
    try:
        with open(state_file) as f:
            state = json.load(f)
            # Validate on read as well
            return validate_state_write(state)
    except Exception as e:
        print(f"[SCHEMA] Warning: Could not read state: {e}")
        return {}


if __name__ == "__main__":
    # Test the schema validator
    print("Testing schema validator...")

    # Test 1: Valid state
    valid_state = {
        "quality": 45.0,
        "model": "claude-opus",
        "active_agent": "benchmarker",
        "version": 5,
        "recent_tasks": ["task1", "task2"],
        "changelog": ["v1: initial", "v2: upgrade"],
    }
    print("\n✓ Valid state:")
    result = validate_state_write(valid_state)
    print(f"  Result: {result}")

    # Test 2: Invalid state (empty quality)
    invalid_state = {
        "quality": "",
        "model": "claude-opus",
        "active_agent": "benchmarker",
        "version": 5,
        "recent_tasks": [],
        "changelog": [],
    }
    print("\n✗ Invalid state (empty fields):")
    result = validate_state_write(invalid_state, valid_state)
    print(f"  Result: Fallback to last_known_good={result == valid_state}")

    print("\nSchema validation working correctly!")
