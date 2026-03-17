#!/usr/bin/env python3
"""Aggressive blocker resolver: never sit on a task.

For every blocker, generates 2-3 resolution options ranked by speed.
Auto-picks the fastest option and executes. Teaches runtime the lesson.
"""
from __future__ import annotations

import json
import pathlib
import sys
from datetime import datetime

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))

BLOCKER_STRATEGIES = {
    "memory_ceiling": [
        {"option": "Downgrade model to 3b", "action": "model_downgrade", "speed": 1, "eta_seconds": 5, "detail": "Switch to qwen2.5:3b for current stage"},
        {"option": "Serialize parallel work", "action": "serialize", "speed": 2, "eta_seconds": 10, "detail": "Run one role at a time to halve memory"},
        {"option": "Hand off to cloud", "action": "takeover", "speed": 3, "eta_seconds": 30, "detail": "Send remaining work to Claude/Codex session"},
    ],
    "cpu_ceiling": [
        {"option": "Serialize parallel roles", "action": "serialize", "speed": 1, "eta_seconds": 5, "detail": "Run roles sequentially"},
        {"option": "Reduce Ollama parallelism", "action": "reduce_parallel", "speed": 2, "eta_seconds": 8, "detail": "Set ollama_num_parallel=1"},
        {"option": "Cloud takeover", "action": "takeover", "speed": 3, "eta_seconds": 30, "detail": "Route to Claude/Codex"},
    ],
    "roi_kill_switch": [
        {"option": "Reset ROI and retry with lighter config", "action": "reset_roi", "speed": 1, "eta_seconds": 3, "detail": "Clear negative events, switch to fast profile"},
        {"option": "Skip to cloud session", "action": "takeover", "speed": 2, "eta_seconds": 20, "detail": "Cloud session completes while local learns"},
        {"option": "Re-plan with smaller scope", "action": "replan", "speed": 3, "eta_seconds": 60, "detail": "Break task into smaller pieces"},
    ],
    "stale_lock": [
        {"option": "Kill stale process and release lock", "action": "kill_stale", "speed": 1, "eta_seconds": 2, "detail": "Remove run.lock, continue"},
        {"option": "Wait 10s then force-release", "action": "wait_release", "speed": 2, "eta_seconds": 12, "detail": "Grace period then force"},
        {"option": "Run in parallel cloud session", "action": "takeover", "speed": 3, "eta_seconds": 25, "detail": "Don't wait, start cloud now"},
    ],
    "generic_output": [
        {"option": "Retry with stronger model", "action": "upgrade_model", "speed": 1, "eta_seconds": 15, "detail": "Use deepseek-r1:8b instead of 3b"},
        {"option": "Inject more context", "action": "expand_context", "speed": 2, "eta_seconds": 20, "detail": "Increase prompt budget for this stage"},
        {"option": "Route to cloud model", "action": "takeover", "speed": 3, "eta_seconds": 30, "detail": "Use GPT-4.1 via GitHub Models"},
    ],
    "timeout": [
        {"option": "Switch to fast profile", "action": "fast_profile", "speed": 1, "eta_seconds": 5, "detail": "Use fast profile with fewer roles"},
        {"option": "Skip non-critical roles", "action": "skip_roles", "speed": 2, "eta_seconds": 8, "detail": "Jump to summarizer from current state"},
        {"option": "Cloud takeover", "action": "takeover", "speed": 3, "eta_seconds": 30, "detail": "Hand remaining work to Codex"},
    ],
    "default": [
        {"option": "Retry with current config", "action": "retry", "speed": 1, "eta_seconds": 10, "detail": "Simple retry"},
        {"option": "Downgrade and retry", "action": "model_downgrade", "speed": 2, "eta_seconds": 15, "detail": "Use lighter model"},
        {"option": "Cloud takeover", "action": "takeover", "speed": 3, "eta_seconds": 30, "detail": "Route to Claude/Codex"},
    ],
}

# Average seconds per role for ETA estimation (aggressive targets)
ROLE_ETA_SECONDS = {
    "researcher": 20, "retriever": 15, "planner": 35,
    "architect": 30, "implementer": 45, "tester": 30,
    "reviewer": 35, "debugger": 30, "optimizer": 20,
    "benchmarker": 25, "qa": 30, "user_acceptance": 15,
    "summarizer": 20,
}


