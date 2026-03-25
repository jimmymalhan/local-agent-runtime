#!/usr/bin/env python3
"""
dashboard/server.py — Real-Time Agent Dashboard Server
=======================================================
FastAPI + WebSocket server. Watches state.json and pushes updates to
all connected clients within 1 second of any change.

Auto-finds a free port starting at 3001. Writes URL to DASHBOARD.txt.
Auto-restarts on crash.

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
DASH_TXT   = os.path.join(ROOT_DIR, "DASHBOARD.txt")

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


def write_dashboard_url(port: int):
    url = f"http://localhost:{port}"
    with open(DASH_TXT, "w") as f:
        f.write(f"Dashboard URL: {url}\n")
        f.write(f"Started: {datetime.now().isoformat()}\n")
        f.write(f"State file: {STATE_FILE}\n")
    print(f"[DASHBOARD] URL written to {DASH_TXT}")
    print(f"[DASHBOARD] Open: {url}")


def read_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {"ts": datetime.now().isoformat(), "error": "state unavailable"}


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

app = FastAPI(title="Local Agent Dashboard")
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
    """Watch state.json every 800ms and push changes to all WS clients."""
    global _last_state_ts
    while True:
        try:
            state = read_state()
            ts = state.get("ts", "")
            if ts != _last_state_ts:
                _last_state_ts = ts
                await _broadcast(json.dumps(state))
        except Exception:
            pass
        await asyncio.sleep(0.8)


@app.on_event("startup")
async def startup():
    asyncio.create_task(_state_watcher())


@app.get("/", response_class=HTMLResponse)
async def get_dashboard():
    html_path = os.path.join(DASH_DIR, "index.html")
    with open(html_path) as f:
        return f.read()


@app.get("/api/state")
async def get_state():
    return read_state()


@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await ws.accept()
    _clients.append(ws)
    # Send current state immediately on connect
    try:
        await ws.send_text(json.dumps(read_state()))
        while True:
            # Keep alive — just wait for disconnect
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
    write_dashboard_url(port)

    uvicorn.run(app, host="0.0.0.0", port=port, log_level="warning")


if __name__ == "__main__":
    main()
