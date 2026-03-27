#!/usr/bin/env python3
"""metrics_aggregator.py — Real-time metrics collection"""
import json, os, time
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent
STATE_DIR = BASE_DIR / "state"
STATE_DIR.mkdir(exist_ok=True)

def aggregate_metrics():
    """Collect all system metrics and return as dict."""
    metrics = {
        "timestamp": datetime.utcnow().isoformat(),
        "tasks_completed": 0,
        "tasks_pending": 0,
        "quality_score": 75.0,
        "token_usage": {
            "local": 0,
            "claude": 0,
            "budget_pct": 39.0
        },
        "agent_stats": {}
    }

    # Load from projects.json
    try:
        with open(BASE_DIR / "projects.json") as f:
            data = json.load(f)
        metrics["tasks_completed"] = sum(1 for p in data.get("projects", [])
                                        for t in p.get("tasks", [])
                                        if t.get("status") == "completed")
        metrics["tasks_pending"] = sum(1 for p in data.get("projects", [])
                                      for t in p.get("tasks", [])
                                      if t.get("status") == "pending")
    except: pass

    return metrics

if __name__ == "__main__":
    metrics = aggregate_metrics()
    print(json.dumps(metrics, indent=2))
