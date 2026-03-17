#!/usr/bin/env python3
"""Codex-style live CLI dashboard with real-time progress, timer, and model usage breakdown."""
from __future__ import annotations

import json
import os
import pathlib
import signal
import sys
import time
from datetime import datetime

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
PROGRESS_PATH = REPO_ROOT / "state" / "progress.json"
SESSION_STATE_PATH = REPO_ROOT / "state" / "session-state.json"
RUN_LOCK_PATH = REPO_ROOT / "state" / "run.lock"
RUNTIME_PATH = REPO_ROOT / "config" / "runtime.json"
RESOURCE_PATH = REPO_ROOT / "state" / "resource-status.json"
ROI_STATE_PATH = REPO_ROOT / "state" / "roi-metrics.json"
LESSONS_PATH = REPO_ROOT / "state" / "runtime-lessons.json"

ANSI_BOLD = "\033[1m"
ANSI_DIM = "\033[2m"
ANSI_GREEN = "\033[32m"
ANSI_YELLOW = "\033[33m"
ANSI_RED = "\033[31m"
ANSI_CYAN = "\033[36m"
ANSI_RESET = "\033[0m"
ANSI_CLEAR_LINE = "\033[2K"
ANSI_UP = "\033[A"


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


def render_bar(percent: float, width: int = 30, color: str = ANSI_GREEN) -> str:
    percent = max(0.0, min(100.0, float(percent)))
    filled = round(width * percent / 100.0)
    empty = width - filled
    bar = f"{color}{'█' * filled}{ANSI_DIM}{'░' * empty}{ANSI_RESET}"
    return f"[{bar}]"


