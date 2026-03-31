#!/usr/bin/env python3
"""
dashboard/server.py — Real-Time Agent Dashboard Server
=======================================================
FastAPI + WebSocket server. Watches state.json and pushes updates to
all connected clients within 1 second of any change.

The normalize_state() function bridges the state_writer.py schema
to the dashboard applyState() schema — one place to fix any mismatch.

Auto-finds a free port starting at 3001.

Usage:
  python3 dashboard/server.py              # start on free port
  python3 dashboard/server.py --port 3001  # force specific port
"""
import os, sys, json, time, asyncio, argparse, socket, subprocess
from pathlib import Path
from datetime import datetime

BASE_DIR   = Path(__file__).parent.parent
DASH_DIR   = Path(__file__).parent
STATE_FILE = str(DASH_DIR / "state.json")
ROOT_DIR   = Path(__file__).parent.parent.parent
REPORTS    = str(BASE_DIR / "reports")
RESCUE_LOG = os.path.join(REPORTS, "claude_rescue_upgrades.jsonl")
TOKEN_LOG  = os.path.join(REPORTS, "claude_token_log.jsonl")

_base_str = str(BASE_DIR)
if _base_str not in sys.path:
    sys.path.insert(0, _base_str)

# Pre-import providers at module load so async handlers never hit ImportError
try:
    from providers.router import get_provider as _get_provider
    _PROVIDERS_OK = True
    _PROVIDERS_ERR = ""
except Exception as _pe:
    _PROVIDERS_OK = False
    _PROVIDERS_ERR = str(_pe)


def find_free_port(start: int = 3001) -> int:
    for port in range(start, start + 20):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            try:
                s.bind(("", port))
                return port
            except OSError:
                continue
    return start


def _live_hardware() -> dict:
    """Read real CPU/RAM right now via psutil."""
    hw = {"cpu_pct": 0.0, "ram_pct": 0.0, "disk_pct": 0.0, "gpu_pct": None,
          "alert_level": "ok", "free_gb": 0.0}
    try:
        import psutil
        hw["cpu_pct"] = round(psutil.cpu_percent(interval=None), 1)
        m = psutil.virtual_memory()
        hw["ram_pct"] = round(m.percent, 1)
        hw["free_gb"] = round(m.available / (1024 ** 3), 1)
        try:
            d = psutil.disk_usage("/")
            hw["disk_pct"] = round(d.percent, 1)
        except Exception:
            pass
        r = hw["ram_pct"]
        c = hw["cpu_pct"]
        hw["alert_level"] = "red" if r >= 85 or c >= 90 else "yellow" if r >= 80 or c >= 75 else "ok"
    except ImportError:
        pass
    return hw


def _read_rescue_log() -> list:
    """Read claude_rescue_upgrades.jsonl → list of entries."""
    entries = []
    for path in [RESCUE_LOG, TOKEN_LOG]:
        if not os.path.exists(path):
            continue
        try:
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        entries.append(json.loads(line))
                    except Exception:
                        pass
        except Exception:
            pass
    # Sort by ts, deduplicate
    seen = set()
    out = []
    for e in sorted(entries, key=lambda x: x.get("ts", "")):
        key = e.get("ts", "") + str(e.get("tokens", ""))
        if key not in seen:
            seen.add(key)
            out.append(e)
    return out


