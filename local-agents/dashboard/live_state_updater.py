#!/usr/bin/env python3
"""live_state_updater.py - Updates dashboard/state.json every 2 seconds."""
import os, json, time, subprocess
from datetime import datetime, timezone
from pathlib import Path

BASE = str(Path(__file__).parent.parent)
STATE = os.path.join(BASE, "dashboard", "state.json")
REPORTS = os.path.join(BASE, "reports")
INTERVAL = 2

def rj(p, d=None):
    try: return json.loads(Path(p).read_text())
    except: return d or {}

def wj(p, data):
    tmp = p + ".tmp"
    Path(tmp).write_text(json.dumps(data, indent=2))
    os.replace(tmp, p)

def get_hw():
    try:
        import psutil
        return {"cpu_pct": round(psutil.cpu_percent(), 1),
                "ram_pct": round(psutil.virtual_memory().percent, 1),
                "alert_level": "warn" if psutil.virtual_memory().percent > 80 else "ok"}
    except:
        return {"cpu_pct": 0, "ram_pct": 0, "alert_level": "ok"}

def get_prs():
    try:
        r = subprocess.run(["gh","pr","list","--state","open","--json","number,title,headRefName"],
                           capture_output=True, text=True, timeout=8)
        return [{"number": p["number"], "title": p["title"], "branch": p.get("headRefName","")}
                for p in json.loads(r.stdout or "[]")]
    except:
        return []

def get_velocity():
    try:
        files = sorted(Path(REPORTS).glob("v*_compare.jsonl"), key=lambda f: f.stat().st_mtime)
        vd = len(files)
        return {"versions_done": vd, "versions_total": 1000,
                "pct": round(vd / 1000 * 100, 2), "eta_human": f"{1000-vd} versions left"}
    except:
        return {"versions_done": 0, "versions_total": 1000, "pct": 0, "eta_human": "starting..."}

def get_rescue():
    log = os.path.join(REPORTS, "claude_rescue_upgrades.jsonl")
    try:
        lines = [json.loads(l) for l in Path(log).read_text().splitlines() if l.strip()]
        used = sum(1 for l in lines if l.get("upgrade_applied"))
        pct = round(used / max(len(lines), 1) * 100, 1)
        return {"budget_pct": pct, "warning": pct >= 8}
    except:
        return {"budget_pct": 0.0, "warning": False}

def cur_version():
    try:
        return int((Path(BASE).parent / "VERSION").read_text().strip().split(".")[1])
    except:
        return 5

def update():
    s = rj(STATE, {})
    now = datetime.now(timezone.utc).isoformat()
    v = cur_version()
    hw = get_hw()
    p = get_prs()
    vel = get_velocity()
    rs = get_rescue()
    health = round(100 - max(0, hw.get("ram_pct", 0) - 60))
    s.update({
        "ts": now,
        "hardware": hw,
        "open_prs": p,
        "velocity": vel,
        "token_usage": rs,
        "version": {"current": v, "total": 1000,
                    "pct_complete": round(v / 1000 * 100, 2),
                    "label": f"v{v} running"},
        "ceo_report": {"ts": now, "health_score": health, "dashboard_live": True,
                       "summary": f"v{v}/1000 | {len(p)} PRs | Claude {rs['budget_pct']}%"},
        "business_summary": {
            "headline": f"v{v}/1000 running | {len(p)} PRs open | Budget {rs['budget_pct']}%",
            "health_score": health, "dashboard_live": True, "version": v, "updated_at": now}
    })
    wj(STATE, s)
    return v

if __name__ == "__main__":
    print(f"[live_state_updater] every {INTERVAL}s -> {STATE}")
    i = 0
    while True:
        try:
            v = update()
            if i % 30 == 0:
                print(f"v{v} @ {datetime.now().strftime(chr(37)+"H:%M:%S")}")
        except Exception as e:
            print(f"ERR: {e}")
        time.sleep(INTERVAL)
        i += 1
