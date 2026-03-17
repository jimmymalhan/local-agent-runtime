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
from http.server import HTTPServer, BaseHTTPRequestHandler
from datetime import datetime
from socket import error as socket_error

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))
from todo_progress import parse_todo, LANE_ORDER, LANE_LABELS, USE_CASE_ORDER, USE_CASE_LABELS


def load_json(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


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

    return {
        "items": items,
        "blockers": blockers,
        "working": working[:10],
        "stats": parsed.get("overall", {"total": 0, "done": 0, "open": 0, "percent": 0.0}),
        "lanes": parsed.get("lanes", {}),
        "use_cases": parsed.get("use_cases", {}),
        "focus": parsed.get("focus", {}),
    }


def _detect_sessions() -> list[dict]:
    """Detect active coding sessions (Claude, Codex, Cursor) from process table."""
    import subprocess
    sessions = []
    try:
        ps = subprocess.run(["ps", "aux"], capture_output=True, text=True, timeout=5)
        for line in ps.stdout.splitlines():
            lower = line.lower()
            if "claude" in lower and ("node" in lower or "claude" in lower):
                if "dashboard_server" not in lower and "grep" not in lower:
                    sessions.append({"type": "claude", "detail": line.split()[-1] if line.split() else "", "status": "active"})
            if "codex" in lower and "grep" not in lower:
                sessions.append({"type": "codex", "detail": line.split()[-1] if line.split() else "", "status": "active"})
            if "cursor" in lower and "grep" not in lower and "helper" not in lower:
                sessions.append({"type": "cursor", "detail": line.split()[-1] if line.split() else "", "status": "active"})
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
                "detail": lock_data.get("task", ""),
                "status": "running",
                "pid": lock_data["pid"],
            })
        except (OSError, ValueError):
            sessions.append({"type": "local-agent", "detail": "stale lock", "status": "stale"})

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


def _session_lane_defaults() -> list[dict]:
    return [
        {"id": "local-agent", "label": "Local Agents", "kind": "local", "default_work": "Fast local repo work, checkpoints, and self-heal."},
        {"id": "manager", "label": "Manager", "kind": "executive", "default_work": "Drive daily execution, unblock handoffs, and cut scope fast."},
        {"id": "director", "label": "Director", "kind": "executive", "default_work": "Prioritize streams, force tradeoffs, and rebalance resources."},
        {"id": "cto", "label": "CTO", "kind": "executive", "default_work": "Choose architecture, model routing, and technical escalations."},
        {"id": "ceo", "label": "CEO", "kind": "executive", "default_work": "Make ROI calls, stop low-yield work, and force ship decisions."},
        {"id": "claude", "label": "Claude", "kind": "cloud", "default_work": "Take over broad reasoning, blocker triage, and release writing."},
        {"id": "codex", "label": "Codex", "kind": "cloud", "default_work": "Take over code surgery, review, and merge-path fixes."},
        {"id": "cursor", "label": "Cursor", "kind": "cloud", "default_work": "Own UI polish, dashboard refinement, and frontend repair."},
    ]


def _session_board(progress: dict, session: dict, sessions: list[dict], blocker_resolution: dict, etas: dict, todo: dict) -> list[dict]:
    by_type = {item["type"]: item for item in sessions}
    current_task = progress.get("task") or session.get("task") or "No active task"
    blocker_type = blocker_resolution.get("type", "none")
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
        elif blocker_type not in {"none", "default"} and blocker_options:
            assigned_work = blocker_options[0]["detail"]
            eta = f"{blocker_options[0].get('eta_seconds', 0)}s"
            active = bool(detected)
        elif open_focus:
            assigned_work = "Standby. Local executives own this until a real blocker requires takeover."
            eta = "standby"
            active = bool(detected)
        else:
            assigned_work = "Standby. No cloud takeover needed."
            eta = "standby"
            active = bool(detected)
        board.append(
            {
                "id": lane["id"],
                "label": lane["label"],
                "kind": lane["kind"],
                "status": detected.get("status", "idle" if not active else "active"),
                "active": active,
                "detail": detected.get("detail", ""),
                "assigned_work": assigned_work,
                "eta_display": eta,
                "decision_deadline_seconds": blocker_options[0].get("eta_seconds", 10) if blocker_options else 10,
                "blocker_type": blocker_type,
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
            {"id": "task", "label": current_task[:48]},
            {"id": "stage", "label": f"Stage: {current_stage}"},
            {"id": "blocker", "label": f"Blocker: {blocker_type}"},
            {"id": "owner", "label": f"Owner: {owner.get('label', 'Unassigned')}"},
            {"id": "finish", "label": f"ETA: {owner.get('eta_display', '--')}"},
        ],
        "edges": [
            {"from": "todo", "to": "task"},
            {"from": "task", "to": "stage"},
            {"from": "stage", "to": "blocker"},
            {"from": "blocker", "to": "owner"},
            {"from": "owner", "to": "finish"},
        ],
    }


