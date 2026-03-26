"""
metrics.py — Aggregate metrics from traces.jsonl for dashboard.
"""
import json
from pathlib import Path
from collections import defaultdict, Counter
from datetime import datetime, timedelta

TRACES_FILE = Path("local-agents/reports/traces.jsonl")

def read_traces(since_hours: int = 24) -> list:
    if not TRACES_FILE.exists(): return []
    cutoff = datetime.utcnow() - timedelta(hours=since_hours)
    traces = []
    with open(TRACES_FILE) as f:
        for line in f:
            try:
                t = json.loads(line)
                ts = datetime.fromisoformat(t["ts"].replace("Z",""))
                if ts >= cutoff: traces.append(t)
            except Exception:
                pass
    return traces

def compute_metrics(since_hours: int = 24) -> dict:
    traces = read_traces(since_hours)
    if not traces:
        return {"tasks_total": 0, "quality_avg": 0, "success_rate": 0}

    total = len(traces)
    ok = [t for t in traces if t["status"] == "ok"]
    qualities = [t["quality"] for t in ok if t["quality"] > 0]
    tool_errors = sum(t.get("tool_error_count", 0) for t in traces)

    by_agent = defaultdict(lambda: {"count": 0, "quality_sum": 0, "ok": 0})
    for t in traces:
        a = by_agent[t["agent"]]
        a["count"] += 1
        a["quality_sum"] += t.get("quality", 0)
        a["ok"] += 1 if t["status"] == "ok" else 0

    if len(traces) >= 2:
        first = datetime.fromisoformat(traces[0]["ts"].replace("Z",""))
        last = datetime.fromisoformat(traces[-1]["ts"].replace("Z",""))
        hours = max((last - first).total_seconds() / 3600, 0.01)
        loop_rate = round(total / hours, 1)
    else:
        loop_rate = 0

    latencies = sorted(t.get("duration_ms", 0) for t in traces)
    p95 = latencies[int(len(latencies) * 0.95)] if latencies else 0

    return {
        "tasks_total": total,
        "tasks_ok": len(ok),
        "success_rate": round(len(ok) / total * 100, 1) if total else 0,
        "quality_avg": round(sum(qualities) / len(qualities), 1) if qualities else 0,
        "loop_rate_per_hour": loop_rate,
        "tool_error_rate": round(tool_errors / total, 2) if total else 0,
        "latency_p95_ms": p95,
        "by_agent": {
            a: {"count": v["count"], "quality_avg": round(v["quality_sum"]/v["count"],1),
                "success_rate": round(v["ok"]/v["count"]*100,1)}
            for a, v in by_agent.items()
        },
        "since_hours": since_hours,
    }

def top_failures(n: int = 5) -> list:
    """Most common error patterns from the past week."""
    traces = read_traces(168)
    errors = [t for t in traces if t.get("error")]
    patterns = Counter(t["error"][:80] for t in errors)
    return [{"pattern": p, "count": c} for p, c in patterns.most_common(n)]
