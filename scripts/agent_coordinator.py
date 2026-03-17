#!/usr/bin/env python3
"""Agent coordinator: prevents agents from stepping on each other during parallel execution.

Tracks file ownership, role locks, and provides collision detection so multiple
local agents can work simultaneously without conflicts.
"""
from __future__ import annotations

import fcntl
import json
import os
import pathlib
import time
from datetime import datetime

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_DIR = REPO_ROOT / "state"
COORDINATION_PATH = STATE_DIR / "agent-coordination.json"
COORDINATION_LOCK = STATE_DIR / "agent-coordination.lock"
STALE_SECONDS = 120


def _now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _load_state() -> dict:
    if not COORDINATION_PATH.exists():
        return {"claims": [], "collisions": [], "updated_at": ""}
    try:
        return json.loads(COORDINATION_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {"claims": [], "collisions": [], "updated_at": ""}


def _save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    state["updated_at"] = _now_iso()
    COORDINATION_PATH.write_text(json.dumps(state, indent=2) + "\n")


def _is_stale(claim: dict) -> bool:
    stamp = claim.get("claimed_at", "")
    if not stamp:
        return True
    try:
        claimed = datetime.fromisoformat(stamp)
    except ValueError:
        return True
    return (datetime.now() - claimed).total_seconds() > STALE_SECONDS


def _prune_stale(state: dict) -> dict:
    state["claims"] = [c for c in state.get("claims", []) if not _is_stale(c)]
    return state


def claim_files(role: str, files: list[str], pid: int | None = None) -> dict:
    """Claim ownership of files for a role. Returns collision info if any."""
    pid = pid or os.getpid()
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    with COORDINATION_LOCK.open("w") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        try:
            state = _prune_stale(_load_state())
            collisions = []

            for file_path in files:
                for existing in state["claims"]:
                    if existing["role"] == role:
                        continue
                    if file_path in existing.get("files", []):
                        collision = {
                            "file": file_path,
                            "claimed_by": existing["role"],
                            "requested_by": role,
                            "detected_at": _now_iso(),
                        }
                        collisions.append(collision)
                        state.setdefault("collisions", []).append(collision)

            if not collisions:
                # Remove old claims by this role, add new
                state["claims"] = [c for c in state["claims"] if c.get("role") != role]
                state["claims"].append({
                    "role": role,
                    "files": files,
                    "pid": pid,
                    "claimed_at": _now_iso(),
                })

            _save_state(state)
        finally:
            fcntl.flock(lock_handle, fcntl.LOCK_UN)

    return {
        "ok": len(collisions) == 0,
        "collisions": collisions,
    }


def release_files(role: str) -> None:
    """Release file claims for a role."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)

    with COORDINATION_LOCK.open("w") as lock_handle:
        fcntl.flock(lock_handle, fcntl.LOCK_EX)
        try:
            state = _prune_stale(_load_state())
            state["claims"] = [c for c in state["claims"] if c.get("role") != role]
            _save_state(state)
        finally:
            fcntl.flock(lock_handle, fcntl.LOCK_UN)


def current_claims() -> list[dict]:
    """Return all active (non-stale) file claims."""
    state = _prune_stale(_load_state())
    return state.get("claims", [])


def recent_collisions(limit: int = 10) -> list[dict]:
    """Return recent collision events."""
    state = _load_state()
    return state.get("collisions", [])[-limit:]


def status_report() -> str:
    """Render a human-readable coordination status."""
    claims = current_claims()
    collisions = recent_collisions()
    lines = ["AGENT COORDINATION STATUS", ""]

    if claims:
        lines.append("Active claims:")
        for claim in claims:
            files = ", ".join(claim.get("files", [])[:5])
            lines.append(f"  {claim['role']:15} pid={claim.get('pid', '?')} files=[{files}]")
    else:
        lines.append("No active file claims.")

    if collisions:
        lines.append("")
        lines.append(f"Recent collisions ({len(collisions)}):")
        for col in collisions[-5:]:
            lines.append(
                f"  {col['detected_at']} {col['file']} claimed by {col['claimed_by']}, "
                f"requested by {col['requested_by']}"
            )

    return "\n".join(lines)


if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "status":
        print(status_report())
    elif len(sys.argv) > 1 and sys.argv[1] == "release" and len(sys.argv) > 2:
        release_files(sys.argv[2])
        print(f"Released claims for {sys.argv[2]}")
    elif len(sys.argv) > 3 and sys.argv[1] == "claim":
        role = sys.argv[2]
        files = sys.argv[3:]
        result = claim_files(role, files)
        if result["ok"]:
            print(f"Claimed {len(files)} files for {role}")
        else:
            print(f"COLLISION: {json.dumps(result['collisions'], indent=2)}")
            sys.exit(1)
    else:
        print("Usage: agent_coordinator.py <status|claim ROLE FILE...|release ROLE>")