def _project_board(todo: dict) -> dict:
    return {
        "lanes": [
            {
                "id": name,
                "label": LANE_LABELS.get(name, name.title()),
                **todo.get("lanes", {}).get(name, {"done": 0, "open": 0, "total": 0, "percent": 0.0}),
            }
            for name in LANE_ORDER
            if todo.get("lanes", {}).get(name, {}).get("total", 0)
        ],
        "use_cases": [
            {
                "id": name,
                "label": USE_CASE_LABELS.get(name, name.title()),
                **todo.get("use_cases", {}).get(name, {"done": 0, "open": 0, "total": 0, "percent": 0.0}),
            }
            for name in USE_CASE_ORDER
            if todo.get("use_cases", {}).get(name, {}).get("total", 0)
        ],
    }


def collect_state() -> dict:
    progress = load_json(REPO_ROOT / "state" / "progress.json")
    session = load_json(REPO_ROOT / "state" / "session-state.json")
    todo = _load_todo()
    sessions = _detect_sessions()
    blocker_resolution = _resolve_blockers()
    etas = _compute_etas()
    session_board = _session_board(progress, session, sessions, blocker_resolution, etas, todo)
    return {
        "progress": progress,
        "session": session,
        "resource": load_json(REPO_ROOT / "state" / "resource-status.json"),
        "lock": load_json(REPO_ROOT / "state" / "run.lock"),
        "roi": load_json(REPO_ROOT / "state" / "roi-metrics.json"),
        "coordination": load_json(REPO_ROOT / "state" / "agent-coordination.json"),
        "takeover": load_json(REPO_ROOT / "state" / "takeover-recommendation.json"),
        "runtime": load_json(REPO_ROOT / "config" / "runtime.json"),
        "lessons": _load_lessons(),
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
        "server_time": datetime.now().isoformat(timespec="seconds"),
    }


def _resolve_blockers() -> dict:
    try:
        from blocker_resolver import classify_blocker, resolve_options
        context = {
            "resource": load_json(REPO_ROOT / "state" / "resource-status.json"),
            "roi": load_json(REPO_ROOT / "state" / "roi-metrics.json"),
            "progress": load_json(REPO_ROOT / "state" / "progress.json"),
            "lock": load_json(REPO_ROOT / "state" / "run.lock"),
        }
        blocker_type = classify_blocker(context)
        options = resolve_options(blocker_type)
        return {"type": blocker_type, "options": options}
    except Exception:
        return {"type": "none", "options": []}


def _compute_etas() -> dict:
    try:
        from blocker_resolver import estimate_completion
        progress = load_json(REPO_ROOT / "state" / "progress.json")
        todo = _load_todo()
        sessions = _detect_sessions()
        return estimate_completion(progress, todo.get("stats", {}), session_count=max(1, len(sessions)))
    except Exception:
        return {}


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


