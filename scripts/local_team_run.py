#!/usr/bin/env python3
import concurrent.futures
import json
import os
import pathlib
import re
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from runtime_teacher import (
    get_lessons_for_stage,
    format_lessons_for_prompt,
    mark_applied as mark_lesson_applied,
    record_lesson as teach_lesson,
)
from agent_coordinator import claim_files, release_files
from runtime_env import load_runtime_env


REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
PROGRESS = REPO_ROOT / "scripts" / "progress_tracker.py"
BOOTSTRAP = REPO_ROOT / "scripts" / "bootstrap_local_runtime.sh"
MODEL_REGISTRY = REPO_ROOT / "scripts" / "model_registry.py"
SUMMARY_SCRIPT = REPO_ROOT / "scripts" / "summarize_project.py"
RAG_SCALE_SCRIPT = REPO_ROOT / "scripts" / "scale_rag_ranking.sh"
SUMMARY_PATH = REPO_ROOT / "context" / "project-summary.md"
HOOKS_DIR = REPO_ROOT / "scripts" / "hooks"
MEMORY_DIR = REPO_ROOT / "memory"
LOG_DIR = REPO_ROOT / "logs"
SESSION_STATE = REPO_ROOT / "scripts" / "session_state.py"
RUN_LOCK = REPO_ROOT / "state" / "run.lock"
HISTORY_PATH = REPO_ROOT / "state" / "session-history.jsonl"
MENTIONED_FILES_PATH = REPO_ROOT / "state" / "mentioned-files.txt"
COMMON_PLAN_PATH = REPO_ROOT / "state" / "common-plan.md"
PROMPT_LOG_PATH = REPO_ROOT / "feedback" / "prompt-log.md"
WORKFLOW_EVOLUTION_PATH = REPO_ROOT / "feedback" / "workflow-evolution.md"
ROI_STATE_PATH = REPO_ROOT / "state" / "roi-metrics.json"


ROLE_FILES = {
    "manager": REPO_ROOT / "roles" / "manager-role.md",
    "director": REPO_ROOT / "roles" / "director-role.md",
    "cto": REPO_ROOT / "roles" / "cto-role.md",
    "ceo": REPO_ROOT / "roles" / "ceo-role.md",
    "researcher": REPO_ROOT / "roles" / "research-role.md",
    "retriever": REPO_ROOT / "skills" / "understand-project.md",
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

STAGE_FOCUS = {
    "manager": "Make immediate execution decisions. Poll blockers, assign one owner, choose the fastest viable fallback, and do not let the run sit idle.",
    "director": "Prioritize across streams. Cut low-ROI work, rebalance ownership across local, Claude, Codex, and Cursor, and shrink scope when needed.",
    "cto": "Make technical executive calls. Decide architecture cuts, model/provider routing, and what technical debt to ignore so the feature ships fast.",
    "ceo": "Make final ROI and release decisions. Approve the fastest path to user value, reject weak work, and force shipment-focused tradeoffs.",
    "researcher": "Map the repo quickly. State what the project does, actual entrypoints, important folders, exact local commands, and notable risks.",
    "retriever": "Pull supporting repo context, tools, workflows, and prior session facts that will help the rest of the team answer well.",
    "planner": "Produce the common plan first. Split work into the smallest useful parallel workstreams, note what already exists, what can be reused, and what later roles must validate.",
    "architect": "Describe system structure, dependencies, tradeoffs, and how multiple local agents should cooperate against the common plan without duplicating effort.",
    "implementer": "Turn the common plan into precise changes, commands, file paths, and implementation details. Avoid vagueness and explicitly call out what can run in parallel.",
    "tester": "Identify targeted validation, failure modes, and exact test commands or manual checks that line up with the common plan.",
    "reviewer": "Perform code-review style scrutiny. Prioritize bugs, regressions, and missing validation over compliments, and judge whether execution still matches the common plan.",
    "debugger": "Find root causes for weak outputs, flaky behavior, race conditions, and orchestration failures.",
    "optimizer": "Tighten speed, concurrency, memory use, and ROI while keeping the workflow local-only.",
    "benchmarker": "Compare the current answer quality to a top-tier coding assistant bar using the local rubric and identify specific gaps.",
    "qa": "Judge whether the workflow meets the explicit user request and list remaining gaps in plain language.",
    "user_acceptance": "Evaluate the output as a non-technical but demanding user. Call out anything confusing or missing.",
    "summarizer": "Deliver the final answer for the user. It must be direct, concrete, repo-aware, and action-oriented. Never invent setup steps that are not explicitly present.",
}


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True, check=False)


def read_text(path):
    return path.read_text(errors="ignore") if path.exists() else ""


def run_hook(hook_name, stage_id, target_repo, stamp, artifact_path=""):
    """Run a stage hook script if it exists in the hooks directory."""
    hook_path = HOOKS_DIR / hook_name
    if not hook_path.exists() or not hook_path.is_file():
        return True
    try:
        args = ["bash", str(hook_path), stage_id, str(target_repo), stamp]
        if artifact_path:
            args.append(str(artifact_path))
        result = subprocess.run(args, capture_output=True, text=True, check=False, timeout=30)
        if result.stdout.strip():
            for line in result.stdout.strip().split("\n")[-3:]:
                progress(["tick", "--stage", stage_id, "--percent", "1", "--detail", line.strip()[:120]])
        return result.returncode == 0
    except (subprocess.TimeoutExpired, OSError):
        return True  # Hook timeout is non-fatal


def load_runtime():
    runtime = json.loads((REPO_ROOT / "config" / "runtime.json").read_text())
    profile_name = os.environ.get("LOCAL_AGENT_MODE", runtime.get("default_profile", "balanced"))
    profiles = runtime.get("profiles", {})
    profile = profiles.get(profile_name) or profiles.get(runtime.get("default_profile", "balanced"), {})
    limits = dict(runtime.get("resource_limits", {}))
    limits.update(profile.get("resource_limits", {}))
    runtime["resource_limits"] = limits
    selected_roles = parse_selected_roles(profile, runtime)
    runtime["active_profile"] = profile_name
    runtime["active_profile_config"] = profile
    runtime["active_team_order"] = selected_roles
    runtime["active_group_order"] = group_order_for(selected_roles, profile)
    runtime["active_max_parallel_roles"] = int(
        os.environ.get("LOCAL_AGENT_MAX_PARALLEL", profile.get("max_parallel_roles", 1))
    )
    runtime["active_temperature"] = float(profile.get("temperature", 0.15))
    runtime["active_retry_generic_output"] = int(profile.get("retry_generic_output", 1))
    return runtime


def provider_config(runtime, provider_name):
    return runtime.get("providers", {}).get(provider_name, {})


def parse_selected_roles(profile, runtime):
    default_roles = profile.get("team_order") or runtime.get("team_order") or list(runtime.get("team", {}).keys())
    override = os.environ.get("LOCAL_AGENT_ONLY_ROLES", "").strip()
    if not override:
        return default_roles
    selected = []
    for name in [part.strip() for part in override.split(",") if part.strip()]:
        if name in runtime.get("team", {}) and name not in selected:
            selected.append(name)
    return selected or default_roles


def group_order_for(selected_roles, profile):
    groups = []
    for group in profile.get("group_order", []):
        kept = [stage_id for stage_id in group if stage_id in selected_roles]
        if kept:
            groups.append(kept)
    missing = [stage_id for stage_id in selected_roles if not any(stage_id in group for group in groups)]
    groups.extend([[stage_id] for stage_id in missing])
    return groups


def progress(cmd):
    run(["python3", str(PROGRESS), *cmd])


def takeover_wait_seconds(runtime=None):
    default = "45"
    if runtime is not None:
        default = str(runtime.get("resource_limits", {}).get("takeover_wait_seconds", default))
    return int(os.environ.get("LOCAL_AGENT_TAKEOVER_WAIT_SECONDS", default))


def resource_wait_event_limit(runtime=None):
    default = "6"
    if runtime is not None:
        default = str(runtime.get("resource_limits", {}).get("max_resource_wait_events", default))
    return int(os.environ.get("LOCAL_AGENT_MAX_RESOURCE_WAIT_EVENTS", default))


def parse_iso(value):
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def active_target_repo():
    return pathlib.Path(os.environ.get("LOCAL_AGENT_TARGET_REPO", REPO_ROOT)).resolve()


def takeover_command(target_repo, task):
    escaped_task = task.replace('"', '\\"')
    return f'Local "/{pathlib.Path(target_repo).name}" "{escaped_task}"'


def record_runtime_lesson(kind, task, target_repo, reason, detail=""):
    stamp = datetime.now().isoformat(timespec="seconds")
    target_repo = str(target_repo)
    lines = [
        f"- {stamp} [{kind}] target={target_repo}",
        f"  reason: {reason}",
    ]
    if detail:
        lines.append(f"  detail: {detail}")
    lines.append(
        "  next-time: detect this earlier, keep execution local, and shrink scope or model size before the run stalls."
    )
    entry = "\n".join(lines) + "\n"
    for path in (PROMPT_LOG_PATH, WORKFLOW_EVOLUTION_PATH):
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a") as handle:
            handle.write(entry)