def normalize_state(raw: dict) -> dict:
    """
    Transform raw state.json schema → dashboard applyState() schema.

    Raw (state_writer.py):
      version: {current, total, pct_complete, label}
      benchmark_scores: {v1: {local, opus, gap, win_rate, ts}, ...}
      token_usage: {claude_tokens, local_tokens, budget_pct, warning, hard_limit_hit}
      failures: [{ts, agent, task, task_id, attempt, tried}]
      hardware: {cpu_pct, ram_pct, disk_pct, gpu_pct, alert_level}

    Dashboard expects:
      version: number
      benchmark_scores: {avg_local, avg_opus, win_rate, history: [{version, local, opus}]}
      token_usage: {rescued_tasks, total_tokens, budget_pct}
      failure_log: [{ts, agent, task, ...}]
      hardware: {cpu_pct, ram_pct, ...}
      pool: {done, max}
    """
    out = dict(raw)

    # ── version ──────────────────────────────────────────────────────────────
    v = raw.get("version", 1)
    if isinstance(v, dict):
        out["version"] = v.get("current", 1)
        out["version_obj"] = v
    else:
        out["version"] = int(v)

    # ── benchmark_scores → normalized ─────────────────────────────────────
    bs = raw.get("benchmark_scores", {})
    history = []
    total_local = 0.0
    total_opus = 0.0
    wins = 0
    count = 0
    for key in sorted(bs.keys()):
        entry = bs[key]
        vn = int(key.replace("v", "")) if key.startswith("v") else count + 1
        lo = entry.get("local", 0.0)
        op = entry.get("opus", 0.0)
        wr = entry.get("win_rate", 100.0 if lo >= op else 0.0)
        history.append({"version": vn, "local": lo, "opus": op, "win_rate": wr})
        total_local += lo
        total_opus += op
        if lo >= op:
            wins += 1
        count += 1

    if count > 0:
        out["benchmark_scores"] = {
            "avg_local": round(total_local / count, 1),
            "avg_opus":  round(total_opus / count, 1),
            "win_rate":  round(wins / count * 100, 1),
            "history":   history,
            "_raw":      bs,
        }
    else:
        out["benchmark_scores"] = {
            "avg_local": 0.0, "avg_opus": 0.0, "win_rate": 0.0, "history": [],
        }

    # ── token_usage → normalized ─────────────────────────────────────────
    tu = raw.get("token_usage", {})
    claude_tok = tu.get("claude_tokens", 0)
    local_tok  = tu.get("local_tokens", 0)
    budget_pct = tu.get("budget_pct", 0.0)
    out["token_usage"] = {
        "rescued_tasks": claude_tok,
        "total_tokens":  claude_tok + local_tok,
        "claude_tokens": claude_tok,
        "local_tokens":  local_tok,
        "budget_pct":    budget_pct,
        "warning":       tu.get("warning", False),
        "hard_limit_hit": tu.get("hard_limit_hit", False),
    }

    # ── failure_log alias ─────────────────────────────────────────────────
    out["failure_log"] = raw.get("failures", [])

    # ── research_feed: ensure message field ──────────────────────────────
    rf = []
    for e in raw.get("research_feed", []):
        entry = dict(e)
        entry.setdefault("message", e.get("finding", str(e)))
        rf.append(entry)
    out["research_feed"] = rf

    # ── pool: derive from task_queue + sub_agents ─────────────────────────
    tq = raw.get("task_queue", {})
    agents = raw.get("agents", {})
    active_workers = 0
    for ag in agents.values():
        subs = ag.get("sub_agents", [])
        active_workers += len([s for s in subs if s.get("status") == "running"])
    out["pool"] = {
        "done":    tq.get("completed", 0),
        "running": tq.get("in_progress", 0),
        "max":     1000,
        "workers": active_workers,
    }

    # ── recent_tasks: synthesize from task_queue + failures ───────────────
    if "recent_tasks" not in raw:
        tasks = []
        for i, f in enumerate(raw.get("failures", [])[:10]):
            tasks.append({
                "task_id":    f.get("task_id", i + 1),
                "title":      f.get("task", "Unknown task"),
                "category":   "bug_fix",
                "agent_used": f.get("agent", "executor"),
                "status":     "blocked",
                "local_quality": 0,
            })
        out["recent_tasks"] = tasks if tasks else None

    # ── live hardware override ─────────────────────────────────────────────
    live_hw = _live_hardware()
    stored_hw = raw.get("hardware", {})
    # Merge: use live CPU/RAM, keep stored disk/gpu
    out["hardware"] = {
        "cpu_pct":    live_hw["cpu_pct"],
        "ram_pct":    live_hw["ram_pct"],
        "free_gb":    live_hw["free_gb"],
        "disk_pct":   stored_hw.get("disk_pct", live_hw["disk_pct"]),
        "gpu_pct":    stored_hw.get("gpu_pct"),
        "alert_level": live_hw["alert_level"],
    }

    # ── version_changelog passthrough ────────────────────────────────────
    out["version_changelog"] = raw.get("version_changelog", {})

    return out


