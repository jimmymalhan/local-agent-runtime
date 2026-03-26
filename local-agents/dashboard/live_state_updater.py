#!/usr/bin/env python3
"""Updates dashboard/state.json every 2 seconds. Run: python3 dashboard/live_state_updater.py &"""
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

def hw():
    try:
        import psutil
        r = psutil.virtual_memory().percent
        return {"cpu_pct": round(psutil.cpu_percent(), 1), "ram_pct": round(r, 1),
                "alert_level": "warn" if r > 80 else "ok"}
    except: return {"cpu_pct": 0, "ram_pct": 0, "alert_level": "ok"}

def prs():
    try:
        r = subprocess.run(["gh","pr","list","--state","open","--json","number,title,headRefName"],
                           capture_output=True, text=True, timeout=8)
        return [{"number": p["number"], "title": p["title"], "branch": p.get("headRefName", "")}
                for p in json.loads(r.stdout or "[]")]
    except: return []

def velocity():
    try:
        fs = sorted(Path(REPORTS).glob("v*_compare.jsonl"), key=lambda f: f.stat().st_mtime)
        vd = len(fs)
        return {"versions_done": vd, "versions_total": 1000,
                "pct": round(vd / 1000 * 100, 2), "eta_human": f"{1000 - vd} versions left"}
    except: return {"versions_done": 0, "versions_total": 1000, "pct": 0, "eta_human": "starting"}

def budget():
    try:
        lines = [json.loads(l) for l in Path(REPORTS, "claude_rescue_upgrades.jsonl").read_text().splitlines() if l.strip()]
        used = sum(1 for l in lines if l.get("upgrade_applied"))
        pct = round(used / max(len(lines), 1) * 100, 1)
        return {"budget_pct": pct, "warning": pct >= 8}
    except: return {"budget_pct": 0.0, "warning": False}

def version():
    try: return int((Path(BASE).parent / "VERSION").read_text().strip().split(".")[1])
    except: return 5

def tick():
    s = rj(STATE, {}); now = datetime.now(timezone.utc).isoformat()
    v = version(); h = hw(); p = prs(); vel = velocity(); b = budget()
    health = round(100 - max(0, h.get("ram_pct", 0) - 60))
    s.update({"ts": now, "hardware": h, "open_prs": p, "velocity": vel, "token_usage": b,
              "version": {"current": v, "total": 1000,
                          "pct_complete": round(v / 1000 * 100, 2), "label": f"v{v}/1000"},
              "ceo_report": {"ts": now, "health_score": health, "dashboard_live": True,
                             "summary": f"v{v}/1000 | {len(p)} PRs open | Budget {b['budget_pct']}%"},
              "business_summary": {"headline": f"v{v}/1000 | {len(p)} PRs | Budget {b['budget_pct']}%",
                                   "health_score": health, "version": v, "updated_at": now}})
    wj(STATE, s); return v

if __name__ == "__main__":
    print(f"[live_state_updater] {INTERVAL}s -> {STATE}")
    i = 0
    while True:
        try:
            v = tick()
            if i % 30 == 0: print(f"  v{v} updated @ {datetime.now().strftime('%H:%M:%S')}")
        except Exception as e: print(f"  ERR: {e}")
        time.sleep(INTERVAL); i += 1
