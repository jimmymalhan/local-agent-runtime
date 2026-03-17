#!/usr/bin/env python3
"""Cloud takeover monitor: detects when local agents are stuck and triggers cloud takeover.

Monitors:
- Execution time vs configured timeout
- Progress stalls (no progress for N seconds)
- Resource ceiling sustained violations
- ROI kill switch state

When triggered, writes a takeover recommendation to state and exits with a codex command.
"""
from __future__ import annotations

import json
import os
import pathlib
import signal
import sys
import time
from datetime import datetime

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PROGRESS_PATH = REPO_ROOT / "state" / "progress.json"
RUN_LOCK_PATH = REPO_ROOT / "state" / "run.lock"
SESSION_STATE_PATH = REPO_ROOT / "state" / "session-state.json"
ROI_STATE_PATH = REPO_ROOT / "state" / "roi-metrics.json"
RESOURCE_PATH = REPO_ROOT / "state" / "resource-status.json"
RUNTIME_PATH = REPO_ROOT / "config" / "runtime.json"
TAKEOVER_STATE_PATH = REPO_ROOT / "state" / "takeover-recommendation.json"

DEFAULT_MAX_STALL_SECONDS = 120
DEFAULT_MAX_TOTAL_SECONDS = 600
DEFAULT_POLL_SECONDS = 5


def load_json(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def is_pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def check_roi_kill_switch() -> bool:
    data = load_json(ROI_STATE_PATH)
    return bool(data.get("kill_switch"))


def check_stall(last_progress_pct: float, current_progress_pct: float, stall_start: float, max_stall: float) -> tuple[bool, float]:
    """Check if progress has stalled. Returns (is_stalled, stall_start_time)."""
    now = time.time()
    if current_progress_pct > last_progress_pct:
        return False, now
    if stall_start == 0:
        return False, now
    elapsed = now - stall_start
    return elapsed >= max_stall, stall_start


def check_total_timeout(started_at: str, max_total: float) -> bool:
    if not started_at:
        return False
    try:
        start = datetime.fromisoformat(started_at)
    except ValueError:
        return False
    return (datetime.now() - start).total_seconds() >= max_total


def check_resource_ceiling() -> bool:
    runtime = load_json(RUNTIME_PATH)
    resource = load_json(RESOURCE_PATH)
    if not resource:
        return False
    limits = runtime.get("resource_limits", {})
    cpu_limit = float(limits.get("cpu_percent", 70))
    mem_limit = float(limits.get("memory_percent", 70))
    return (
        float(resource.get("cpu_percent", 0)) > cpu_limit
        or float(resource.get("memory_percent", 0)) > mem_limit
    )


def write_takeover(reason: str, task: str, target_repo: str) -> None:
    recommendation = {
        "reason": reason,
        "task": task,
        "target_repo": target_repo,
        "recommended_at": datetime.now().isoformat(timespec="seconds"),
        "command": f'codex "{target_repo}" "{task}"',
    }
    TAKEOVER_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    TAKEOVER_STATE_PATH.write_text(json.dumps(recommendation, indent=2) + "\n")


def monitor(
    max_stall: float = DEFAULT_MAX_STALL_SECONDS,
    max_total: float = DEFAULT_MAX_TOTAL_SECONDS,
    poll: float = DEFAULT_POLL_SECONDS,
) -> int:
    """Run the takeover monitor loop. Returns 0 if task completes, 2 if takeover triggered."""
    stop = False

    def on_signal(_sig, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    last_pct = 0.0
    stall_start = time.time()

    while not stop:
        progress = load_json(PROGRESS_PATH)
        lock = load_json(RUN_LOCK_PATH)
        overall = progress.get("overall", {})
        status = overall.get("status", "")
        current_pct = float(overall.get("percent", 0.0))
        task = progress.get("task", "")
        target_repo = lock.get("target_repo", str(REPO_ROOT))

        # Task done?
        if status in {"completed", "failed"}:
            return 0

        # Process dead?
        lock_pid = int(lock.get("pid", 0) or 0)
        if lock_pid > 0 and not is_pid_alive(lock_pid):
            if status == "running":
                reason = f"Local agent process (pid {lock_pid}) died unexpectedly"
                write_takeover(reason, task, target_repo)
                print(f"TAKEOVER: {reason}", file=sys.stderr)
                print(f'codex "{target_repo}" "{task}"')
                return 2

        # ROI kill switch
        if check_roi_kill_switch():
            reason = "ROI kill switch active: repeated negative trend"
            write_takeover(reason, task, target_repo)
            print(f"TAKEOVER: {reason}", file=sys.stderr)
            print(f'codex "{target_repo}" "{task}"')
            return 2

        # Stall detection
        stalled, stall_start = check_stall(last_pct, current_pct, stall_start, max_stall)
        if stalled:
            stall_duration = int(time.time() - stall_start)
            reason = f"Progress stalled at {current_pct:.1f}% for {stall_duration}s"
            write_takeover(reason, task, target_repo)
            print(f"TAKEOVER: {reason}", file=sys.stderr)
            print(f'codex "{target_repo}" "{task}"')
            return 2

        # Total timeout
        if check_total_timeout(progress.get("started_at", ""), max_total):
            reason = f"Total execution time exceeded {max_total}s"
            write_takeover(reason, task, target_repo)
            print(f"TAKEOVER: {reason}", file=sys.stderr)
            print(f'codex "{target_repo}" "{task}"')
            return 2

        last_pct = current_pct
        time.sleep(poll)

    return 0


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Monitor local agents and trigger cloud takeover on stall")
    parser.add_argument("--max-stall", type=float, default=DEFAULT_MAX_STALL_SECONDS)
    parser.add_argument("--max-total", type=float, default=DEFAULT_MAX_TOTAL_SECONDS)
    parser.add_argument("--poll", type=float, default=DEFAULT_POLL_SECONDS)
    args = parser.parse_args()
    sys.exit(monitor(args.max_stall, args.max_total, args.poll))
