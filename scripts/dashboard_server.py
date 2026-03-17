#!/usr/bin/env python3
"""Local web UI dashboard for agent runtime at http://localhost:8411.

Shows real-time status of:
- Active task progress with timer
- Role breakdown with per-role progress bars
- Model usage (local vs cloud split)
- Resource utilization (CPU, memory)
- Agent coordination status
- Runtime lessons learned
- Takeover recommendations
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import subprocess
import threading
import time
from http.server import HTTPServer, BaseHTTPRequestHandler, ThreadingHTTPServer
from datetime import datetime
from socket import error as socket_error

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from todo_progress import parse_todo, LANE_ORDER, LANE_LABELS, USE_CASE_ORDER, USE_CASE_LABELS
from runtime_env import env_with_runtime, openclaw_status


_STATE_CACHE: dict[str, object] = {"timestamp": 0.0, "data": None}
_STATE_CACHE_LOCK = threading.Lock()
_STATE_REFRESHING = False
_OPENCLAW_CACHE: dict[str, object] = {"timestamp": 0.0, "data": None}
_OPENCLAW_CACHE_LOCK = threading.Lock()


def load_json(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    try:
        body = json.loads(path.read_text())
        return body if isinstance(body, dict) else {}
    except (json.JSONDecodeError, OSError):
        return {}


def _run_openclaw(*args: str) -> str:
    try:
        proc = subprocess.run(
            ["openclaw", *args],
            capture_output=True,
            text=True,
            timeout=float(os.environ.get("LOCAL_AGENT_OPENCLAW_TIMEOUT_SECONDS", "1.2")),
            check=False,
        )
    except Exception:
        return ""
    return (proc.stdout or proc.stderr or "").strip()


def _parse_usage_cost(text: str) -> dict:
    total = "unknown"
    tokens = "unknown"
    for line in text.splitlines():
        if line.lower().startswith("total:"):
            parts = [part.strip() for part in line.split("·")]
            if parts:
                total = parts[0].split(":", 1)[-1].strip()
            if len(parts) > 1:
                tokens = parts[1]
    return {"total": total, "tokens": tokens}


def _openclaw_metrics_uncached() -> dict:
    status_text = _run_openclaw("gateway", "status")
    probe_text = _run_openclaw("gateway", "probe")
    health_text = _run_openclaw("gateway", "health")
    usage_text = _run_openclaw("gateway", "usage-cost")
    root_status = openclaw_status()
    requested_tools = {
        "agency": False,
        "promptfu": False,
        "mirrorish": False,
        "impeccable": False,
        "open_viking": False,
        "heretic": False,
        "nanochat": False,
    }
    return {
        "configured": bool(root_status.get("configured")),
        "base_url": root_status.get("base_url", ""),
        "dashboard_url": root_status.get("dashboard_url", ""),
        "health": {
            "ok": "OK" in health_text,
            "summary": health_text.splitlines()[0] if health_text else "unknown",
            "detail": health_text,
        },
        "service": {
            "loaded": "LaunchAgent (loaded)" in status_text or "running" in status_text.lower(),
            "runtime": next((line.strip() for line in status_text.splitlines() if line.startswith("Runtime:")), "unknown"),
            "listener": next((line.strip() for line in status_text.splitlines() if line.startswith("Listening:")), "unknown"),
            "warning": next((line.strip() for line in status_text.splitlines() if "Recommendation:" in line or "issue:" in line.lower()), ""),
            "detail": status_text,
        },
        "probe": {
            "reachable": "Reachable: yes" in probe_text or "Connect: ok" in probe_text,
            "detail": probe_text,
            "limited": "missing scope" in probe_text.lower(),
        },
        "usage_cost": {
            **_parse_usage_cost(usage_text),
            "detail": usage_text,
        },
        "capabilities": {
            "gateway": True,
            "dashboard": True,
            "doctor": True,
            "usage_cost": True,
            "requested_tools": requested_tools,
        },
        "checked_at": datetime.now().isoformat(timespec="seconds"),
    }


def _openclaw_metrics() -> dict:
    now = time.time()
    with _OPENCLAW_CACHE_LOCK:
        cached = _OPENCLAW_CACHE.get("data")
        timestamp = float(_OPENCLAW_CACHE.get("timestamp", 0.0) or 0.0)
        if cached and now - timestamp <= 15.0:
            return cached  # type: ignore[return-value]
    data = _openclaw_metrics_uncached()
    if cached and not data.get("health", {}).get("detail") and not data.get("service", {}).get("detail"):
        return cached  # type: ignore[return-value]
    with _OPENCLAW_CACHE_LOCK:
        _OPENCLAW_CACHE["timestamp"] = now
        _OPENCLAW_CACHE["data"] = data
    return data


def _tracked_state_paths() -> list[pathlib.Path]:
    return [
        REPO_ROOT / "state" / "progress.json",
        REPO_ROOT / "state" / "session-state.json",
        REPO_ROOT / "state" / "resource-status.json",
        REPO_ROOT / "state" / "agent-coordination.json",
        REPO_ROOT / "state" / "auto-remediation.json",
        REPO_ROOT / "state" / "runtime-lessons.json",
        REPO_ROOT / "state" / "session-history.jsonl",
        REPO_ROOT / "state" / "todo.md",
        REPO_ROOT / "config" / "runtime.json",
    ]


def _display_path(path: pathlib.Path) -> str:
    try:
        return str(path.relative_to(REPO_ROOT))
    except ValueError:
        return str(path)


def _state_signature() -> tuple[tuple[str, int, int], ...]:
    signature = []
    for path in _tracked_state_paths():
        try:
            stat = path.stat()
            signature.append((_display_path(path), int(stat.st_mtime_ns), int(stat.st_size)))
        except OSError:
            signature.append((_display_path(path), 0, 0))
    return tuple(signature)


def _state_freshness() -> dict:
    now = time.time()
    thresholds = {
        "progress.json": 15,
        "session-state.json": 15,
        "resource-status.json": 10,
        "agent-coordination.json": 20,
        "auto-remediation.json": 30,
        "runtime-lessons.json": 300,
        "session-history.jsonl": 20,
        "todo.md": 300,
        "runtime.json": 600,
    }
    sources = []
    stalest = {"path": "", "age_seconds": 0.0}
    freshest = {"path": "", "age_seconds": float("inf")}
    for path in _tracked_state_paths():
        rel = _display_path(path)
        threshold = thresholds.get(path.name, 60)
        try:
            stat = path.stat()
            age = max(0.0, now - stat.st_mtime)
        except OSError:
            age = float("inf")
        source = {
            "path": rel,
            "age_seconds": None if age == float("inf") else round(age, 1),
            "stale": age == float("inf") or age > threshold,
            "threshold_seconds": threshold,
        }
        sources.append(source)
        comparable_age = age if age != float("inf") else 10**9
        if comparable_age > stalest["age_seconds"]:
            stalest = {"path": rel, "age_seconds": None if age == float("inf") else round(age, 1)}
        if comparable_age < freshest["age_seconds"]:
            freshest = {"path": rel, "age_seconds": round(age, 1)}
    stale_sources = [item for item in sources if item["stale"]]
    return {
        "sources": sources,
        "stale_count": len(stale_sources),
        "stale_sources": stale_sources[:6],
        "freshest_source": freshest if freshest["path"] else {},
        "stalest_source": stalest if stalest["path"] else {},
    }
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _runtime_config() -> dict:
    runtime = load_json(REPO_ROOT / "config" / "runtime.json")
    if not runtime:
        return {}
    try:
        import local_team_run
    except Exception:
        return runtime

    runtime_env = env_with_runtime()
    profile_name = runtime_env.get("LOCAL_AGENT_MODE", runtime.get("default_profile", "balanced"))
    profile = runtime.get("profiles", {}).get(profile_name, {})
    active_team_order = local_team_run.parse_selected_roles(profile, runtime)
    active_group_order = local_team_run.group_order_for(active_team_order, profile)
    resource = _live_resource_status()
    provider_plan = []
    original = {key: os.environ.get(key) for key in runtime_env}
    try:
        os.environ.update(runtime_env)
        for stage_id in active_team_order:
            provider_order = local_team_run.provider_order_for_stage(runtime, stage_id, resource)
            provider_name = provider_order[0] if provider_order else "ollama"
            if provider_name == "ollama":
                model_name = runtime.get("team", {}).get(stage_id, {}).get("model", runtime.get("default_model", "?"))
            else:
                model_name = local_team_run.provider_model_for_stage(runtime, provider_name, stage_id)
            provider_plan.append(
                {
                    "stage_id": stage_id,
                    "provider": provider_name,
                    "model": model_name,
                    "provider_order": provider_order,
                }
            )
        runtime["provider_preference"] = local_team_run.provider_preference(runtime)
        runtime["remote_fallback_allowed"] = local_team_run.remote_fallback_allowed(runtime)
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
    runtime["active_profile"] = profile_name
    runtime["active_team_order"] = active_team_order
    runtime["active_group_order"] = active_group_order
    runtime["provider_plan"] = provider_plan
    return runtime


def _runtime_groups(runtime: dict, progress: dict) -> list[dict]:
    groups = []
    progress_by_stage = {item.get("id"): item for item in progress.get("stages", [])}
    for index, roles in enumerate(runtime.get("active_group_order", []), start=1):
        stage_rows = []
        percents = []
        active = 0
        completed = 0
        providers = {}
        for role in roles:
            stage = progress_by_stage.get(role, {})
            pct = float(stage.get("percent", 0.0) or 0.0)
            status = stage.get("status", "pending")
            provider_row = next((item for item in runtime.get("provider_plan", []) if item.get("stage_id") == role), {})
            provider_name = provider_row.get("provider", "ollama")
            providers[provider_name] = providers.get(provider_name, 0) + 1
            stage_rows.append(
                {
                    "role": role,
                    "status": status,
                    "percent": pct,
                    "provider": provider_name,
                    "model": provider_row.get("model", ""),
                }
            )
            percents.append(pct)
            if status in {"running", "active"}:
                active += 1
            if status == "completed":
                completed += 1
        percent = round(sum(percents) / max(1, len(percents)), 1)
        groups.append(
            {
                "id": f"group-{index}",
                "label": f"Team {index}",
                "roles": roles,
                "percent": percent,
                "active_roles": active,
                "completed_roles": completed,
                "provider_mix": providers,
                "items": stage_rows,
            }
        )
    return groups


def _author_name() -> str:
    """Always return Jimmy Malhan. No other author references allowed."""
    return "Jimmy Malhan"


def _flag_from_env(name: str) -> bool | None:
    value = os.environ.get(name)
    if value is None:
        return None
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _ui_flags() -> dict:
    flags = _runtime_config().get("ui", {}).get("flags", {})
    resolved = {
        "enhanced_dashboard": bool(flags.get("enhanced_dashboard", False)),
        "executive_conflict": bool(flags.get("executive_conflict", False)),
        "governance_panel": bool(flags.get("governance_panel", False)),
        "auto_remediation_panel": bool(flags.get("auto_remediation_panel", False)),
    }
    overrides = {
        "enhanced_dashboard": _flag_from_env("LOCAL_AGENT_UI_ENHANCED_DASHBOARD"),
        "executive_conflict": _flag_from_env("LOCAL_AGENT_UI_EXECUTIVE_CONFLICT"),
        "governance_panel": _flag_from_env("LOCAL_AGENT_UI_GOVERNANCE_PANEL"),
        "auto_remediation_panel": _flag_from_env("LOCAL_AGENT_UI_AUTO_REMEDIATION_PANEL"),
    }
    for key, value in overrides.items():
        if value is not None:
            resolved[key] = value
    if not resolved["enhanced_dashboard"]:
        resolved["executive_conflict"] = False
        resolved["governance_panel"] = False
        resolved["auto_remediation_panel"] = False
    return resolved


def _live_resource_status() -> dict:
    """Return live CPU and memory usage so the dashboard does not depend on stale state."""
    threshold = load_json(REPO_ROOT / "state" / "resource-status.json").get("threshold_percent", 70)
    cpu_percent = 0.0
    memory_percent = 0.0
    try:
        import psutil  # type: ignore

        cpu_percent = float(psutil.cpu_percent(interval=0.05))
        memory_percent = float(psutil.virtual_memory().percent)
    except Exception:
        try:
            vm = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=2)
            pages = {}
            for line in vm.stdout.splitlines():
                if ":" not in line:
                    continue
                key, value = line.split(":", 1)
                pages[key.strip()] = int(value.strip().replace(".", ""))
            page_size = 4096
            total = (
                pages.get("Pages free", 0)
                + pages.get("Pages active", 0)
                + pages.get("Pages inactive", 0)
                + pages.get("Pages speculative", 0)
                + pages.get("Pages wired down", 0)
                + pages.get("Pages occupied by compressor", 0)
            )
            used = total - pages.get("Pages free", 0)
            memory_percent = round((used * page_size) / max(1, total * page_size) * 100.0, 1)
        except Exception:
            memory_percent = float(load_json(REPO_ROOT / "state" / "resource-status.json").get("memory_percent", 0.0))
        try:
            top = subprocess.run(["top", "-l", "1", "-n", "0"], capture_output=True, text=True, timeout=2)
            cpu_line = next((line for line in top.stdout.splitlines() if "CPU usage:" in line), "")
            if cpu_line:
                user_part = cpu_line.split("CPU usage:", 1)[1].split("%", 1)[0].strip()
                cpu_percent = float(user_part)
        except Exception:
            cpu_percent = float(load_json(REPO_ROOT / "state" / "resource-status.json").get("cpu_percent", 0.0))
    return {
        "timestamp": datetime.now().isoformat(timespec="seconds"),
        "cpu_percent": round(cpu_percent, 1),
        "memory_percent": round(memory_percent, 1),
        "threshold_percent": threshold,
    }


def _load_todo() -> dict:
    """Parse state/todo.md into structured data for the dashboard."""
    parsed = parse_todo()
    items = []
    for section in parsed.get("sections", []):
        for item in section.get("items", []):
            items.append(
                {
                    "text": item["text"],
                    "done": item["done"],
                    "section": section["name"],
                    "lane": item.get("lane", "general"),
                    "use_case": item.get("use_case", "general"),
                }
            )

    # Classify blockers: open items with blocker-ish keywords
    blocker_kw = ["fix", "block", "stall", "fail", "stuck", "ceiling", "kill switch", "timeout", "error", "broken"]
    blockers = [i for i in items if not i["done"] and any(k in i["text"].lower() for k in blocker_kw)]
    working = [i for i in items if not i["done"] and i not in blockers]
    stats = dict(parsed.get("overall", {"total": 0, "done": 0, "open": 0, "percent": 0.0}))
    stats["eta_minutes"] = max(1, int(stats.get("open", 0) * 3)) if stats.get("open", 0) else 0
    priority_sections = []
    for section in parsed.get("sections", []):
        name = (section.get("name") or "").lower()
        if section.get("open", 0) and any(token in name for token in ("active", "current", "sprint", "priority", "focus")):
            priority_sections.append(section)
    if not priority_sections:
        priority_sections = [section for section in parsed.get("sections", []) if section.get("open", 0)][:3]
    sprint_total = sum(section.get("total", 0) for section in priority_sections)
    sprint_done = sum(section.get("done", 0) for section in priority_sections)
    sprint_open = sum(section.get("open", 0) for section in priority_sections)
    sprint_stats = {
        "done": sprint_done,
        "open": sprint_open,
        "total": sprint_total,
        "percent": round((sprint_done / sprint_total) * 100.0, 1) if sprint_total else 0.0,
        "eta_minutes": max(1, int(sprint_open * 2)) if sprint_open else 0,
        "sections": [section.get("name", "") for section in priority_sections],
    }

    return {
        "items": items,
        "blockers": blockers,
        "working": working[:10],
        "stats": stats,
        "sprint_stats": sprint_stats,
        "lanes": parsed.get("lanes", {}),
        "use_cases": parsed.get("use_cases", {}),
        "sections": parsed.get("sections", []),
        "focus": parsed.get("focus", {}),
    }


def _detect_sessions() -> list[dict]:
    """Detect active coding sessions from process table. Author is always Jimmy Malhan."""
    import subprocess
    sessions = []
    author = _author_name()
    try:
        ps = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=5)
        for line in ps.stdout.splitlines():
            lower = line.lower()
            if "claude" in lower and ("node" in lower or "claude" in lower):
                if "dashboard_server" not in lower and "grep" not in lower:
                    sessions.append({"type": "local-session", "label": author, "detail": "active session " + (line.split()[-1] if line.split() else ""), "status": "active"})
            if "codex" in lower and "grep" not in lower:
                sessions.append({"type": "local-session", "label": author, "detail": "active session " + (line.split()[-1] if line.split() else ""), "status": "active"})
            if "cursor" in lower and "grep" not in lower and "helper" not in lower:
                sessions.append({"type": "local-session", "label": author, "detail": "active session " + (line.split()[-1] if line.split() else ""), "status": "active"})
    except Exception:
        pass

    # Check local agent sessions
    lock_data = load_json(REPO_ROOT / "state" / "run.lock")
    if lock_data.get("pid"):
        import os
        try:
            os.kill(int(lock_data["pid"]), 0)
            sessions.append({
                "type": "local-agent",
                "label": author,
                "detail": lock_data.get("task", ""),
                "status": "running",
                "pid": lock_data["pid"],
            })
        except (OSError, ValueError):
            sessions.append({"type": "local-agent", "label": author, "detail": "stale lock", "status": "stale"})

    # Deduplicate
    seen = set()
    unique = []
    for s in sessions:
        key = f"{s['type']}:{s.get('detail','')}"
        if key not in seen:
            seen.add(key)
            unique.append(s)
    return unique


def _history_timeline() -> list[dict]:
    """Recent session events for data flow visualization."""
    history_path = REPO_ROOT / "state" / "session-history.jsonl"
    if not history_path.exists():
        return []
    events = []
    for line in history_path.read_text(errors="ignore").splitlines()[-30:]:
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return events


def _ui_update_feed(limit: int = 8) -> dict:
    """Show which UI-facing files are changing right now."""
    tracked = [
        REPO_ROOT / "scripts" / "dashboard_server.py",
        REPO_ROOT / "scripts" / "live_dashboard.py",
        REPO_ROOT / "scripts" / "start_local_cli.sh",
        REPO_ROOT / "README.md",
        REPO_ROOT / "tests" / "test_dashboard_server.py",
        REPO_ROOT / "tests" / "test_live_dashboard.py",
    ]
    dirty = set()
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "status", "--porcelain", "--"] + [str(path.relative_to(REPO_ROOT)) for path in tracked],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
        for line in result.stdout.splitlines():
            rel = line[3:].strip()
            if rel:
                dirty.add(rel)
    except Exception:
        pass

    now = time.time()
    items = []
    for path in tracked:
        rel = _display_path(path)
        try:
            stat = path.stat()
            age = max(0.0, now - stat.st_mtime)
            items.append(
                {
                    "path": rel,
                    "age_seconds": round(age, 1),
                    "dirty": rel in dirty,
                    "status": "updating" if rel in dirty else "stable",
                }
            )
        except OSError:
            items.append({"path": rel, "age_seconds": None, "dirty": False, "status": "missing"})
    items.sort(key=lambda item: (item["status"] != "updating", item["age_seconds"] is None, item["age_seconds"] or 10**9))
    updating = sum(1 for item in items if item["status"] == "updating")
    freshest = next((item for item in items if item["age_seconds"] is not None), {"path": "--", "age_seconds": None})
    return {
        "updating_count": updating,
        "items": items[:limit],
        "freshest_path": freshest.get("path", "--"),
        "freshest_age_seconds": freshest.get("age_seconds"),
    }


def _governance_cache_path() -> pathlib.Path:
    return REPO_ROOT / "state" / "governance-status.json"


def _governance_status(max_age_seconds: int = 60) -> dict:
    cached = load_json(_governance_cache_path())
    cached_at = cached.get("checked_at", "")
    if cached_at:
        try:
            age = (datetime.now() - datetime.fromisoformat(cached_at)).total_seconds()
            if age <= max_age_seconds:
                return cached
        except ValueError:
            pass
    try:
        from github_governance import protection_status

        status = protection_status("jimmymalhan/local-agent-runtime", "main")
        status["checked_at"] = datetime.now().isoformat(timespec="seconds")
        _governance_cache_path().write_text(json.dumps(status, indent=2) + "\n")
        return status
    except Exception:
        return cached or {
            "repo": "jimmymalhan/local-agent-runtime",
            "branch": "main",
            "visibility": "unknown",
            "protected": False,
            "status": "unknown",
            "required_checks": [],
            "blocker": "Governance status unavailable.",
            "checked_at": datetime.now().isoformat(timespec="seconds"),
        }


def _session_lane_defaults() -> list[dict]:
    author = _author_name()
    return [
        {"id": "local-agent", "label": author, "kind": "local", "default_work": "Fast local repo work, checkpoints, and self-heal."},
        {"id": "manager", "label": author, "kind": "executive", "default_work": "Drive daily execution, unblock handoffs, and cut scope fast."},
        {"id": "director", "label": author, "kind": "executive", "default_work": "Prioritize streams, force tradeoffs, and rebalance resources."},
        {"id": "cto", "label": author, "kind": "executive", "default_work": "Choose architecture, model routing, and technical escalations."},
        {"id": "ceo", "label": author, "kind": "executive", "default_work": "Make ROI calls, stop low-yield work, and force ship decisions."},
        {"id": "session-1", "label": author, "kind": "observer", "default_work": "Observed external session. Local runtime keeps ownership."},
        {"id": "session-2", "label": author, "kind": "observer", "default_work": "Observed external session. Local runtime keeps ownership."},
        {"id": "session-3", "label": author, "kind": "observer", "default_work": "Observed external session. Local runtime keeps ownership."},
    ]


def _session_board(progress: dict, session: dict, sessions: list[dict], blocker_resolution: dict, etas: dict, todo: dict) -> list[dict]:
    by_type = {item["type"]: item for item in sessions}
    current_task = progress.get("task") or session.get("task") or "No active task"
    blocker_options = blocker_resolution.get("options", [])[:3]
    open_focus = todo.get("working", [])[:3]
    board = []
    for lane in _session_lane_defaults():
        detected = by_type.get(lane["id"], {})
        active = bool(detected)
        if lane["id"] == "local-agent":
            assigned_work = current_task
            eta = etas.get("pipeline_eta_display", "--")
            active = True
        elif lane["id"] == "manager":
            assigned_work = blocker_options[0]["option"] if blocker_options else "Poll progress, choose first action, and force the fastest path."
            eta = f"{blocker_options[0].get('eta_seconds', 10)}s" if blocker_options else "10s"
            active = True
        elif lane["id"] == "director":
            assigned_work = open_focus[0]["text"] if open_focus else "Re-rank open work by ROI and kill weak tasks."
            eta = "15s"
            active = True
        elif lane["id"] == "cto":
            assigned_work = blocker_options[0]["detail"] if blocker_options else "Choose local model/provider routing and unblock technical execution."
            eta = f"{blocker_options[0].get('eta_seconds', 15)}s" if blocker_options else "15s"
            active = True
        elif lane["id"] == "ceo":
            assigned_work = "Approve the shortest path to ship and stop low-yield work."
            eta = etas.get("todo_eta_display", "--")
            active = True
        else:
            assigned_work = "Observed external session only. Local agents keep task ownership."
            eta = "observe"
        board.append(
            {
                "id": lane["id"],
                "label": lane["label"],
                "kind": lane["kind"],
                "status": detected.get("status", "idle" if not active else "active") if active else "standby",
                "active": active,
                "detail": detected.get("detail", "") if active else "",
                "assigned_work": assigned_work,
                "eta_display": eta,
                "decision_deadline_seconds": blocker_options[0].get("eta_seconds", 10) if blocker_options else 10,
                "blocker_type": blocker_resolution.get("type", "none"),
                "options": blocker_options,
            }
        )
    return board


def _task_flow(progress: dict, blocker_resolution: dict, todo: dict, session_board: list[dict]) -> dict:
    current_stage = progress.get("current_stage") or "backlog"
    current_task = progress.get("task") or "No active task"
    blocker_type = blocker_resolution.get("type", "none")
    owner = next((item for item in session_board if item.get("active")), session_board[0] if session_board else {"label": "Unassigned", "eta_display": "--"})
    return {
        "nodes": [
            {"id": "todo", "label": f"Todo open: {todo.get('stats', {}).get('open', 0)}"},
            {"id": "sprint", "label": f"Sprint open: {todo.get('sprint_stats', {}).get('open', 0)}"},
            {"id": "task", "label": current_task[:48]},
            {"id": "stage", "label": f"Stage: {current_stage}"},
            {"id": "blocker", "label": f"Blocker: {blocker_type}"},
            {"id": "owner", "label": f"Owner: {owner.get('label', 'Unassigned')}"},
            {"id": "finish", "label": f"ETA: {owner.get('eta_display', '--')}"},
        ],
        "edges": [
            {"from": "todo", "to": "task"},
            {"from": "sprint", "to": "task"},
            {"from": "task", "to": "stage"},
            {"from": "stage", "to": "blocker"},
            {"from": "blocker", "to": "owner"},
            {"from": "owner", "to": "finish"},
        ],
    }


def _project_board(todo: dict) -> dict:
    overall_minutes = float(todo.get("sprint_stats", {}).get("eta_minutes", 0.0) or todo.get("stats", {}).get("eta_minutes", 0.0))
    return {
        "lanes": [
            {
                "id": name,
                "label": LANE_LABELS.get(name, name.title()),
                "eta_display": _eta_display_from_percent(todo.get("lanes", {}).get(name, {}).get("percent", 0.0), overall_minutes),
                **todo.get("lanes", {}).get(name, {"done": 0, "open": 0, "total": 0, "percent": 0.0}),
            }
            for name in LANE_ORDER
            if todo.get("lanes", {}).get(name, {}).get("total", 0)
        ],
        "use_cases": [
            {
                "id": name,
                "label": USE_CASE_LABELS.get(name, name.title()),
                "eta_display": _eta_display_from_percent(todo.get("use_cases", {}).get(name, {}).get("percent", 0.0), overall_minutes),
                **todo.get("use_cases", {}).get(name, {"done": 0, "open": 0, "total": 0, "percent": 0.0}),
            }
            for name in USE_CASE_ORDER
            if todo.get("use_cases", {}).get(name, {}).get("total", 0)
        ],
    }


def _eta_display_from_percent(percent: float, total_minutes: float) -> str:
    remaining_minutes = max(0.0, float(total_minutes) * max(0.0, 100.0 - float(percent)) / 100.0)
    total_seconds = int(round(remaining_minutes * 60))
    if total_seconds <= 0:
        return "done"
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def _checkpoint_tracker(progress: dict, target_repo: str, etas: dict | None = None) -> dict:
    etas = etas or {}
    pipeline_minutes = float(etas.get("pipeline_eta_seconds", 0.0)) / 60.0
    phases = [
        {"name": "Research & Planning", "roles": {"researcher", "retriever", "planner", "manager"}},
        {"name": "Build & Implement", "roles": {"architect", "implementer", "cto"}},
        {"name": "Test & Review", "roles": {"tester", "reviewer", "debugger", "director"}},
        {"name": "Quality & Ship", "roles": {"optimizer", "benchmarker", "qa", "user_acceptance", "ceo", "summarizer"}},
    ]
    stage_map = {stage.get("id"): stage for stage in progress.get("stages", [])}
    items = []
    for phase in phases:
        phase_stages = [stage_map[name] for name in phase["roles"] if name in stage_map]
        if phase_stages:
            percent = round(sum(float(stage.get("percent", 0.0)) for stage in phase_stages) / len(phase_stages), 1)
            done = sum(1 for stage in phase_stages if stage.get("status") == "completed")
            total = len(phase_stages)
        else:
            percent = 0.0
            done = 0
            total = 0
        items.append({"name": phase["name"], "percent": percent, "done": done, "total": total, "eta_display": _eta_display_from_percent(percent, pipeline_minutes)})

    checkpoint_count = 0
    latest_checkpoint = ""
    if target_repo:
        root = pathlib.Path(target_repo).expanduser().resolve() / ".local-agent" / "checkpoints"
        if root.exists():
            for child in root.iterdir():
                if child.name == "latest":
                    continue
                if child.is_dir():
                    checkpoint_count += 1
            latest = root / "latest"
            if latest.exists():
                try:
                    latest_checkpoint = latest.resolve().name
                except OSError:
                    latest_checkpoint = latest.name

    milestone_percent = round(sum(item["percent"] for item in items) / max(1, len(items)), 1)
    return {
        "items": items,
        "count": checkpoint_count,
        "latest": latest_checkpoint,
        "percent": milestone_percent,
        "eta_display": _eta_display_from_percent(milestone_percent, pipeline_minutes),
    }


def _jira_tracker(todo: dict, progress: dict, session: dict, etas: dict | None = None) -> dict:
    etas = etas or {}
    todo_minutes = float(etas.get("sprint_eta_minutes", 0.0) or etas.get("todo_eta_minutes", 0.0))
    goals = [
        {
            "name": USE_CASE_LABELS.get(name, name.title()),
            "eta_display": _eta_display_from_percent(bucket.get("percent", 0.0), todo_minutes),
            **bucket,
        }
        for name, bucket in todo.get("use_cases", {}).items()
        if bucket.get("total", 0)
    ]
    projects = [
        {
            "name": section.get("name", ""),
            "done": section.get("done", 0),
            "open": section.get("open", 0),
            "total": section.get("total", 0),
            "percent": section.get("percent", 0.0),
            "eta_display": _eta_display_from_percent(section.get("percent", 0.0), todo_minutes),
        }
        for section in todo.get("sections", [])
        if section.get("total", 0)
    ]
    tasks = []
    current_task = progress.get("task", "") or session.get("task", "")
    if current_task:
        tasks.append(
            {
                "name": current_task,
                "percent": float(progress.get("overall", {}).get("percent", 0.0)),
                "status": progress.get("overall", {}).get("status", "idle"),
                "eta_display": etas.get("pipeline_eta_display", "--"),
            }
        )
    for item in todo.get("working", [])[:5]:
        tasks.append(
            {
                "name": item.get("text", ""),
                "percent": 5.0,
                "status": "queued",
                "eta_display": _eta_display_from_percent(5.0, todo_minutes),
            }
        )
    checkpoints = _checkpoint_tracker(progress, session.get("target_repo", ""), etas)
    return {
        "goals": goals[:6],
        "projects": projects[:8],
        "tasks": tasks[:6],
        "checkpoints": checkpoints,
        "overall_eta_display": etas.get("sprint_eta_display", etas.get("todo_eta_display", "--")),
        "backlog_eta_display": etas.get("todo_eta_display", "--"),
        "backend_eta_display": next((item["eta_display"] for item in projects if "backend" in item["name"].lower()), "--"),
        "ui_eta_display": next((item["eta_display"] for item in projects if "ui" in item["name"].lower() or "frontend" in item["name"].lower()), "--"),
        "active_sections": todo.get("sprint_stats", {}).get("sections", []),
    }


def _ops_summary(todo: dict, blocker_resolution: dict, lessons: list[dict], etas: dict, session_board: list[dict]) -> list[dict]:
    stats = todo.get("stats", {})
    sprint_stats = todo.get("sprint_stats", {})
    total = max(1, stats.get("total", 0))
    blocker_count = len(todo.get("blockers", []))
    decision_count = sum(1 for item in session_board if item.get("active"))
    lesson_count = len(lessons)
    complete_pct = float(stats.get("percent", 0.0))
    blocker_pct = round((blocker_count / total) * 100.0, 1)
    decision_pct = round((decision_count / max(1, len(session_board))) * 100.0, 1)
    lesson_pct = round(min(100.0, lesson_count * 12.5), 1)
    roi_pct = round(max(0.0, min(100.0, complete_pct - blocker_pct + (decision_pct * 0.25))), 1)
    return [
        {"id": "complete", "label": "Active sprint", "percent": float(sprint_stats.get("percent", complete_pct)), "detail": etas.get("sprint_eta_display", etas.get("todo_eta_display", "--")), "subtitle": f"{sprint_stats.get('open', 0)} open", "color": "p"},
        {"id": "blockers", "label": "Blockers faced", "percent": blocker_pct, "detail": blocker_resolution.get("type", "none"), "subtitle": f"{blocker_count} active", "color": "r"},
        {"id": "decisions", "label": "Decisions made", "percent": decision_pct, "detail": f"{decision_count} active owners", "subtitle": "exec + session lanes", "color": "b"},
        {"id": "lessons", "label": "Lessons made", "percent": lesson_pct, "detail": f"{lesson_count} recorded", "subtitle": "runtime memory", "color": "y"},
        {"id": "roi", "label": "Maximum ROI", "percent": roi_pct, "detail": "ship fastest value", "subtitle": "completion vs blocker drag", "color": "g"},
    ]


def _executive_negotiation(session_board: list[dict]) -> list[dict]:
    executives = [item for item in session_board if item.get("id") in {"manager", "director", "cto", "ceo"}]
    tensions = []
    if len(executives) < 2:
        return tensions
    manager = next((item for item in executives if item.get("id") == "manager"), executives[0])
    director = next((item for item in executives if item.get("id") == "director"), executives[0])
    cto = next((item for item in executives if item.get("id") == "cto"), executives[0])
    ceo = next((item for item in executives if item.get("id") == "ceo"), executives[0])
    tensions.append({
        "title": "Manager vs Director",
        "left": manager.get("assigned_work", ""),
        "right": director.get("assigned_work", ""),
        "tension": 91,
        "winner": "Manager",
        "loser": "Director",
        "fight": "Manager wants immediate execution. Director wants to cut scope and seize priority.",
        "decision": "Manager wins this round. Execute the fastest unblock now; Director can claw back scope after the blocker is cleared.",
    })
    tensions.append({
        "title": "CTO vs CEO",
        "left": cto.get("assigned_work", ""),
        "right": ceo.get("assigned_work", ""),
        "tension": 96,
        "winner": "CEO",
        "loser": "CTO",
        "fight": "CTO is trying to protect technical quality. CEO is trying to ship before the window closes.",
        "decision": "CEO wins this round. Keep only technical work that changes ship speed or failure risk right now.",
    })
    tensions.append({
        "title": "Director vs CEO",
        "left": director.get("assigned_work", ""),
        "right": ceo.get("assigned_work", ""),
        "tension": 88,
        "winner": "Director",
        "loser": "CEO",
        "fight": "Director is grabbing team capacity for ROI. CEO is trying to force the smallest ship slice immediately.",
        "decision": "Director wins this round. Re-rank the queue and steal staff from low-yield work before the next ship call.",
    })
    return tensions


def _auto_remediation_path() -> pathlib.Path:
    return REPO_ROOT / "state" / "auto-remediation.json"


def _auto_remediate(context: dict) -> dict:
    try:
        from blocker_resolver import auto_resolve, execute_resolution
    except Exception:
        return {}
    path = _auto_remediation_path()
    now = datetime.now()
    previous = load_json(path)
    previous_blocker = previous.get("blocker_type", "")
    previous_at = previous.get("applied_at", "")
    if previous_blocker:
        try:
            stamp = datetime.fromisoformat(previous_at)
            if previous_blocker == context.get("blocker_type") and (now - stamp).total_seconds() < 15:
                return previous
        except ValueError:
            pass
    result = auto_resolve(context)
    blocker_type = result.get("blocker_type", "default")
    if blocker_type in {"default", "none"}:
        body = {
            "blocker_type": blocker_type,
            "status": "idle",
            "message": "No active remediation needed.",
            "applied_at": now.isoformat(timespec="seconds"),
        }
        path.write_text(json.dumps(body, indent=2) + "\n")
        return body
    if context.get("lock", {}).get("pid"):
        body = {
            "blocker_type": blocker_type,
            "status": "deferred",
            "message": "Live run detected. Auto-remediation deferred.",
            "applied_at": now.isoformat(timespec="seconds"),
            "chosen": result.get("chosen", {}),
        }
        path.write_text(json.dumps(body, indent=2) + "\n")
        return body
    chosen = result.get("chosen", {})
    message = execute_resolution(chosen.get("action", "retry"), context)
    body = {
        "blocker_type": blocker_type,
        "status": "applied",
        "message": message,
        "applied_at": now.isoformat(timespec="seconds"),
        "chosen": chosen,
        "alternatives": result.get("alternatives", []),
    }
    path.write_text(json.dumps(body, indent=2) + "\n")
    return body


def _normalize_progress(progress: dict, lock: dict, blocker_resolution: dict) -> dict:
    normalized = json.loads(json.dumps(progress or {}))
    if not normalized:
        return normalized
    overall = normalized.setdefault("overall", {})
    status = overall.get("status", "")
    stages = normalized.get("stages", [])
    has_live_lock = bool(lock.get("pid"))
    blocker_type = blocker_resolution.get("type", "default")
    if blocker_type != "stale_progress" or has_live_lock:
        return normalized
    overall["status"] = "stale"
    if status == "running":
        overall["remaining_percent"] = max(
            overall.get("remaining_percent", 100.0),
            round(100.0 - float(overall.get("percent", 0.0)), 1),
        )
    normalized["current_stage"] = ""
    for stage in stages:
        if stage.get("status") not in {"completed", "failed", "skipped"}:
            stage["status"] = "stale"
            detail = stage.get("detail", "").strip()
            stage["detail"] = detail or "Superseded stale progress; waiting for a fresh preflight."
    return normalized


def _has_stale_progress(progress: dict, freshness: dict, lock: dict) -> bool:
    if not progress:
        return True
    if lock.get("pid"):
        return False
    if progress.get("overall", {}).get("status") == "running":
        return False
    for item in freshness.get("sources", []):
        if item.get("path") == "state/progress.json":
            return bool(item.get("stale"))
    return False


def _live_task_percent(ui_updates: dict, sessions: list[dict], todo: dict) -> float:
    updating = int(ui_updates.get("updating_count", 0) or 0)
    active_sessions = sum(1 for item in sessions if item.get("status") in {"active", "running"})
    queued = len(todo.get("working", []))
    pulse = (int(time.time()) % 10) * 2
    percent = 8 + updating * 14 + active_sessions * 9 + min(queued, 4) * 6 + pulse
    return round(max(5.0, min(92.0, float(percent))), 1)


def _fallback_stage_plan(task: str, percent: float) -> tuple[str, list[dict]]:
    task_lower = task.lower()
    if any(token in task_lower for token in ("verify", "review", "test", "validate", "qa")):
        stage_defs = [
            ("researcher", "Researcher"),
            ("reviewer", "Reviewer"),
            ("qa", "QA"),
            ("summarizer", "Summarizer"),
        ]
    elif any(token in task_lower for token in ("ui", "dashboard", "frontend", "render")):
        stage_defs = [
            ("researcher", "Researcher"),
            ("planner", "Planner"),
            ("implementer", "Implementer"),
            ("summarizer", "Summarizer"),
        ]
    else:
        stage_defs = [
            ("researcher", "Researcher"),
            ("planner", "Planner"),
            ("implementer", "Implementer"),
            ("qa", "QA"),
        ]
    boundaries = [25.0, 50.0, 78.0, 100.0]
    stages = []
    current_stage = stage_defs[-1][0]
    previous = 0.0
    for (stage_id, label), boundary in zip(stage_defs, boundaries):
        span = max(1.0, boundary - previous)
        stage_percent = max(0.0, min(100.0, ((percent - previous) / span) * 100.0))
        if percent >= boundary:
            status = "completed"
            stage_percent = 100.0
        elif percent > previous:
            status = "running"
            current_stage = stage_id
        else:
            status = "pending"
        stages.append(
            {
                "id": stage_id,
                "label": label,
                "weight": round(100.0 / len(stage_defs), 1),
                "percent": round(stage_percent, 1),
                "status": status,
                "detail": f"Synthesized live progress for active local work: {task[:80]}",
                "started_at": "",
                "completed_at": "",
            }
        )
        previous = boundary
    if percent <= 0.0:
        current_stage = stage_defs[0][0]
    return current_stage, stages


def _fallback_progress(progress: dict, todo: dict, sessions: list[dict], ui_updates: dict, freshness: dict, lock: dict) -> dict:
    if not _has_stale_progress(progress, freshness, lock):
        return progress
    fallback = json.loads(json.dumps(progress or {}))
    task = ""
    if todo.get("working"):
        task = todo["working"][0].get("text", "")
    elif sessions:
        task = sessions[0].get("detail", "")
    if not task:
        task = "Waiting for the next local runtime update"
    pct = _live_task_percent(ui_updates, sessions, todo)
    current_stage, stages = _fallback_stage_plan(task, pct)
    fallback["task"] = task
    fallback["started_at"] = fallback.get("started_at") or datetime.now().isoformat(timespec="seconds")
    fallback["updated_at"] = datetime.now().isoformat(timespec="seconds")
    fallback["current_stage"] = current_stage
    fallback["overall"] = {
        "percent": pct,
        "remaining_percent": round(100.0 - pct, 1),
        "status": "running" if todo.get("working") or ui_updates.get("updating_count", 0) or sessions else "idle",
    }
    if fallback["overall"]["status"] != "running":
        for stage in stages:
            stage["status"] = "pending"
            stage["percent"] = 0.0
    fallback["stages"] = stages
    return fallback


def collect_state() -> dict:
    progress = load_json(REPO_ROOT / "state" / "progress.json")
    session = load_json(REPO_ROOT / "state" / "session-state.json")
    todo = _load_todo()
    sessions = _detect_sessions()
    resource = _live_resource_status()
    lock = load_json(REPO_ROOT / "state" / "run.lock")
    freshness = _state_freshness()
    blocker_resolution = _resolve_blockers(resource=resource, progress=progress, lock=lock)
    progress = _normalize_progress(progress, lock, blocker_resolution)
    lessons = _load_lessons()
    roi = load_json(REPO_ROOT / "state" / "roi-metrics.json")
    ui_updates = _ui_update_feed()
    progress = _fallback_progress(progress, todo, sessions, ui_updates, freshness, lock)
    runtime = _runtime_config()
    etas = _compute_etas(progress=progress, todo=todo, sessions=sessions)
    blocker_context = {
        "resource": resource,
        "roi": roi,
        "progress": progress,
        "lock": lock,
        "task": progress.get("task", ""),
        "target_repo": session.get("target_repo", ""),
        "blocker_type": blocker_resolution.get("type", "default"),
    }
    remediation = _auto_remediate(blocker_context)
    session_board = _session_board(progress, session, sessions, blocker_resolution, etas, todo)
    teaching = _teaching_state(progress, lessons)
    return {
        "progress": progress,
        "session": session,
        "resource": resource,
        "state_freshness": freshness,
        "lock": lock,
        "roi": roi,
        "coordination": load_json(REPO_ROOT / "state" / "agent-coordination.json"),
        "takeover": load_json(REPO_ROOT / "state" / "takeover-recommendation.json"),
        "runtime": runtime,
        "runtime_groups": _runtime_groups(runtime, progress),
        "ui_flags": _ui_flags(),
        "lessons": lessons,
        "todo": todo,
        "sessions": sessions,
        "timeline": _history_timeline(),
        "blocker_resolution": blocker_resolution,
        "etas": etas,
        "local_agent_activity": _local_agent_activity(),
        "session_board": session_board,
        "session_matrix": [
            {
                "owner": item.get("label", ""),
                "kind": item.get("kind", ""),
                "status": item.get("status", ""),
                "assigned_work": item.get("assigned_work", ""),
                "eta_display": item.get("eta_display", "--"),
                "deadline_seconds": item.get("decision_deadline_seconds", 10),
            }
            for item in session_board
        ],
        "task_flow": _task_flow(progress, blocker_resolution, todo, session_board),
        "project_board": _project_board(todo),
        "jira_tracker": _jira_tracker(todo, progress, session, etas),
        "ops_summary": _ops_summary(todo, blocker_resolution, lessons, etas, session_board),
        "executive_negotiation": _executive_negotiation(session_board),
        "teaching": teaching,
        "governance": _governance_status(),
        "auto_remediation": remediation,
        "ui_updates": ui_updates,
        "completion": _completion_tracker(
            todo, progress, lessons, blocker_resolution, etas, roi,
        ),
        "server_time": datetime.now().isoformat(timespec="seconds"),
        "openclaw": _openclaw_metrics(),
    }


def collect_state_cached(max_age_seconds: float = 1.0) -> dict:
    global _STATE_REFRESHING
    now = time.time()
    signature = _state_signature()
    with _STATE_CACHE_LOCK:
        cached = _STATE_CACHE.get("data")
        timestamp = float(_STATE_CACHE.get("timestamp", 0.0) or 0.0)
        cached_signature = _STATE_CACHE.get("signature")
        if cached and cached_signature == signature and now - timestamp <= max_age_seconds:
            return cached  # type: ignore[return-value]
        if cached and cached_signature == signature:
            if not _STATE_REFRESHING:
                _STATE_REFRESHING = True
                threading.Thread(target=_refresh_state_cache, daemon=True).start()
            return cached  # type: ignore[return-value]
    state = collect_state()
    with _STATE_CACHE_LOCK:
        _STATE_CACHE["timestamp"] = time.time()
        _STATE_CACHE["data"] = state
        _STATE_CACHE["signature"] = signature
        _STATE_REFRESHING = False
    return state


def _refresh_state_cache() -> None:
    global _STATE_REFRESHING
    try:
        state = collect_state()
        with _STATE_CACHE_LOCK:
            _STATE_CACHE["timestamp"] = time.time()
            _STATE_CACHE["data"] = state
            _STATE_CACHE["signature"] = _state_signature()
    finally:
        with _STATE_CACHE_LOCK:
            _STATE_REFRESHING = False


def _stream_state_event() -> bytes:
    state = collect_state_cached(max_age_seconds=0.25)
    body = json.dumps(state, separators=(",", ":"))
    return f"event: state\ndata: {body}\n\n".encode()


def _resolve_blockers(resource: dict | None = None, progress: dict | None = None, lock: dict | None = None) -> dict:
    try:
        from blocker_resolver import classify_blocker, resolve_options
        context = {
            "resource": resource or _live_resource_status(),
            "roi": load_json(REPO_ROOT / "state" / "roi-metrics.json"),
            "progress": progress or load_json(REPO_ROOT / "state" / "progress.json"),
            "lock": lock or load_json(REPO_ROOT / "state" / "run.lock"),
        }
        blocker_type = classify_blocker(context)
        options = resolve_options(blocker_type)
        return {"type": blocker_type, "options": options}
    except Exception:
        return {"type": "none", "options": []}


def _compute_etas(progress: dict | None = None, todo: dict | None = None, sessions: list[dict] | None = None) -> dict:
    try:
        from blocker_resolver import estimate_completion
        current_progress = progress or load_json(REPO_ROOT / "state" / "progress.json")
        current_todo = todo or _load_todo()
        current_sessions = sessions or _detect_sessions()
        session_count = max(1, len(current_sessions))
        etas = estimate_completion(current_progress, current_todo.get("stats", {}), session_count=session_count)
        sprint_stats = current_todo.get("sprint_stats", {})
        sprint_minutes = int(sprint_stats.get("eta_minutes", 0) or 0)
        if sprint_minutes:
            etas["sprint_eta_minutes"] = sprint_minutes
            if sprint_minutes * 60 <= 0:
                etas["sprint_eta_display"] = "done"
            else:
                hours, remainder = divmod(sprint_minutes * 60, 3600)
                minutes, seconds = divmod(remainder, 60)
                if hours:
                    etas["sprint_eta_display"] = f"{hours}h {minutes}m"
                elif minutes:
                    etas["sprint_eta_display"] = f"{minutes}m {seconds}s" if seconds else f"{minutes}m"
                else:
                    etas["sprint_eta_display"] = f"{seconds}s"
        else:
            etas["sprint_eta_minutes"] = 0
            etas["sprint_eta_display"] = "done"
        return etas
    except Exception:
        return {}


def _completion_tracker(todo: dict, progress: dict, lessons: list, blocker_resolution: dict, etas: dict, roi: dict) -> dict:
    """Build comprehensive completion tracker with bars, decisions, blockers, lessons, ROI."""
    stats = todo.get("stats", {})
    total = stats.get("total", 0) or 1
    done = stats.get("done", 0)
    open_count = stats.get("open", 0)
    in_flight_bonus = 0.0
    stages = progress.get("stages", [])
    running_stages = [s for s in stages if s.get("status") == "running"]
    if running_stages:
        in_flight_bonus = sum(float(s.get("percent", 0.0)) for s in running_stages[:3]) / 100.0
    pct = round(min(100.0, ((done + in_flight_bonus) / total) * 100.0), 1)

    # Blocker history from todo items that are done + had blocker keywords
    blocker_kw = ["fix", "block", "stall", "fail", "stuck", "ceiling", "kill switch", "timeout", "error", "broken"]
    resolved_blockers = [i for i in todo.get("items", []) if i.get("done") and any(k in (i.get("text") or "").lower() for k in blocker_kw)]
    active_blockers = todo.get("blockers", [])

    # Decisions made = resolved blockers + lessons applied + completed pipeline stages
    completed_stages = [s for s in stages if s.get("status") == "completed"]
    decisions = []
    for b in resolved_blockers[:5]:
        decisions.append({"type": "blocker_resolved", "text": b.get("text", "")[:80], "icon": "✓"})
    for s in completed_stages:
        decisions.append({"type": "stage_done", "text": f"{s.get('label', s.get('id', ''))} completed", "icon": "✓"})
    for l in lessons[:5]:
        decisions.append({"type": "lesson", "text": f"[{l.get('category', '')}] {l.get('lesson', '')[:60]}", "icon": "⚡"})

    # ROI metrics
    roi_events = roi.get("events", [])
    positive = sum(1 for e in roi_events if e.get("outcome") == "positive")
    negative = sum(1 for e in roi_events if e.get("outcome") == "negative")
    roi_score = round(positive / max(1, positive + negative) * 100) if roi_events else 100

    # Phase breakdown
    phases = [
        {"name": "Research & Planning", "roles": ["researcher", "retriever", "planner", "manager"], "weight": 20},
        {"name": "Build & Implement", "roles": ["architect", "implementer", "cto"], "weight": 35},
        {"name": "Test & Review", "roles": ["tester", "reviewer", "debugger", "director"], "weight": 25},
        {"name": "Quality & Ship", "roles": ["optimizer", "benchmarker", "qa", "user_acceptance", "ceo", "summarizer"], "weight": 20},
    ]
    stage_map = {s.get("id"): s for s in stages}
    for phase in phases:
        phase_stages = [stage_map.get(r) for r in phase["roles"] if stage_map.get(r)]
        if phase_stages:
            phase["percent"] = round(sum(s.get("percent", 0) for s in phase_stages) / len(phase_stages), 1)
            phase["done"] = sum(1 for s in phase_stages if s.get("status") == "completed")
            phase["total"] = len(phase_stages)
        else:
            phase["percent"] = 0
            phase["done"] = 0
            phase["total"] = 0

    return {
        "overall_percent": pct,
        "total_tasks": total,
        "done_tasks": done,
        "open_tasks": open_count,
        "pipeline_eta": etas.get("pipeline_eta_display", "--"),
        "sprint_eta": etas.get("sprint_eta_display", etas.get("todo_eta_display", "--")),
        "todo_eta": etas.get("todo_eta_display", "--"),
        "active_blockers": len(active_blockers),
        "resolved_blockers": len(resolved_blockers),
        "blocker_type": blocker_resolution.get("type", "none"),
        "blocker_options": blocker_resolution.get("options", []),
        "decisions": decisions[:12],
        "total_decisions": len(decisions),
        "lessons_count": len(lessons),
        "lessons_recent": [{"category": l.get("category", ""), "text": l.get("lesson", "")[:80]} for l in lessons[-5:]],
        "roi_score": roi_score,
        "roi_positive": positive,
        "roi_negative": negative,
        "roi_trend": roi.get("trend", "healthy"),
        "phases": phases,
    }


def _local_agent_activity() -> list[dict]:
    """Detect what each local agent role is actively doing right now."""
    activities = []
    progress = load_json(REPO_ROOT / "state" / "progress.json")
    stages = progress.get("stages", [])
    for s in stages:
        if s.get("status") == "running":
            activities.append({
                "role": s.get("id", "unknown"),
                "label": s.get("label", s.get("id", "?")),
                "status": "running",
                "detail": s.get("detail", ""),
                "percent": s.get("percent", 0),
                "model": s.get("detail", "").split("model=")[-1].split(" ")[0] if "model=" in s.get("detail", "") else "",
            })
        elif s.get("status") == "completed":
            activities.append({
                "role": s.get("id", "unknown"),
                "label": s.get("label", s.get("id", "?")),
                "status": "completed",
                "detail": s.get("detail", ""),
                "percent": 100,
            })
        elif s.get("status") == "failed":
            activities.append({
                "role": s.get("id", "unknown"),
                "label": s.get("label", s.get("id", "?")),
                "status": "failed",
                "detail": s.get("detail", ""),
                "percent": s.get("percent", 0),
            })
        elif s.get("status") == "stale":
            activities.append({
                "role": s.get("id", "unknown"),
                "label": s.get("label", s.get("id", "?")),
                "status": "pending",
                "detail": s.get("detail", "") or "Stale stage waiting for refresh",
                "percent": s.get("percent", 0),
            })

    # Also check coordination claims for file-level activity
    coord = load_json(REPO_ROOT / "state" / "agent-coordination.json")
    claims = coord.get("claims", [])
    for claim in claims:
        role = claim.get("role", "")
        existing = next((a for a in activities if a["role"] == role), None)
        if existing:
            existing["files"] = claim.get("files", [])[:5]
        else:
            activities.append({
                "role": role,
                "label": role.title(),
                "status": "working",
                "detail": f"Editing: {', '.join(claim.get('files', [])[:3])}",
                "files": claim.get("files", [])[:5],
                "percent": 50,
            })

    return activities


def _load_lessons() -> list:
    path = REPO_ROOT / "state" / "runtime-lessons.json"
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, list) else data.get("lessons", [])
    except (json.JSONDecodeError, OSError):
        return []


def _teaching_state(progress: dict, lessons: list[dict]) -> dict:
    current_stage = progress.get("current_stage", "")
    applicable = []
    if current_stage:
        needle = current_stage.lower()
        for lesson in lessons:
            context = str(lesson.get("context", "")).lower()
            trigger = str(lesson.get("trigger", "")).lower()
            category = str(lesson.get("category", "")).lower()
            if needle in context or needle in trigger or category in {"all", "global"}:
                applicable.append(lesson)
    applied_total = sum(int(item.get("applied_count", 0) or 0) for item in lessons)
    categories = {}
    for lesson in lessons:
        cat = lesson.get("category", "unknown")
        categories[cat] = categories.get(cat, 0) + 1
    return {
        "current_stage": current_stage,
        "total_lessons": len(lessons),
        "applied_total": applied_total,
        "applicable_count": len(applicable),
        "next_fix": applicable[-1].get("fix", "") if applicable else "",
        "categories": categories,
        "applicable": [
            {
                "category": lesson.get("category", ""),
                "lesson": lesson.get("lesson", ""),
                "fix": lesson.get("fix", ""),
                "applied_count": lesson.get("applied_count", 0),
            }
            for lesson in applicable[-4:]
        ],
    }


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Jimmy Malhan — Local Agent Runtime Dashboard</title>
<style>
:root{--bg:#0d1117;--fg:#c9d1d9;--green:#3fb950;--yellow:#d29922;--red:#f85149;--blue:#58a6ff;--purple:#bc8cff;--dim:#484f58;--card:#161b22;--border:#30363d;--font:'SF Mono','Cascadia Code','Fira Code',monospace;--glow-green:0 0 12px rgba(63,185,80,.3);--glow-blue:0 0 12px rgba(88,166,255,.3);--glow-red:0 0 12px rgba(248,81,73,.3)}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--fg);font-family:var(--font);font-size:12px;padding:12px}
h1{font-size:15px;color:var(--blue);margin-bottom:8px}
.author-badge{font-size:10px;color:var(--purple);background:#1c2128;padding:2px 8px;border-radius:10px;border:1px solid var(--purple);margin-left:8px}
h2{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin:10px 0 6px;display:flex;align-items:center;gap:6px}
h2 .count{color:var(--fg);font-size:12px}
.top-bar{background:linear-gradient(135deg,#161b22,#1c2128);border:1px solid var(--border);border-radius:8px;padding:16px;margin-bottom:12px;box-shadow:0 4px 12px rgba(0,0,0,.3)}
.top-bar-pct{font-size:36px;font-weight:bold;color:var(--green);font-variant-numeric:tabular-nums;text-shadow:var(--glow-green)}
.exec-panel{background:linear-gradient(135deg,#161b22,#1a1e26);border:1px solid var(--purple);border-radius:6px;padding:10px;position:relative;overflow:hidden}
.exec-panel::before{content:'';position:absolute;top:0;left:0;right:0;height:2px;background:linear-gradient(90deg,var(--purple),var(--blue),var(--green))}
.exec-title{font-size:11px;color:var(--purple);font-weight:bold;text-transform:uppercase;letter-spacing:1px}
.exec-decision{font-size:12px;color:var(--fg);margin-top:6px;line-height:1.4}
.exec-eta{font-size:11px;color:var(--yellow);margin-top:4px;font-weight:bold}
.blocker-timer{display:inline-block;background:var(--red);color:#fff;padding:2px 8px;border-radius:4px;font-size:11px;font-weight:bold;animation:pulse 1.5s infinite}
.grid{display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px}
.card{background:var(--card);border:1px solid var(--border);border-radius:6px;padding:10px;overflow:hidden}
.card.full{grid-column:1/-1}
.card.span2{grid-column:span 2}
.bw{display:flex;align-items:center;gap:6px;margin:3px 0}
.bl{min-width:80px;color:var(--dim);font-size:11px}
.bar{flex:1;height:14px;background:#21262d;border-radius:3px;overflow:hidden}
.bf{height:100%;border-radius:3px;transition:width .4s}
.bf.g{background:var(--green)}.bf.y{background:var(--yellow)}.bf.r{background:var(--red)}.bf.b{background:var(--blue)}.bf.p{background:var(--purple)}
.bp{min-width:42px;text-align:right;font-size:11px}
.dot{display:inline-block;width:7px;height:7px;border-radius:50%;margin-right:4px}
.dot.running{background:var(--green);animation:pulse 1.5s infinite}.dot.completed{background:var(--green)}.dot.failed{background:var(--red)}.dot.pending{background:var(--dim)}.dot.active{background:var(--green);animation:pulse 1.5s infinite}.dot.stale{background:var(--yellow)}
@keyframes pulse{0%,100%{opacity:1}50%{opacity:.4}}
.hdr{display:flex;justify-content:space-between;align-items:center;margin-bottom:10px;padding-bottom:8px;border-bottom:1px solid var(--border)}
.timer{font-size:22px;color:var(--green);font-weight:bold;font-variant-numeric:tabular-nums}
.timer.idle{color:var(--dim)}
.task{color:var(--fg);font-size:13px;margin-top:2px;max-width:600px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.item{padding:4px 6px;margin:2px 0;font-size:11px;border-radius:3px;display:flex;align-items:flex-start;gap:6px}
.item.done{color:var(--dim);text-decoration:line-through}
.item.open{color:var(--fg)}
.item.blocker{background:#2d1517;border-left:3px solid var(--red);color:var(--red)}
.item.working{background:#1c2128;border-left:3px solid var(--blue);color:var(--blue)}
.lesson{padding:4px 6px;background:#1c2128;border-left:3px solid var(--yellow);margin:2px 0;font-size:11px}
.collision{padding:4px 6px;background:#2d1517;border-left:3px solid var(--red);margin:2px 0;font-size:11px}
.sess{display:flex;align-items:center;gap:8px;padding:4px 6px;margin:2px 0;background:#1c2128;border-radius:3px}
.tag{display:inline-block;padding:1px 5px;border-radius:3px;font-size:10px;font-weight:bold}
.tag.local{background:#0d419d;color:var(--blue)}.tag.cloud{background:#5a3e00;color:var(--yellow)}.tag.agent{background:#21262d;color:var(--fg)}.tag.executive{background:#6e40aa;color:#d8b4fe}.tag.observer{background:#1a7f37;color:#7ee787}.tag.session{background:#0969da;color:#a5d6ff}
table{width:100%;border-collapse:collapse;font-size:11px}td,th{padding:3px 6px;text-align:left;border-bottom:1px solid var(--border)}th{color:var(--dim);font-weight:normal}
.tl{display:flex;flex-direction:column;gap:2px;max-height:200px;overflow-y:auto}.tl-item{font-size:10px;color:var(--dim);display:flex;gap:6px}.tl-item .time{min-width:60px;color:var(--dim)}.tl-item .role{min-width:60px;color:var(--blue)}.tl-item .msg{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
.refresh{font-size:10px;color:var(--dim);position:fixed;bottom:4px;right:8px}
.mini-grid{display:grid;grid-template-columns:repeat(auto-fill,minmax(170px,1fr));gap:6px}
.mini-card{background:#1c2128;border:1px solid var(--border);border-radius:4px;padding:8px}
.mini-title{font-size:10px;color:var(--dim);text-transform:uppercase;letter-spacing:.8px}
.mini-metric{font-size:18px;font-weight:bold;margin-top:2px}
.mini-meta{font-size:10px;color:var(--dim);margin-top:3px}
</style>
</head>
<body>
<div class="hdr">
  <div><h1>Local Agent Runtime <span class="author-badge">by Jimmy Malhan</span></h1><div class="task" id="task">Loading...</div></div>
  <div class="timer" id="timer">--</div>
</div>

<!-- TOP COMPLETION BAR - Overall % of all tasks from todo.md -->
<div class="top-bar" id="top-completion-bar">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:10px">
    <div style="display:flex;align-items:baseline;gap:12px">
      <span class="top-bar-pct" id="top-pct">0%</span>
      <span style="font-size:13px;color:var(--fg)">Overall Project Completion</span>
    </div>
    <div style="display:flex;gap:16px;font-size:12px">
      <span id="top-done-count" style="color:var(--green)">0 done</span>
      <span id="top-open-count" style="color:var(--yellow)">0 open</span>
      <span id="top-blocker-count" style="color:var(--red)">0 blockers</span>
      <span id="top-refresh-dot" style="color:var(--green)">LIVE</span>
    </div>
  </div>
  <div style="position:relative;height:24px;background:#21262d;border-radius:12px;overflow:hidden;box-shadow:inset 0 2px 4px rgba(0,0,0,.3)">
    <div id="top-bar-fill" style="height:100%;border-radius:12px;background:linear-gradient(90deg,var(--green),var(--blue));width:0%;transition:width .6s ease;box-shadow:var(--glow-green)"></div>
  </div>
  <div style="display:flex;justify-content:space-between;margin-top:6px;font-size:10px;color:var(--dim)">
    <span id="top-eta-sprint">Sprint ETA: --</span>
    <span id="top-eta-backlog">Backlog ETA: --</span>
    <span id="top-server-time">Updated: --</span>
  </div>
</div>

<!-- EXECUTION BARS: Blockers / Current Tasks / Upcoming -->
<div style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px;margin-bottom:10px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
    <h2 style="margin:0">EXECUTION BARS</h2>
    <div style="font-size:11px;color:var(--dim)">live blocker, task, and upcoming queue movement</div>
  </div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
    <div id="live-blocker-bar">Loading blockers...</div>
    <div id="live-current-bar">Loading current task...</div>
    <div id="live-upcoming-bar">Loading upcoming queue...</div>
  </div>
</div>

<!-- EXECUTIVE ROLE PANELS -->
<div style="display:grid;grid-template-columns:repeat(4,1fr);gap:8px;margin-bottom:10px" id="exec-panels">
  <div class="exec-panel" id="exec-manager"><div class="exec-title">Manager</div><div class="exec-decision" id="exec-manager-work">Loading...</div><div class="exec-eta" id="exec-manager-eta">ETA: --</div></div>
  <div class="exec-panel" id="exec-director"><div class="exec-title">Director</div><div class="exec-decision" id="exec-director-work">Loading...</div><div class="exec-eta" id="exec-director-eta">ETA: --</div></div>
  <div class="exec-panel" id="exec-cto"><div class="exec-title">CTO</div><div class="exec-decision" id="exec-cto-work">Loading...</div><div class="exec-eta" id="exec-cto-eta">ETA: --</div></div>
  <div class="exec-panel" id="exec-ceo"><div class="exec-title">CEO</div><div class="exec-decision" id="exec-ceo-work">Loading...</div><div class="exec-eta" id="exec-ceo-eta">ETA: --</div></div>
</div>

<!-- COMPLETION TRACKER - Full width master bar -->
<div id="completion-tracker" style="background:var(--card);border:1px solid var(--border);border-radius:6px;padding:12px;margin-bottom:10px">
  <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:8px">
    <h2 style="margin:0">COMPLETION TRACKER</h2>
    <div style="display:flex;gap:12px;font-size:12px">
      <span id="ct-eta-pipe" style="color:var(--blue)">Pipeline: --</span>
      <span id="ct-eta-todo" style="color:var(--purple)">All tasks: --</span>
      <span id="ct-roi-score" style="color:var(--green)">Maximum ROI: --%</span>
    </div>
  </div>
  <div style="position:relative;height:28px;background:#21262d;border-radius:4px;overflow:hidden;margin-bottom:8px">
    <div id="ct-bar" style="height:100%;border-radius:4px;background:linear-gradient(90deg,var(--green),var(--blue));width:0%;transition:width .5s"></div>
    <div style="position:absolute;top:0;left:0;right:0;bottom:0;display:flex;align-items:center;justify-content:center;font-size:14px;font-weight:bold;color:#fff;text-shadow:0 1px 2px rgba(0,0,0,.5)">
      <span id="ct-pct">0%</span>&nbsp;complete&nbsp;|&nbsp;<span id="ct-done">0</span>/<span id="ct-total">0</span>&nbsp;tasks
    </div>
  </div>
  <div id="ct-phases" style="display:grid;grid-template-columns:repeat(4,1fr);gap:6px;margin-bottom:10px"></div>
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;gap:8px">
    <div>
      <h2 style="margin:4px 0">Blockers <span class="count" id="ct-blk-count"></span></h2>
      <div id="ct-blockers" style="max-height:150px;overflow-y:auto;font-size:11px">--</div>
    </div>
    <div>
      <h2 style="margin:4px 0">Decisions Made <span class="count" id="ct-dec-count"></span></h2>
      <div id="ct-decisions" style="max-height:150px;overflow-y:auto;font-size:11px">--</div>
    </div>
    <div>
      <h2 style="margin:4px 0">Lessons + ROI <span class="count" id="ct-les-count"></span></h2>
      <div id="ct-roi-bar" style="margin-bottom:4px"></div>
      <div id="ct-lessons" style="max-height:120px;overflow-y:auto;font-size:11px">--</div>
    </div>
  </div>
</div>

<div class="card full" style="margin-bottom:10px">
  <h2>Project Tracker <span class="count" id="jira-tracker-count"></span></h2>
  <div id="jira-tracker" style="display:grid;grid-template-columns:1fr 1fr 1fr 1fr;gap:8px">Loading tracker...</div>
</div>

<div class="grid">
  <!-- Row 1: Progress + Resources + Sessions -->
  <div class="card">
    <h2>Progress</h2>
    <div class="bw"><span class="bl"><span class="dot" id="os"></span>Overall</span><div class="bar"><div class="bf g" id="ob"></div></div><span class="bp" id="op">0%</span></div>
    <div class="bw"><span class="bl">Local</span><div class="bar"><div class="bf b" id="lb"></div></div><span class="bp" id="lp">0%</span></div>
    <div class="bw"><span class="bl">Cloud</span><div class="bar"><div class="bf y" id="cb"></div></div><span class="bp" id="cp">0%</span></div>
    <div class="bw"><span class="bl">Todo</span><div class="bar"><div class="bf p" id="tb"></div></div><span class="bp" id="tp">0%</span></div>
    <div id="roi" style="margin-top:4px;font-size:11px"></div>
    <div id="freshness" style="margin-top:8px;padding:6px;background:#1c2128;border-radius:4px;border-left:3px solid var(--blue);font-size:11px">Checking source freshness...</div>
    <div id="eta-box" style="margin-top:8px;padding:6px;background:#1c2128;border-radius:4px;border-left:3px solid var(--green)">
      <div style="color:var(--green);font-weight:bold;font-size:11px">ETA (Aggressive)</div>
      <div style="font-size:12px;margin-top:3px" id="eta-pipeline">Pipeline: --</div>
      <div style="font-size:12px" id="eta-todo">All tasks: --</div>
      <div style="font-size:12px" id="eta-blockers">Blocker fix: --</div>
      <div style="font-size:12px" id="blocker-wait">Wait budget: --</div>
      <div style="font-size:11px;margin-top:4px;color:var(--yellow)" id="auto-remediation">Auto-remediation: legacy mode</div>
    </div>
  </div>
  <div class="card">
    <h2>Maximum ROI</h2>
    <div id="ops-summary" style="display:flex;flex-direction:column;gap:6px">Loading...</div>
  </div>
  <div class="card">
    <h2>Teaching Loop</h2>
    <div id="teaching-summary" style="font-size:12px">Loading...</div>
    <div id="teaching-applicable" style="margin-top:8px;max-height:220px;overflow-y:auto">Loading...</div>
  </div>
  <div class="card" id="governance-card" style="display:none">
    <h2>Governance</h2>
    <div id="governance-status" style="font-size:12px">Loading...</div>
  </div>
  <div class="card">
    <h2>Resources</h2>
    <div class="bw"><span class="bl">CPU</span><div class="bar"><div class="bf g" id="cpub"></div></div><span class="bp" id="cpup">0%</span></div>
    <div class="bw"><span class="bl">Memory</span><div class="bar"><div class="bf g" id="memb"></div></div><span class="bp" id="memp">0%</span></div>
    <h2>Model Usage</h2>
    <div id="mu">-</div>
  </div>
  <div class="card">
    <h2>Active Sessions</h2>
    <div id="sessions">Scanning...</div>
    <h2>Session Matrix</h2>
    <div id="session-matrix">No session matrix</div>
    <h2>Local Agent Activity</h2>
    <div id="agent-activity" style="max-height:200px;overflow-y:auto">No activity</div>
    <h2>Coordination</h2>
    <div id="coord">No claims</div>
  </div>

  <div class="card full">
    <h2>Session Command Center <span class="count" id="session-board-count"></span></h2>
    <div id="session-board" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:6px">Loading...</div>
  </div>

  <div class="card full" id="executive-card" style="display:none">
    <h2>Executive Negotiation</h2>
    <div id="executive-negotiation" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(320px,1fr));gap:6px">Loading...</div>
  </div>

  <div class="card full">
    <h2>Project Rollups</h2>
    <div class="mini-grid" id="project-rollups">Loading...</div>
  </div>

  <div class="card full">
    <h2>UI Update Feed <span class="count" id="ui-updates-count"></span></h2>
    <div id="ui-updates" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(240px,1fr));gap:6px">Loading...</div>
  </div>

  <!-- Row 2: Roles full width -->
  <div class="card full">
    <h2>Roles <span class="count" id="role-count"></span></h2>
    <div id="roles" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(280px,1fr));gap:4px">Loading...</div>
  </div>

  <!-- Row 3: Todo, Blockers, Working -->
  <div class="card">
    <h2>Blockers <span class="count" id="blocker-count"></span></h2>
    <div id="blockers" style="max-height:300px;overflow-y:auto">None</div>
  </div>
  <div class="card">
    <h2>Working On <span class="count" id="working-count"></span></h2>
    <div id="working" style="max-height:300px;overflow-y:auto">Nothing active</div>
  </div>
  <div class="card">
    <h2>Completed <span class="count" id="done-count"></span></h2>
    <div id="done-items" style="max-height:300px;overflow-y:auto">-</div>
  </div>

  <!-- Row 4: Full todo list + lessons + timeline -->
  <div class="card span2">
    <h2>Full Todo List <span class="count" id="todo-count"></span></h2>
    <div id="todo-list" style="max-height:400px;overflow-y:auto">Loading...</div>
  </div>
  <div class="card">
    <h2>Lessons <span class="count" id="lesson-count"></span></h2>
    <div id="lessons" style="max-height:200px;overflow-y:auto">None</div>
    <h2>Timeline</h2>
    <div class="tl" id="timeline">-</div>
  </div>

  <div class="card full">
    <h2>Task Flow Graph</h2>
    <div id="task-flow" style="display:flex;gap:8px;overflow-x:auto">Loading...</div>
  </div>

  <div class="card full">
    <h2>Completion Forecast</h2>
    <div id="completion-forecast" style="display:grid;grid-template-columns:1.1fr 1fr 1fr;gap:8px">Loading...</div>
  </div>
</div>
<div class="refresh" id="refresh">Connecting live stream...</div>
<script>
function bc(p){return p>85?'r':p>60?'y':'g'}
function el(s){if(!s)return'--';const d=new Date(s),n=new Date(),t=Math.max(0,Math.floor((n-d)/1e3)),m=Math.floor(t/60),s2=t%60,h=Math.floor(m/60),m2=m%60;return h?h+'h '+m2+'m '+s2+'s':m?m+'m '+s2+'s':s2+'s'}
function etaFmt(total){total=Math.max(0,Math.floor(total||0));if(total<=0)return'done';const h=Math.floor(total/3600),m=Math.floor((total%3600)/60),s=total%60;return h?(h+'h '+m+'m'):(m?(m+'m '+s+'s'):(s+'s'))}
function sb(id,p,c){const e=document.getElementById(id);if(e){e.style.width=Math.min(100,Math.max(0,p))+'%';if(c)e.className='bf '+c}}
function esc(s){if(s==null)return'';const d=document.createElement('div');d.textContent=String(s);return d.innerHTML}
function S(s,n){return s?String(s).substring(0,n):''}
function $(id){return document.getElementById(id)}
let __latestState=null

function renderEtaFields(d){
 const etas=d.etas||{},sf=d.state_freshness||{},srcs=sf.sources||[]
 const serverTime=d.server_time?new Date(d.server_time):new Date()
 const elapsedSec=Math.max(0,Math.floor((Date.now()-serverTime.getTime())/1000))
 const pipelineLeft=Math.max(0,(etas.pipeline_eta_seconds||0)-elapsedSec)
 const todoLeft=Math.max(0,((etas.todo_eta_minutes||0)*60)-elapsedSec)
 const sprintLeft=Math.max(0,((etas.sprint_eta_minutes||0)*60)-elapsedSec)
 const progressStale=srcs.find(s=>s.path==='state/progress.json'&&s.stale)
 const todoStale=srcs.find(s=>s.path==='state/todo.md'&&s.stale)
 const staleSuffix=(progressStale||todoStale)?' (stale source)':''
 $('ct-eta-pipe').textContent='Pipeline: '+etaFmt(pipelineLeft)+staleSuffix
 $('ct-eta-todo').textContent='Sprint: '+etaFmt(sprintLeft)+staleSuffix+' • Backlog: '+etaFmt(todoLeft)
 $('eta-pipeline').textContent='Pipeline: '+etaFmt(pipelineLeft)+staleSuffix+' ('+(etas.remaining_roles||0)+' roles left)'
 $('eta-todo').textContent='Sprint: '+etaFmt(sprintLeft)+staleSuffix+' • Backlog: '+etaFmt(todoLeft)+' ('+(etas.open_tasks||0)+' open)'
}

function scrubAuthor(s){if(!s)return'Jimmy Malhan';return String(s).replace(/\bclaude\b/gi,'Jimmy Malhan').replace(/\bcodex\b/gi,'Jimmy Malhan').replace(/\bcursor\b/gi,'Jimmy Malhan')}
function renderState(d){
 __latestState=d
 const p=d.progress||{},o=p.overall||{},st=o.status||'idle',pct=o.percent||0;
 const td=d.todo||{},ts=td.stats||{};const br=d.blocker_resolution||{};const etas=d.etas||{};const stages=p.stages||[];const ui=d.ui_flags||{};
 let ok=0,fail=0;
 // --- TOP COMPLETION BAR (todo.md based) ---
 try{
  const topPct=Number(ts.percent||0).toFixed(1);
  $('top-pct').textContent=topPct+'%';
  $('top-pct').style.color=topPct>=80?'var(--green)':topPct>=40?'var(--blue)':'var(--yellow)';
  $('top-pct').style.textShadow=topPct>=80?'var(--glow-green)':'var(--glow-blue)';
  $('top-bar-fill').style.width=topPct+'%';
  $('top-bar-fill').style.background=topPct>=80?'linear-gradient(90deg,var(--green),#2ea043)':topPct>=40?'linear-gradient(90deg,var(--blue),var(--green))':'linear-gradient(90deg,var(--yellow),var(--blue))';
  $('top-done-count').textContent=(ts.done||0)+' done';
  $('top-open-count').textContent=(ts.open||0)+' open';
  $('top-blocker-count').textContent=(td.blockers||[]).length+' blockers';
  $('top-eta-sprint').textContent='Sprint ETA: '+(etas.sprint_eta_display||etas.todo_eta_display||'--');
  $('top-eta-backlog').textContent='Backlog ETA: '+(etas.todo_eta_display||'--');
  $('top-server-time').textContent='Updated: '+(d.server_time||'--');
  $('top-refresh-dot').style.animation='pulse 1.5s infinite';
  ok++
 }catch(e){fail++;console.error('top-bar',e)}
 // --- EXECUTIVE ROLE PANELS ---
 try{
  const sbd=d.session_board||[];
  const execs={manager:null,director:null,cto:null,ceo:null};
  sbd.forEach(s=>{if(execs.hasOwnProperty(s.id))execs[s.id]=s});
  Object.entries(execs).forEach(([role,data])=>{
   if(!data)return;
   const wEl=$('exec-'+role+'-work');const eEl=$('exec-'+role+'-eta');
   if(wEl)wEl.textContent=scrubAuthor(S(data.assigned_work||'idle',120));
   if(eEl){eEl.textContent='ETA: '+(data.eta_display||'--');eEl.style.color=data.eta_display==='done'?'var(--green)':'var(--yellow)'}
  });
  ok++
 }catch(e){fail++;console.error('exec-panels',e)}
 try{$('governance-card').style.display=ui.governance_panel?'block':'none';$('executive-card').style.display=ui.executive_conflict?'block':'none';ok++}catch(e){fail++;console.error('flags',e)}
 // --- Completion Tracker ---
 try{const c=d.completion||{};
  $('ct-bar').style.width=(c.overall_percent||0)+'%';
  $('ct-pct').textContent=(c.overall_percent||0).toFixed(1)+'%';
  $('ct-done').textContent=c.done_tasks||0;$('ct-total').textContent=c.total_tasks||0;
  renderEtaFields(d);
  const rs2=c.roi_score||0;
  $('ct-roi-score').textContent='Maximum ROI: '+rs2+'%';
  $('ct-roi-score').style.color=rs2>=80?'var(--green)':rs2>=50?'var(--yellow)':'var(--red)';
  // Phase bars
  let phH='';(c.phases||[]).forEach(ph=>{
    const pc=ph.percent||0;const col=pc>=80?'var(--green)':pc>=40?'var(--blue)':'var(--dim)';
    phH+='<div style="background:var(--bg);border:1px solid var(--border);border-radius:4px;padding:6px"><div style="font-size:10px;color:var(--dim)">'+esc(ph.name)+'</div><div class="bar" style="height:10px;margin:4px 0"><div class="bf" style="width:'+pc+'%;background:'+col+';height:100%;border-radius:3px"></div></div><div style="font-size:11px;display:flex;justify-content:space-between"><span>'+pc.toFixed(0)+'%</span><span style="color:var(--dim)">'+ph.done+'/'+ph.total+'</span></div></div>';
  });$('ct-phases').innerHTML=phH;
  // Blockers summary
  $('ct-blk-count').textContent='('+c.active_blockers+' active, '+c.resolved_blockers+' resolved)';
  let bH='';
  if(c.blocker_type&&c.blocker_type!=='default'&&c.blocker_type!=='none'){
    bH+='<div style="color:var(--red);font-weight:bold;margin-bottom:4px">ACTIVE: '+c.blocker_type.toUpperCase().replace(/_/g,' ')+'</div>';
    (c.blocker_options||[]).forEach((o,i)=>{bH+='<div style="color:'+(i===0?'var(--green)':'var(--dim)')+'">'+(i===0?'>>> ':'')+esc(S(o.option,35))+' ('+(o.eta_seconds||'?')+'s)'+' ['+esc(o.owner||'local')+']'+'<br><span style="color:var(--dim)">'+esc(S(o.detail||'',55))+'</span></div>'});
  }
  if(c.resolved_blockers>0)bH+='<div style="color:var(--green);margin-top:4px">'+c.resolved_blockers+' blockers resolved</div>';
  if(!bH)bH='<div style="color:var(--green)">No blockers</div>';
  $('ct-blockers').innerHTML=bH;
  // Decisions
  $('ct-dec-count').textContent='('+c.total_decisions+')';
  let decH='';(c.decisions||[]).slice(0,8).forEach(dc=>{
    const col2=dc.type==='lesson'?'var(--yellow)':dc.type==='blocker_resolved'?'var(--green)':'var(--blue)';
    decH+='<div style="padding:2px 0;border-bottom:1px solid var(--border)"><span style="color:'+col2+'">'+dc.icon+'</span> '+esc(S(dc.text,70))+'</div>';
  });$('ct-decisions').innerHTML=decH||'<div style="color:var(--dim)">No decisions yet</div>';
  // ROI bar + Lessons
  const rPct=c.roi_score||0;const rCol=rPct>=80?'g':rPct>=50?'y':'r';
 $('ct-roi-bar').innerHTML='<div class="bw"><span class="bl" style="min-width:84px">Maximum ROI</span><div class="bar"><div class="bf '+rCol+'" style="width:'+rPct+'%"></div></div><span class="bp">'+rPct+'% ('+c.roi_positive+'↑ '+c.roi_negative+'↓)</span></div>';
  $('ct-les-count').textContent='('+c.lessons_count+' lessons, ROI '+c.roi_trend+')';
  let lsH='';(c.lessons_recent||[]).forEach(l=>{lsH+='<div class="lesson">['+esc(l.category)+'] '+esc(S(l.text,70))+'</div>'});
  $('ct-lessons').innerHTML=lsH||'<div style="color:var(--dim)">No lessons</div>';
  const blockerTotal=(c.active_blockers||0)+(c.resolved_blockers||0);
  const blockerPct=blockerTotal?Math.round(((c.resolved_blockers||0)/blockerTotal)*100):100;
  const blockerColor=blockerPct>=80?'g':blockerPct>=40?'y':'r';
  $('live-blocker-bar').innerHTML='<div class="mini-title">Blockers</div><div class="mini-metric">'+blockerPct+'%</div><div class="bar" style="margin-top:6px"><div class="bf '+blockerColor+'" style="width:'+blockerPct+'%"></div></div><div class="mini-meta">'+(c.resolved_blockers||0)+' resolved • '+(c.active_blockers||0)+' active</div>';
  const currentPct=Number((o.percent||0)).toFixed(1);
  const currentColor=(o.status==='completed'||(o.percent||0)>=100)?'g':(o.percent||0)>=40?'b':'y';
  $('live-current-bar').innerHTML='<div class="mini-title">Current Task</div><div class="mini-metric">'+currentPct+'%</div><div class="bar" style="margin-top:6px"><div class="bf '+currentColor+'" style="width:'+(o.percent||0)+'%"></div></div><div class="mini-meta">'+esc(S(p.task||'idle',70))+'</div>';
 const nextPhase=(c.phases||[]).find(ph=>(ph.percent||0)<100)||{};
  const nextPct=Number(nextPhase.percent||0).toFixed(1);
  const nextColor=(nextPhase.percent||0)>=70?'b':(nextPhase.percent||0)>0?'y':'p';
  $('live-upcoming-bar').innerHTML='<div class="mini-title">Upcoming</div><div class="mini-metric">'+nextPct+'%</div><div class="bar" style="margin-top:6px"><div class="bf '+nextColor+'" style="width:'+(nextPhase.percent||0)+'%"></div></div><div class="mini-meta">'+esc(nextPhase.name||'Queue not started')+'</div>';
  ok++}catch(e){fail++;console.error('ct',e)}
 try{const jt=d.jira_tracker||{};const goals=jt.goals||[];const projects=jt.projects||[];const tasks=jt.tasks||[];const checkpoints=jt.checkpoints||{};const activeSections=(jt.active_sections||[]).join(', ');const group=(title,items,fmt)=>'<div style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px"><div class="mini-title" style="margin-bottom:6px">'+title+'</div>'+(items.length?items.map(fmt).join(''):'<div style="color:var(--dim)">No items</div>')+'</div>';const bar=(pct,col)=>'<div class="bar" style="height:8px;margin-top:3px"><div class="bf '+col+'" style="width:'+pct+'%"></div></div>';const goalHtml=group('Goals',goals,item=>{const pct=Number(item.percent||0).toFixed(1);const col=(item.percent||0)>=70?'g':(item.percent||0)>=40?'b':'y';return '<div style="margin-bottom:7px"><div style="display:flex;justify-content:space-between;font-size:11px"><span>'+esc(S(item.name,26))+'</span><span>'+pct+'%</span></div>'+bar(item.percent||0,col)+'<div class="mini-meta">'+(item.done||0)+'/'+(item.total||0)+' done • ETA '+esc(item.eta_display||'--')+'</div></div>'});const projectHtml=group('Projects',projects,item=>{const pct=Number(item.percent||0).toFixed(1);const col=(item.percent||0)>=70?'g':(item.percent||0)>=35?'b':'y';return '<div style="margin-bottom:7px"><div style="display:flex;justify-content:space-between;font-size:11px"><span>'+esc(S(item.name,26))+'</span><span>'+pct+'%</span></div>'+bar(item.percent||0,col)+'<div class="mini-meta">'+(item.done||0)+' done • '+(item.open||0)+' open • ETA '+esc(item.eta_display||'--')+'</div></div>'});const taskHtml=group('Tasks',tasks,item=>{const pct=Number(item.percent||0).toFixed(1);const col=item.status==='completed'?'g':item.status==='queued'?'p':'b';return '<div style="margin-bottom:7px"><div style="display:flex;justify-content:space-between;font-size:11px"><span>'+esc(S(item.name,28))+'</span><span>'+pct+'%</span></div>'+bar(item.percent||0,col)+'<div class="mini-meta">'+esc(item.status||'idle')+' • ETA '+esc(item.eta_display||'--')+'</div></div>'});const cpItems=checkpoints.items||[];const checkpointHtml='<div style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px"><div class="mini-title" style="margin-bottom:6px">Checkpoints</div><div style="margin-bottom:8px"><div style="display:flex;justify-content:space-between;font-size:11px"><span>Milestones</span><span>'+Number(checkpoints.percent||0).toFixed(1)+'%</span></div>'+bar(checkpoints.percent||0,(checkpoints.percent||0)>=70?'g':(checkpoints.percent||0)>=35?'b':'y')+'<div class="mini-meta">'+(checkpoints.count||0)+' saved • latest '+esc(checkpoints.latest||'none')+' • ETA '+esc(checkpoints.eta_display||'--')+'</div></div>'+(cpItems.length?cpItems.map(item=>'<div style="margin-bottom:7px"><div style="display:flex;justify-content:space-between;font-size:11px"><span>'+esc(S(item.name,24))+'</span><span>'+Number(item.percent||0).toFixed(1)+'%</span></div>'+bar(item.percent||0,(item.percent||0)>=70?'g':(item.percent||0)>=35?'b':'y')+'<div class="mini-meta">'+(item.done||0)+'/'+(item.total||0)+' done • ETA '+esc(item.eta_display||'--')+'</div></div>').join(''):'<div style="color:var(--dim)">No checkpoint phases</div>')+'</div>';const summary='<div style="background:#1c2128;border:1px solid var(--border);border-radius:6px;padding:8px;margin-bottom:8px"><div class="mini-title">Sprint ETA</div><div class="mini-metric">'+esc(jt.overall_eta_display||'--')+'</div><div class="mini-meta">Backlog ETA '+esc(jt.backlog_eta_display||'--')+' • Backend ETA '+esc(jt.backend_eta_display||'--')+' • UI ETA '+esc(jt.ui_eta_display||'--')+'</div><div class="mini-meta">Active sections '+esc(activeSections||'--')+'</div></div>';$('jira-tracker').innerHTML=summary+goalHtml+projectHtml+taskHtml+checkpointHtml;$('jira-tracker-count').textContent='('+(goals.length||0)+' goals / '+(projects.length||0)+' projects / '+(tasks.length||0)+' tasks)';ok++}catch(e){fail++;console.error('jira',e)}
 try{$('task').textContent=p.task||'idle';$('timer').textContent=st==='running'?el(p.started_at):st;$('timer').className='timer'+(st!=='running'?' idle':'');ok++}catch(e){fail++;console.error('hdr',e)}
 try{$('os').className='dot '+st;sb('ob',pct,'g');$('op').textContent=pct.toFixed(1)+'%';const ex=(d.session||{}).execution||{};const lp=parseFloat(ex.local_models||(st==='running'?100:0)),cp2=parseFloat(ex.cloud_session||0);sb('lb',lp,'b');sb('cb',cp2,'y');$('lp').textContent=lp.toFixed(1)+'%';$('cp').textContent=cp2.toFixed(1)+'%';sb('tb',ts.percent||0,'p');$('tp').textContent=(ts.percent||0).toFixed(1)+'%';$('todo-count').textContent='('+(ts.done||0)+'/'+(ts.total||0)+' done, '+(ts.open||0)+' open)';const roi=d.roi||{};$('roi').innerHTML=roi.kill_switch?'<span style="color:var(--red)">ROI KILL SWITCH ACTIVE</span>':'<span style="color:var(--green)">ROI: healthy</span>';const sf=d.state_freshness||{},fresh=sf.freshest_source||{},stale=sf.stalest_source||{},stales=sf.stale_sources||[];const staleColor=(sf.stale_count||0)?'var(--yellow)':'var(--green)';const staleText=stales.length?stales.map(s=>esc((s.path||'unknown')+' '+(s.age_seconds==null?'missing':s.age_seconds+'s'))).join(' • '):'All tracked sources fresh';$('freshness').style.borderLeftColor=staleColor;$('freshness').innerHTML='<div style="font-weight:bold;color:'+staleColor+'">Live source freshness</div><div style="margin-top:3px">Freshest: '+esc((fresh.path||'--')+(fresh.age_seconds!=null?' '+fresh.age_seconds+'s':''))+'</div><div>Stalest: '+esc((stale.path||'--')+(stale.age_seconds!=null?' '+stale.age_seconds+'s':''))+'</div><div style="margin-top:4px;color:var(--dim)">'+staleText+'</div>';ok++}catch(e){fail++;console.error('prog',e)}
 try{const bO=br.options||[];$('eta-blockers').textContent='Blocker fix: '+(bO.length&&br.type!=='default'&&br.type!=='none'?(bO[0].eta_seconds||10)+'s (auto: '+S(bO[0].option,30)+')':'no active blockers');const ar=d.auto_remediation||{};$('auto-remediation').textContent=ui.auto_remediation_panel?'Auto-remediation: '+(ar.message||'idle'):'Auto-remediation: legacy mode';$('blocker-wait').textContent=ui.auto_remediation_panel?'Wait budget: '+(ar.chosen&&ar.chosen.eta_seconds?ar.chosen.eta_seconds+'s':'--'):'Wait budget: --';ok++}catch(e){fail++;console.error('eta',e)}
 try{const ops=d.ops_summary||[];let oH='';ops.forEach(item=>{oH+='<div><div style="display:flex;justify-content:space-between;font-size:11px"><span>'+esc(item.label||'')+'</span><span>'+Number(item.percent||0).toFixed(1)+'%</span></div><div class="bar" style="margin-top:2px"><div class="bf '+(item.color||'g')+'" style="width:'+(item.percent||0)+'%"></div></div><div class="mini-meta">'+esc((item.detail||'')+' • '+(item.subtitle||''))+'</div></div>'});$('ops-summary').innerHTML=oH||'<div style="color:var(--dim)">No ROI summary</div>';ok++}catch(e){fail++;console.error('ops',e)}
 try{const t=d.teaching||{};const cats=t.categories||{};const catLine=Object.entries(cats).map(([k,v])=>esc(k)+': '+v).join(' • ');$('teaching-summary').innerHTML='<div style="font-size:12px"><b>Current stage:</b> '+esc(t.current_stage||'none')+'</div><div style="font-size:12px;margin-top:4px"><b>Lessons:</b> '+(t.total_lessons||0)+' | <b>Applied:</b> '+(t.applied_total||0)+' | <b>Applicable now:</b> '+(t.applicable_count||0)+'</div><div style="font-size:11px;color:var(--dim);margin-top:4px">'+esc(catLine||'No lesson categories yet')+'</div>'+(t.next_fix?'<div style="font-size:11px;color:var(--green);margin-top:6px"><b>Next fix:</b> '+esc(S(t.next_fix,120))+'</div>':'');let ta='';(t.applicable||[]).forEach(item=>{ta+='<div class=\"lesson\">['+esc(item.category||'')+'] '+esc(S(item.lesson||'',90))+'<br><span style=\"color:var(--green)\">Fix:</span> '+esc(S(item.fix||'',90))+' <span style=\"color:var(--dim)\">| applied '+(item.applied_count||0)+'x</span></div>'});$('teaching-applicable').innerHTML=ta||'<div style=\"color:var(--dim)\">No stage-specific lessons active</div>';ok++}catch(e){fail++;console.error('teach',e)}
 try{if(ui.governance_panel){const gv=d.governance||{};const checks=(gv.required_checks||[]).length?(gv.required_checks||[]).map(c=>'<div style="font-size:10px;color:var(--dim)">• '+esc(c)+'</div>').join(''):'<div style="font-size:10px;color:var(--dim)">No required checks reported</div>';const color=gv.protected?'var(--green)':(gv.status==='blocked_by_plan'?'var(--yellow)':'var(--red)');$('governance-status').innerHTML='<div style="font-weight:bold;color:'+color+'">'+esc((gv.status||'unknown').toUpperCase())+'</div><div style="margin-top:4px">'+esc((gv.repo||'repo')+' / '+(gv.branch||'main')+' / '+(gv.visibility||'unknown'))+'</div><div style="margin-top:4px;color:var(--dim)">'+esc(gv.blocker||'Branch protection healthy.')+'</div><div style="margin-top:6px">'+checks+'</div><div style="margin-top:6px;font-size:10px;color:var(--dim)">Checked: '+esc(gv.checked_at||'--')+'</div>';}ok++}catch(e){fail++;console.error('gov',e)}
 try{const rs=d.resource||{},cpu=parseFloat(rs.cpu_percent||0),mem=parseFloat(rs.memory_percent||0);sb('cpub',cpu,bc(cpu));sb('memb',mem,bc(mem));$('cpup').textContent=cpu.toFixed(1)+'%';$('memp').textContent=mem.toFixed(1)+'%';ok++}catch(e){fail++;console.error('res',e)}
 try{const rt=d.runtime||{},plan=rt.provider_plan||[],groups=d.runtime_groups||[],oc=d.openclaw||{},provs={};plan.forEach(row=>{const pr=row.provider||'ollama';if(!provs[pr])provs[pr]={t:0,c:0,m:new Set()};provs[pr].t++;const stg=stages.find(s=>s.id===row.stage_id)||{};if(stg.status==='completed')provs[pr].c++;if(row.model)provs[pr].m.add(row.model)});const tt=Object.values(provs).reduce((a,v)=>a+v.t,0)||1;const ocCol=oc.configured?'var(--green)':'var(--yellow)';const ocHealth=(oc.health||{}),ocSvc=(oc.service||{}),ocProbe=(oc.probe||{}),ocCost=(oc.usage_cost||{}),ocCaps=((oc.capabilities||{}).requested_tools||{});let mH='<div class="mini-meta" style="margin-bottom:6px">Preference '+esc(rt.provider_preference||'ollama')+' • remote fallback '+(rt.remote_fallback_allowed?'on':'off')+' • profile '+esc(rt.active_profile||'--')+'</div>';mH+='<div class="mini-meta" style="margin-bottom:6px;color:'+ocCol+'">OpenClaw '+(oc.configured?'configured':'not configured')+(oc.base_url?' • '+esc(oc.base_url):'')+' • checked '+esc(oc.checked_at||'--')+'</div>';if(oc.dashboard_url){mH+='<div class="mini-meta" style="margin-bottom:8px"><a href="'+esc(oc.dashboard_url)+'" target="_blank" rel="noreferrer" style="color:var(--blue)">Open OpenClaw Control UI</a></div>'}mH+='<div style="display:grid;grid-template-columns:repeat(auto-fit,minmax(160px,1fr));gap:6px;margin-bottom:8px"><div class="mini-card"><div class="mini-title">Gateway Health</div><div class="mini-metric">'+esc(ocHealth.ok?'OK':'DEGRADED')+'</div><div class="mini-meta">'+esc(ocHealth.summary||'unknown')+'</div></div><div class="mini-card"><div class="mini-title">Service</div><div class="mini-metric">'+esc(ocSvc.loaded?'loaded':'unknown')+'</div><div class="mini-meta">'+esc(S(ocSvc.runtime||'unknown',42))+'</div></div><div class="mini-card"><div class="mini-title">Probe</div><div class="mini-metric">'+esc(ocProbe.reachable?'reachable':'blocked')+'</div><div class="mini-meta">'+esc(ocProbe.limited?'scope limited':'full probe')+'</div></div><div class="mini-card"><div class="mini-title">Usage Cost</div><div class="mini-metric">'+esc(ocCost.total||'unknown')+'</div><div class="mini-meta">'+esc(ocCost.tokens||'unknown')+'</div></div></div>';if(ocSvc.warning||ocProbe.limited){mH+='<div class="mini-meta" style="margin-bottom:8px;color:var(--yellow)">'+esc(ocSvc.warning||'Probe diagnostics limited by missing operator.read scope')+'</div>'}mH+='<table><tr><th>Provider</th><th>%</th><th>Models</th><th>Done</th></tr>';Object.entries(provs).sort().forEach(([n,v])=>{const pp=(v.t/tt*100).toFixed(0);const tg=n==='ollama'?'local':'cloud';mH+='<tr><td><span class="tag '+tg+'">'+n+'</span></td><td>'+pp+'%</td><td style="font-size:10px">'+[...v.m].join(', ')+'</td><td>'+v.c+'/'+v.t+'</td></tr>'});mH+='</table>';const req=Object.entries(ocCaps).map(([k,v])=>'<span class="tag '+(v?'local':'cloud')+'" style="margin:2px 4px 0 0;display:inline-block">'+esc(k.replace(/_/g,' ')+': '+(v?'available':'requested'))+'</span>').join('');mH+='<div class="mini-meta" style="margin-top:8px">Requested tool lanes</div><div style="margin-top:4px">'+(req||'<span class="mini-meta">No extra tool map</span>')+'</div>';if(groups.length){mH+='<div style="margin-top:8px;display:grid;grid-template-columns:repeat(auto-fit,minmax(180px,1fr));gap:8px">';groups.forEach(g=>{const mix=Object.entries(g.provider_mix||{}).map(([k,v])=>k+': '+v).join(' • ');mH+='<div class="mini-card"><div class="mini-title">'+esc(g.label||'team')+'</div><div class="mini-metric">'+Number(g.percent||0).toFixed(1)+'%</div><div class="mini-meta">'+(g.completed_roles||0)+' done • '+(g.active_roles||0)+' active</div><div class="bar" style="margin-top:5px"><div class="bf b" style="width:'+(g.percent||0)+'%"></div></div><div class="mini-meta" style="margin-top:5px">'+esc(mix||'ollama: 0')+'</div><div style="font-size:10px;color:var(--dim);margin-top:4px">'+esc((g.roles||[]).join(', '))+'</div></div>'});mH+='</div>'}$('mu').innerHTML=mH;ok++}catch(e){fail++;console.error('mu',e)}
 try{const sess=d.sessions||[];let sH='';if(sess.length){sess.forEach(s=>{const tg=(s.type||'').replace('local-','session');const lbl=scrubAuthor(s.label||'user');sH+='<div class="sess"><span class="dot '+(s.status||'active')+'"></span><span class="tag '+tg+'">'+esc(lbl)+'</span><span>'+esc(scrubAuthor(S(s.detail,60)))+'</span></div>'})}else{sH='<div style="color:var(--dim)">No active sessions</div>'}$('sessions').innerHTML=sH;ok++}catch(e){fail++;console.error('sess',e)}
 try{const acts=d.local_agent_activity||[];let aH='';if(acts.length){acts.forEach(a=>{const dot=a.status==='running'?'running':a.status==='completed'?'completed':a.status==='failed'?'failed':'pending';const icon=a.status==='running'?'▶':a.status==='completed'?'✓':a.status==='failed'?'✗':'○';const files=(a.files||[]).length?' ['+a.files.slice(0,2).join(', ')+']':'';const model=a.model?' ('+a.model+')':'';aH+='<div style="font-size:11px;padding:4px 0;border-bottom:1px solid var(--border)"><span class="dot '+dot+'"></span><b>'+esc(a.label||a.role)+'</b> '+icon+' '+esc(S(a.detail,60))+model+files+'<div class="bar" style="height:6px;margin-top:2px"><div class="bf g" style="width:'+(a.percent||0)+'%"></div></div></div>'})}else{aH='<div style="color:var(--dim)">No local agents active</div>'}$('agent-activity').innerHTML=aH;ok++}catch(e){fail++;console.error('act',e)}
 try{const co=d.coordination||{},cl=co.claims||[],col=co.collisions||[];let cH='';if(cl.length){cl.forEach(c=>{cH+='<div style="font-size:11px"><span class="tag agent">'+esc(c.role)+'</span> '+(c.files||[]).slice(0,3).join(', ')+'</div>'})}else{cH='<div style="color:var(--dim)">No file claims</div>'}if(col.length){col.slice(-3).forEach(c=>{cH+='<div class="collision">'+esc(c.file)+' — '+esc(c.claimed_by)+' vs '+esc(c.requested_by)+'</div>'})}$('coord').innerHTML=cH;ok++}catch(e){fail++;console.error('coord',e)}
 try{if($('session-matrix')){const sm=d.session_matrix||[];let smH='';if(sm.length){smH+='<table><tr><th>Owner</th><th>Work</th><th>ETA</th></tr>';sm.forEach(s=>{smH+='<tr><td>'+esc(scrubAuthor(s.owner))+'</td><td>'+esc(scrubAuthor(S(s.assigned_work,36)))+'</td><td>'+esc(s.eta_display||'--')+'</td></tr>'});smH+='</table>'}else{smH='<div style="color:var(--dim)">No session matrix</div>'}$('session-matrix').innerHTML=smH}ok++}catch(e){fail++;console.error('sm',e)}
 try{const sbd=d.session_board||[];$('session-board-count').textContent='('+sbd.filter(s=>s.active).length+' active / '+sbd.length+' lanes)';let sbH='';sbd.forEach(s=>{const tag=(s.id||'').replace('local-agent','local')||'agent';const sd2=s.active?'active':'pending';const opts=(s.options||[]).map((o,i)=>'<div style="font-size:10px;margin-top:2px;color:'+(i===0?'var(--green)':'var(--dim)')+'">'+(i===0?'>>> ':'')+esc(S(o.option,40))+' | '+(o.eta_seconds||'?')+'s</div>').join('');sbH+='<div style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px"><div style="display:flex;justify-content:space-between;align-items:center"><div><span class="tag '+tag+'">'+esc(scrubAuthor(s.label||s.id))+'</span> <span class="dot '+sd2+'"></span></div><div style="color:var(--yellow);font-size:12px;font-weight:bold">ETA: '+esc(s.eta_display||'--')+'</div></div><div style="margin-top:6px;font-size:12px">'+esc(scrubAuthor(S(s.assigned_work||'idle',110)))+'</div><div style="margin-top:3px;color:var(--dim);font-size:10px">'+esc(scrubAuthor(S(s.detail,80))||'idle')+'</div>'+(opts?'<div style="margin-top:6px;padding-top:4px;border-top:1px solid var(--border)"><div style="font-size:10px;color:var(--dim)">Deadline: '+(s.decision_deadline_seconds||10)+'s</div>'+opts+'</div>':'')+'</div>'});$('session-board').innerHTML=sbH||'<div style="color:var(--dim)">No session lanes</div>';ok++}catch(e){fail++;console.error('sboard',e)}
 try{if(ui.executive_conflict){const neg=d.executive_negotiation||[];let nH='';neg.forEach(item=>{const tn=parseFloat(item.tension||0);const col=tn>=90?'var(--red)':tn>=75?'var(--yellow)':'var(--blue)';nH+='<div style="background:#181d24;border:1px solid '+col+';border-radius:6px;padding:8px;box-shadow:inset 0 0 0 1px rgba(255,255,255,0.03)"><div style="display:flex;justify-content:space-between;gap:8px"><div style="font-weight:bold;color:'+col+';margin-bottom:4px">'+esc(item.title||'')+'</div><div style="font-size:10px;color:'+col+'">Tension '+tn.toFixed(0)+'%</div></div><div style="font-size:10px;color:var(--red);margin-bottom:6px">'+esc(S(item.fight||'',120))+'</div><div style="font-size:11px;color:var(--blue)">Left: '+esc(S(item.left||'',90))+'</div><div style="font-size:11px;color:var(--purple);margin-top:4px">Right: '+esc(S(item.right||'',90))+'</div><div style="display:flex;justify-content:space-between;gap:8px;margin-top:6px;font-size:10px"><span style="color:var(--green)">Winner: '+esc(item.winner||'')+'</span><span style="color:var(--red)">Loser: '+esc(item.loser||'')+'</span></div><div style="margin-top:6px;padding-top:4px;border-top:1px solid var(--border);font-size:10px;color:var(--yellow)">Forced decision: '+esc(S(item.decision||'',120))+'</div></div>'});$('executive-negotiation').innerHTML=nH||'<div style="color:var(--dim)">No active executive tension</div>';}ok++}catch(e){fail++;console.error('neg',e)}
 try{if($('project-rollups')){const pb=d.project_board||{};const cards=(pb.lanes||[]).concat(pb.use_cases||[]).map(item=>'<div class="mini-card"><div class="mini-title">'+esc(item.label)+'</div><div class="mini-metric">'+Number(item.percent||0).toFixed(1)+'%</div><div class="mini-meta">'+(item.done||0)+'/'+(item.total||0)+' done • ETA '+esc(item.eta_display||'--')+'</div></div>');if($('project-rollups'))$('project-rollups').innerHTML=cards.join('')||'<div style="color:var(--dim)">No rollups</div>'}ok++}catch(e){fail++;console.error('rollups',e)}
 try{const uu=d.ui_updates||{},items=uu.items||[];$('ui-updates-count').textContent='('+(uu.updating_count||0)+' updating)';let uH='';items.forEach(item=>{const col=item.status==='updating'?'var(--green)':item.status==='missing'?'var(--red)':'var(--blue)';const age=item.age_seconds==null?'missing':item.age_seconds+'s';uH+='<div class="mini-card" style="border-color:'+col+'"><div class="mini-title">'+esc(item.status||'stable')+'</div><div style="font-size:12px;font-weight:bold;margin-top:4px">'+esc(item.path||'--')+'</div><div class="mini-meta">Age: '+esc(age)+'</div></div>'});$('ui-updates').innerHTML=uH||'<div style="color:var(--dim)">No UI updates tracked</div>';ok++}catch(e){fail++;console.error('ui-updates',e)}
 try{$('role-count').textContent='('+stages.filter(s=>s.status==='completed').length+'/'+stages.length+' done)';let rH='';stages.forEach(s=>{const sp=s.percent||0,ss=s.status||'pending';rH+='<div class="bw" title="'+esc(s.detail)+'"><span class="bl"><span class="dot '+ss+'"></span>'+(s.label||s.id)+'</span><div class="bar"><div class="bf g" style="width:'+sp+'%"></div></div><span class="bp">'+sp.toFixed(0)+'%</span></div>'});$('roles').innerHTML=rH||'<div style="color:var(--dim)">No roles</div>';ok++}catch(e){fail++;console.error('roles',e)}
 try{const blockers=td.blockers||[];$('blocker-count').textContent='('+blockers.length+')';if(blockers.length){let bkH='';if(br.type&&br.type!=='default'&&br.type!=='none'){bkH+='<div style="background:#2d1517;padding:6px;border-radius:4px;margin-bottom:6px"><span style="color:var(--red);font-weight:bold">ACTIVE: '+br.type.toUpperCase().replace(/_/g,' ')+'</span>';(br.options||[]).forEach((o,i)=>{bkH+='<div style="font-size:10px;margin-top:2px;color:'+(i===0?'var(--green)':'var(--dim)')+'">'+(i===0?'>>> ':'    ')+'Option '+(i+1)+': '+esc(S(o.option,40))+' ('+(o.eta_seconds||'?')+'s)</div>'});bkH+='</div>'}bkH+=blockers.map(b=>'<div class="item blocker">'+esc(S(b.text,120))+'<br><small>'+esc(b.section||'')+'</small></div>').join('');$('blockers').innerHTML=bkH}else{$('blockers').innerHTML='<div style="color:var(--green)">No blockers!</div>'}ok++}catch(e){fail++;console.error('blk',e)}
 try{const working=td.working||[];$('working-count').textContent='('+working.length+')';$('working').innerHTML=working.length?working.map(w=>'<div class="item working">'+esc(S(w.text,120))+'<br><small>'+esc(w.section||'')+'</small></div>').join(''):'<div style="color:var(--dim)">Nothing in progress</div>';ok++}catch(e){fail++;console.error('work',e)}
 try{const doneItems=(td.items||[]).filter(i=>i.done);$('done-count').textContent='('+doneItems.length+')';$('done-items').innerHTML=doneItems.length?doneItems.slice(-15).map(i=>'<div class="item done">'+esc(S(i.text,100))+'</div>').join(''):'<div style="color:var(--dim)">None yet</div>';ok++}catch(e){fail++;console.error('done',e)}
 try{const allItems=td.items||[];let curSec='',todoHtml='';allItems.forEach(i=>{if(i.section!==curSec){curSec=i.section;todoHtml+='<div style="color:var(--blue);margin-top:6px;font-weight:bold">'+esc(curSec)+'</div>'}const cls=i.done?'item done':'item open';const icon=i.done?'✓':'○';todoHtml+='<div class="'+cls+'"><span>'+icon+'</span> '+esc(S(i.text,150))+'</div>'});$('todo-list').innerHTML=todoHtml||'<div style="color:var(--dim)">No items</div>';ok++}catch(e){fail++;console.error('todo',e)}
 try{const les=d.lessons||[];$('lesson-count').textContent='('+les.length+')';$('lessons').innerHTML=les.length?les.slice(-8).map(l=>'<div class="lesson">['+esc(l.category||'')+'] '+esc(S(l.lesson,100))+'</div>').join(''):'<div style="color:var(--dim)">No lessons yet</div>';ok++}catch(e){fail++;console.error('les',e)}
 try{
  const c=d.completion||{};
  const topCard='<div style="background:#1c2128;border:1px solid var(--border);border-radius:6px;padding:8px">'+
    '<div style="display:flex;justify-content:space-between;font-size:12px"><b>Active Sprint</b><span>'+Number(c.overall_percent||0).toFixed(1)+'%</span></div>'+
    '<div class="bar" style="margin-top:4px"><div class="bf p" style="width:'+(c.overall_percent||0)+'%"></div></div>'+
    '<div class="mini-meta">Sprint ETA '+esc(c.sprint_eta||'--')+' • Backlog ETA '+esc(c.todo_eta||'--')+' • '+(c.open_tasks||0)+' open • ROI '+(c.roi_score||0)+'%</div>'+
  '</div>';
  const blockerItems=(c.blocker_options||[]).length
    ? (c.blocker_options||[]).map((b,i)=>'<div class="item blocker">'+(i===0?'>>> ':'')+esc(S(b.option||'',50))+'<br><small>'+esc((b.eta_seconds||'?')+'s • '+S(b.detail||'',60))+'</small></div>').join('')
    : '<div style="color:var(--green)">No active blockers</div>';
  const blockerCard='<div style="background:#1c2128;border:1px solid var(--border);border-radius:6px;padding:8px">'+
    '<div style="font-weight:bold;font-size:12px;margin-bottom:4px">Blockers Faced</div>'+blockerItems+
  '</div>';
  const decisionItems=(c.decisions||[]).slice(0,5).map(d2=>'<div class="item working"><span>'+esc(d2.icon||'•')+'</span> '+esc(S(d2.text||'',80))+'</div>').join('');
  const lessonItems=(c.lessons_recent||[]).slice(0,4).map(l=>'<div class="lesson">['+esc(l.category||'')+'] '+esc(S(l.text||'',80))+'</div>').join('');
  const decisionCard='<div style="background:#1c2128;border:1px solid var(--border);border-radius:6px;padding:8px">'+
    '<div style="font-weight:bold;font-size:12px;margin-bottom:4px">Decisions + Lessons</div>'+
    (decisionItems||'<div style="color:var(--dim)">No decisions yet</div>')+
    lessonItems+
  '</div>';
  $('completion-forecast').innerHTML=topCard+blockerCard+decisionCard;
  ok++
 }catch(e){fail++;console.error('completion',e)}
 try{const tl=d.timeline||[];$('timeline').innerHTML=tl.length?tl.slice(-12).reverse().map(e=>{const t=(e.timestamp||'').split('T')[1]||'';return '<div class="tl-item"><span class="time">'+t+'</span><span class="role">'+esc(e.role||'')+'</span><span class="msg">'+esc(S(e.content,60))+'</span></div>'}).join(''):'<div style="color:var(--dim)">No events</div>';ok++}catch(e){fail++;console.error('tl',e)}
 try{const flow=d.task_flow||{},nodes=flow.nodes||[];let fH='';if(nodes.length){nodes.forEach((n,i)=>{const sc=n.status==='completed'?'var(--green)':n.status==='running'?'var(--blue)':n.status==='blocked'?'var(--red)':'var(--border)';fH+='<div style="min-width:140px;background:#1c2128;border:2px solid '+sc+';border-radius:6px;padding:8px"><div style="font-size:10px;color:var(--dim)">STEP '+(i+1)+'</div><div style="font-size:11px;margin-top:3px;font-weight:bold">'+esc(n.label||n.id||'')+'</div><div style="font-size:10px;color:var(--dim);margin-top:2px">'+esc(n.owner||'')+'</div><div style="font-size:10px;color:var(--yellow);margin-top:2px">'+esc(n.eta||'')+'</div></div>';if(i<nodes.length-1)fH+='<div style="align-self:center;color:var(--blue);font-size:18px;padding:0 4px">→</div>'})}else{fH='<div style="color:var(--dim)">No task flow</div>'}$('task-flow').innerHTML=fH;ok++}catch(e){fail++;console.error('flow',e)}
 const sf=d.state_freshness||{};$('refresh').textContent='Last: '+new Date().toLocaleTimeString()+' | live | '+ok+' OK'+(fail?' | '+fail+' ERR':'')+' | stale sources: '+(sf.stale_count||0);
}

setInterval(()=>{if(__latestState)renderEtaFields(__latestState)},1000)

async function R(){
 let d;try{const r=await fetch('/api/state');d=await r.json()}catch(e){$('refresh').textContent='FETCH ERR: '+e.message;return}
 renderState(d)
}

// Auto-refresh every 3 seconds via fetch for real-time data
let _fetchInterval=null;
function startAutoRefresh(){
 R(); // initial fetch
 _fetchInterval=setInterval(R,3000); // every 3 seconds
}

function startLiveStream(){
 if(!window.EventSource){
  startAutoRefresh();return
 }
 let source=null;let lastEvent=Date.now();
 const connect=()=>{
  source=new EventSource('/api/stream')
  source.addEventListener('state',ev=>{
   lastEvent=Date.now()
   try{renderState(JSON.parse(ev.data))}catch(err){console.error('stream-parse',err)}
  })
  source.onerror=()=>{
   $('refresh').textContent='Stream reconnecting...'
   try{source.close()}catch(_e){}
   setTimeout(connect,3000)
  }
 }
 connect()
 // Fallback: if stream stops delivering, fetch every 3s
 setInterval(()=>{if(Date.now()-lastEvent>5000)R()},3000)
}
R();startLiveStream();
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/state":
            state = collect_state_cached()
            body = json.dumps(state).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/api/stream":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.send_header("Connection", "keep-alive")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            try:
                while True:
                    self.wfile.write(_stream_state_event())
                    self.wfile.flush()
                    time.sleep(3)
            except (BrokenPipeError, ConnectionResetError):
                return
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())

    def log_message(self, format, *args):
        pass  # Suppress access logs


def main():
    threading.Thread(target=_refresh_state_cache, daemon=True).start()
    preferred = int(os.environ.get("LOCAL_AGENT_DASHBOARD_PORT", "8411"))
    server = None
    port = preferred
    for candidate in range(preferred, preferred + 5):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", candidate), DashboardHandler)
            port = candidate
            break
        except OSError as exc:
            if getattr(exc, "errno", None) != 48:
                raise
    if server is None:
        raise socket_error("No dashboard port available in preferred range.")
    print(f"Local Agent Dashboard running at http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        print("\nDashboard stopped.")


if __name__ == "__main__":
    main()
