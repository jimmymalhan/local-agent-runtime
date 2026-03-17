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

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "scripts"))


def load_json(path: pathlib.Path) -> dict:
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def collect_state() -> dict:
    return {
        "progress": load_json(REPO_ROOT / "state" / "progress.json"),
        "session": load_json(REPO_ROOT / "state" / "session-state.json"),
        "resource": load_json(REPO_ROOT / "state" / "resource-status.json"),
        "lock": load_json(REPO_ROOT / "state" / "run.lock"),
        "roi": load_json(REPO_ROOT / "state" / "roi-metrics.json"),
        "coordination": load_json(REPO_ROOT / "state" / "agent-coordination.json"),
        "takeover": load_json(REPO_ROOT / "state" / "takeover-recommendation.json"),
        "runtime": load_json(REPO_ROOT / "config" / "runtime.json"),
        "lessons": _load_lessons(),
        "server_time": datetime.now().isoformat(timespec="seconds"),
    }


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
<title>Local Agent Runtime</title>
<style>
:root {
  --bg: #0d1117; --fg: #c9d1d9; --green: #3fb950; --yellow: #d29922;
  --red: #f85149; --blue: #58a6ff; --dim: #484f58; --card: #161b22;
  --border: #30363d; --font: 'SF Mono', 'Cascadia Code', 'Fira Code', monospace;
}
* { margin: 0; padding: 0; box-sizing: border-box; }
body { background: var(--bg); color: var(--fg); font-family: var(--font); font-size: 13px; padding: 16px; }
h1 { font-size: 16px; color: var(--blue); margin-bottom: 12px; }
h2 { font-size: 13px; color: var(--dim); text-transform: uppercase; letter-spacing: 1px; margin: 16px 0 8px; }
.grid { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.card { background: var(--card); border: 1px solid var(--border); border-radius: 6px; padding: 12px; }
.card.full { grid-column: 1 / -1; }
.bar-wrap { display: flex; align-items: center; gap: 8px; margin: 4px 0; }
.bar-label { min-width: 100px; color: var(--dim); }
.bar { flex: 1; height: 16px; background: #21262d; border-radius: 3px; overflow: hidden; }
.bar-fill { height: 100%; border-radius: 3px; transition: width 0.5s; }
.bar-fill.green { background: var(--green); }
.bar-fill.yellow { background: var(--yellow); }
.bar-fill.red { background: var(--red); }
.bar-fill.blue { background: var(--blue); }
.bar-pct { min-width: 50px; text-align: right; }
.status { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 6px; }
.status.running { background: var(--green); animation: pulse 1.5s infinite; }
.status.completed { background: var(--green); }
.status.failed { background: var(--red); }
.status.pending { background: var(--dim); }
.status.idle { background: var(--dim); }
@keyframes pulse { 0%,100% { opacity: 1; } 50% { opacity: 0.4; } }
.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 16px; }
.timer { font-size: 20px; color: var(--green); font-weight: bold; }
.timer.idle { color: var(--dim); }
.task-name { color: var(--fg); font-size: 14px; margin-top: 4px; }
.lesson { padding: 6px 8px; background: #1c2128; border-left: 3px solid var(--yellow); margin: 4px 0; font-size: 12px; }
.collision { padding: 6px 8px; background: #1c2128; border-left: 3px solid var(--red); margin: 4px 0; font-size: 12px; }
table { width: 100%; border-collapse: collapse; }
td, th { padding: 4px 8px; text-align: left; border-bottom: 1px solid var(--border); }
th { color: var(--dim); font-weight: normal; }
.tag { display: inline-block; padding: 1px 6px; border-radius: 3px; font-size: 11px; }
.tag.local { background: #0d419d; color: var(--blue); }
.tag.cloud { background: #5a3e00; color: var(--yellow); }
</style>
</head>
<body>
<div class="header">
  <div>
    <h1>Local Agent Runtime</h1>
    <div class="task-name" id="task">Loading...</div>
  </div>
  <div class="timer" id="timer">--</div>
</div>

<div class="grid">
  <div class="card full">
    <h2>Task Progress</h2>
    <div class="bar-wrap">
      <span class="bar-label"><span class="status" id="overall-status"></span>Overall</span>
      <div class="bar"><div class="bar-fill green" id="overall-bar"></div></div>
      <span class="bar-pct" id="overall-pct">0%</span>
    </div>
    <div class="bar-wrap">
      <span class="bar-label">Local</span>
      <div class="bar"><div class="bar-fill blue" id="local-bar"></div></div>
      <span class="bar-pct" id="local-pct">0%</span>
    </div>
    <div class="bar-wrap">
      <span class="bar-label">Cloud</span>
      <div class="bar"><div class="bar-fill yellow" id="cloud-bar"></div></div>
      <span class="bar-pct" id="cloud-pct">0%</span>
    </div>
  </div>

  <div class="card">
    <h2>Resources</h2>
    <div class="bar-wrap">
      <span class="bar-label">CPU</span>
      <div class="bar"><div class="bar-fill green" id="cpu-bar"></div></div>
      <span class="bar-pct" id="cpu-pct">0%</span>
    </div>
    <div class="bar-wrap">
      <span class="bar-label">Memory</span>
      <div class="bar"><div class="bar-fill green" id="mem-bar"></div></div>
      <span class="bar-pct" id="mem-pct">0%</span>
    </div>
    <div id="roi-status" style="margin-top:8px;color:var(--dim)"></div>
  </div>

  <div class="card">
    <h2>Model Usage</h2>
    <div id="model-usage">Loading...</div>
  </div>

  <div class="card full">
    <h2>Roles</h2>
    <div id="roles">Loading...</div>
  </div>

  <div class="card">
    <h2>Agent Coordination</h2>
    <div id="coordination">No active claims</div>
  </div>

  <div class="card">
    <h2>Runtime Lessons</h2>
    <div id="lessons">No lessons recorded</div>
  </div>
</div>

<script>
function barColor(pct) { return pct > 70 ? 'red' : pct > 50 ? 'yellow' : 'green'; }

function elapsed(startedAt) {
  if (!startedAt) return '--';
  const start = new Date(startedAt);
  const now = new Date();
  const s = Math.max(0, Math.floor((now - start) / 1000));
  const m = Math.floor(s / 60), sec = s % 60;
  const h = Math.floor(m / 60), min = m % 60;
  if (h) return h + 'h ' + min + 'm ' + sec + 's';
  if (min) return min + 'm ' + sec + 's';
  return sec + 's';
}

function setBar(id, pct, colorClass) {
  const el = document.getElementById(id);
  if (el) { el.style.width = Math.min(100, Math.max(0, pct)) + '%'; if (colorClass) { el.className = 'bar-fill ' + colorClass; } }
}

async function refresh() {
  try {
    const res = await fetch('/api/state');
    const d = await res.json();
    const p = d.progress || {};
    const o = p.overall || {};
    const task = p.task || 'no active task';
    const status = o.status || 'idle';
    const pct = o.percent || 0;

    document.getElementById('task').textContent = task;
    document.getElementById('timer').textContent = status === 'running' ? elapsed(p.started_at) : status;
    document.getElementById('timer').className = 'timer' + (status !== 'running' ? ' idle' : '');
    document.getElementById('overall-status').className = 'status ' + status;
    setBar('overall-bar', pct, 'green');
    document.getElementById('overall-pct').textContent = pct.toFixed(1) + '%';

    const exec = (d.session || {}).execution || {};
    const localPct = parseFloat(exec.local_models || (status === 'running' ? 100 : 0));
    const cloudPct = parseFloat(exec.cloud_session || 0);
    setBar('local-bar', localPct, 'blue');
    setBar('cloud-bar', cloudPct, 'yellow');
    document.getElementById('local-pct').textContent = localPct.toFixed(1) + '%';
    document.getElementById('cloud-pct').textContent = cloudPct.toFixed(1) + '%';

    const r = d.resource || {};
    const cpu = parseFloat(r.cpu_percent || 0);
    const mem = parseFloat(r.memory_percent || 0);
    setBar('cpu-bar', cpu, barColor(cpu));
    setBar('mem-bar', mem, barColor(mem));
    document.getElementById('cpu-pct').textContent = cpu.toFixed(1) + '%';
    document.getElementById('mem-pct').textContent = mem.toFixed(1) + '%';

    const roi = d.roi || {};
    document.getElementById('roi-status').textContent = roi.kill_switch ? 'ROI Kill Switch: ACTIVE' : 'ROI: healthy';
    document.getElementById('roi-status').style.color = roi.kill_switch ? 'var(--red)' : 'var(--green)';

    // Roles
    const stages = (p.stages || []);
    let rolesHtml = '';
    stages.forEach(s => {
      const sp = s.percent || 0;
      const st = s.status || 'pending';
      const detail = s.detail ? ' | ' + s.detail : '';
      rolesHtml += '<div class="bar-wrap"><span class="bar-label"><span class="status ' + st + '"></span>' + (s.label || s.id) + '</span>';
      rolesHtml += '<div class="bar"><div class="bar-fill green" style="width:' + sp + '%"></div></div>';
      rolesHtml += '<span class="bar-pct">' + sp.toFixed(1) + '%</span></div>';
    });
    document.getElementById('roles').innerHTML = rolesHtml || 'No stages';

    // Model usage
    const team = (d.runtime || {}).team || {};
    const providers = {};
    stages.forEach(s => {
      if (s.id === 'preflight') return;
      let prov = 'ollama';
      const det = s.detail || '';
      if (det.includes('github_models')) prov = 'github_models';
      else if (det.includes('clawbot')) prov = 'clawbot';
      else if (det.includes('openclaw')) prov = 'openclaw';
      if (!providers[prov]) providers[prov] = {total: 0, completed: 0, models: new Set()};
      providers[prov].total++;
      if (s.status === 'completed') providers[prov].completed++;
      providers[prov].models.add((team[s.id] || {}).model || '?');
    });
    let muHtml = '<table><tr><th>Provider</th><th>%</th><th>Done</th><th>Models</th></tr>';
    const totalStages = Object.values(providers).reduce((a, v) => a + v.total, 0) || 1;
    Object.entries(providers).sort().forEach(([name, info]) => {
      const ppct = (info.total / totalStages * 100).toFixed(1);
      const tag = name === 'ollama' ? 'local' : 'cloud';
      muHtml += '<tr><td><span class="tag ' + tag + '">' + name + '</span></td><td>' + ppct + '%</td><td>' + info.completed + '/' + info.total + '</td><td>' + [...info.models].join(', ') + '</td></tr>';
    });
    muHtml += '</table>';
    document.getElementById('model-usage').innerHTML = muHtml;

    // Coordination
    const coord = d.coordination || {};
    const claims = coord.claims || [];
    const collisions = coord.collisions || [];
    let coordHtml = '';
    if (claims.length) {
      claims.forEach(c => { coordHtml += '<div>' + c.role + ': ' + (c.files || []).join(', ') + '</div>'; });
    } else { coordHtml = 'No active claims'; }
    if (collisions.length) {
      collisions.slice(-3).forEach(c => {
        coordHtml += '<div class="collision">' + c.file + ' — ' + c.claimed_by + ' vs ' + c.requested_by + '</div>';
      });
    }
    document.getElementById('coordination').innerHTML = coordHtml;

    // Lessons
    const lessons = d.lessons || [];
    let lHtml = '';
    if (lessons.length) {
      lessons.slice(-5).forEach(l => {
        lHtml += '<div class="lesson">[' + l.category + '] ' + l.lesson + '</div>';
      });
    } else { lHtml = 'No lessons recorded'; }
    document.getElementById('lessons').innerHTML = lHtml;

  } catch(e) { console.error(e); }
}

refresh();
setInterval(refresh, 2000);
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
    port = int(os.environ.get("LOCAL_AGENT_DASHBOARD_PORT", "8411"))
    server = HTTPServer(("127.0.0.1", port), DashboardHandler)
    print(f"Local Agent Dashboard running at http://localhost:{port}")
    print("Press Ctrl+C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        server.shutdown()
        print("\nDashboard stopped.")


if __name__ == "__main__":
    main()
