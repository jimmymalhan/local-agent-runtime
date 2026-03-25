#!/usr/bin/env python3
"""
state_writer.py — Shared state update utility
===============================================
All agents call these functions to update the dashboard state BEFORE
and AFTER any action. Dashboard reads state.json and pushes via WebSocket.

Usage:
  from dashboard.state_writer import update_agent, update_task_queue, log_failure

Protocol: The board updates FIRST. Always. No agent moves without updating state.
"""
import os, json, time, fcntl
from pathlib import Path
from datetime import datetime

STATE_FILE = str(Path(__file__).parent / "state.json")
_DEFAULT_STATE = {
    "ts": "",
    "version": {"current": 0, "total": 100, "pct_complete": 0.0, "label": ""},
    "agents": {},
    "task_queue": {"total": 100, "completed": 0, "in_progress": 0, "failed": 0, "pending": 100},
    "benchmark_scores": {},
    "token_usage": {"claude_tokens": 0, "local_tokens": 0, "budget_pct": 0.0,
                    "warning": False, "hard_limit_hit": False},
    "hardware": {"cpu_pct": 0.0, "ram_pct": 0.0, "disk_pct": 0.0,
                 "gpu_pct": None, "alert_level": "ok"},
    "failures": [],
    "research_feed": [],
    "version_changelog": {},
}


def _read() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return dict(_DEFAULT_STATE)


def _write(state: dict):
    state["ts"] = datetime.now().isoformat()
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)  # atomic replace


def update_agent(agent_name: str, status: str, task: str = "", task_id=None,
                 elapsed_s: float = 0.0):
    """
    Update agent status on the board BEFORE the agent does anything.
    Preserves existing sub_agents field so worker state survives status changes.
    status: idle | planning | executing | reviewing | blocked | restarting | upgrading
    """
    state = _read()
    if "agents" not in state:
        state["agents"] = {}
    # Preserve existing sub_agents when just updating status
    existing = state["agents"].get(agent_name, {})
    state["agents"][agent_name] = {
        "status": status,
        "task": task[:80] if task else "",
        "task_id": task_id,
        "elapsed_s": elapsed_s,
        "last_activity": datetime.now().isoformat(),
        "sub_agents": existing.get("sub_agents", []),
        "worker_count": existing.get("worker_count", 0),
    }
    _write(state)


def update_sub_agents(agent_name: str, workers: list):
    """
    Write sub-agent worker list for an agent to dashboard state.
    Called by SubAgentPool on spawn, progress, and completion.

    Each worker dict: {id, status, task, model, elapsed_s, quality}
    status: running | done | idle | failed
    """
    state = _read()
    if "agents" not in state:
        state["agents"] = {}
    existing = state["agents"].get(agent_name, {})
    clean = []
    for w in workers:
        clean.append({
            "id": w.get("id", 0),
            "status": w.get("status", "idle"),
            "task": str(w.get("task", ""))[:50],
            "model": w.get("model", ""),
            "elapsed_s": round(float(w.get("elapsed_s", 0)), 1),
            "quality": int(w.get("quality", 0)),
        })
    existing["sub_agents"] = clean
    existing["worker_count"] = len([w for w in clean if w["status"] == "running"])
    existing.setdefault("last_activity", datetime.now().isoformat())
    state["agents"][agent_name] = existing
    _write(state)


def update_version(current: int, total: int = 100, label: str = ""):
    """Update current benchmark version on the board."""
    state = _read()
    pct = round(current / total * 100, 1) if total else 0
    state["version"] = {
        "current": current,
        "total": total,
        "pct_complete": pct,
        "label": label or f"v{current}",
    }
    _write(state)


def update_task_queue(total: int, completed: int, in_progress: int,
                      failed: int, pending: int):
    """Update task queue counts."""
    state = _read()
    state["task_queue"] = {
        "total": total, "completed": completed, "in_progress": in_progress,
        "failed": failed, "pending": pending,
    }
    _write(state)


def update_benchmark_score(version: int, local_avg: float, opus_avg: float,
                            win_rate: float, gap: float):
    """Add/update benchmark score for a version."""
    state = _read()
    if "benchmark_scores" not in state:
        state["benchmark_scores"] = {}
    state["benchmark_scores"][f"v{version}"] = {
        "local": round(local_avg, 1),
        "opus": round(opus_avg, 1),
        "gap": round(gap, 1),
        "win_rate": round(win_rate, 1),
        "ts": datetime.now().isoformat(),
    }
    _write(state)


def update_token_usage(claude_tokens: int, local_tokens: int, total_tasks: int):
    """Update token usage tracker with warning if Claude exceeds 10% budget."""
    state = _read()
    # budget_pct = claude tasks / total_tasks (token count isn't the budget, task count is)
    budget_pct = round(claude_tokens / max(local_tokens + claude_tokens, 1) * 100, 1)
    state["token_usage"] = {
        "claude_tokens": claude_tokens,
        "local_tokens": local_tokens,
        "budget_pct": budget_pct,
        "warning": budget_pct > 8.0,
        "hard_limit_hit": budget_pct >= 10.0,
    }
    _write(state)


def update_hardware(cpu_pct: float, ram_pct: float, disk_pct: float = 0.0,
                    gpu_pct=None):
    """Update hardware monitor readings."""
    state = _read()
    if ram_pct >= 85 or cpu_pct >= 90:
        alert = "red"
    elif ram_pct >= 80 or cpu_pct >= 80:
        alert = "yellow"
    else:
        alert = "ok"
    state["hardware"] = {
        "cpu_pct": round(cpu_pct, 1),
        "ram_pct": round(ram_pct, 1),
        "disk_pct": round(disk_pct, 1),
        "gpu_pct": gpu_pct,
        "alert_level": alert,
    }
    _write(state)


def log_failure(agent_name: str, task_name: str, task_id, attempt: int,
                what_was_tried: str):
    """Log a failure to the failures list (max 10 entries)."""
    state = _read()
    if "failures" not in state:
        state["failures"] = []
    entry = {
        "ts": datetime.now().isoformat(),
        "agent": agent_name,
        "task": task_name[:60],
        "task_id": task_id,
        "attempt": attempt,
        "tried": what_was_tried[:120],
    }
    state["failures"] = [entry] + state["failures"][:9]  # keep last 10
    _write(state)


def log_research(finding: str, source: str = ""):
    """Add an entry to the research feed (max 10)."""
    state = _read()
    if "research_feed" not in state:
        state["research_feed"] = []
    entry = {"ts": datetime.now().isoformat(), "finding": finding[:200], "source": source}
    state["research_feed"] = [entry] + state["research_feed"][:9]
    _write(state)


def update_version_changelog(version: int, changes: list,
                              before_score: float, after_score: float):
    """Log what was upgraded in current version vs last."""
    state = _read()
    if "version_changelog" not in state:
        state["version_changelog"] = {}
    state["version_changelog"][f"v{version}"] = {
        "changes": changes,
        "before_score": before_score,
        "after_score": after_score,
        "delta": round(after_score - before_score, 1),
        "ts": datetime.now().isoformat(),
    }
    _write(state)