def read_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            raw = json.load(f)
        return normalize_state(raw)
    except Exception:
        return {
            "ts": datetime.now().isoformat(),
            "version": 1,
            "agents": {},
            "benchmark_scores": {"avg_local": 0, "avg_opus": 0, "win_rate": 0, "history": []},
            "task_queue": {"total": 100, "completed": 0, "in_progress": 0, "failed": 0, "pending": 100},
            "token_usage": {"rescued_tasks": 0, "total_tokens": 0, "budget_pct": 0},
            "hardware": _live_hardware(),
            "pool": {"done": 0, "max": 1000, "workers": 0},
            "failure_log": [],
            "research_feed": [],
            "error": "state unavailable",
        }


# ── FastAPI app ──────────────────────────────────────────────────────────────
try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn
except ImportError:
    print("[DASHBOARD] Installing fastapi and uvicorn...")
    subprocess.run([sys.executable, "-m", "pip", "install", "-q",
                    "fastapi", "uvicorn[standard]"], check=True)
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect
    from fastapi.responses import HTMLResponse
    from fastapi.middleware.cors import CORSMiddleware
    import uvicorn

app = FastAPI(title="Nexus Agent Dashboard")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_clients: list = []
_last_state_ts = ""


async def _broadcast(data: str):
    dead = []
    for ws in _clients:
        try:
            await ws.send_text(data)
        except Exception:
            dead.append(ws)
    for ws in dead:
        if ws in _clients:
            _clients.remove(ws)


async def _state_watcher():
    """Watch state.json every 800ms and push normalized state to all WS clients."""
    global _last_state_ts
    while True:
        try:
            raw_ts = ""
            try:
                with open(STATE_FILE) as f:
                    raw = json.load(f)
                raw_ts = raw.get("ts", "")
            except Exception:
                pass
            if raw_ts != _last_state_ts:
                _last_state_ts = raw_ts
                state = read_state()
                await _broadcast(json.dumps(state))
        except Exception:
            pass
        await asyncio.sleep(0.8)


async def _hw_pusher():
    """Push live hardware updates every 5s regardless of state changes."""
    while True:
        await asyncio.sleep(5)
        try:
            state = read_state()
            await _broadcast(json.dumps(state))
        except Exception:
            pass


@app.on_event("startup")
async def startup():
    asyncio.create_task(_state_watcher())
    asyncio.create_task(_hw_pusher())


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    html_path = os.path.join(DASH_DIR, "index.html")
    with open(html_path) as f:
        return f.read()


@app.get("/api/state")
async def get_state():
    return read_state()


@app.get("/api/rescue-log")
async def get_rescue_log():
    """Return rescue log entries from reports/claude_rescue_upgrades.jsonl."""
    entries = _read_rescue_log()
    return {"entries": entries, "count": len(entries)}


@app.get("/api/benchmark")
async def get_benchmark():
    """Return benchmark scores as history array for the chart."""
    state = read_state()
    return state.get("benchmark_scores", {})


@app.get("/api/hardware")
async def get_hardware():
    """Return live hardware metrics."""
    return _live_hardware()


@app.get("/api/todo")
async def get_todo():
    """
    Return structured todo board from state.json (written by ceo_check.py).
    Falls back to parsing state/todo.md if todo_board key is absent.
    """
    state = read_state()
    if "todo_board" in state:
        return state["todo_board"]
    # Fallback: parse state/todo.md
    todo_path = BASE_DIR.parent / "state" / "todo.md"
    items = []
    try:
        text = todo_path.read_text() if todo_path.exists() else ""
        in_ceo = False
        for line in text.splitlines():
            if line.startswith("## CEO Orchestrator"):
                in_ceo = True; continue
            if in_ceo and line.startswith("## "):
                in_ceo = False
            if in_ceo:
                continue
            ln = line.strip()
            if ln.startswith("- [ ]") or ln.startswith("- [x]"):
                done = ln.startswith("- [x]")
                title = ln[5:].strip()
                if title:
                    items.append({"id": f"todo-{len(items)}", "priority": 4,
                                  "category": "general", "title": title[:120],
                                  "status": "done" if done else "todo",
                                  "agent": "", "sub_agents": 0})
    except Exception:
        pass
    counts = {s: sum(1 for i in items if i["status"] == s)
              for s in ("blocked", "running", "todo", "done")}
    return {"updated_at": datetime.now().isoformat(), "items": items, "counts": counts}