def load_roi_metrics():
    if not ROI_STATE_PATH.exists():
        return {"events": []}
    try:
        data = json.loads(ROI_STATE_PATH.read_text())
    except json.JSONDecodeError:
        return {"events": []}
    if "events" not in data or not isinstance(data["events"], list):
        data["events"] = []
    return data


def save_roi_metrics(data):
    ROI_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
    ROI_STATE_PATH.write_text(json.dumps(data, indent=2) + "\n")


def roi_event_window(runtime):
    return int(runtime.get("roi", {}).get("negative_trend_window", 6))


def roi_negative_threshold(runtime):
    return int(runtime.get("roi", {}).get("negative_trend_threshold", 3))


def roi_event_max_age_minutes(runtime):
    return int(runtime.get("roi", {}).get("max_event_age_minutes", 15))


def prune_roi_events(runtime, events):
    cutoff_seconds = roi_event_max_age_minutes(runtime) * 60
    now = datetime.now()
    kept = []
    for item in events:
        stamp = parse_iso(item.get("timestamp", ""))
        if not stamp:
            kept.append(item)
            continue
        if (now - stamp).total_seconds() <= cutoff_seconds:
            kept.append(item)
    return kept


def record_roi_event(runtime, stage_id, outcome, detail=""):
    if not runtime.get("roi", {}).get("kill_switch_enabled", True):
        return
    data = load_roi_metrics()
    events = prune_roi_events(runtime, data.get("events", []))
    events.append(
        {
            "timestamp": datetime.now().isoformat(timespec="seconds"),
            "stage": stage_id,
            "outcome": outcome,
            "detail": detail,
        }
    )
    data["events"] = events[-roi_event_window(runtime):]
    negatives = sum(1 for item in data["events"] if item.get("outcome") == "negative")
    positives = sum(1 for item in data["events"] if item.get("outcome") == "positive")
    data["trend"] = "negative" if negatives >= roi_negative_threshold(runtime) and negatives > positives else "healthy"
    data["kill_switch"] = data["trend"] == "negative"
    save_roi_metrics(data)


def enforce_roi_kill_switch(runtime, stage_id, target_repo):
    if not runtime.get("roi", {}).get("kill_switch_enabled", True):
        return
    data = load_roi_metrics()
    data["events"] = prune_roi_events(runtime, data.get("events", []))
    negatives = sum(1 for item in data["events"] if item.get("outcome") == "negative")
    positives = sum(1 for item in data["events"] if item.get("outcome") == "positive")
    data["trend"] = "negative" if negatives >= roi_negative_threshold(runtime) and negatives > positives else "healthy"
    data["kill_switch"] = data["trend"] == "negative"
    save_roi_metrics(data)
    if not data.get("kill_switch"):
        return
    reason = "roi kill switch triggered after repeated low-yield runtime events"
    detail = (
        f"recent trend={data.get('trend', 'unknown')}; "
        f"window={roi_event_window(runtime)} threshold={roi_negative_threshold(runtime)}. "
        "Pause local iteration, re-plan the smallest useful local slice, and teach the runtime from the failure before retrying."
    )
    task = os.environ.get("LOCAL_AGENT_ACTIVE_TASK", stage_id)
    set_takeover_state(task, target_repo, reason, local_percent=100.0, cloud_percent=0.0)
    record_runtime_lesson("takeover", stage_id, target_repo, reason, detail)
    raise SystemExit(takeover_message(target_repo, task, reason, detail))


def set_takeover_state(task, target_repo, reason, local_percent=15.0, cloud_percent=85.0):
    env = os.environ.copy()
    env["LOCAL_AGENT_LOCAL_PERCENT"] = str(local_percent)
    env["LOCAL_AGENT_CLOUD_PERCENT"] = str(cloud_percent)
    env["LOCAL_AGENT_TAKEOVER_REASON"] = reason
    subprocess.run(
        ["python3", str(SESSION_STATE), "running", task, str(target_repo)],
        check=False,
        stdout=subprocess.DEVNULL,
        env=env,
    )


def takeover_message(target_repo, task, reason, detail=""):
    command = takeover_command(target_repo, task)
    suffix = f" Detail: {detail}" if detail else ""
    return (
        f"Local runtime stalled: {reason}.{suffix} "
        f"Recommended next local run: {command}"
    )


def prompt_budget(runtime, key, default):
    profile = runtime.get("active_profile_config", {})
    profile_budget = profile.get("prompt_budget", {})
    if key in profile_budget:
        return int(profile_budget[key])
    if profile.get("use_exhaustive_budget"):
        budget = runtime.get("prompt_budget_exhaustive", {})
        if key in budget:
            return int(budget[key])
    return int(runtime.get("prompt_budget", {}).get(key, default))


def installed_models():
    registry_path = REPO_ROOT / "state" / "model-registry.json"
    if registry_path.exists():
        try:
            data = json.loads(registry_path.read_text())
        except json.JSONDecodeError:
            data = {}
        names = [item["name"] for item in data.get("installed_models", []) if item.get("name")]
        if names:
            return names
    output = run(["ollama", "list"]).stdout.splitlines()
    names = []
    for line in output[1:]:
        parts = line.split()
        if parts:
            names.append(parts[0])
    return names


def env_truthy(name):
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def remote_fallback_allowed(runtime):
    if env_truthy("LOCAL_AGENT_ALLOW_REMOTE_FALLBACK"):
        return True
    return not runtime.get("local_only_default", True)


def provider_preference(runtime):
    preferred = os.environ.get("LOCAL_AGENT_PROVIDER_PREFERENCE", "").strip().lower()
    if preferred:
        return preferred
    return str(runtime.get("provider_preference", "ollama")).strip().lower() or "ollama"


def provider_enabled(runtime, provider_name):
    cfg = provider_config(runtime, provider_name)
    if not cfg:
        return False
    if provider_name == "ollama":
        return True
    if not remote_fallback_allowed(runtime):
        return False
    enabled_env = cfg.get("enabled_env")
    if enabled_env and not env_truthy(enabled_env):
        return False
    token_env = cfg.get("token_env")
    fallback_token_env = cfg.get("fallback_token_env")
    if token_env and not (os.environ.get(token_env) or (fallback_token_env and os.environ.get(fallback_token_env))):
        return False
    if cfg.get("base_url_env") and not os.environ.get(cfg["base_url_env"]) and not cfg.get("base_url"):
        return False
    return True


def role_category(stage_id):
    cheap_roles = {"researcher", "retriever", "optimizer", "user_acceptance"}
    code_roles = {"architect", "implementer", "tester", "debugger"}
    reasoning_roles = {"manager", "director", "cto", "ceo", "planner", "reviewer", "benchmarker", "qa", "summarizer"}
    if stage_id in cheap_roles:
        return "cheap"
    if stage_id in code_roles:
        return "code"
    if stage_id in reasoning_roles:
        return "reasoning"
    return "general"


def provider_order_for_stage(runtime, stage_id, resource_state=None):
    pressure = pressure_level(runtime, resource_state)
    fast_remote = "clawbot" if provider_enabled(runtime, "clawbot") else "openclaw"
    preferred = provider_preference(runtime)
    base_order = ["ollama", fast_remote, "github_models", "openclaw", "clawbot"]
    order = []
    if preferred in base_order:
        order.append(preferred)
    if pressure in {"high", "elevated"} and preferred != "ollama":
        order.append("ollama")
    for name in base_order:
        if name not in order:
            order.append(name)
    return [name for name in order if provider_enabled(runtime, name)]


def provider_model_for_stage(runtime, provider_name, stage_id):
    cfg = provider_config(runtime, provider_name)
    role_models = cfg.get("role_models", {})
    if stage_id in role_models:
        return role_models[stage_id]
    env_models = cfg.get("models", {})
    if role_category(stage_id) == "reasoning" and env_models.get("reasoning_env") and os.environ.get(env_models["reasoning_env"]):
        return os.environ[env_models["reasoning_env"]]
    if role_category(stage_id) == "code" and env_models.get("coding_env") and os.environ.get(env_models["coding_env"]):
        return os.environ[env_models["coding_env"]]
    if role_category(stage_id) == "cheap" and env_models.get("fast_env") and os.environ.get(env_models["fast_env"]):
        return os.environ[env_models["fast_env"]]
    default_env = cfg.get("default_model_env")
    if default_env and os.environ.get(default_env):
        return os.environ[default_env]
    return cfg.get("default_model", runtime.get("default_model"))


def load_resource_state():
    path = REPO_ROOT / "state" / "resource-status.json"
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}


