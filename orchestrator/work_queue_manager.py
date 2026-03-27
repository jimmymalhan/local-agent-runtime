#!/usr/bin/env python3
"""work_queue_manager.py — Continuous Work Queue Monitoring"""

import json
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent
PROJECTS_FILE = BASE_DIR / "projects.json"
ALERT_FILE = BASE_DIR / "reports" / "work_queue_alerts.jsonl"


def get_queue_depth():
    """Count pending tasks."""
    try:
        with open(PROJECTS_FILE) as f:
            data = json.load(f)
        return sum(
            sum(1 for t in p.get("tasks", []) if t.get("status") == "pending")
            for p in data.get("projects", [])
        )
    except:
        return 0


def check_queue_health():
    """Monitor queue and alert if empty."""
    pending = get_queue_depth()
    in_progress = sum(
        sum(1 for t in p.get("tasks", []) if t.get("status") == "in_progress")
        for p in (json.load(open(PROJECTS_FILE)).get("projects", []))
    )

    total_active = pending + in_progress

    if total_active == 0:
        return "CRITICAL"
    elif total_active < 3:
        return "WARNING"
    else:
        return "HEALTHY"


def monitor_work_queue():
    """Main monitoring function."""
    status = check_queue_health()
    return {"status": status, "pending": get_queue_depth()}