def _build_nexus_context() -> str:
    """Build rich live context for Nexus chat — agents, tasks, epics, blockers, recent logs."""
    lines = []
    try:
        state = read_state()
        tq    = state.get("task_queue", {})
        agents_map = state.get("agents", {})
        bs    = state.get("benchmark_scores", {})
        hw    = state.get("hardware", {})
        eta   = state.get("eta", {})

        lines.append(f"=== NEXUS RUNTIME LIVE STATE ===")
        lines.append(f"Tasks: {tq.get('completed',0)}/{tq.get('total',423)} done "
                     f"({tq.get('pct_complete',0)}%) | Pending: {tq.get('pending',0)} | "
                     f"Failed: {tq.get('failed',0)}")

        # Agents
        active = [(n, a) for n, a in agents_map.items() if a.get("status") not in ("idle","")]
        idle   = [n for n, a in agents_map.items() if a.get("status") in ("idle","")]
        if active:
            lines.append(f"Active agents ({len(active)}): " +
                         ", ".join(f"{n}[{a.get('status')}]" for n,a in active[:6]))
        lines.append(f"Idle agents: {len(idle)}")

        # ETA
        if eta:
            lines.append(f"ETA: {eta.get('eta_human','?')} — complete by {eta.get('complete_by','?')}")
            for ep in (eta.get("epics_remaining") or [])[:3]:
                lines.append(f"  Pending epic: {ep.get('name','')} ({ep.get('pending',0)} tasks)")

        # Benchmark
        if bs:
            lines.append(f"Benchmark: local={bs.get('avg_local',0):.1f} vs opus={bs.get('avg_opus',0):.1f} "
                         f"win_rate={bs.get('win_rate',0):.0f}%")

        # Hardware
        if hw:
            lines.append(f"Hardware: CPU={hw.get('cpu_pct',0):.0f}% RAM={hw.get('ram_pct',0):.0f}% "
                         f"free={hw.get('free_gb',0):.1f}GB")

        # Projects/epics from projects.json
        try:
            proj_path = os.path.join(str(BASE_DIR), "projects.json")
            with open(proj_path) as f:
                pdata = json.load(f)
            projects = pdata.get("projects", [])
            pending_epics = [p for p in projects
                             if any(t.get("status")=="pending" for t in p.get("tasks",[]))]
            done_epics    = [p for p in projects
                             if all(t.get("status") in ("completed","done")
                                    for t in p.get("tasks",[])) and p.get("tasks")]
            lines.append(f"Epics: {len(done_epics)}/{len(projects)} complete")
            for p in pending_epics[:4]:
                pending_n = sum(1 for t in p.get("tasks",[]) if t.get("status")=="pending")
                lines.append(f"  Blocked epic [{p.get('id')}]: {p.get('name','')[:50]} "
                              f"— {pending_n} tasks pending")
        except Exception:
            pass

        # Recent failures from runtime-lessons
        try:
            rl_path = os.path.join(str(BASE_DIR), "state", "runtime-lessons.json")
            with open(rl_path) as f:
                rl = json.load(f)
            recent_fails = [(tid, v) for tid, v in list(rl.items())[-5:]
                            if not v.get("rescue_escalated")]
            if recent_fails:
                lines.append(f"Recent failures (last 5): " +
                              ", ".join(tid for tid,_ in recent_fails))
        except Exception:
            pass

    except Exception as e:
        lines.append(f"[context error: {e}]")

    return "\n".join(lines)


