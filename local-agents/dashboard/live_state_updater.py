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
                "free_gb": round(psutil.virtual_memory().available / 1024**3, 1),
                "alert_level": "warn" if r > 80 else "ok"}
    except: return {"cpu_pct": 0, "ram_pct": 0, "free_gb": 0, "alert_level": "ok"}

def prs():
    try:
        r = subprocess.run(["gh","pr","list","--state","open","--json","number,title,headRefName"],
                           capture_output=True, text=True, timeout=8)
        return [{"number": p["number"], "title": p["title"], "branch": p.get("headRefName", "")}
                for p in json.loads(r.stdout or "[]")]
    except: return []

def benchmarks():
    """
    Read all v*_compare.jsonl files and compute per-version benchmark_scores.
    Returns dict in the format normalize_state() expects:
      {"v1": {"local": N, "opus": N, "win_rate": N, "gap": N, "ts": "..."}, ...}
    """
    scores = {}
    try:
        for f in sorted(Path(REPORTS).glob("v*_compare.jsonl")):
            vkey = f.stem.replace("_compare", "")   # "v1", "v2", ...
            lines = [json.loads(l) for l in f.read_text().splitlines() if l.strip()]
            if not lines:
                continue
            locals_ = [l.get("local_quality", 0) for l in lines]
            opus_   = [l.get("opus_quality", 0) for l in lines]
            wins    = sum(1 for l in lines if l.get("local_won", False))
            avg_lo  = round(sum(locals_) / len(locals_), 1)
            avg_op  = round(sum(opus_) / len(opus_), 1)
            wr      = round(wins / len(lines) * 100, 1)
            scores[vkey] = {
                "local":    avg_lo,
                "opus":     avg_op,
                "win_rate": wr,
                "gap":      round(avg_lo - avg_op, 1),
                "ts":       lines[-1].get("ts", ""),
                "tasks":    len(lines),
            }
    except Exception:
        pass
    return scores

def token_usage():
    """
    Read claude_token_log.jsonl + claude_rescue_upgrades.jsonl.
    Returns full token_usage dict that dashboard + normalize_state() expect.
    """
    claude_tokens = 0
    local_tokens  = 0
    rescued_tasks = 0
    try:
        tok_log = Path(REPORTS, "claude_token_log.jsonl")
        if tok_log.exists():
            for line in tok_log.read_text().splitlines():
                if not line.strip(): continue
                e = json.loads(line)
                claude_tokens += e.get("tokens", 0)
    except Exception:
        pass
    try:
        rescue_log = Path(REPORTS, "claude_rescue_upgrades.jsonl")
        if rescue_log.exists():
            lines = [json.loads(l) for l in rescue_log.read_text().splitlines() if l.strip()]
            rescued_tasks = sum(1 for l in lines if l.get("upgrade_applied"))
    except Exception:
        pass
    # Estimate local tokens from loop log (heuristic: 500 tokens per task)
    try:
        loop_log = Path(REPORTS, "loop_20260325.jsonl")
        if loop_log.exists():
            task_count = sum(1 for l in loop_log.read_text().splitlines() if l.strip())
            local_tokens = task_count * 500
    except Exception:
        pass

    total = claude_tokens + local_tokens
    # Budget = claude as % of total (hard cap 10%)
    budget_pct = round(claude_tokens / max(total, 1) * 100, 1) if total > 0 else 0.0
    return {
        "claude_tokens":  claude_tokens,
        "local_tokens":   local_tokens,
        "total_tokens":   total,
        "rescued_tasks":  rescued_tasks,
        "budget_pct":     budget_pct,
        "warning":        budget_pct >= 8,
        "hard_limit_hit": budget_pct >= 10,
    }

def velocity():
    try:
        fs = sorted(Path(REPORTS).glob("v*_compare.jsonl"), key=lambda f: f.stat().st_mtime)
        vd = len(fs)
        return {"versions_done": vd, "versions_total": 1000,
                "pct": round(vd / 1000 * 100, 2), "eta_human": f"{1000 - vd} versions left"}
    except: return {"versions_done": 0, "versions_total": 1000, "pct": 0, "eta_human": "starting"}

def version():
    try: return int((Path(BASE).parent / "VERSION").read_text().strip().split(".")[1])
    except: return 5

def tick():
    s = rj(STATE, {}); now = datetime.now(timezone.utc).isoformat()
    v = version(); h = hw(); p = prs(); vel = velocity()
    b  = token_usage()
    bs = benchmarks()
    health = round(100 - max(0, h.get("ram_pct", 0) - 60))
    s.update({
        "ts":              now,
        "hardware":        h,
        "open_prs":        p,
        "velocity":        vel,
        "token_usage":     b,
        "benchmark_scores": bs,   # now populated from v*_compare.jsonl
        "version": {
            "current":     v,
            "total":       1000,
            "pct_complete": round(v / 1000 * 100, 2),
            "label":       f"v{v}/1000",
        },
        "ceo_report": {
            "ts": now, "health_score": health, "dashboard_live": True,
            "summary": f"v{v}/1000 | {len(p)} PRs open | Budget {b['budget_pct']}%",
        },
        "business_summary": {
            "headline":     f"v{v}/1000 | {len(p)} PRs | Budget {b['budget_pct']}%",
            "health_score": health,
            "version":      v,
            "updated_at":   now,
        },
    })
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