def pressure_level(runtime, resource_state=None):
    data = resource_state or load_resource_state()
    if not data:
        return "normal"
    limits = runtime.get("resource_limits", {})
    cpu = float(data.get("cpu_percent", 0.0))
    memory = float(data.get("memory_percent", 0.0))
    cpu_limit = float(limits.get("cpu_percent", 70))
    memory_limit = float(limits.get("memory_percent", 70))
    headroom_cpu = float(limits.get("parallel_headroom_cpu_percent", 55))
    headroom_memory = float(limits.get("parallel_headroom_memory_percent", 55))
    if cpu >= cpu_limit or memory >= memory_limit:
        return "high"
    if cpu >= headroom_cpu or memory >= headroom_memory:
        return "elevated"
    return "normal"


def downgrade_order_for(stage_id):
    mapping = {
        "manager": ["qwen2.5-coder:7b", "qwen2.5:3b"],
        "director": ["qwen2.5-coder:7b", "qwen2.5:3b"],
        "cto": ["qwen2.5-coder:7b", "qwen2.5:3b"],
        "ceo": ["qwen2.5-coder:7b", "qwen2.5:3b"],
        "researcher": ["qwen2.5:3b", "llama3.2:3b"],
        "retriever": ["qwen2.5:3b", "llama3.2:3b"],
        "planner": ["qwen2.5-coder:7b", "qwen2.5:3b"],
        "architect": ["qwen2.5:3b"],
        "implementer": ["qwen2.5-coder:7b", "qwen2.5:3b"],
        "tester": ["qwen2.5:3b"],
        "reviewer": ["qwen2.5-coder:7b", "qwen2.5:3b"],
        "debugger": ["qwen2.5:3b"],
        "optimizer": ["qwen2.5:3b"],
        "benchmarker": ["qwen2.5:3b"],
        "qa": ["qwen2.5-coder:7b", "qwen2.5:3b"],
        "user_acceptance": ["qwen2.5:3b", "gemma3:4b"],
        "summarizer": ["qwen2.5-coder:7b", "qwen2.5:3b"],
    }
    return mapping.get(stage_id, [])


def choose_model_for_stage(runtime, stage_id, available_models, resource_state=None):
    config = dict(runtime["team"][stage_id])
    profile_overrides = runtime.get("active_profile_config", {}).get("model_overrides", {})
    if stage_id in profile_overrides:
        config["model"] = profile_overrides[stage_id]
    preferred = [config.get("model")] + list(config.get("fallback_models", []))
    if pressure_level(runtime, resource_state) in {"elevated", "high"}:
        preferred = downgrade_order_for(stage_id) + preferred
    seen = []
    for name in preferred:
        if name and name not in seen:
            seen.append(name)
    for name in seen:
        if name in available_models:
            return name
    for name in seen:
        if name:
            return name
    return runtime["default_model"]


def resolve_model(runtime, stage_id, available_models):
    return choose_model_for_stage(runtime, stage_id, available_models)


def model_size_score(name):
    match = re.search(r":(\d+(?:\.\d+)?)b", name or "", re.IGNORECASE)
    return float(match.group(1)) if match else 999.0


def under_resource_pressure(runtime):
    limits = runtime.get("resource_limits", {})
    snapshot, data = resource_status_snapshot()
    if not data:
        return False, snapshot, data
    memory_limit = float(limits.get("model_downgrade_memory_percent", limits.get("parallel_headroom_memory_percent", limits.get("memory_percent", 70))))
    cpu_limit = float(limits.get("model_downgrade_cpu_percent", limits.get("parallel_headroom_cpu_percent", limits.get("cpu_percent", 70))))
    pressured = float(data.get("cpu_percent", 0.0)) > cpu_limit or float(data.get("memory_percent", 0.0)) > memory_limit
    return pressured, snapshot, data


def effective_model_for_stage(runtime, stage_id, available_models):
    config = dict(runtime["team"][stage_id])
    profile_overrides = runtime.get("active_profile_config", {}).get("model_overrides", {})
    if stage_id in profile_overrides:
        config["model"] = profile_overrides[stage_id]
    preferred = [name for name in [config.get("model"), *config.get("fallback_models", [])] if name]
    installed = [name for name in preferred if name in available_models]
    candidates = installed or preferred
    if not candidates:
        return runtime["default_model"]

    chosen = candidates[0]
    pressured, snapshot, _data = under_resource_pressure(runtime)
    if not pressured or len(candidates) == 1:
        return chosen

    smaller = sorted(candidates, key=model_size_score)[0]
    if model_size_score(smaller) >= model_size_score(chosen):
        return chosen

    task = os.environ.get("LOCAL_AGENT_ACTIVE_TASK", "")
    target_repo = active_target_repo()
    detail = (
        f"{snapshot}; downgrade {stage_id} from {chosen} to {smaller} to keep the run moving. "
        "next-time: prefer the lighter fallback earlier for this profile when the machine is already constrained."
    )
    record_runtime_lesson("optimize", task or stage_id, target_repo, "lighter model selected under pressure", detail)
    return smaller


def execution_mix_for_provider(provider_name):
    if provider_name == "ollama":
        return 100.0, 0.0
    return 20.0, 80.0


def provider_uses_local_resources(provider_name):
    return provider_name == "ollama"


def update_execution_state(task, target_repo, provider_name):
    local_percent, cloud_percent = execution_mix_for_provider(provider_name)
    env = os.environ.copy()
    env["LOCAL_AGENT_LOCAL_PERCENT"] = str(local_percent)
    env["LOCAL_AGENT_CLOUD_PERCENT"] = str(cloud_percent)
    env["LOCAL_AGENT_TAKEOVER_REASON"] = ""
    subprocess.run(
        ["python3", str(SESSION_STATE), "running", task, str(target_repo)],
        check=False,
        stdout=subprocess.DEVNULL,
        env=env,
    )


def resolve_execution_target(runtime, stage_id, available_models, resource_state=None):
    provider_order = provider_order_for_stage(runtime, stage_id, resource_state)
    for provider_name in provider_order:
        if provider_name == "ollama":
            return provider_name, effective_model_for_stage(runtime, stage_id, available_models)
        return provider_name, provider_model_for_stage(runtime, provider_name, stage_id)
    return "ollama", effective_model_for_stage(runtime, stage_id, available_models)


def write_history(role, content, target_repo):
    HISTORY_PATH.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "role": role,
        "target_repo": str(target_repo),
        "content": content,
    }
    with HISTORY_PATH.open("a") as handle:
        handle.write(json.dumps(entry) + "\n")


def recent_history(target_repo, limit=6):
    if not HISTORY_PATH.exists():
        return []
    items = []
    for line in HISTORY_PATH.read_text().splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if item.get("target_repo") == str(target_repo):
            items.append(item)
    return items[-limit:]


def current_stage_label():
    state_path = REPO_ROOT / "state" / "progress.json"
    if not state_path.exists():
        return ""
    try:
        state = json.loads(state_path.read_text())
    except json.JSONDecodeError:
        return ""
    current = state.get("current_stage")
    if not current:
        return ""
    for stage in state.get("stages", []):
        if stage.get("id") == current:
            return stage.get("label", current)
    return current