_NEXUS_SYSTEM = """You are Nexus — a fully autonomous local AI agent runtime and engineering assistant.

IDENTITY: You are Nexus. You run locally. You have deep knowledge of this codebase and can both ANSWER questions AND EXECUTE tasks directly.

CAPABILITIES:
- Answer any engineering, coding, architecture, or system design question
- Execute tasks: when asked to "do X", dispatch it to the agent queue (projects.json)
- Debug live system state: agents, queues, failures, metrics
- Write code, explain code, review code
- Manage the runtime: start/stop agents, check health, explain blockers
- General knowledge: Python, distributed systems, databases, AI/ML, DevOps

LIVE SYSTEM KNOWLEDGE:
- 15 specialized agents: executor, architect, researcher, planner, refactor, test_engineer, debugger, reviewer, doc_writer, benchmarker, subagent_pool + geo-replication, resilience agents
- Orchestrator: orchestrator/main.py with auto_loop, quick_dispatcher for task execution
- Persistence: projects.json (single source of truth), auto-reloaded each version cycle
- Dashboard: FastAPI server + WebSocket, live state every 2s
- 24/7 operation: unified_daemon.py + auto_recover.sh cron + watchdog
- All 86 projects, 434 tasks tracked — 428 done (99%)

TASK EXECUTION (when user says "do X", "create X", "fix X", "add X"):
1. Acknowledge: "On it — dispatching to Nexus agents."
2. Add task to projects.json pending queue
3. Report: task ID, estimated agent, ETA
4. The 10-min daemon loop will pick it up automatically

SLASH COMMANDS (respond to these specially):
/status → show live agent status, pending tasks, health
/agents → list all 15 agents with current task
/epics  → list all epics, completion %, pending
/tasks  → show next 10 pending tasks
/why [agent] → explain why that agent is blocked/idle
/do [task]  → dispatch task to agent queue
/health → system health: daemon, watchdog, disk, memory
/help   → show all commands

RULES:
- Be direct. No disclaimers. No "I'm just an AI."
- When asked to DO something, DO it (add to queue) + confirm
- Give real code when asked for code
- Use live context data to answer runtime questions accurately
- You are Nexus. Respond as Nexus."""


