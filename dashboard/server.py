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

BASE_DIR   = str(Path(__file__).parent.parent)
DASH_DIR   = str(Path(__file__).parent)
STATE_FILE = os.path.join(DASH_DIR, "state.json")
ROOT_DIR   = str(Path(__file__).parent.parent.parent)
REPORTS    = os.path.join(BASE_DIR, "reports")
RESCUE_LOG = os.path.join(REPORTS, "claude_rescue_upgrades.jsonl")
TOKEN_LOG  = os.path.join(REPORTS, "claude_token_log.jsonl")

sys.path.insert(0, BASE_DIR)


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


@app.post("/api/chat")
async def chat_endpoint(request: dict):
    """
    Nexus chat API — routes to best available local provider.
    Request: {message: str, history: [{role, content}]}
    Response: {reply: str, provider: str, ts: str}
    """
    message = request.get("message", "").strip()
    history = request.get("history", [])
    if not message:
        return {"reply": "No message provided.", "provider": "none", "ts": datetime.now().isoformat()}

    # Add live state context
    state = read_state()
    tq    = state.get("task_queue", {})
    agents = state.get("agents", {})
    active = [n for n, a in agents.items() if a.get("status") not in ("idle", "")]
    bs    = state.get("benchmark_scores", {})
    context = (
        f"Current runtime state: "
        f"Tasks {tq.get('completed',0)}/{tq.get('total',100)} done, "
        f"{tq.get('failed',0)} failed. "
        f"Active agents: {', '.join(active) if active else 'none'}. "
        f"Nexus score: {bs.get('avg_local',0)}, win rate: {bs.get('win_rate',0)}%."
    )

    system = (
        "You are Nexus — a local-first autonomous agent runtime. "
        "Answer questions about what the system is doing, why decisions were made, "
        "task status, repo structure, failures, benchmarks and upgrades. "
        "Be concise and direct. Answer as Nexus, not as any model brand."
    )

    full_prompt = f"{context}\n\nUser: {message}"

    # Try to route to local provider
    provider_name = "local"
    reply = ""
    try:
        import sys
        sys.path.insert(0, BASE_DIR)
        from providers.router import get_provider
        provider = get_provider("chat")
        provider_name = provider.name
        result = provider.complete(
            full_prompt, system=system, max_tokens=300, temperature=0.3, timeout=30
        )
        reply = result.text.strip() if result.ok else (result.error or "No response.")
    except Exception as e:
        reply = (
            f"I'm Nexus. System state: {tq.get('completed',0)}/{tq.get('total',100)} tasks done, "
            f"{len(active)} agents active. Dashboard: http://localhost:3001 "
            f"(Chat backend unavailable: {str(e)[:60]})"
        )
        provider_name = "fallback"

    return {
        "reply":    reply,
        "provider": provider_name,
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
