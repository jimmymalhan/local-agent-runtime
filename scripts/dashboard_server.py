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


def _load_todo() -> dict:
    """Parse state/todo.md into structured data for the dashboard."""
    todo_path = REPO_ROOT / "state" / "todo.md"
    if not todo_path.exists():
        return {"sections": [], "items": [], "stats": {"total": 0, "done": 0, "open": 0, "percent": 0.0}}
    items = []
    section = "General"
    for line in todo_path.read_text(errors="ignore").splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            section = stripped[3:].strip()
            continue
        if stripped.startswith("- [x]"):
            items.append({"text": stripped[5:].strip(), "done": True, "section": section})
        elif stripped.startswith("- [ ]"):
            items.append({"text": stripped[5:].strip(), "done": False, "section": section})
    done = sum(1 for i in items if i["done"])
    total = len(items)
    open_count = total - done

    # Classify blockers: open items with blocker-ish keywords
    blocker_kw = ["fix", "block", "stall", "fail", "stuck", "ceiling", "kill switch", "timeout", "error", "broken"]
    blockers = [i for i in items if not i["done"] and any(k in i["text"].lower() for k in blocker_kw)]
    working = [i for i in items if not i["done"] and i not in blockers]

    return {
        "items": items,
        "blockers": blockers,
        "working": working[:10],
        "stats": {
            "total": total,
            "done": done,
            "open": open_count,
            "percent": round(done / total * 100, 1) if total else 0.0,
        },
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
        "todo": _load_todo(),
        "sessions": _detect_sessions(),
        "timeline": _history_timeline(),
        "blocker_resolution": _resolve_blockers(),
        "etas": _compute_etas(),
        "local_agent_activity": _local_agent_activity(),
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
    <h2>Local Agent Activity</h2>
    <div id="agent-activity" style="max-height:200px;overflow-y:auto">No activity</div>
    <h2>Coordination</h2>
    <div id="coord">No claims</div>
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
</div>
<div class="refresh" id="refresh">Refreshing every 2s</div>
<script>
function bc(p){return p>85?'r':p>60?'y':'g'}
function el(s){if(!s)return'--';const d=new Date(s),n=new Date(),t=Math.max(0,Math.floor((n-d)/1e3)),m=Math.floor(t/60),s2=t%60,h=Math.floor(m/60),m2=m%60;return h?h+'h '+m2+'m '+s2+'s':m?m+'m '+s2+'s':s2+'s'}
function sb(id,p,c){const e=document.getElementById(id);if(e){e.style.width=Math.min(100,Math.max(0,p))+'%';if(c)e.className='bf '+c}}
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}