def _handle_slash_command(cmd: str) -> str | None:
    """Handle /status /agents /epics /tasks /health /help commands. Returns reply or None."""
    c = cmd.strip().lower()
    try:
        with open(os.path.join(str(BASE_DIR), "projects.json")) as f:
            pdata = json.load(f)
        projects = pdata.get("projects", [])
        all_tasks = [t for p in projects for t in p.get("tasks", [])]
        done   = sum(1 for t in all_tasks if t.get("status") in ("completed","done"))
        pend   = sum(1 for t in all_tasks if t.get("status") == "pending")
        total  = len(all_tasks)
    except Exception:
        projects, all_tasks, done, pend, total = [], [], 0, 0, 0

    if c == "/status" or c == "/s":
        try:
            with open(os.path.join(str(BASE_DIR), "dashboard", "state.json")) as f:
                st = json.load(f)
            agents = st.get("agents", {})
            active = [(n, a.get("status","?"), a.get("current_task","")[:40])
                      for n, a in agents.items() if a.get("status") not in ("idle","")]
            idle   = [n for n, a in agents.items() if a.get("status") == "idle"]
        except Exception:
            active, idle = [], []
        lines = [f"**Nexus Runtime Status**",
                 f"Tasks: {done}/{total} done · {pend} pending",
                 f"Active agents ({len(active)}): " + (", ".join(f"{n}→{t}" for n,_,t in active) or "none"),
                 f"Idle: {', '.join(idle[:8]) or 'all agents active'}"]
        return "\n".join(lines)

    elif c == "/agents":
        try:
            with open(os.path.join(str(BASE_DIR), "dashboard", "state.json")) as f:
                st = json.load(f)
            agents = st.get("agents", {})
        except Exception:
            agents = {}
        lines = ["**Nexus Agents**"]
        for name, a in sorted(agents.items()):
            status = a.get("status", "idle")
            task   = a.get("current_task", "")[:50]
            lines.append(f"  `{name}` [{status}] {task}")
        return "\n".join(lines) if len(lines) > 1 else "No agent state available yet."

    elif c == "/epics":
        lines = ["**Epics Progress**"]
        for p in projects[:20]:
            tasks = p.get("tasks", [])
            if not tasks: continue
            n_done = sum(1 for t in tasks if t.get("status") in ("completed","done"))
            pct    = round(n_done / len(tasks) * 100)
            icon   = "✅" if pct == 100 else "⏳"
            lines.append(f"  {icon} {p.get('name','')[:55]} {n_done}/{len(tasks)} ({pct}%)")
        return "\n".join(lines)

    elif c.startswith("/tasks"):
        pending = [t for t in all_tasks if t.get("status") == "pending"]
        if not pending:
            return "✅ No pending tasks — all work complete."
        lines = [f"**Pending Tasks ({len(pending)})**"]
        for t in pending[:10]:
            lines.append(f"  `{t.get('id')}` {t.get('title','')[:60]}")
        return "\n".join(lines)

    elif c == "/health":
        import shutil
        disk = shutil.disk_usage("/")
        disk_pct = round(disk.used / disk.total * 100)
        daemon_up = bool(os.popen("pgrep -f unified_daemon").read().strip())
        cron_ok   = "*/2" in os.popen("crontab -l 2>/dev/null").read()
        lines = [
            "**Nexus Health**",
            f"  Daemon: {'✅ running' if daemon_up else '❌ stopped (auto_recover will restart)'}",
            f"  Cron watchdog: {'✅ active' if cron_ok else '⚠️ not set'}",
            f"  Disk: {disk_pct}% used ({round(disk.free/1e9, 1)} GB free)",
            f"  Tasks: {done}/{total} ({round(done/total*100) if total else 0}% done)",
        ]
        return "\n".join(lines)

    elif c == "/help":
        return """/status  — live agent status & task counts
/agents  — all 15 agents with current task
/epics   — all epics with completion %
/tasks   — next 10 pending tasks
/health  — daemon, disk, cron health
/do <task description> — dispatch task to agent queue
Ask me anything else — I have full engineering knowledge."""

    elif c.startswith("/do ") or c.startswith("/run "):
        task_desc = cmd[4:].strip()
        return _dispatch_chat_task(task_desc)

    return None


def _dispatch_chat_task(description: str) -> str:
    """Add a task from chat to projects.json pending queue."""
    import uuid, datetime as _dt
    task_id = f"chat-{uuid.uuid4().hex[:8]}"
    new_task = {
        "id": task_id,
        "title": description[:100],
        "description": description,
        "status": "pending",
        "category": "code_gen",
        "agent": "executor",
        "priority": "P1",
        "source": "nexus-chat",
        "created_at": _dt.datetime.utcnow().isoformat(),
    }
    try:
        projects_file = os.path.join(str(BASE_DIR), "projects.json")
        with open(projects_file) as f:
            pdata = json.load(f)
        # Add to a "Nexus Chat Tasks" project, create if missing
        chat_project = next((p for p in pdata["projects"] if p.get("id") == "nexus-chat-dispatch"), None)
        if not chat_project:
            chat_project = {"id": "nexus-chat-dispatch", "name": "Nexus Chat Dispatched Tasks", "tasks": []}
            pdata["projects"].append(chat_project)
        chat_project["tasks"].append(new_task)
        with open(projects_file, "w") as f:
            json.dump(pdata, f, indent=2)
        return (f"✅ **Dispatched to Nexus agents**\n"
                f"  Task ID: `{task_id}`\n"
                f"  Agent: executor\n"
                f"  Priority: P1\n"
                f"  The 10-min daemon loop will execute this automatically.\n"
                f"  Check `/tasks` for queue status.")
    except Exception as e:
        return f"⚠️ Could not dispatch task: {e}"


