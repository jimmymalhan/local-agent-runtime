#!/usr/bin/env python3
import json
import os
import pathlib
import re
from datetime import datetime


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = json.loads((REPO_ROOT / "config" / "runtime.json").read_text())
PROGRESS_PATH = REPO_ROOT / "state" / "progress.json"
TODO_PATH = REPO_ROOT / "state" / "todo.md"


def render_bar(percent, width=20):
    percent = max(0.0, min(100.0, float(percent)))
    filled = round(width * percent / 100.0)
    return "[" + "#" * filled + "-" * (width - filled) + "]"


def active_profile():
    env_mode = os.environ.get("LOCAL_AGENT_MODE")
    if env_mode:
        return env_mode
    runtime_env = REPO_ROOT / "state" / "runtime.env"
    if runtime_env.exists():
        for line in runtime_env.read_text().splitlines():
            if line.startswith("LOCAL_AGENT_MODE="):
                return line.split("=", 1)[1].strip()
    return RUNTIME.get("default_profile", "balanced")


def load_progress():
    if not PROGRESS_PATH.exists():
        return {}
    try:
        return json.loads(PROGRESS_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def todo_progress():
    if not TODO_PATH.exists():
        return {"total": 0, "done": 0, "open": 0, "percent": 0.0}
    text = TODO_PATH.read_text()
    done = len(re.findall(r"^- \[x\] ", text, flags=re.MULTILINE | re.IGNORECASE))
    open_items = len(re.findall(r"^- \[ \] ", text, flags=re.MULTILINE))
    total = done + open_items
    percent = round((done / total) * 100.0, 1) if total else 0.0
    return {"total": total, "done": done, "open": open_items, "percent": percent}


def installed_models():
    registry_path = REPO_ROOT / "state" / "model-registry.json"
    if not registry_path.exists():
        return set()
    try:
        body = json.loads(registry_path.read_text())
    except json.JSONDecodeError:
        return set()
    return {item.get("name") for item in body.get("installed_models", []) if item.get("name")}


def first_paragraph(path):
    if not path.exists():
        return "No role description."
    lines = [line.strip() for line in path.read_text(errors="ignore").splitlines()]
    chunks = []
    current = []
    for line in lines:
        if not line or line.startswith("#") or line.startswith("**"):
            if current:
                chunks.append(" ".join(current))
                current = []
            continue
        current.append(line)
    if current:
        chunks.append(" ".join(current))
    return (chunks[0] if chunks else "No role description.")[:180]


def role_description(role):
    role_map = {
        "researcher": REPO_ROOT / "roles" / "research-role.md",
        "planner": REPO_ROOT / "roles" / "planner-role.md",
        "architect": REPO_ROOT / "roles" / "architect-role.md",
        "implementer": REPO_ROOT / "roles" / "implementation-role.md",
        "tester": REPO_ROOT / "roles" / "test-role.md",
        "reviewer": REPO_ROOT / "roles" / "review-role.md",
        "debugger": REPO_ROOT / "roles" / "debugger-role.md",
        "optimizer": REPO_ROOT / "roles" / "optimizer-role.md",
        "benchmarker": REPO_ROOT / "roles" / "benchmarker-role.md",
        "qa": REPO_ROOT / "roles" / "qa-role.md",
        "user_acceptance": REPO_ROOT / "roles" / "user-acceptance-role.md",
        "summarizer": REPO_ROOT / "roles" / "summarizer-role.md",
    }
    role_path = role_map.get(role)
    if role_path and role_path.exists():
        return first_paragraph(role_path)
    skill_map = {
        "retriever": REPO_ROOT / "skills" / "understand-project.md",
    }
    return first_paragraph(skill_map.get(role, REPO_ROOT / "README.md"))


def stage_state(progress, stage_id):
    for stage in progress.get("stages", []):
        if stage.get("id") == stage_id:
            return stage
    return {"percent": 0.0, "status": "pending", "detail": ""}


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def elapsed_label(progress):
    started_at = parse_iso(progress.get("started_at", ""))
    if not started_at:
        return "0s"
    delta = datetime.now() - started_at
    total_seconds = max(0, int(delta.total_seconds()))
    minutes, seconds = divmod(total_seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def execution_mix(progress, team_order):
    active_stages = {stage.get("id") for stage in progress.get("stages", []) if stage.get("status") in {"running", "completed"}}
    local_roles = sum(1 for role in team_order if role in active_stages)
    local_percent = 100.0 if local_roles else 0.0
    return {
        "local_models": local_percent,
        "cloud_session": 0.0,
    }


def main():
    profile_name = active_profile()
    profile = RUNTIME.get("profiles", {}).get(profile_name, {})
    progress = load_progress()
    progress_stage_ids = [stage.get("id") for stage in progress.get("stages", []) if stage.get("id") in RUNTIME.get("team", {})]
    team_order = progress_stage_ids or profile.get("team_order") or RUNTIME.get("team_order") or list(RUNTIME.get("team", {}).keys())
    todo = todo_progress()
    installed = installed_models()

    if progress:
        overall = progress.get("overall", {})
        print(f"Working ({elapsed_label(progress)} • ctrl-c to interrupt)")
        print(
            f"TASK {render_bar(overall.get('percent', 0.0), 24)} "
            f"{overall.get('percent', 0.0):5.1f}% | remaining {overall.get('remaining_percent', 100.0):5.1f}%"
        )
        print(f"task={progress.get('task', '')}")
    else:
        print("TASK [------------------------]   0.0% | remaining 100.0%")
        print("task=no active progress state")

    print(
        f"PROJECT {render_bar(todo['percent'], 24)} {todo['percent']:5.1f}% | "
        f"done {todo['done']} / total {todo['total']} | open {todo['open']}"
    )
    mix = execution_mix(progress, team_order)
    print(
        f"EXECUTION {render_bar(mix['local_models'], 24)} local {mix['local_models']:5.1f}% | "
        f"cloud {mix['cloud_session']:5.1f}%"
    )
    print(f"profile={profile_name}")
    print("")
    print("ROLE BREAKDOWN")

    total_weight = sum(float(RUNTIME["team"][role].get("weight", 0.0)) for role in team_order) or 1.0
    for role in team_order:
        cfg = RUNTIME["team"][role]
        weight = float(cfg.get("weight", 0.0))
        weight_percent = round((weight / total_weight) * 100.0, 1)
        stage = stage_state(progress, role)
        done_percent = float(stage.get("percent", 0.0))
        contribution_done = round(weight_percent * done_percent / 100.0, 1)
        contribution_left = round(weight_percent - contribution_done, 1)
        model = cfg.get("model", RUNTIME.get("default_model", "unknown"))
        installed_flag = "installed" if model in installed else "missing"
        label = cfg.get("label", role)
        detail = stage.get("detail", "")
        if detail:
            detail = f" | {detail}"
        print(
            f"- {label}: {render_bar(done_percent)} {done_percent:5.1f}% | "
            f"share {weight_percent:4.1f}% | left {contribution_left:4.1f}% | "
            f"model {model} ({installed_flag}) | status {stage.get('status', 'pending')}{detail}"
        )
        print(f"  does: {role_description(role)}")


if __name__ == "__main__":
    main()
