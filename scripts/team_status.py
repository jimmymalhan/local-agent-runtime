#!/usr/bin/env python3
import json
import os
import pathlib
import sys
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from todo_progress import parse_todo
from runtime_teacher import get_lessons_for_stage, load_lessons
from runtime_env import env_with_runtime, openclaw_status


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
RUNTIME = json.loads((REPO_ROOT / "config" / "runtime.json").read_text())
PROGRESS_PATH = REPO_ROOT / "state" / "progress.json"
SESSION_STATE_PATH = REPO_ROOT / "state" / "session-state.json"
RUN_LOCK_PATH = REPO_ROOT / "state" / "run.lock"
STALE_SECONDS = 15


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


def effective_runtime():
    runtime_env = env_with_runtime()
    runtime = json.loads((REPO_ROOT / "config" / "runtime.json").read_text())
    runtime["provider_preference"] = runtime_env.get("LOCAL_AGENT_PROVIDER_PREFERENCE", runtime.get("provider_preference", "nexus"))
    runtime["remote_fallback_allowed"] = runtime_env.get("LOCAL_AGENT_ALLOW_REMOTE_FALLBACK", "0") in {"1", "true", "yes", "on"}
    return runtime


def load_progress():
    if not PROGRESS_PATH.exists():
        return {}
    try:
        return json.loads(PROGRESS_PATH.read_text())
    except json.JSONDecodeError:
        return {}


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
        "manager": REPO_ROOT / "roles" / "manager-role.md",
        "director": REPO_ROOT / "roles" / "director-role.md",
        "cto": REPO_ROOT / "roles" / "cto-role.md",
        "ceo": REPO_ROOT / "roles" / "ceo-role.md",
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


def is_pid_alive(pid):
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def lock_pid():
    if not RUN_LOCK_PATH.exists():
        return 0
    try:
        body = json.loads(RUN_LOCK_PATH.read_text())
    except json.JSONDecodeError:
        return 0
    return int(body.get("pid", 0) or 0)


def progress_is_stale(progress):
    overall_status = progress.get("overall", {}).get("status", "")
    if overall_status != "running":
        return False
    pid = lock_pid()
    if pid and is_pid_alive(pid):
        return False
    updated_at = parse_iso(progress.get("updated_at", ""))
    if not updated_at:
        return True
    age = (datetime.now() - updated_at).total_seconds()
    return age >= STALE_SECONDS


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
    fallback = None
    stale = progress_is_stale(progress)
    active_stages = {stage.get("id") for stage in progress.get("stages", []) if stage.get("status") in {"running", "completed"}}
    local_roles = sum(1 for role in team_order if role in active_stages)
    overall_status = progress.get("overall", {}).get("status")
    if not stale and (local_roles or overall_status == "running"):
        fallback = {
            "local_models": 100.0,
            "cloud_session": 0.0,
        }
    if SESSION_STATE_PATH.exists():
        try:
            session = json.loads(SESSION_STATE_PATH.read_text())
        except json.JSONDecodeError:
            session = {}
        execution = session.get("execution", {})
        if execution:
            resolved = {
                "local_models": float(execution.get("local_models", 0.0)),
                "cloud_session": float(execution.get("cloud_session", 0.0)),
            }
            if resolved["local_models"] > 0.0 or resolved["cloud_session"] > 0.0:
                return resolved
            if fallback:
                return fallback
            return resolved
    if fallback:
        return fallback
    return {
        "local_models": 0.0,
        "cloud_session": 0.0,
    }


def focus_text(items):
    if not items:
        return "none"
    item = items[0]
    return f"{item['section']}: {item['text']}"


def teaching_snapshot(progress):
    current_stage = progress.get("current_stage", "")
    all_lessons = load_lessons()
    stage_lessons = get_lessons_for_stage(current_stage) if current_stage else []
    applied_total = sum(int(item.get("applied_count", 0) or 0) for item in all_lessons)
    top_fix = stage_lessons[-1].get("fix", "") if stage_lessons else ""
    return {
        "current_stage": current_stage,
        "stage_lessons": stage_lessons,
        "all_lessons": all_lessons,
        "applied_total": applied_total,
        "top_fix": top_fix,
    }