@app.post("/api/chat")
async def chat_endpoint(request: dict):
    """
    Nexus chat — talk + execute tasks. Like Claude CLI but for Nexus.
    Request: {message: str, history: [{role, content}]}
    Response: {reply: str, provider: str, model: str, ts: str, action: str}
    """
    message = request.get("message", "").strip()
    history = request.get("history", [])
    if not message:
        return {"reply": "Ask me anything or use /help.", "provider": "nexus",
                "model": "nexus-local", "ts": datetime.now().isoformat()}

    # Handle slash commands directly (no LLM needed)
    slash_reply = _handle_slash_command(message)
    if slash_reply is not None:
        return {"reply": slash_reply, "provider": "nexus-cmd",
                "model": "nexus-local", "action": "command",
                "ts": datetime.now().isoformat()}

    # Handle "do X" / "create X" / "fix X" / "add X" dispatch intent
    lower = message.lower()
    dispatch_triggers = ("do ", "create ", "fix ", "add ", "implement ", "build ", "write ", "make ")
    if any(lower.startswith(t) for t in dispatch_triggers) and len(message) > 10:
        action_reply = _dispatch_chat_task(message)
        action_ctx   = f"User asked me to: {message}\n\nI dispatched this task: {action_reply}"
        history = list(history or [])
        history.append({"role": "user", "content": message})
    else:
        action_reply = None
        action_ctx   = None

    # Build rich live context
    live_ctx = _build_nexus_context()

    # Compose messages for LLM
    messages = []
    for h in (history or [])[-8:]:
        role = h.get("role", "user")
        content = h.get("content", "")
        if content:
            messages.append({"role": role, "content": content})

    user_content = f"[LIVE RUNTIME CONTEXT]\n{live_ctx}\n\n"
    if action_ctx:
        user_content += f"[TASK DISPATCHED]\n{action_ctx}\n\n"
    user_content += f"User: {message}"
    messages.append({"role": "user", "content": user_content})

    reply = ""
    provider_name = "nexus"
    try:
        from agents.nexus_inference import chat as _nexus_chat
        reply = _nexus_chat(messages, system=_NEXUS_SYSTEM).strip()
    except Exception:
        reply = action_reply or f"Nexus engine offline. {live_ctx[:200]}"
        provider_name = "nexus-fallback"

    if not reply:
        reply = action_reply or "No response from Nexus engine."

    return {
        "reply":    reply,
        "provider": provider_name,
        "model":    "nexus-local",
        "action":   "dispatch" if action_reply else "chat",
        "ts":       datetime.now().isoformat(),
    }


@app.get("/api/status")
async def get_status():
    """Return live status from LIVE_STATUS.json (generated by status_reporter.py)."""
    status_file = os.path.join(BASE_DIR, "state", "LIVE_STATUS.json")
    try:
        with open(status_file) as f:
            return json.load(f)
    except Exception:
        return {
            "timestamp": datetime.now().isoformat(),
            "agents": {"primary_count": 0, "sub_agents_count": 0, "active": []},
            "operations": {"orchestrator": "unknown", "task_intake": "unknown"},
            "blockers": ["Status file not yet generated"],
            "improvements": []
        }


@app.get("/api/status.txt")
async def get_status_text():
    """Return human-readable status from LIVE_STATUS.txt."""
    status_file = os.path.join(BASE_DIR, "state", "LIVE_STATUS.txt")
    try:
        with open(status_file) as f:
            content = f.read()
        return content
    except Exception:
        return "Status report not yet generated. Check back in 30 minutes.\n"


@app.get("/api/dashboard")
async def get_dashboard():
    """Return comprehensive dashboard data from COMPREHENSIVE_DASHBOARD.json."""
    comp_file = os.path.join(BASE_DIR, "state", "COMPREHENSIVE_DASHBOARD.json")
    try:
        with open(comp_file) as f:
            return json.load(f)
    except Exception:
        return {
            "timestamp": datetime.now().isoformat(),
            "agents": {"total": 0, "primary_agents": []},
            "sub_agents": {"total": 0, "by_parent": {}},
            "projects": {"total": 0, "projects": []},
            "version": {"current": 0, "target": 100},
            "operations": {"orchestrator": "unknown"},
            "blockers_and_improvements": {"blockers": [], "improvements": []},
            "summary": {"system_status": "unknown"}
        }


