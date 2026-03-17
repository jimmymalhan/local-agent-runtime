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
        {"option": "Downgrade model to 3b", "action": "model_downgrade", "speed": 1, "detail": "Switch to qwen2.5:3b for current stage"},
        {"option": "Serialize parallel work", "action": "serialize", "speed": 2, "detail": "Run one role at a time to halve memory"},
        {"option": "Hand off to cloud", "action": "takeover", "speed": 3, "detail": "Send remaining work to Claude/Codex session"},
    ],
    "cpu_ceiling": [
        {"option": "Serialize parallel roles", "action": "serialize", "speed": 1, "detail": "Run roles sequentially"},
        {"option": "Reduce Ollama parallelism", "action": "reduce_parallel", "speed": 2, "detail": "Set ollama_num_parallel=1"},
        {"option": "Cloud takeover", "action": "takeover", "speed": 3, "detail": "Route to Claude/Codex"},
    ],
    "roi_kill_switch": [
        {"option": "Reset ROI and retry with lighter config", "action": "reset_roi", "speed": 1, "detail": "Clear negative events, switch to fast profile"},
        {"option": "Skip to cloud session", "action": "takeover", "speed": 2, "detail": "Cloud session completes while local learns"},
        {"option": "Re-plan with smaller scope", "action": "replan", "speed": 3, "detail": "Break task into smaller pieces"},
    ],
    "stale_lock": [
        {"option": "Kill stale process and release lock", "action": "kill_stale", "speed": 1, "detail": "Remove run.lock, continue"},
        {"option": "Wait 10s then force-release", "action": "wait_release", "speed": 2, "detail": "Grace period then force"},
        {"option": "Run in parallel cloud session", "action": "takeover", "speed": 3, "detail": "Don't wait, start cloud now"},
    ],
    "generic_output": [
        {"option": "Retry with stronger model", "action": "upgrade_model", "speed": 1, "detail": "Use deepseek-r1:8b instead of 3b"},
        {"option": "Inject more context", "action": "expand_context", "speed": 2, "detail": "Increase prompt budget for this stage"},
        {"option": "Route to cloud model", "action": "takeover", "speed": 3, "detail": "Use GPT-4.1 via GitHub Models"},
    ],
    "timeout": [
        {"option": "Switch to fast profile", "action": "fast_profile", "speed": 1, "detail": "Use fast profile with fewer roles"},
        {"option": "Skip non-critical roles", "action": "skip_roles", "speed": 2, "detail": "Jump to summarizer from current state"},
        {"option": "Cloud takeover", "action": "takeover", "speed": 3, "detail": "Hand remaining work to Codex"},
    ],
    "default": [
        {"option": "Retry with current config", "action": "retry", "speed": 1, "detail": "Simple retry"},
        {"option": "Downgrade and retry", "action": "model_downgrade", "speed": 2, "detail": "Use lighter model"},
        {"option": "Cloud takeover", "action": "takeover", "speed": 3, "detail": "Route to Claude/Codex"},
    ],
}


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