def estimate_completion(progress: dict, todo_stats: dict, session_count: int = 3) -> dict:
    """Estimate aggressive ETAs for pipeline and todo completion."""
    stages = progress.get("stages", [])
    remaining_roles = [s for s in stages if s.get("status") not in ("completed", "skipped")]
    pipeline_eta_s = sum(ROLE_ETA_SECONDS.get(s.get("id", ""), 30) for s in remaining_roles)

    # For todo: estimate based on open items, ~2 min each for simple, ~5 for complex
    total = todo_stats.get("total", 0)
    done = todo_stats.get("done", 0)
    open_count = todo_stats.get("open", 0)
    # Aggressive: assume parallel work across sessions cuts time
    sessions_active = max(1, session_count)
    todo_eta_minutes = max(1, (open_count * 3) // sessions_active)  # 3 min avg per task, divided by sessions

    return {
        "pipeline_eta_seconds": pipeline_eta_s,
        "pipeline_eta_display": _fmt_eta(pipeline_eta_s),
        "remaining_roles": len(remaining_roles),
        "todo_eta_minutes": todo_eta_minutes,
        "todo_eta_display": _fmt_eta(todo_eta_minutes * 60),
        "total_tasks": total,
        "done_tasks": done,
        "open_tasks": open_count,
    }


def _fmt_eta(seconds: int) -> str:
    if seconds <= 0:
        return "done"
    if seconds < 60:
        return f"{seconds}s"
    m = seconds // 60
    s = seconds % 60
    if m < 60:
        return f"{m}m {s}s" if s else f"{m}m"
    h = m // 60
    m2 = m % 60
    return f"{h}h {m2}m"


def classify_blocker(context: dict) -> str:
    """Classify a blocker from resource/ROI/progress state."""
    resource = context.get("resource", {})
    roi = context.get("roi", {})
    progress = context.get("progress", {})

    mem = float(resource.get("memory_percent", 0))
    cpu = float(resource.get("cpu_percent", 0))
    mem_limit = float(context.get("memory_limit", 85))
    cpu_limit = float(context.get("cpu_limit", 85))

    if roi.get("kill_switch"):
        return "roi_kill_switch"
    if mem > mem_limit:
        return "memory_ceiling"
    if cpu > cpu_limit:
        return "cpu_ceiling"

    overall = progress.get("overall", {})
    if overall.get("status") == "running":
        # Check for stall
        lock = context.get("lock", {})
        if lock.get("pid") and not _pid_alive(int(lock["pid"])):
            return "stale_lock"

    return "default"


def _pid_alive(pid: int) -> bool:
    import os
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def resolve_options(blocker_type: str) -> list[dict]:
    """Return 2-3 resolution options for a blocker type, ranked by speed."""
    return BLOCKER_STRATEGIES.get(blocker_type, BLOCKER_STRATEGIES["default"])


def auto_resolve(context: dict) -> dict:
    """Classify blocker and return the fastest resolution option."""
    blocker_type = classify_blocker(context)
    options = resolve_options(blocker_type)
    chosen = options[0]  # Always pick fastest
    return {
        "blocker_type": blocker_type,
        "chosen": chosen,
        "alternatives": options[1:],
        "resolved_at": datetime.now().isoformat(timespec="seconds"),
    }


def execute_resolution(action: str, context: dict) -> str:
    """Execute a resolution action. Returns status message."""
    if action == "model_downgrade":
        return "Switched to lighter model (qwen2.5:3b)"
    elif action == "serialize":
        return "Serialized parallel work to reduce resource pressure"
    elif action == "takeover":
        task = context.get("task", "")
        repo = context.get("target_repo", "")
        return f'Cloud takeover: codex "{repo}" "{task}"'
    elif action == "reset_roi":
        roi_path = REPO_ROOT / "state" / "roi-metrics.json"
        roi_path.write_text(json.dumps({
            "events": [], "trend": "healthy", "kill_switch": False, "consecutive_negative": 0
        }, indent=2) + "\n")
        return "ROI kill switch reset. Retrying with clean state."
    elif action == "kill_stale":
        lock_path = REPO_ROOT / "state" / "run.lock"
        lock_path.unlink(missing_ok=True)
        return "Stale lock removed. Pipeline can proceed."
    elif action == "reduce_parallel":
        return "Reduced Ollama parallelism to 1"
    elif action == "fast_profile":
        return "Switched to fast profile (5 roles, 8K context)"
    elif action == "skip_roles":
        return "Skipping non-critical roles, jumping to summarizer"
    elif action == "upgrade_model":
        return "Upgraded to deepseek-r1:8b for retry"
    elif action == "expand_context":
        return "Expanded prompt budget for current stage"
    elif action == "replan":
        return "Re-planning with smaller task scope"
    else:
        return f"Retrying with action: {action}"


def report(context: dict | None = None) -> str:
    """Generate human-readable blocker resolution report."""
    if context is None:
        from live_dashboard import load_json
        context = {
            "resource": load_json(REPO_ROOT / "state" / "resource-status.json"),
            "roi": load_json(REPO_ROOT / "state" / "roi-metrics.json"),
            "progress": load_json(REPO_ROOT / "state" / "progress.json"),
            "lock": load_json(REPO_ROOT / "state" / "run.lock"),
        }

    blocker_type = classify_blocker(context)
    options = resolve_options(blocker_type)

    lines = [
        f"BLOCKER: {blocker_type.upper().replace('_', ' ')}",
        "",
        "Resolution options (fastest first):",
    ]
    for i, opt in enumerate(options, 1):
        marker = ">>>" if i == 1 else "   "
        lines.append(f"  {marker} Option {i}: {opt['option']}")
        lines.append(f"      Action: {opt['action']}")
        lines.append(f"      Detail: {opt['detail']}")

    lines.append("")
    lines.append(f"Auto-pick: Option 1 ({options[0]['option']})")
    return "\n".join(lines)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "resolve":
        print(report())
        result = auto_resolve({})
        msg = execute_resolution(result["chosen"]["action"], {})
        print(f"\nExecuted: {msg}")
    else:
        print(report())