def main():
    runtime = effective_runtime()
    profile_name = active_profile()
    profile = runtime.get("profiles", {}).get(profile_name, {})
    progress = load_progress()
    overall_status = progress.get("overall", {}).get("status", "")
    progress_stage_ids = [stage.get("id") for stage in progress.get("stages", []) if stage.get("id") in runtime.get("team", {})]
    team_order = progress_stage_ids or profile.get("team_order") or runtime.get("team_order") or list(runtime.get("team", {}).keys())
    todo = parse_todo()
    installed = installed_models()

    stale_progress = progress_is_stale(progress) if progress else False

    if progress and overall_status == "running" and not stale_progress:
        overall = progress.get("overall", {})
        print(f"Working ({elapsed_label(progress)} • ctrl-c to interrupt • live)")
        print(
            f"TASK {render_bar(overall.get('percent', 0.0), 24)} "
            f"{overall.get('percent', 0.0):5.1f}% | remaining {overall.get('remaining_percent', 100.0):5.1f}%"
        )
        print(f"task={progress.get('task', '')}")
    elif progress:
        overall = progress.get("overall", {})
        status = "stale" if stale_progress else (overall_status or "idle")
        print(f"TASK {render_bar(overall.get('percent', 0.0), 24)} {overall.get('percent', 0.0):5.1f}% | status {status}")
        print(f"task={progress.get('task', '')}")
    else:
        print("TASK [------------------------]   0.0% | remaining 100.0%")
        print("task=no active progress state")

    print(
        f"PROJECT {render_bar(todo['overall']['percent'], 24)} {todo['overall']['percent']:5.1f}% | "
        f"done {todo['overall']['done']} / total {todo['overall']['total']} | open {todo['overall']['open']}"
    )
    mix = execution_mix(progress, team_order)
    print(
        f"EXECUTION {render_bar(mix['local_models'], 24)} local {mix['local_models']:5.1f}% | "
        f"cloud {mix['cloud_session']:5.1f}%"
    )
    print(f"profile={profile_name}")
    oc = openclaw_status()
    print(
        f"openclaw={'configured' if oc.get('configured') else 'missing'} | "
        f"provider-preference={runtime.get('provider_preference', 'nexus')} | "
        f"remote-fallback={'on' if runtime.get('remote_fallback_allowed') else 'off'}"
    )
    for lane in ("local", "cloud", "shared", "general"):
        lane_data = todo["lanes"][lane]
        if lane_data["total"] == 0:
            continue
        print(
            f"{lane.upper():7} {render_bar(lane_data['percent'], 24)} {lane_data['percent']:5.1f}% | "
            f"done {lane_data['done']} / total {lane_data['total']} | open {lane_data['open']}"
        )
    for use_case in ("product", "business", "technical", "general"):
        bucket = todo["use_cases"][use_case]
        if bucket["total"] == 0:
            continue
        print(
            f"{use_case[:7].upper():7} {render_bar(bucket['percent'], 24)} {bucket['percent']:5.1f}% | "
            f"done {bucket['done']} / total {bucket['total']} | open {bucket['open']}"
        )
    focus = todo.get("focus", {})
    if focus:
        print("")
        print("FOCUS")
        print(f"next={focus_text(focus.get('overall', []))}")
        print(f"local-next={focus_text(focus.get('lanes', {}).get('local', []))}")
        print(f"cloud-next={focus_text(focus.get('lanes', {}).get('cloud', []))}")
        print(f"product-next={focus_text(focus.get('use_cases', {}).get('product', []))}")
        print(f"business-next={focus_text(focus.get('use_cases', {}).get('business', []))}")
    # Model usage breakdown
    from live_dashboard import model_usage_breakdown
    providers = model_usage_breakdown(progress, runtime)
    if providers:
        print("")
        print("MODEL USAGE")
        total_stages = sum(p["total"] for p in providers.values()) or 1
        for name, info in sorted(providers.items()):
            pct = round(info["total"] / total_stages * 100, 1)
            models = ", ".join(sorted(info["models"]))
            parts = []
            if info["completed"]:
                parts.append(f"{info['completed']} done")
            if info["running"]:
                parts.append(f"{info['running']} running")
            pending = info["total"] - info["completed"] - info["running"]
            if pending > 0:
                parts.append(f"{pending} pending")
            print(f"  {name:15} {pct:5.1f}% | {' | '.join(parts)} | {models}")

    teaching = teaching_snapshot(progress)
    print("")
    print("TEACHING LOOP")
    print(
        f"lessons={len(teaching['all_lessons'])} | applied={teaching['applied_total']} | "
        f"current-stage={teaching['current_stage'] or 'none'} | stage-lessons={len(teaching['stage_lessons'])}"
    )
    if teaching["top_fix"]:
        print(f"next-fix={teaching['top_fix']}")
    for lesson in teaching["stage_lessons"][-2:]:
        print(
            f"- [{lesson.get('category', 'unknown')}] {lesson.get('lesson', '')[:120]} "
            f"| fix {lesson.get('fix', '')[:80]} | applied {lesson.get('applied_count', 0)}x"
        )

    print("")
    print("ROLE BREAKDOWN")

    total_weight = sum(float(runtime["team"][role].get("weight", 0.0)) for role in team_order) or 1.0
    for role in team_order:
        cfg = runtime["team"][role]
        weight = float(cfg.get("weight", 0.0))
        weight_percent = round((weight / total_weight) * 100.0, 1)
        stage = stage_state(progress, role)
        done_percent = float(stage.get("percent", 0.0))
        contribution_done = round(weight_percent * done_percent / 100.0, 1)
        contribution_left = round(weight_percent - contribution_done, 1)
        model = cfg.get("model", runtime.get("default_model", "unknown"))
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