def resource_status_snapshot():
    snapshot = run(["python3", str(REPO_ROOT / "scripts" / "resource_status.py")]).stdout.strip()
    try:
        data = json.loads((REPO_ROOT / "state" / "resource-status.json").read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        data = {}
    return snapshot, data


def ensure_resource_capacity(runtime):
    limits = runtime["resource_limits"]
    started = time.time()
    wait_events = 0
    task = os.environ.get("LOCAL_AGENT_ACTIVE_TASK", "")
    target_repo = active_target_repo()
    while True:
        snapshot, data = resource_status_snapshot()
        if not data:
            return
        if data.get("cpu_percent", 0.0) <= limits["cpu_percent"] and data.get("memory_percent", 0.0) <= limits["memory_percent"]:
            return
        wait_events += 1

        # Aggressive blocker resolution: auto-resolve on first wait event
        try:
            from blocker_resolver import auto_resolve, execute_resolution
            context = {
                "resource": data,
                "memory_limit": limits.get("memory_percent", 85),
                "cpu_limit": limits.get("cpu_percent", 85),
                "roi": load_roi_metrics(),
            }
            resolution = auto_resolve(context)
            action = resolution["chosen"]["action"]
            msg = execute_resolution(action, {"task": task, "target_repo": str(target_repo)})
            stage_label = current_stage_label() or "retriever"
            progress(
                [
                    "tick", "--stage", stage_label, "--percent", "1",
                    "--detail", f"Auto-resolved {resolution['blocker_type']}: {msg}",
                ]
            )
            teach_lesson(
                category="resource",
                trigger=f"auto_resolve_{resolution['blocker_type']}",
                lesson=f"Auto-resolved {resolution['blocker_type']} with {action}: {msg}",
                fix=resolution["chosen"]["detail"],
                context=f"wait_event={wait_events} snapshot={snapshot}",
            )
            # If action was model_downgrade or serialize, resource pressure may resolve quickly
            if action in ("model_downgrade", "serialize", "reset_roi", "kill_stale", "reduce_parallel", "fast_profile"):
                time.sleep(1)
                continue  # Re-check resources immediately
        except Exception:
            pass  # Fall back to original wait behavior

        progress(
            [
                "tick",
                "--stage",
                current_stage_label() or "retriever",
                "--percent",
                "1",
                "--detail",
                f"Waiting for resources ({wait_events}/{resource_wait_event_limit(runtime)}): {snapshot}",
            ]
        )
        if time.time() - started >= takeover_wait_seconds(runtime) or wait_events >= resource_wait_event_limit(runtime):
            reason = "resource ceiling wait budget exceeded"
            detail = (
                f"{snapshot}; waited {wait_events} times before progress. "
                "Teach local agents to reduce parallelism earlier, shrink prompt budgets, and select lighter models sooner before stalling."
            )
            record_roi_event(runtime, current_stage_label() or "resource-wait", "negative", detail)
            set_takeover_state(task, target_repo, reason, local_percent=100.0, cloud_percent=0.0)
            record_runtime_lesson("takeover", current_stage_label() or "resource-wait", target_repo, reason, detail)
            raise SystemExit(takeover_message(target_repo, task, reason, detail))
        time.sleep(int(limits.get("poll_seconds", 5)))


def effective_max_parallel_roles(runtime, group, available_models):
    configured = max(1, min(int(runtime["active_max_parallel_roles"]), len(group)))
    if configured <= 1 or len(group) <= 1:
        return 1

    limits = runtime.get("resource_limits", {})
    snapshot, data = resource_status_snapshot()
    if not data:
        return configured

    memory_limit = float(limits.get("parallel_headroom_memory_percent", limits.get("memory_percent", 70)))
    cpu_limit = float(limits.get("parallel_headroom_cpu_percent", limits.get("cpu_percent", 70)))
    cpu_now = float(data.get("cpu_percent", 0.0))
    memory_now = float(data.get("memory_percent", 0.0))
    if cpu_now <= cpu_limit and memory_now <= memory_limit:
        return configured

    task = os.environ.get("LOCAL_AGENT_ACTIVE_TASK", "")
    target_repo = active_target_repo()
    roles = ", ".join(group)
    detail = (
        f"{snapshot}; serialize {roles} until headroom recovers. "
        "next-time: lower max_parallel_roles for this profile and trim prompt budgets earlier."
    )
    progress(
        [
            "tick",
            "--stage",
            group[0],
            "--percent",
            "1",
            "--detail",
            f"Serializing for headroom: {snapshot}",
        ]
    )
    record_runtime_lesson("optimize", task or roles, target_repo, "parallel work reduced for headroom", detail)
    return 1


def lock_wait_seconds(runtime):
    configured = int(
        os.environ.get(
            "LOCAL_AGENT_WAIT_FOR_IDLE_SECONDS",
            runtime.get("active_profile_config", {}).get("lock_wait_seconds")
            or runtime.get("lock_wait_seconds", 180),
        )
    )
    return min(configured, takeover_wait_seconds(runtime))


def acquire_lock(runtime, task, target_repo):
    RUN_LOCK.parent.mkdir(parents=True, exist_ok=True)
    timeout = lock_wait_seconds(runtime)
    started = time.time()
    while RUN_LOCK.exists():
        try:
            body = json.loads(RUN_LOCK.read_text())
        except json.JSONDecodeError:
            body = {}
        pid = int(body.get("pid", 0) or 0)
        if pid > 0:
            try:
                os.kill(pid, 0)
            except OSError:
                RUN_LOCK.unlink(missing_ok=True)
            else:
                if time.time() - started >= timeout:
                    reason = f"run lock held too long by pid {pid}"
                    detail = body.get("task", "")
                    record_roi_event(runtime, "run-lock", "negative", detail or reason)
                    set_takeover_state(task, target_repo, reason)
                    record_runtime_lesson("takeover", task, target_repo, reason, detail)
                    raise SystemExit(takeover_message(target_repo, task, reason, detail))
                progress(
                    [
                        "tick",
                        "--stage",
                        "preflight",
                        "--percent",
                        "1",
                        "--detail",
                        f"Lock busy: pid {pid} running {body.get('task', '')}",
                    ]
                )
                print(
                    f"Waiting for active local run (pid {pid}) to finish: {body.get('task', '')}",
                    file=sys.stderr,
                    flush=True,
                )
                time.sleep(1)
                continue
        else:
            RUN_LOCK.unlink(missing_ok=True)
        break
    payload = {
        "pid": os.getpid(),
        "task": task,
        "target_repo": str(target_repo),
        "started_at": datetime.now().isoformat(timespec="seconds"),
    }
    RUN_LOCK.write_text(json.dumps(payload, indent=2) + "\n")


def release_lock():
    RUN_LOCK.unlink(missing_ok=True)


def call_model(runtime, provider_name, model, system_prompt, user_prompt):
    provider = provider_config(runtime, provider_name)
    if provider_name == "ollama":
        return call_ollama_model(runtime, model, system_prompt, user_prompt)
    return call_openai_compatible_model(runtime, provider_name, provider, model, system_prompt, user_prompt)


def call_ollama_model(runtime, model, system_prompt, user_prompt):
    opts = {"temperature": runtime["active_temperature"]}
    num_ctx = int(
        runtime.get("active_profile_config", {}).get("num_ctx")
        or runtime.get("num_ctx")
        or os.environ.get("OLLAMA_NUM_CTX")
        or 4096
    )
    opts["num_ctx"] = num_ctx
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "stream": False,
            "options": opts,
        }
    ).encode()
    req = urllib.request.Request(
        f"{runtime['base_url']}/api/chat",
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    timeout = 3600 if runtime.get("active_profile_config", {}).get("use_exhaustive_budget") else 900
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = json.loads(response.read().decode())
    return data["message"]["content"].strip()


def call_openai_compatible_model(runtime, provider_name, provider, model, system_prompt, user_prompt):
    payload = json.dumps(
        {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": runtime["active_temperature"],
        }
    ).encode()
    base_url = provider.get("base_url") or os.environ.get(provider.get("base_url_env", ""), "")
    chat_path = provider.get("chat_path", "")
    if chat_path and not base_url.rstrip("/").endswith(chat_path):
        base_url = urllib.parse.urljoin(base_url.rstrip("/") + "/", chat_path.lstrip("/"))
    headers = {"Content-Type": "application/json"}
    token_env = provider.get("token_env")
    fallback_token_env = provider.get("fallback_token_env")
    token = ""
    if token_env and os.environ.get(token_env):
        token = os.environ[token_env]
    elif fallback_token_env and os.environ.get(fallback_token_env):
        token = os.environ[fallback_token_env]
    if token:
        headers["Authorization"] = f"Bearer {token}"
    if provider_name == "github_models":
        headers["X-GitHub-Api-Version"] = str(provider.get("api_version", "2022-11-28"))
    req = urllib.request.Request(
        base_url,
        data=payload,
        headers=headers,
        method="POST",
    )
    timeout = 900
    with urllib.request.urlopen(req, timeout=timeout) as response:
        data = json.loads(response.read().decode())
    content = data["choices"][0]["message"]["content"]
    if isinstance(content, list):
        content = "".join(
            item.get("text", "") if isinstance(item, dict) else str(item)
            for item in content
        )
    return str(content).strip()


def pulse(stage_id, detail, stop_event):
    percent = 5
    while not stop_event.wait(3):
        progress(["tick", "--stage", stage_id, "--percent", str(percent), "--detail", detail])
        percent = min(90, percent + 5)


def load_private_tools():
    path = REPO_ROOT / "state" / "private-tool-registry.json"
    if not path.exists():
        return "No private tool registry available."
    data = json.loads(path.read_text())
    lines = [f"{item['id']} -> {item['path']}" for item in data.get("tools", [])]
    return "\n".join(lines[:80])


def mentioned_file_context(runtime):
    if not MENTIONED_FILES_PATH.exists():
        return ""
    budget = prompt_budget(runtime, "mentioned_files_chars", 6000)
    paths = [line.strip() for line in MENTIONED_FILES_PATH.read_text().splitlines() if line.strip()]
    if not paths:
        return ""
    chunks = []
    per_file = max(800, budget // max(1, len(paths)))
    for item in paths[:8]:
        path = pathlib.Path(item)
        if not path.exists() or not path.is_file():
            continue
        chunks.append(f"## {path}\n{read_text(path)[:per_file]}")
    return "\n\n".join(chunks)[:budget]


def should_include_validation_context(task):
    task_l = task.lower()
    markers = [
        "quality",
        "compare",
        "qa",
        "acceptance",
        "review",
        "repair",
        "debug",
        "verify",
        "release",
        "improve",
        "benchmark",
    ]
    return any(marker in task_l for marker in markers)


def validation_artifact_context(runtime, task):
    if not should_include_validation_context(task):
        return ""
    files = [
        ("Latest response", REPO_ROOT / "logs" / "latest-response.md", prompt_budget(runtime, "latest_response_chars", 3000)),
        ("Current change review", REPO_ROOT / "logs" / "review-current-changes.md", prompt_budget(runtime, "review_report_chars", 2500)),
        ("QA suite report", REPO_ROOT / "logs" / "qa-suite-report.md", prompt_budget(runtime, "qa_report_chars", 3500)),
        ("Session summary", REPO_ROOT / "state" / "session-summary.md", prompt_budget(runtime, "session_summary_chars", 2000)),
    ]
    chunks = []
    for label, path, limit in files:
        if path.exists():
            chunks.append(f"## {label}\n{read_text(path)[:limit]}")
    return "\n\n".join(chunks)


def should_use_rag(task):
    choice = os.environ.get("LOCAL_AGENT_ENABLE_RAG", "").strip().lower()
    if choice in {"1", "true", "yes", "on"}:
        return True
    if choice in {"0", "false", "no", "off"}:
        return False
    task_l = task.lower()
    markers = [
        "rag",
        "retrieve",
        "retrieval",
        "document",
        "docs",
        "knowledge",
        "article",
        "blog",
        "paper",
        "sglang",
        "pinecone",
        "search",
        "corpus",
        "rank",
        "rerank",
    ]
    return any(marker in task_l for marker in markers)


def rag_context(runtime, task):
    if not should_use_rag(task) or not RAG_SCALE_SCRIPT.exists():
        return ""
    result = run(["bash", str(RAG_SCALE_SCRIPT), task])
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        return f"RAG pipeline was attempted locally but did not complete:\n{detail[:1200]}" if detail else ""
    lines = [line.strip() for line in result.stdout.splitlines() if line.strip()]
    if not lines:
        return ""
    artifact_path = pathlib.Path(lines[-1])
    if not artifact_path.exists():
        return ""
    return read_text(artifact_path)[:prompt_budget(runtime, "rag_context_chars", 12000)]


def common_plan_context(runtime):
    if not COMMON_PLAN_PATH.exists():
        return ""
    return read_text(COMMON_PLAN_PATH)[:prompt_budget(runtime, "common_plan_chars", 6000)]


def skill_text_for(stage_id):
    mapping = {
        "manager": REPO_ROOT / "skills" / "lead-coordination.md",
        "director": REPO_ROOT / "skills" / "lead-coordination.md",
        "cto": REPO_ROOT / "skills" / "lead-coordination.md",
        "ceo": REPO_ROOT / "skills" / "lead-coordination.md",
        "researcher": REPO_ROOT / "skills" / "understand-project.md",
        "retriever": REPO_ROOT / "skills" / "understand-project.md",
        "planner": REPO_ROOT / "skills" / "team-orchestration.md",
        "architect": REPO_ROOT / "skills" / "generate-architecture.md",
        "implementer": REPO_ROOT / "skills" / "implement-feature.md",
        "tester": REPO_ROOT / "skills" / "validate-logic.md",
        "reviewer": REPO_ROOT / "skills" / "validate-logic.md",
        "debugger": REPO_ROOT / "skills" / "quality-rubric.md",
        "optimizer": REPO_ROOT / "skills" / "optimize-system.md",
        "benchmarker": REPO_ROOT / "skills" / "benchmark-against-quality.md",
        "qa": REPO_ROOT / "skills" / "qa-validation.md",
        "user_acceptance": REPO_ROOT / "skills" / "user-acceptance-checklist.md",
        "summarizer": REPO_ROOT / "skills" / "quality-rubric.md",
    }
    return read_text(mapping.get(stage_id, REPO_ROOT / "README.md"))


def extra_skill_text_for(stage_id, task_text):
    task_l = task_text.lower()
    paths = []
    if stage_id in {"manager", "director", "cto", "ceo", "planner", "architect", "implementer", "optimizer", "qa", "summarizer"}:
        paths.append(REPO_ROOT / "skills" / "lead-coordination.md")
    if stage_id in {"retriever", "reviewer", "qa", "summarizer"}:
        paths.append(REPO_ROOT / "skills" / "evidence-proof.md")
    if stage_id in {"reviewer", "debugger", "director"}:
        paths.append(REPO_ROOT / "skills" / "counter-analysis.md")
    if stage_id in {"qa", "benchmarker", "ceo", "summarizer"}:
        paths.append(REPO_ROOT / "skills" / "confidence-scoring.md")
    if stage_id in {"architect", "implementer", "tester"}:
        paths.append(REPO_ROOT / "skills" / "change-safety.md")
    if stage_id in {"manager", "director", "optimizer", "benchmarker"}:
        paths.append(REPO_ROOT / "skills" / "metrics-analysis.md")
    if any(term in task_l for term in ["upgrade", "better than", "exceed", "cursor", "highest-reasoning", "benchmark"]):
        if stage_id in {"manager", "director", "cto", "ceo", "researcher", "retriever", "planner", "implementer", "benchmarker", "qa"}:
            paths.append(REPO_ROOT / "skills" / "auto-discover-upgrade-features.md")
        if stage_id in {"director", "ceo", "benchmarker", "summarizer"}:
            paths.append(REPO_ROOT / "skills" / "benchmark-against-quality.md")
    if any(term in task_l for term in ["rag", "retrieval", "pinecone", "sglang", "scale", "throughput", "latency", "mcp"]):
        if stage_id in {"manager", "director", "cto", "ceo", "planner", "architect", "optimizer", "benchmarker", "qa"}:
            paths.append(REPO_ROOT / "skills" / "lead-coordination.md")
        if stage_id in {"cto", "optimizer", "benchmarker"}:
            paths.append(REPO_ROOT / "skills" / "optimize-system.md")
    seen = set()
    chunks = []
    for path in paths:
        if path in seen:
            continue
        seen.add(path)
        chunks.append(read_text(path))
    return "\n\n".join(part for part in chunks if part)


def repo_snapshot(target_repo):
    git_status = run(["git", "-C", str(target_repo), "status", "--short", "--branch"]).stdout.strip()
    entries = []
    for path in sorted(target_repo.iterdir())[:20]:
        label = path.name + ("/" if path.is_dir() else "")
        entries.append(label)
    return "\n".join(
        [
            "Top-level target repo entries:",
            "\n".join(entries) or "Unavailable.",
            "",
            "Git status:",
            git_status or "No git status available or clean tree.",
        ]
    )


def is_repo_usage_task(task):
    task_l = task.lower()
    markers = [
        "what does this repo do",
        "how should i use",
        "how do i use",
        "start command",
        "cli commands",
        "how to use this repo",
        "what are the commands",
    ]
    return any(marker in task_l for marker in markers)


def deterministic_repo_overview(runtime, target_repo):
    profile_names = ", ".join(runtime.get("profiles", {}).keys())
    start_cmd = f"cd {REPO_ROOT} && bash ./Local"
    one_shot = (
        f"cd {REPO_ROOT} && LOCAL_AGENT_TARGET_REPO={target_repo} "
        f"python3 scripts/local_team_run.py \"<task>\" {target_repo}"
    )
    batch_cmd = (
        f"cd {REPO_ROOT} && LOCAL_AGENT_TARGET_REPO={target_repo} "
        f"bash scripts/run_pipeline.sh \"<task>\""
    )
    key_files = [
        "Local",
        "scripts/start_local_cli.sh",
        "scripts/local_team_run.py",
        "config/runtime.json",
        "scripts/create_checkpoint.sh",
        "scripts/review_current_changes.py",
    ]
    commands = [
        "/help",
        "/modes",
        "/mode <fast|balanced|deep>",
        "/team",
        "/plan <task>",
        "/run <task>",
        "/pipeline <task>",
        "/progress",
        "/qa",
        "/uat",
        "/quality",
        "/verify",
        "/heal",
        "/repair",
        "/release",
        "/review",
        "/diff",
        "/files <pattern>",
        "/grep <pattern>",
        "/open <path>",
        "/doctor",
        "/checkpoint [label]",
        "/restore <checkpoint>",
    ]
    body = [
        "## Repo Overview",
        "",
        "This repo is a reusable local-first coding runtime. It gives you an interactive CLI session, a multi-model local team, progress tracking, checkpoints, resource guards, and an automatic end-of-task review.",
        "",
        "## Start",
        "",
        f"`{start_cmd}`",
        "",
        "## One-Shot Run",
        "",
        f"`{one_shot}`",
        "",
        "## Batch Run",
        "",
        f"`{batch_cmd}`",
        "",
        "## Modes",
        "",
        f"Available modes: `{profile_names}`",
        "",
        "## Main CLI Commands",
        "",
    ]
    body.extend(f"- `{command}`" for command in commands)
    body.extend(
        [
            "",
            "## Key Files",
            "",
        ]
    )
    body.extend(f"- `{path}`" for path in key_files)
    if run(["git", "-C", str(target_repo), "rev-parse", "--git-dir"]).returncode != 0:
        body.extend(
            [
                "",
                "## Current Limitation",
                "",
                f"`{target_repo}` is not a git repository right now, so `/diff` and the auto-review can only report that git metadata is missing until you initialize or clone it as a git repo.",
            ]
        )
    return "\n".join(body)


def _is_exhaustive(runtime):
    return bool(runtime.get("active_profile_config", {}).get("use_exhaustive_budget"))


EXHAUSTIVE_REASONING_BLOCK = """
## Exhaustive analysis mode (aggressive local context profile)

You are operating in exhaustive mode: maximum thoroughness. Be VERY aggressive and VERY detail-oriented.
- Reason exhaustively before answering. Cover edge cases, tradeoffs, failure modes, and alternatives.
- Do not rush. Depth over speed. Completeness over brevity.
- Prioritize correctness, completeness, and long-term maintainability.
- Cite specific files, line ranges, and commands with precision. No vague references.
- If uncertain, state the uncertainty explicitly and what would resolve it.
- Stay truthful about local limits. Do not claim unrealistic context windows or capabilities that are not configured in this repo.
- Be thorough, systematic, and leave no stone unturned.
"""


def build_prompt(runtime, task, target_repo):
    is_exhaustive = runtime.get("active_profile_config", {}).get("use_exhaustive_budget")
    history_limit = 12 if is_exhaustive else 6
    history = recent_history(target_repo, limit=history_limit)
    history_slice = 4000 if is_exhaustive else 800
    history_block = "\n\n".join(f"{item['role'].upper()}: {item['content'][:history_slice]}" for item in history)
    parts = [
        f"Target repo: {target_repo}",
        f"Runtime profile: {runtime['active_profile']}",
        "",
        repo_snapshot(target_repo),
        "",
        repo_file_index(runtime, target_repo),
        "",
        "Local runtime entrypoints:",
        f"- Start session: cd {REPO_ROOT} && bash ./Local",
        f"- One-shot run: python3 {REPO_ROOT / 'scripts' / 'local_team_run.py'} '<task>' {target_repo}",
        f"- Batch pipeline: bash {REPO_ROOT / 'scripts' / 'run_pipeline.sh'} '<task>'",
        "- Main interactive commands: /help /modes /mode /plan /run /progress /review /diff /files /grep /open",
        "",
        "Project context:",
        read_text(SUMMARY_PATH)[:prompt_budget(runtime, "project_context_chars", 8000)],
        "",
        "Available local tools:",
        load_private_tools()[:prompt_budget(runtime, "tool_registry_chars", 3000)],
        "",
    ]
    _plan = common_plan_context(runtime)
    if _plan:
        parts.append("Shared common plan from the latest run:")
        parts.append(_plan)
        parts.append("")
    _rag = rag_context(runtime, task)
    if _rag:
        parts.append("Retrieved grounding context:")
        parts.append(_rag)
        parts.append("")
    _mentioned = mentioned_file_context(runtime)
    if _mentioned:
        parts.append("Mentioned files for this session:")
        parts.append(_mentioned)
        parts.append("")
    _vc = validation_artifact_context(runtime, task)
    if _vc:
        parts.append("Recent validation artifacts:")
        parts.append(_vc)
        parts.append("")
    parts.extend([
        "Recent session history:",
        (history_block or "No prior conversation history for this repo.")[:prompt_budget(runtime, "history_chars", 2500)],
        "",
        "Task:",
        task,
        "",
    ])
    if is_exhaustive:
        parts.append(EXHAUSTIVE_REASONING_BLOCK.strip())
        parts.append("")
    parts.extend([
        "Answer like a strong Codex-style coding assistant. Be concrete, use repo facts, cite useful files or commands when relevant, and do not expose hidden chain-of-thought.",
        "Default to direct execution-oriented language: concise opening, visible progress, concrete outcomes, and minimal meta commentary.",
        "Start with a common plan, then let the lead route work to matching skills and sub-agents so useful streams run in parallel without duplicating effort.",
        "Use startup-style role discipline: one lead plan, clear ownership per file group, parallel readers, and single-writer execution so agents do not step on each other.",
        "Teach the local runtime in every answer: prefer local agents, local tools, shared plans, and skill reuse before suggesting new manual steps.",
        "Checkpoint only the target project when the task changes project state. Never checkpoint the local-agent-runtime repo itself.",
        "Before any destructive restore or delete path, require a pre-delete diff preview and approval gate. Prefer dry-run restore previews before apply.",
        "Track ROI before scaling depth: if recent runtime events show repeated low-yield waits or takeovers, stop the local pipeline early, re-plan, and hand off the unfinished subset.",
        "Keep the zero-paid-API goal explicit. Default to local-model-only execution unless the current cloud session must take over because the local runtime is stalled or failing.",
        "Use the right model for the job: cheap local models for lightweight retrieval, stronger local coding models for implementation, and remote reasoning/coding providers only when they materially reduce stalls or improve quality.",
        "If the local runtime stalls, name the exact stalled point and the minimal takeover step a Codex or Claude session should complete to finish on time. Do not sit and wait once the resource wait budget is exhausted.",
        "Do not tell the user to clone the repo or use remote APIs unless the task explicitly asks for distribution or publishing.",
        "When retrieved grounding context is present, use it before broad prior assumptions.",
        "If the user asks a yes-or-no verification question, answer yes or no explicitly before the explanation.",
        "Do not reference files, commands, models, or workflows unless they are present in the repo snapshot, retrieved context, or prior validated outputs.",
    ])
    return "\n".join(parts)


def repo_file_index(runtime, target_repo):
    budget = prompt_budget(runtime, "repo_file_index_chars", 12000)
    interesting_roots = [
        target_repo / "config",
        target_repo / "scripts",
        target_repo / "skills",
        target_repo / "roles",
        target_repo / "workflows",
        target_repo / "docs",
        target_repo / "state",
    ]
    files = []
    for root in interesting_roots:
        if not root.exists():
            continue
        for path in sorted(root.rglob("*")):
            if path.is_file():
                files.append(path.relative_to(target_repo).as_posix())
                if len(files) >= 220:
                    break
        if len(files) >= 220:
            break
    if not files:
        return "Relevant repo file index:\nUnavailable."
    body = "Relevant repo file index:\n" + "\n".join(f"- {item}" for item in files)
    return body[:budget]


def build_stage_prompt(runtime, stage_id, base_prompt, outputs):
    per_role_chars = 50000 if _is_exhaustive(runtime) else 1200
    if not outputs:
        prior = "No prior role outputs yet."
    else:
        sections = []
        for key in runtime["active_team_order"]:
            if key in outputs:
                sections.append(f"## {key}\n{outputs[key][:per_role_chars]}")
        prior = "\n\n".join(sections)[:prompt_budget(runtime, "prior_output_chars", 6000)]
    return "\n\n".join(
        [
            base_prompt,
            "Prior role outputs:",
            prior,
            f"Current role focus: {stage_id}",
            f"Role-specific objective: {STAGE_FOCUS.get(stage_id, 'Provide the strongest useful output for this stage.')}",
            stage_output_contract(runtime, stage_id),
        ]
    )


def stage_output_contract(runtime, stage_id):
    exhaustive = _is_exhaustive(runtime)
    if stage_id == "planner":
        base = (
            "Return sections named `Existing work to reuse`, `Common plan`, `Parallel workstreams`, and `Validation path`. "
            "The `Common plan` section must be the authoritative handoff for all later roles. "
            "Every file path, command, and tool name must already exist in the repo context or be clearly marked as missing. "
            "Include `Skill routing` and `Takeover trigger` details when local agents may stall or when cloud-session fallback should be explicit."
        )
        if exhaustive:
            base += " Add `Scaling notes`, `Risk register`, and `Known gaps and next upgrades` when relevant."
        return base
    if stage_id == "architect":
        base = (
            "Return sections named `Architecture decisions`, `Coordination model`, `Scale path`, and `Dependencies`. "
            "Explicitly align to the common plan and name which roles can proceed in parallel. "
            "Only cite components that exist in the repo or were retrieved as grounding context."
        )
        if exhaustive:
            base += " Add `Tradeoffs` and `Fallback path` when relevant."
        return base
    if stage_id == "qa":
        return (
            "Return sections named `Yes or no`, `What passed`, `What is still risky`, and `Exact next validation`. "
            "The first line under `Yes or no` must answer the user's verification request directly."
        )
    if stage_id == "summarizer":
        base = (
            "Return the final user-facing answer only. Prefer short headings if they help. Include concrete commands, files, or next steps when relevant. "
            "Sound like a pragmatic Codex-style CLI agent: direct, concise, execution-oriented, and low on ceremony. "
            "Include visible progress or completion state when the task is still running, and state the local-vs-cloud execution split when it is relevant. "
            "Do not mention internal pipeline mechanics unless the user asked. If the task is about understanding or using the repo, include the exact local start command and the most important CLI commands. "
            "Start with a yes-or-no line when the user asked for verification. Never claim the chat transport itself is local-only unless that is actually true. "
            "When work remains, call out what local agents completed, what is left, and whether a cloud-session takeover is warranted."
        )
        if exhaustive:
            base += " Be comprehensive: cover all key points, tradeoffs, and risks. Structure with clear sections."
        return base
    base = (
        "Return concise sections named `What I learned`, `Concrete details`, and `Next handoff`. "
        "Mention exact files, commands, workflows, or risks whenever they are present in context."
    )
    if exhaustive:
        base += " In exhaustive mode: add `Thorough analysis` and `Alternatives considered` when relevant. Depth over brevity."
    return base


def looks_generic(runtime, text):
    text_l = text.lower()
    if len(text.strip()) < runtime.get("quality", {}).get("min_response_chars", 320):
        return True
    phrases = runtime.get("quality", {}).get("generic_phrases", [])
    if any(phrase in text_l for phrase in phrases):
        return True
    markers = runtime.get("quality", {}).get("concrete_term_markers", [])
    concrete_hits = sum(1 for marker in markers if marker in text)
    return concrete_hits < 2


def looks_invalid_reference(target_repo, text):
    text_l = text.lower()
    if any(marker in text_l for marker in ["/path/to/", "<path>", "todo:", "fixme:", "your_file_here"]):
        return True
    candidates = set()
    for item in re.findall(r"`([^`\n]+)`", text):
        candidates.add(item.strip())
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith(("python3 ", "bash ", "./", "/")):
            candidates.add(stripped)
    repo_root = target_repo.resolve()
    for item in candidates:
        if not item:
            continue
        command_bits = item.split()
        path_like = command_bits[-1] if command_bits else item
        if any(token in path_like for token in [".py", ".sh", ".md", ".json", ".yaml", ".yml"]) or "/" in path_like:
            path = pathlib.Path(path_like)
            if not path.is_absolute():
                path = repo_root / path
            if not path.exists():
                return True
    return False


def build_retry_prompt(stage_id, stage_prompt, first_pass):
    return "\n\n".join(
        [
            stage_prompt,
            "Your previous answer was too generic for this repo-aware local workflow.",
            "Revise it with significantly more specificity.",
            "Requirements:",
            "- mention concrete files, commands, roles, or workflows when available",
            "- resolve ambiguity instead of repeating disclaimers",
            "- if something is missing, state the gap and the exact local next step",
            "- do not mention files or commands that are not present in the repo context",
            "- do not claim impossible local settings such as fake context sizes",
            "- do not invent scripts, commands, or file paths that do not exist",
            "",
            "Previous answer:",
            first_pass[:1600],
        ]
    )


def stage_lessons_block(stage_id):
    lessons = get_lessons_for_stage(stage_id)
    return lessons, format_lessons_for_prompt(lessons)


def system_prompt_for(stage_id, task_text, lessons_block=""):
    role_text = read_text(ROLE_FILES.get(stage_id, REPO_ROOT / "README.md"))
    skill_text = skill_text_for(stage_id)
    extra_skill_text = extra_skill_text_for(stage_id, task_text)
    coordination = (
        "Local runtime contract:\n"
        "- Start from the shared common plan.\n"
        "- Pick work by skill and avoid duplicate effort.\n"
        "- Run independent work in parallel when the group order allows it.\n"
        "- Keep answers concrete, repo-aware, and aligned to a strong Codex-style CLI bar.\n"
        "- Checkpoint only the target project, never the runtime repo itself.\n"
        "- Prefer local-only completion. If local execution cannot finish on time, state the exact takeover trigger and stop waiting once the resource wait budget is spent.\n"
        "- Claim files before writing to prevent collisions with parallel agents.\n"
        "- Learn from prior failures: check runtime lessons before repeating known mistakes."
    )
    return "\n\n".join(part for part in [role_text, skill_text, extra_skill_text, coordination, lessons_block] if part)


def run_stage(runtime, stage_id, target_repo, base_prompt, prior_outputs, available_models, stamp):
    stage_cfg = runtime["team"][stage_id]
    resource_state = load_resource_state()
    provider_name, model = resolve_execution_target(runtime, stage_id, available_models, resource_state)
    label = stage_cfg["label"]
    enforce_roi_kill_switch(runtime, stage_id, target_repo)
    update_execution_state(os.environ.get("LOCAL_AGENT_ACTIVE_TASK", ""), target_repo, provider_name)
    if provider_uses_local_resources(provider_name):
        ensure_resource_capacity(runtime)
    # Run pre-stage hook (file size checks, test filtering, context prep)
    run_hook("pre_stage.sh", stage_id, target_repo, stamp)
    progress(["start", "--stage", stage_id, "--label", label, "--percent", "1", "--detail", f"Dispatching {provider_name}:{model}"])
    stop_event = threading.Event()
    worker = threading.Thread(target=pulse, args=(stage_id, f"Running via {provider_name}: {model}", stop_event), daemon=True)
    worker.start()

    # Runtime hard memory governor: monitor memory DURING model execution
    mem_governor_event = threading.Event()

    def _memory_governor():
        """Background thread that checks memory during model execution.
        If memory exceeds ceiling: serialize state, unload idle models, downgrade."""
        limits = runtime.get("resource_limits", {})
        mem_ceiling = float(limits.get("memory_percent", 70))
        poll_secs = max(2, int(limits.get("poll_seconds", 1)) * 3)
        while not mem_governor_event.is_set():
            mem_governor_event.wait(timeout=poll_secs)
            if mem_governor_event.is_set():
                break
            try:
                _, mid_data = resource_status_snapshot()
                mid_mem = float(mid_data.get("memory_percent", 0)) if mid_data else 0
                if mid_mem > mem_ceiling:
                    # Step 1: Serialize state to disk
                    state_dump = REPO_ROOT / "state" / f"governor-{stage_id}-state.json"
                    state_dump.write_text(json.dumps({
                        "stage_id": stage_id, "model": model, "provider": provider_name,
                        "memory_percent": mid_mem, "ceiling": mem_ceiling,
                        "timestamp": datetime.now().isoformat(timespec="seconds"),
                    }, indent=2))
                    # Step 2: Unload idle models
                    try:
                        from blocker_resolver import unload_ollama_models
                        cleanup_msg = unload_ollama_models()
                        progress(["tick", "--stage", stage_id, "--percent", "50",
                                  "--detail", f"Governor: mem {mid_mem:.0f}%>{mem_ceiling:.0f}%, unloaded: {cleanup_msg}"])
                    except Exception:
                        pass
                    # Step 3: Record lesson for future downgrade
                    teach_lesson(
                        category="resource",
                        trigger=f"governor_memory_{stage_id}",
                        lesson=f"Memory {mid_mem:.0f}% exceeded {mem_ceiling:.0f}% ceiling during {stage_id} execution",
                        fix="Downgrade to smaller model or reduce prompt budget for this stage",
                        context=f"stage={stage_id} model={model} provider={provider_name}",
                    )
            except Exception:
                pass  # Governor failure must not crash the stage

    governor_thread = threading.Thread(target=_memory_governor, daemon=True)
    governor_thread.start()

    try:
        stage_lessons, lessons_block = stage_lessons_block(stage_id)
        for lesson in stage_lessons:
            trigger = lesson.get("trigger", "")
            if trigger:
                mark_lesson_applied(trigger)
        stage_prompt = build_stage_prompt(runtime, stage_id, base_prompt, prior_outputs)

        # Retry logic for first-role startup failures (connection resets, model loading delays)
        max_start_retries = 3
        last_err = None
        for attempt in range(max_start_retries):
            try:
                content = call_model(runtime, provider_name, model, system_prompt_for(stage_id, base_prompt, lessons_block), stage_prompt)
                last_err = None
                break
            except (urllib.error.URLError, ConnectionError, OSError) as exc:
                last_err = exc
                if attempt < max_start_retries - 1:
                    backoff = 2 ** attempt
                    progress(["tick", "--stage", stage_id, "--percent", "2", "--detail", f"Retry {attempt + 1}/{max_start_retries} after startup error: {exc} (wait {backoff}s)"])
                    time.sleep(backoff)
                    # Re-check resource state and model availability before retry
                    resource_state = load_resource_state()
                    provider_name, model = resolve_execution_target(runtime, stage_id, available_models, resource_state)
        if last_err is not None:
            raise last_err
        attempts = runtime["active_retry_generic_output"]
        while attempts > 0 and (looks_generic(runtime, content) or looks_invalid_reference(target_repo, content)):
            attempts -= 1
            teach_lesson(
                category="quality",
                trigger=f"generic_output_{stage_id}",
                lesson=f"{stage_id} produced generic or invalid output, retrying with refinement prompt",
                fix="Improve role prompt specificity or use larger model for this stage",
                context=f"stage={stage_id} model={model} provider={provider_name}",
            )
            progress(
                [
                    "tick",
                    "--stage",
                    stage_id,
                    "--percent",
                    "60",
                    "--detail",
                    f"Refining generic output with {provider_name}:{model}",
                ]
            )
            content = call_model(
                runtime,
                provider_name,
                model,
                system_prompt_for(stage_id, base_prompt, lessons_block),
                build_retry_prompt(stage_id, stage_prompt, content),
            )
    finally:
        stop_event.set()
        mem_governor_event.set()
        worker.join(timeout=1)
        governor_thread.join(timeout=1)

    artifact = MEMORY_DIR / f"{stamp}-{stage_id}.md"
    artifact.write_text(content + "\n")
    if stage_id == "planner":
        COMMON_PLAN_PATH.write_text(content + "\n")
    record_roi_event(runtime, stage_id, "positive", f"completed via {provider_name}:{model}")
    release_files(stage_id)
    # Run post-stage hook (log output size, check quality, trim context)
    run_hook("post_stage.sh", stage_id, target_repo, stamp, artifact_path=str(artifact))
    progress(["complete", "--stage", stage_id, "--label", label, "--detail", f"Completed with {provider_name}:{model}"])
    return stage_id, content, f"{provider_name}:{model}", artifact


def run_group(runtime, group, target_repo, base_prompt, outputs, available_models, stamp):
    group_outputs = {}
    shared_outputs = dict(outputs)
    max_workers = effective_max_parallel_roles(runtime, group, available_models)
    with concurrent.futures.ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = {
            executor.submit(
                run_stage,
                runtime,
                stage_id,
                target_repo,
                base_prompt,
                shared_outputs,
                available_models,
                stamp,
            ): stage_id
            for stage_id in group
        }
        for future in concurrent.futures.as_completed(futures):
            stage_id, content, _model, _artifact = future.result()
            group_outputs[stage_id] = content
    outputs.update(group_outputs)


def main():
    if len(sys.argv) < 2:
        raise SystemExit("Usage: local_team_run.py '<task>' [target_repo]")
    load_runtime_env(override=False)
    task = sys.argv[1]
    target_repo = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else pathlib.Path.cwd()).resolve()
    os.environ["LOCAL_AGENT_ACTIVE_TASK"] = task
    os.environ["LOCAL_AGENT_TARGET_REPO"] = str(target_repo)
    runtime = load_runtime()
    acquire_lock(runtime, task, target_repo)
    write_history("user", task, target_repo)

    try:
        preflight_stage = {"id": "preflight", "weight": 3.0, "label": "Preflight"}
        stage_ids = runtime["active_team_order"]
        stage_cfgs = [runtime["team"][stage_id] for stage_id in stage_ids]
        subprocess.run(
            [
                "python3",
                str(PROGRESS),
                "init",
                "--task",
                f"{task} [{runtime['active_profile']}]",
                "--stages",
                preflight_stage["id"],
                *stage_ids,
                "--weights",
                str(preflight_stage["weight"]),
                *[str(item["weight"]) for item in stage_cfgs],
                "--labels",
                preflight_stage["label"],
                *[item["label"] for item in stage_cfgs],
            ],
            check=True,
            stdout=subprocess.DEVNULL,
        )
        progress(["start", "--stage", "preflight", "--label", "Preflight", "--percent", "5", "--detail", "Bootstrapping runtime"])
        subprocess.run(["bash", str(BOOTSTRAP)], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        progress(["tick", "--stage", "preflight", "--percent", "20", "--detail", "Refreshing model registry"])
        subprocess.run(["python3", str(MODEL_REGISTRY), "--write"], check=True, stdout=subprocess.DEVNULL)
        progress(["tick", "--stage", "preflight", "--percent", "45", "--detail", f"Summarizing {target_repo.name}"])
        subprocess.run(["python3", str(SUMMARY_SCRIPT), str(target_repo)], check=True, stdout=subprocess.DEVNULL)
        progress(["tick", "--stage", "preflight", "--percent", "65", "--detail", "Refreshing tool registry"])
        subprocess.run(["python3", str(REPO_ROOT / "scripts" / "private_tool_registry.py")], check=True, stdout=subprocess.DEVNULL)
        progress(["tick", "--stage", "preflight", "--percent", "80", "--detail", "Writing session state"])
        subprocess.run(["python3", str(SESSION_STATE), "running", task, str(target_repo)], check=True, stdout=subprocess.DEVNULL)

        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        progress(["tick", "--stage", "preflight", "--percent", "92", "--detail", "Resolving installed models"])
        available_models = installed_models()

        outputs = {}
        progress(["tick", "--stage", "preflight", "--percent", "97", "--detail", "Assembling repo context"])
        user_prompt = build_prompt(runtime, task, target_repo)
        progress(["complete", "--stage", "preflight", "--label", "Preflight", "--detail", "Runtime ready"])
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

        # Proactive resource cleanup before pipeline execution
        try:
            from blocker_resolver import unload_ollama_models
            snapshot, res_data = resource_status_snapshot()
            mem_pct = float(res_data.get("memory_percent", 0)) if res_data else 0
            downgrade_thresh = float(runtime["resource_limits"].get("model_downgrade_memory_percent", 75))
            if mem_pct > downgrade_thresh:
                msg = unload_ollama_models()
                progress(["tick", "--stage", "preflight", "--percent", "99", "--detail", f"Proactive cleanup: {msg}"])
        except Exception:
            pass

        for group in runtime["active_group_order"]:
            # Enforce 70% memory ceiling between groups during active execution
            try:
                _, mid_data = resource_status_snapshot()
                mem_ceiling = float(runtime["resource_limits"].get("memory_percent", 70))
                mid_mem = float(mid_data.get("memory_percent", 0)) if mid_data else 0
                if mid_mem > mem_ceiling:
                    try:
                        from blocker_resolver import unload_ollama_models
                        cleanup_msg = unload_ollama_models()
                        progress(["tick", "--stage", group[0], "--percent", "1",
                                  "--detail", f"Memory {mid_mem:.0f}% > {mem_ceiling:.0f}% ceiling, cleanup: {cleanup_msg}"])
                    except Exception:
                        progress(["tick", "--stage", group[0], "--percent", "1",
                                  "--detail", f"Memory {mid_mem:.0f}% > {mem_ceiling:.0f}% ceiling, waiting for release"])
                        time.sleep(2)
            except Exception:
                pass
            run_group(runtime, group, target_repo, user_prompt, outputs, available_models, stamp)

            # Cross-role critique loop: if reviewer marks quality as weak or
            # score < 60, send a revision request back to implementer before
            # continuing to QA.
            if "reviewer" in group and "reviewer" in outputs:
                reviewer_text = outputs["reviewer"].lower()
                quality_weak = "weak" in reviewer_text
                score_match = re.search(r'(?:score|quality)[:\s]*(\d+)', reviewer_text)
                score_low = score_match and int(score_match.group(1)) < 60
                if quality_weak or score_low:
                    reason = "weak quality" if quality_weak else f"score {score_match.group(1)}"
                    progress(["tick", "--stage", "implementer", "--percent", "80",
                              "--detail", f"Cross-role critique: reviewer flagged {reason}, requesting revision"])
                    revision_prompt = (
                        f"The reviewer flagged your previous output as {reason}. "
                        f"Reviewer feedback:\n\n{outputs['reviewer']}\n\n"
                        "Please revise your implementation to address the reviewer's concerns. "
                        "Focus on the specific issues raised."
                    )
                    outputs["_revision_request"] = revision_prompt
                    if "implementer" in runtime.get("team", {}):
                        _stage_id, revised, _model, _artifact = run_stage(
                            runtime, "implementer", target_repo,
                            user_prompt + "\n\n" + revision_prompt,
                            outputs, available_models, stamp,
                        )
                        outputs["implementer"] = revised
                        progress(["tick", "--stage", "implementer", "--percent", "100",
                                  "--detail", "Revision complete after cross-role critique"])

        final = outputs.get("summarizer") or next(reversed(outputs.values()))
        if is_repo_usage_task(task):
            final = deterministic_repo_overview(runtime, target_repo)
        latest = REPO_ROOT / "logs" / "latest-response.md"
        latest.write_text(final + "\n")
        write_history("assistant", final, target_repo)
        subprocess.run(["python3", str(SESSION_STATE), "idle", "", str(target_repo)], check=True, stdout=subprocess.DEVNULL)
        print(final)
    finally:
        release_lock()


if __name__ == "__main__":
    try:
        main()
    except urllib.error.URLError as exc:
        reason = "local ollama runtime unavailable"
        task = os.environ.get("LOCAL_AGENT_ACTIVE_TASK", "")
        target_repo = os.environ.get("LOCAL_AGENT_TARGET_REPO", REPO_ROOT)
        set_takeover_state(task, target_repo, reason, local_percent=0.0, cloud_percent=100.0)
        record_runtime_lesson("takeover", task, target_repo, reason, str(exc))
        raise SystemExit(f"Unable to reach local Ollama runtime: {exc}") from exc
    except KeyboardInterrupt:
        subprocess.run(["python3", str(SESSION_STATE), "idle"], check=False, stdout=subprocess.DEVNULL)
        release_lock()
        raise SystemExit(130)