DASHBOARD_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Local Agent Runtime — Dashboard</title>
<style>
:root{--bg:#0d1117;--fg:#c9d1d9;--green:#3fb950;--yellow:#d29922;--red:#f85149;--blue:#58a6ff;--purple:#bc8cff;--dim:#484f58;--card:#161b22;--border:#30363d;--font:'SF Mono','Cascadia Code','Fira Code',monospace}
*{margin:0;padding:0;box-sizing:border-box}
body{background:var(--bg);color:var(--fg);font-family:var(--font);font-size:12px;padding:12px}
h1{font-size:15px;color:var(--blue);margin-bottom:8px}
h2{font-size:11px;color:var(--dim);text-transform:uppercase;letter-spacing:1px;margin:10px 0 6px;display:flex;align-items:center;gap:6px}
h2 .count{color:var(--fg);font-size:12px}
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
.tag.local{background:#0d419d;color:var(--blue)}.tag.cloud{background:#5a3e00;color:var(--yellow)}.tag.claude{background:#6e40aa;color:#d8b4fe}.tag.codex{background:#1a7f37;color:#7ee787}.tag.cursor{background:#0969da;color:#a5d6ff}.tag.agent{background:#21262d;color:var(--fg)}
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
  <div><h1>Local Agent Runtime</h1><div class="task" id="task">Loading...</div></div>
  <div class="timer" id="timer">--</div>
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
    <div id="eta-box" style="margin-top:8px;padding:6px;background:#1c2128;border-radius:4px;border-left:3px solid var(--green)">
      <div style="color:var(--green);font-weight:bold;font-size:11px">ETA (Aggressive)</div>
      <div style="font-size:12px;margin-top:3px" id="eta-pipeline">Pipeline: --</div>
      <div style="font-size:12px" id="eta-todo">All tasks: --</div>
      <div style="font-size:12px" id="eta-blockers">Blocker fix: --</div>
      <div style="font-size:12px" id="blocker-wait">Wait budget: --</div>
    </div>
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

  <div class="card full">
    <h2>Project Rollups</h2>
    <div class="mini-grid" id="project-rollups">Loading...</div>
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
</div>
<div class="refresh" id="refresh">Refreshing every 2s</div>
<script>
function bc(p){return p>85?'r':p>60?'y':'g'}
function el(s){if(!s)return'--';const d=new Date(s),n=new Date(),t=Math.max(0,Math.floor((n-d)/1e3)),m=Math.floor(t/60),s2=t%60,h=Math.floor(m/60),m2=m%60;return h?h+'h '+m2+'m '+s2+'s':m?m+'m '+s2+'s':s2+'s'}
function sb(id,p,c){const e=document.getElementById(id);if(e){e.style.width=Math.min(100,Math.max(0,p))+'%';if(c)e.className='bf '+c}}
function esc(s){if(s==null)return'';const d=document.createElement('div');d.textContent=String(s);return d.innerHTML}
function S(s,n){return s?String(s).substring(0,n):''}
function $(id){return document.getElementById(id)}

async function R(){
 let d;try{const r=await fetch('/api/state');d=await r.json()}catch(e){$('refresh').textContent='FETCH ERR: '+e.message;return}
 const p=d.progress||{},o=p.overall||{},st=o.status||'idle',pct=o.percent||0;
 const td=d.todo||{},ts=td.stats||{};const br=d.blocker_resolution||{};const etas=d.etas||{};const stages=p.stages||[];
 let ok=0,fail=0;
 try{$('task').textContent=p.task||'idle';$('timer').textContent=st==='running'?el(p.started_at):st;$('timer').className='timer'+(st!=='running'?' idle':'');ok++}catch(e){fail++;console.error('hdr',e)}
 try{$('os').className='dot '+st;sb('ob',pct,'g');$('op').textContent=pct.toFixed(1)+'%';const ex=(d.session||{}).execution||{};const lp=parseFloat(ex.local_models||(st==='running'?100:0)),cp2=parseFloat(ex.cloud_session||0);sb('lb',lp,'b');sb('cb',cp2,'y');$('lp').textContent=lp.toFixed(1)+'%';$('cp').textContent=cp2.toFixed(1)+'%';sb('tb',ts.percent||0,'p');$('tp').textContent=(ts.percent||0).toFixed(1)+'%';$('todo-count').textContent='('+(ts.done||0)+'/'+(ts.total||0)+' done, '+(ts.open||0)+' open)';const roi=d.roi||{};$('roi').innerHTML=roi.kill_switch?'<span style="color:var(--red)">ROI KILL SWITCH ACTIVE</span>':'<span style="color:var(--green)">ROI: healthy</span>';ok++}catch(e){fail++;console.error('prog',e)}
 try{$('eta-pipeline').textContent='Pipeline: '+(etas.pipeline_eta_display||'--')+' ('+(etas.remaining_roles||0)+' roles left)';$('eta-todo').textContent='All tasks: '+(etas.todo_eta_display||'--')+' ('+(etas.open_tasks||0)+' open)';const bO=br.options||[];$('eta-blockers').textContent='Blocker fix: '+(bO.length&&br.type!=='default'&&br.type!=='none'?(bO[0].eta_seconds||10)+'s (auto: '+S(bO[0].option,30)+')':'no active blockers');ok++}catch(e){fail++;console.error('eta',e)}
 try{const rs=d.resource||{},cpu=parseFloat(rs.cpu_percent||0),mem=parseFloat(rs.memory_percent||0);sb('cpub',cpu,bc(cpu));sb('memb',mem,bc(mem));$('cpup').textContent=cpu.toFixed(1)+'%';$('memp').textContent=mem.toFixed(1)+'%';ok++}catch(e){fail++;console.error('res',e)}
 try{const team=(d.runtime||{}).team||{},provs={};stages.forEach(s=>{if(s.id==='preflight')return;let pr='ollama';const dt=s.detail||'';if(dt.includes('github_models'))pr='github_models';else if(dt.includes('clawbot'))pr='clawbot';else if(dt.includes('openclaw'))pr='openclaw';if(!provs[pr])provs[pr]={t:0,c:0,m:new Set()};provs[pr].t++;if(s.status==='completed')provs[pr].c++;provs[pr].m.add((team[s.id]||{}).model||'?')});const tt=Object.values(provs).reduce((a,v)=>a+v.t,0)||1;let mH='<table><tr><th>Provider</th><th>%</th><th>Models</th><th>Done</th></tr>';Object.entries(provs).sort().forEach(([n,v])=>{const pp=(v.t/tt*100).toFixed(0);const tg=n==='ollama'?'local':'cloud';mH+='<tr><td><span class="tag '+tg+'">'+n+'</span></td><td>'+pp+'%</td><td style="font-size:10px">'+[...v.m].join(', ')+'</td><td>'+v.c+'/'+v.t+'</td></tr>'});mH+='</table>';$('mu').innerHTML=mH;ok++}catch(e){fail++;console.error('mu',e)}
 try{const sess=d.sessions||[];let sH='';if(sess.length){sess.forEach(s=>{const tg=(s.type||'').replace('local-','');sH+='<div class="sess"><span class="dot '+(s.status||'active')+'"></span><span class="tag '+tg+'">'+esc(s.type)+'</span><span>'+esc(S(s.detail,60))+'</span></div>'})}else{sH='<div style="color:var(--dim)">No active sessions</div>'}$('sessions').innerHTML=sH;ok++}catch(e){fail++;console.error('sess',e)}
 try{const acts=d.local_agent_activity||[];let aH='';if(acts.length){acts.forEach(a=>{const dot=a.status==='running'?'running':a.status==='completed'?'completed':a.status==='failed'?'failed':'pending';const icon=a.status==='running'?'▶':a.status==='completed'?'✓':a.status==='failed'?'✗':'○';const files=(a.files||[]).length?' ['+a.files.slice(0,2).join(', ')+']':'';const model=a.model?' ('+a.model+')':'';aH+='<div style="font-size:11px;padding:4px 0;border-bottom:1px solid var(--border)"><span class="dot '+dot+'"></span><b>'+esc(a.label||a.role)+'</b> '+icon+' '+esc(S(a.detail,60))+model+files+'<div class="bar" style="height:6px;margin-top:2px"><div class="bf g" style="width:'+(a.percent||0)+'%"></div></div></div>'})}else{aH='<div style="color:var(--dim)">No local agents active</div>'}$('agent-activity').innerHTML=aH;ok++}catch(e){fail++;console.error('act',e)}
 try{const co=d.coordination||{},cl=co.claims||[],col=co.collisions||[];let cH='';if(cl.length){cl.forEach(c=>{cH+='<div style="font-size:11px"><span class="tag agent">'+esc(c.role)+'</span> '+(c.files||[]).slice(0,3).join(', ')+'</div>'})}else{cH='<div style="color:var(--dim)">No file claims</div>'}if(col.length){col.slice(-3).forEach(c=>{cH+='<div class="collision">'+esc(c.file)+' — '+esc(c.claimed_by)+' vs '+esc(c.requested_by)+'</div>'})}$('coord').innerHTML=cH;ok++}catch(e){fail++;console.error('coord',e)}
 try{if($('session-matrix')){const sm=d.session_matrix||[];let smH='';if(sm.length){smH+='<table><tr><th>Owner</th><th>Work</th><th>ETA</th></tr>';sm.forEach(s=>{smH+='<tr><td>'+esc(s.owner)+'</td><td>'+esc(S(s.assigned_work,36))+'</td><td>'+esc(s.eta_display||'--')+'</td></tr>'});smH+='</table>'}else{smH='<div style="color:var(--dim)">No session matrix</div>'}$('session-matrix').innerHTML=smH}ok++}catch(e){fail++;console.error('sm',e)}
 try{const sbd=d.session_board||[];$('session-board-count').textContent='('+sbd.filter(s=>s.active).length+' active / '+sbd.length+' lanes)';let sbH='';sbd.forEach(s=>{const tag=(s.id||'').replace('local-agent','local')||'agent';const sd2=s.active?'active':'pending';const opts=(s.options||[]).map((o,i)=>'<div style="font-size:10px;margin-top:2px;color:'+(i===0?'var(--green)':'var(--dim)')+'">'+(i===0?'>>> ':'')+esc(S(o.option,40))+' | '+(o.eta_seconds||'?')+'s</div>').join('');sbH+='<div style="background:var(--bg);border:1px solid var(--border);border-radius:6px;padding:8px"><div style="display:flex;justify-content:space-between;align-items:center"><div><span class="tag '+tag+'">'+esc(s.label||s.id)+'</span> <span class="dot '+sd2+'"></span></div><div style="color:var(--yellow);font-size:12px;font-weight:bold">ETA: '+esc(s.eta_display||'--')+'</div></div><div style="margin-top:6px;font-size:12px">'+esc(S(s.assigned_work||'idle',110))+'</div><div style="margin-top:3px;color:var(--dim);font-size:10px">'+esc(S(s.detail,80)||'idle')+'</div>'+(opts?'<div style="margin-top:6px;padding-top:4px;border-top:1px solid var(--border)"><div style="font-size:10px;color:var(--dim)">Deadline: '+(s.decision_deadline_seconds||10)+'s</div>'+opts+'</div>':'')+'</div>'});$('session-board').innerHTML=sbH||'<div style="color:var(--dim)">No session lanes</div>';ok++}catch(e){fail++;console.error('sboard',e)}
 try{if($('project-rollups')){const pb=d.project_board||{};const cards=(pb.lanes||[]).concat(pb.use_cases||[]).map(item=>'<div class="mini-card"><div class="mini-title">'+esc(item.label)+'</div><div class="mini-metric">'+Number(item.percent||0).toFixed(1)+'%</div><div class="mini-meta">'+(item.done||0)+'/'+(item.total||0)+' done</div></div>');if($('project-rollups'))$('project-rollups').innerHTML=cards.join('')||'<div style="color:var(--dim)">No rollups</div>'}ok++}catch(e){fail++;console.error('rollups',e)}
 try{$('role-count').textContent='('+stages.filter(s=>s.status==='completed').length+'/'+stages.length+' done)';let rH='';stages.forEach(s=>{const sp=s.percent||0,ss=s.status||'pending';rH+='<div class="bw" title="'+esc(s.detail)+'"><span class="bl"><span class="dot '+ss+'"></span>'+(s.label||s.id)+'</span><div class="bar"><div class="bf g" style="width:'+sp+'%"></div></div><span class="bp">'+sp.toFixed(0)+'%</span></div>'});$('roles').innerHTML=rH||'<div style="color:var(--dim)">No roles</div>';ok++}catch(e){fail++;console.error('roles',e)}
 try{const blockers=td.blockers||[];$('blocker-count').textContent='('+blockers.length+')';if(blockers.length){let bkH='';if(br.type&&br.type!=='default'&&br.type!=='none'){bkH+='<div style="background:#2d1517;padding:6px;border-radius:4px;margin-bottom:6px"><span style="color:var(--red);font-weight:bold">ACTIVE: '+br.type.toUpperCase().replace(/_/g,' ')+'</span>';(br.options||[]).forEach((o,i)=>{bkH+='<div style="font-size:10px;margin-top:2px;color:'+(i===0?'var(--green)':'var(--dim)')+'">'+(i===0?'>>> ':'    ')+'Option '+(i+1)+': '+esc(S(o.option,40))+' ('+(o.eta_seconds||'?')+'s)</div>'});bkH+='</div>'}bkH+=blockers.map(b=>'<div class="item blocker">'+esc(S(b.text,120))+'<br><small>'+esc(b.section||'')+'</small></div>').join('');$('blockers').innerHTML=bkH}else{$('blockers').innerHTML='<div style="color:var(--green)">No blockers!</div>'}ok++}catch(e){fail++;console.error('blk',e)}
 try{const working=td.working||[];$('working-count').textContent='('+working.length+')';$('working').innerHTML=working.length?working.map(w=>'<div class="item working">'+esc(S(w.text,120))+'<br><small>'+esc(w.section||'')+'</small></div>').join(''):'<div style="color:var(--dim)">Nothing in progress</div>';ok++}catch(e){fail++;console.error('work',e)}
 try{const doneItems=(td.items||[]).filter(i=>i.done);$('done-count').textContent='('+doneItems.length+')';$('done-items').innerHTML=doneItems.length?doneItems.slice(-15).map(i=>'<div class="item done">'+esc(S(i.text,100))+'</div>').join(''):'<div style="color:var(--dim)">None yet</div>';ok++}catch(e){fail++;console.error('done',e)}
 try{const allItems=td.items||[];let curSec='',todoHtml='';allItems.forEach(i=>{if(i.section!==curSec){curSec=i.section;todoHtml+='<div style="color:var(--blue);margin-top:6px;font-weight:bold">'+esc(curSec)+'</div>'}const cls=i.done?'item done':'item open';const icon=i.done?'✓':'○';todoHtml+='<div class="'+cls+'"><span>'+icon+'</span> '+esc(S(i.text,150))+'</div>'});$('todo-list').innerHTML=todoHtml||'<div style="color:var(--dim)">No items</div>';ok++}catch(e){fail++;console.error('todo',e)}
 try{const les=d.lessons||[];$('lesson-count').textContent='('+les.length+')';$('lessons').innerHTML=les.length?les.slice(-8).map(l=>'<div class="lesson">['+esc(l.category||'')+'] '+esc(S(l.lesson,100))+'</div>').join(''):'<div style="color:var(--dim)">No lessons yet</div>';ok++}catch(e){fail++;console.error('les',e)}
 try{const tl=d.timeline||[];$('timeline').innerHTML=tl.length?tl.slice(-12).reverse().map(e=>{const t=(e.timestamp||'').split('T')[1]||'';return '<div class="tl-item"><span class="time">'+t+'</span><span class="role">'+esc(e.role||'')+'</span><span class="msg">'+esc(S(e.content,60))+'</span></div>'}).join(''):'<div style="color:var(--dim)">No events</div>';ok++}catch(e){fail++;console.error('tl',e)}
 try{const flow=d.task_flow||{},nodes=flow.nodes||[];let fH='';if(nodes.length){nodes.forEach((n,i)=>{const sc=n.status==='completed'?'var(--green)':n.status==='running'?'var(--blue)':n.status==='blocked'?'var(--red)':'var(--border)';fH+='<div style="min-width:140px;background:#1c2128;border:2px solid '+sc+';border-radius:6px;padding:8px"><div style="font-size:10px;color:var(--dim)">STEP '+(i+1)+'</div><div style="font-size:11px;margin-top:3px;font-weight:bold">'+esc(n.label||n.id||'')+'</div><div style="font-size:10px;color:var(--dim);margin-top:2px">'+esc(n.owner||'')+'</div><div style="font-size:10px;color:var(--yellow);margin-top:2px">'+esc(n.eta||'')+'</div></div>';if(i<nodes.length-1)fH+='<div style="align-self:center;color:var(--blue);font-size:18px;padding:0 4px">→</div>'})}else{fH='<div style="color:var(--dim)">No task flow</div>'}$('task-flow').innerHTML=fH;ok++}catch(e){fail++;console.error('flow',e)}
 $('refresh').textContent='Last: '+new Date().toLocaleTimeString()+' | 2s | '+ok+' OK'+(fail?' | '+fail+' ERR':'');
}
R();setInterval(R,2000);
</script>
</body>
</html>"""


class DashboardHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/api/state":
            state = collect_state()
            body = json.dumps(state).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(body)
        else:
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(DASHBOARD_HTML.encode())

    def log_message(self, format, *args):
        pass  # Suppress access logs


def main():
    preferred = int(os.environ.get("LOCAL_AGENT_DASHBOARD_PORT", "8411"))
    server = None
    port = preferred
    for candidate in range(preferred, preferred + 5):
        try:
            server = HTTPServer(("127.0.0.1", candidate), DashboardHandler)
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