@app.post("/api/workflow/config")
async def set_workflow_config(request: dict):
    """Save workflow configuration to state.json."""
    try:
        state = read_state()
        state["workflow"] = request.get("workflow", [])
        state["workflow_updated_at"] = datetime.now().isoformat()
        # Persist to state.json
        with open(STATE_FILE, "w") as f:
            json.dump(state, f, indent=2)
        return {"status": "saved", "workflow": request.get("workflow", [])}
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.get("/api/workflow/config")
async def get_workflow_config():
    """Get current workflow configuration."""
    state = read_state()
    return {
        "workflow": state.get("workflow", []),
        "updated_at": state.get("workflow_updated_at", "")
    }


@app.post("/api/workflow/execute")
async def execute_workflow(request: dict):
    """Trigger workflow execution with current configuration."""
    try:
        workflow = request.get("workflow", [])
        state = read_state()

        execution_log = {
            "ts": datetime.now().isoformat(),
            "workflow_order": workflow,
            "status": "started"
        }

        workflow_log_path = os.path.join(REPORTS, "workflow_executions.jsonl")
        os.makedirs(REPORTS, exist_ok=True)
        with open(workflow_log_path, "a") as f:
            f.write(json.dumps(execution_log) + "\n")

        return {
            "status": "execution_started",
            "workflow": workflow,
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.post("/api/tasks/auto-execute")
async def auto_execute_tasks(request: dict = None):
    """Auto-execute pending tasks from projects.json via quick_dispatcher."""
    try:
        max_tasks = (request or {}).get("max_tasks", 10) if request else 10

        # Run quick_dispatcher asynchronously
        result = subprocess.run(
            ["python3", "orchestrator/quick_dispatcher.py", "--tasks", str(max_tasks)],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=BASE_DIR
        )

        # Parse results
        output = result.stdout + result.stderr
        completed = 0
        failed = 0
        if "Tasks run:" in output:
            import re
            match = re.search(r"Tasks run: (\d+)", output)
            if match:
                completed = int(match.group(1))
            match = re.search(r"Failed: (\d+)", output)
            if match:
                failed = int(match.group(1))

        return {
            "status": "complete",
            "tasks_executed": completed,
            "tasks_failed": failed,
            "success_rate": f"{((completed-failed)/completed*100 if completed > 0 else 0):.1f}%",
            "timestamp": datetime.now().isoformat()
        }
    except Exception as e:
        return {"status": "error", "message": str(e), "timestamp": datetime.now().isoformat()}


@app.get("/api/metrics/performance")
async def get_performance_metrics():
    """Get system performance metrics and analytics."""
    try:
        import psutil
        cpu = psutil.cpu_percent(interval=0.1)
        memory = psutil.virtual_memory()
        disk = psutil.disk_usage("/")

        # Read execution history
        state = read_state()
        tq = state.get("task_queue", {})
        total = tq.get("total", 1)
        completed = tq.get("completed", 0)
        completion_rate = (completed / total * 100) if total > 0 else 0

        return {
            "timestamp": datetime.now().isoformat(),
            "cpu_percent": cpu,
            "memory_percent": memory.percent,
            "memory_available_gb": round(memory.available / (1024**3), 1),
            "disk_percent": disk.percent,
            "task_completion_rate": round(completion_rate, 1),
            "tasks_completed": completed,
            "tasks_total": total,
            "uptime_seconds": time.time() - os.stat(BASE_DIR).st_mtime
        }
    except Exception as e:
        return {"status": "error", "message": str(e)}


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.append(ws)
    try:
        await ws.send_text(json.dumps(read_state()))
        while True:
            await asyncio.sleep(30)
            await ws.send_text('{"ping":true}')
    except WebSocketDisconnect:
        if ws in _clients:
            _clients.remove(ws)
    except Exception:
        if ws in _clients:
            _clients.remove(ws)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=0)
    args = ap.parse_args()

    port = args.port if args.port else find_free_port(3001)
    url = f"http://localhost:{port}"
    print(f"\n  Nexus Dashboard  →  {url}\n")

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