def elapsed_str(started_at: str | None) -> str:
    if not started_at:
        return "0s"
    try:
        start = datetime.fromisoformat(started_at)
    except ValueError:
        return "0s"
    delta = datetime.now() - start
    total = max(0, int(delta.total_seconds()))
    minutes, seconds = divmod(total, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def model_usage_breakdown(progress: dict, runtime: dict) -> dict[str, dict]:
    """Return per-provider usage counts from progress stages and runtime config."""
    team = runtime.get("team", {})
    providers: dict[str, dict] = {}
    stages = progress.get("stages", [])

    for stage in stages:
        stage_id = stage.get("id", "")
        if stage_id == "preflight":
            continue
        detail = stage.get("detail", "")
        status = stage.get("status", "pending")

        provider = "ollama"
        model = team.get(stage_id, {}).get("model", "unknown")

        if "github_models" in detail:
            provider = "github_models"
        elif "clawbot" in detail:
            provider = "clawbot"
        elif "openclaw" in detail:
            provider = "openclaw"

        if ":" in detail and ("Completed" in detail or "Dispatching" in detail or "Running" in detail):
            parts = detail.split(":")
            if len(parts) >= 2:
                model = parts[-1].strip()

        if provider not in providers:
            providers[provider] = {"total": 0, "completed": 0, "running": 0, "models": set()}
        providers[provider]["total"] += 1
        providers[provider]["models"].add(model)
        if status == "completed":
            providers[provider]["completed"] += 1
        elif status == "running":
            providers[provider]["running"] += 1

    return providers


def recent_lessons(limit: int = 3) -> list[dict]:
    lessons = load_json(LESSONS_PATH)
    if isinstance(lessons, list):
        return lessons[-limit:]
    if isinstance(lessons, dict):
        return lessons.get("lessons", [])[-limit:]
    return []


def live_resource_snapshot() -> dict:
    try:
        from resource_status import cpu_percent, memory_percent, threshold_percent

        return {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "cpu_percent": cpu_percent(),
            "memory_percent": memory_percent(),
            "threshold_percent": threshold_percent(),
        }
    except Exception:
        return load_json(RESOURCE_PATH)


def next_decision(progress: dict, resource: dict, roi: dict) -> str:
    cpu = float(resource.get("cpu_percent", 0.0))
    mem = float(resource.get("memory_percent", 0.0))
    if roi.get("kill_switch"):
        return "ROI kill switch: cut scope, re-plan locally, and retry the smallest useful slice."
    if mem > 70:
        return "Memory high: unload resident Ollama models or downgrade before dispatch."
    if cpu > 70:
        return "CPU high: serialize roles and lower Ollama parallelism."
    stages = progress.get("stages", [])
    running = next((stage for stage in stages if stage.get("status") == "running"), None)
    if running:
        return f"Push {running.get('label', running.get('id', 'current stage'))} forward with smallest next diff."
    return "No active blocker: start the next local role immediately."


def executive_tension(progress: dict, resource: dict, roi: dict) -> list[str]:
    cpu = float(resource.get("cpu_percent", 0.0))
    mem = float(resource.get("memory_percent", 0.0))
    active = next((stage for stage in progress.get("stages", []) if stage.get("status") == "running"), {})
    current = active.get("label", active.get("id", "next stage")) if active else "next stage"
    lines = [
        f"    Manager  wants immediate progress on {current}",
        "    Director wants backlog cuts and tighter priority ordering",
    ]
    if mem > 70 or cpu > 70:
        lines.append("    CTO      wants lighter models / serialization before any expansion")
        lines.append("    CEO      wants the shortest ROI-positive slice shipped now")
    elif roi.get("kill_switch"):
        lines.append("    CTO      wants a smaller local plan and stricter routing")
        lines.append("    CEO      wants low-yield work stopped immediately")
    else:
        lines.append("    CTO      wants stable local execution with tighter local-only routing")
        lines.append("    CEO      wants the next shippable increment, not a big-bang batch")
    return lines


def format_dashboard(progress: dict, runtime: dict, session: dict, resource: dict, lock: dict, roi: dict | None = None, lessons: list[dict] | None = None) -> str:
    lines: list[str] = []
    roi = roi or {}
    lessons = lessons or []

    overall = progress.get("overall", {})
    overall_pct = overall.get("percent", 0.0)
    overall_status = overall.get("status", "idle")
    task = progress.get("task", "no active task")

    lock_pid = int(lock.get("pid", 0) or 0)
    is_running = overall_status == "running" and lock_pid > 0 and is_pid_alive(lock_pid)

    elapsed = elapsed_str(progress.get("started_at"))

    if is_running:
        status_icon = f"{ANSI_GREEN}●{ANSI_RESET}"
        status_text = f"Working ({elapsed} • ctrl-c to interrupt • live)"
    elif overall_status == "completed":
        status_icon = f"{ANSI_GREEN}✓{ANSI_RESET}"
        status_text = f"Completed ({elapsed})"
    elif overall_status == "failed":
        status_icon = f"{ANSI_RED}✗{ANSI_RESET}"
        status_text = f"Failed ({elapsed})"
    else:
        status_icon = f"{ANSI_DIM}○{ANSI_RESET}"
        status_text = f"Idle"

    lines.append(f"{ANSI_BOLD}{status_icon} {status_text}{ANSI_RESET}")
    lines.append(f"  {ANSI_DIM}task={ANSI_RESET}{task}")
    lines.append("")

    lines.append(f"  PROGRESS {render_bar(overall_pct)} {overall_pct:5.1f}%")

    # Execution mix (local vs cloud)
    execution = session.get("execution", {})
    local_pct = float(execution.get("local_models", 100.0 if is_running else 0.0))
    cloud_pct = float(execution.get("cloud_session", 0.0))
    lines.append(f"  LOCAL    {render_bar(local_pct, 30, ANSI_CYAN)} {local_pct:5.1f}%")
    lines.append(f"  CLOUD    {render_bar(cloud_pct, 30, ANSI_YELLOW)} {cloud_pct:5.1f}%")

    # Resource usage
    cpu = float(resource.get("cpu_percent", 0.0))
    mem = float(resource.get("memory_percent", 0.0))
    cpu_color = ANSI_RED if cpu > 70 else ANSI_YELLOW if cpu > 50 else ANSI_GREEN
    mem_color = ANSI_RED if mem > 70 else ANSI_YELLOW if mem > 50 else ANSI_GREEN
    lines.append(f"  CPU      {render_bar(cpu, 30, cpu_color)} {cpu:5.1f}%")
    lines.append(f"  MEMORY   {render_bar(mem, 30, mem_color)} {mem:5.1f}%")
    roi_score = 100
    events = roi.get("events", [])
    if events:
        positive = sum(1 for item in events if item.get("outcome") == "positive")
        negative = sum(1 for item in events if item.get("outcome") == "negative")
        roi_score = round(positive / max(1, positive + negative) * 100)
    roi_color = ANSI_RED if roi.get("kill_switch") else ANSI_GREEN if roi_score >= 70 else ANSI_YELLOW
    lines.append(f"  ROI      {render_bar(roi_score, 30, roi_color)} {roi_score:5.1f}%")
    lines.append("")

    # Model usage breakdown
    providers = model_usage_breakdown(progress, runtime)
    if providers:
        lines.append(f"  {ANSI_BOLD}MODEL USAGE{ANSI_RESET}")
        total_stages = sum(p["total"] for p in providers.values()) or 1
        for name, info in sorted(providers.items()):
            pct = round(info["total"] / total_stages * 100, 1)
            models = ", ".join(sorted(info["models"]))
            status_parts = []
            if info["completed"]:
                status_parts.append(f"{info['completed']} done")
            if info["running"]:
                status_parts.append(f"{info['running']} running")
            pending = info["total"] - info["completed"] - info["running"]
            if pending > 0:
                status_parts.append(f"{pending} pending")
            lines.append(f"    {name:15} {pct:5.1f}% | {' | '.join(status_parts)} | {models}")
        lines.append("")

    # Role breakdown
    stages = progress.get("stages", [])
    if stages:
        lines.append(f"  {ANSI_BOLD}ROLES{ANSI_RESET}")
        for stage in stages:
            sid = stage.get("id", "")
            pct = float(stage.get("percent", 0.0))
            status = stage.get("status", "pending")
            detail = stage.get("detail", "")
            label = stage.get("label", sid)

            if status == "completed":
                icon = f"{ANSI_GREEN}✓{ANSI_RESET}"
            elif status == "running":
                icon = f"{ANSI_YELLOW}▶{ANSI_RESET}"
            elif status == "failed":
                icon = f"{ANSI_RED}✗{ANSI_RESET}"
            else:
                icon = f"{ANSI_DIM}○{ANSI_RESET}"

            detail_str = f" {ANSI_DIM}| {detail}{ANSI_RESET}" if detail else ""
            lines.append(f"    {icon} {label:18} {render_bar(pct, 15)} {pct:5.1f}%{detail_str}")

    decision = next_decision(progress, resource, roi)
    lines.append("")
    lines.append(f"  {ANSI_BOLD}NEXT DECISION{ANSI_RESET}")
    lines.append(f"    {decision}")
    lines.append("")
    lines.append(f"  {ANSI_BOLD}EXECUTIVE NEGOTIATION{ANSI_RESET}")
    lines.extend(executive_tension(progress, resource, roi))

    if lessons:
        lines.append("")
        lines.append(f"  {ANSI_BOLD}TEACHING LOOP{ANSI_RESET}")
        for lesson in lessons[-3:]:
            category = lesson.get("category", "lesson")
            text = lesson.get("lesson", "")[:90]
            fix = lesson.get("fix", "")[:90]
            lines.append(f"    [{category}] {text}")
            if fix:
                lines.append(f"      fix: {fix}")

    return "\n".join(lines)


def clear_screen_lines(count: int) -> None:
    for _ in range(count):
        sys.stdout.write(f"{ANSI_UP}{ANSI_CLEAR_LINE}")
    sys.stdout.flush()


def run_dashboard(poll_interval: float = 1.0) -> None:
    stop = False

    def on_signal(_sig, _frame):
        nonlocal stop
        stop = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    prev_lines = 0
    runtime = load_json(RUNTIME_PATH)

    while not stop:
        progress = load_json(PROGRESS_PATH)
        session = load_json(SESSION_STATE_PATH)
        resource = live_resource_snapshot()
        lock = load_json(RUN_LOCK_PATH)
        roi = load_json(ROI_STATE_PATH)
        lessons = recent_lessons()

        output = format_dashboard(progress, runtime, session, resource, lock, roi, lessons)
        line_count = output.count("\n") + 1

        if prev_lines > 0:
            clear_screen_lines(prev_lines)

        sys.stdout.write(output + "\n")
        sys.stdout.flush()
        prev_lines = line_count

        # Stop polling if completed or failed and not running
        overall_status = progress.get("overall", {}).get("status", "")
        if overall_status in {"completed", "failed"}:
            lock_pid = int(lock.get("pid", 0) or 0)
            if not is_pid_alive(lock_pid):
                break

        time.sleep(poll_interval)

    print(f"\n{ANSI_DIM}Dashboard stopped.{ANSI_RESET}")


def snapshot() -> str:
    """Return a single-frame dashboard string without looping."""
    runtime = load_json(RUNTIME_PATH)
    progress = load_json(PROGRESS_PATH)
    session = load_json(SESSION_STATE_PATH)
    resource = live_resource_snapshot()
    lock = load_json(RUN_LOCK_PATH)
    roi = load_json(ROI_STATE_PATH)
    lessons = recent_lessons()
    return format_dashboard(progress, runtime, session, resource, lock, roi, lessons)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--snapshot":
        print(snapshot())
    else:
        interval = float(sys.argv[1]) if len(sys.argv) > 1 else 1.0
        run_dashboard(interval)