async function R(){
 try{
  const r=await fetch('/api/state'),d=await r.json();
  const p=d.progress||{},o=p.overall||{},st=o.status||'idle',pct=o.percent||0;
  document.getElementById('task').textContent=p.task||'idle';
  document.getElementById('timer').textContent=st==='running'?el(p.started_at):st;
  document.getElementById('timer').className='timer'+(st!=='running'?' idle':'');
  document.getElementById('os').className='dot '+st;
  sb('ob',pct,'g');document.getElementById('op').textContent=pct.toFixed(1)+'%';
  const ex=(d.session||{}).execution||{};
  const lp=parseFloat(ex.local_models||(st==='running'?100:0)),cp2=parseFloat(ex.cloud_session||0);
  sb('lb',lp,'b');sb('cb',cp2,'y');
  document.getElementById('lp').textContent=lp.toFixed(1)+'%';
  document.getElementById('cp').textContent=cp2.toFixed(1)+'%';
  const rs=d.resource||{},cpu=parseFloat(rs.cpu_percent||0),mem=parseFloat(rs.memory_percent||0);
  sb('cpub',cpu,bc(cpu));sb('memb',mem,bc(mem));
  document.getElementById('cpup').textContent=cpu.toFixed(1)+'%';
  document.getElementById('memp').textContent=mem.toFixed(1)+'%';
  const roi=d.roi||{};
  document.getElementById('roi').innerHTML=roi.kill_switch?'<span style="color:var(--red)">ROI KILL SWITCH ACTIVE</span>':'<span style="color:var(--green)">ROI: healthy</span>';

  // Todo
  const td=d.todo||{},ts=td.stats||{};
  sb('tb',ts.percent||0,'p');
  document.getElementById('tp').textContent=(ts.percent||0).toFixed(1)+'%';
  document.getElementById('todo-count').textContent='('+ts.done+'/'+ts.total+' done, '+ts.open+' open)';

  // Blockers with ETA
  const blockers=td.blockers||[];
  document.getElementById('blocker-count').textContent='('+blockers.length+')';
  if(blockers.length){
    let bkH='';
    if(br.type&&br.type!=='default'&&br.type!=='none'){
      bkH+='<div style="background:#2d1517;padding:6px;border-radius:4px;margin-bottom:6px"><span style="color:var(--red);font-weight:bold">ACTIVE: '+br.type.toUpperCase().replace(/_/g,' ')+'</span>';
      (br.options||[]).forEach((o,i)=>{
        const pick=i===0?' style="color:var(--green);font-weight:bold"':'';
        bkH+='<div style="font-size:10px;margin-top:2px"'+(i===0?pick:'')+'>'+(i===0?'>>> ':'    ')+'Option '+(i+1)+': '+esc(o.option)+' ('+( o.eta_seconds||'?')+'s)</div>';
      });
      bkH+='</div>';
    }
    bkH+=blockers.map(b=>'<div class="item blocker">'+esc(b.text.substring(0,120))+'<br><small>'+esc(b.section)+'</small></div>').join('');
    document.getElementById('blockers').innerHTML=bkH;
  }else{
    document.getElementById('blockers').innerHTML='<div style="color:var(--green)">No blockers!</div>';
  }

  // Working
  const working=td.working||[];
  document.getElementById('working-count').textContent='('+working.length+')';
  document.getElementById('working').innerHTML=working.length?working.map(w=>'<div class="item working">'+esc(w.text.substring(0,120))+'<br><small>'+esc(w.section)+'</small></div>').join(''):'Nothing in progress';

  // Done items
  const doneItems=(td.items||[]).filter(i=>i.done);
  document.getElementById('done-count').textContent='('+doneItems.length+')';
  document.getElementById('done-items').innerHTML=doneItems.length?doneItems.slice(-15).map(i=>'<div class="item done">'+esc(i.text.substring(0,100))+'</div>').join(''):'None yet';

  // Full todo
  const allItems=td.items||[];
  let curSec='';let todoHtml='';
  allItems.forEach(i=>{
    if(i.section!==curSec){curSec=i.section;todoHtml+='<div style="color:var(--blue);margin-top:6px;font-weight:bold">'+esc(curSec)+'</div>';}
    const cls=i.done?'item done':'item open';
    const icon=i.done?'✓':'○';
    todoHtml+='<div class="'+cls+'"><span>'+icon+'</span> '+esc(i.text.substring(0,150))+'</div>';
  });
  document.getElementById('todo-list').innerHTML=todoHtml||'No items';

  // Roles
  const stages=p.stages||[];
  document.getElementById('role-count').textContent='('+stages.filter(s=>s.status==='completed').length+'/'+stages.length+' done)';
  let rH='';stages.forEach(s=>{
    const sp=s.percent||0,ss=s.status||'pending',det=s.detail||'';
    rH+='<div class="bw"><span class="bl"><span class="dot '+ss+'"></span>'+(s.label||s.id)+'</span><div class="bar"><div class="bf g" style="width:'+sp+'%"></div></div><span class="bp">'+sp.toFixed(0)+'%</span></div>';
  });
  document.getElementById('roles').innerHTML=rH||'No roles';

  // Model usage
  const team=(d.runtime||{}).team||{},provs={};
  stages.forEach(s=>{if(s.id==='preflight')return;let pr='ollama';const dt=s.detail||'';if(dt.includes('github_models'))pr='github_models';else if(dt.includes('clawbot'))pr='clawbot';else if(dt.includes('openclaw'))pr='openclaw';if(!provs[pr])provs[pr]={t:0,c:0,m:new Set()};provs[pr].t++;if(s.status==='completed')provs[pr].c++;provs[pr].m.add((team[s.id]||{}).model||'?')});
  const tt=Object.values(provs).reduce((a,v)=>a+v.t,0)||1;
  let mH='<table><tr><th>Provider</th><th>%</th><th>Status</th></tr>';
  Object.entries(provs).sort().forEach(([n,i])=>{const pp=(i.t/tt*100).toFixed(0);const tg=n==='ollama'?'local':'cloud';mH+='<tr><td><span class="tag '+tg+'">'+n+'</span></td><td>'+pp+'%</td><td>'+i.c+'/'+i.t+'</td></tr>'});
  mH+='</table>';document.getElementById('mu').innerHTML=mH;

  // Sessions
  const sess=d.sessions||[];
  let sH='';
  if(sess.length){sess.forEach(s=>{
    const tg=s.type.replace('local-','');
    sH+='<div class="sess"><span class="dot '+(s.status||'active')+'"></span><span class="tag '+tg+'">'+s.type+'</span><span>'+esc((s.detail||'').substring(0,40))+'</span></div>';
  })}else{sH='<div style="color:var(--dim)">No active sessions detected</div>'}
  document.getElementById('sessions').innerHTML=sH;

  // ETAs
  const etas=d.etas||{};
  document.getElementById('eta-pipeline').textContent='Pipeline: '+(etas.pipeline_eta_display||'--')+' ('+( etas.remaining_roles||0)+' roles left)';
  document.getElementById('eta-todo').textContent='All tasks: '+(etas.todo_eta_display||'--')+' ('+( etas.open_tasks||0)+' open)';
  const br=d.blocker_resolution||{};
  const bOpts=br.options||[];
  const blockerEta=bOpts.length&&br.type!=='default'?(bOpts[0].eta_seconds||10)+'s (auto-pick: '+bOpts[0].option+')':'no blockers';
  document.getElementById('eta-blockers').textContent='Blocker fix: '+blockerEta;

  // Local Agent Activity
  const acts=d.local_agent_activity||[];
  let aH='';
  if(acts.length){acts.forEach(a=>{
    const dot=a.status==='running'?'running':a.status==='completed'?'completed':a.status==='failed'?'failed':'pending';
    const icon=a.status==='running'?'▶':a.status==='completed'?'✓':a.status==='failed'?'✗':'○';
    const files=(a.files||[]).length?' ['+a.files.slice(0,2).join(', ')+']':'';
    const model=a.model?' ('+a.model+')':'';
    aH+='<div style="font-size:11px;padding:3px 0;border-bottom:1px solid var(--border)"><span class="dot '+dot+'"></span><b>'+esc(a.label)+'</b> '+icon+' '+esc(a.detail.substring(0,50))+model+files+'<div class="bar" style="height:6px;margin-top:2px"><div class="bf g" style="width:'+a.percent+'%"></div></div></div>';
  })}else{aH='<div style="color:var(--dim)">No local agents active</div>'}
  document.getElementById('agent-activity').innerHTML=aH;

  // Coordination
  const co=d.coordination||{},cl=co.claims||[],col=co.collisions||[];
  let cH='';
  if(cl.length){cl.forEach(c=>{cH+='<div style="font-size:11px"><span class="tag agent">'+c.role+'</span> '+(c.files||[]).slice(0,3).join(', ')+'</div>'})}
  else{cH='<div style="color:var(--dim)">No file claims</div>'}
  if(col.length){col.slice(-3).forEach(c=>{cH+='<div class="collision">'+esc(c.file)+' — '+c.claimed_by+' vs '+c.requested_by+'</div>'})}
  document.getElementById('coord').innerHTML=cH;

  // Lessons
  const les=d.lessons||[];
  document.getElementById('lesson-count').textContent='('+les.length+')';
  document.getElementById('lessons').innerHTML=les.length?les.slice(-8).map(l=>'<div class="lesson">['+l.category+'] '+esc(l.lesson.substring(0,100))+'</div>').join(''):'No lessons yet';

  // Timeline
  const tl=d.timeline||[];
  document.getElementById('timeline').innerHTML=tl.length?tl.slice(-12).reverse().map(e=>{
    const t=(e.timestamp||'').split('T')[1]||'';
    return '<div class="tl-item"><span class="time">'+t+'</span><span class="role">'+esc(e.role||'')+'</span><span class="msg">'+esc((e.content||'').substring(0,60))+'</span></div>';
  }).join(''):'No events';

  document.getElementById('refresh').textContent='Last: '+new Date().toLocaleTimeString()+' • Refreshing every 2s';
 }catch(e){console.error(e)}
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
