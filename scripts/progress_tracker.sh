#!/bin/bash
# progress_tracker.sh — Track epic completion progress every 10 minutes

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PROGRESS_LOG="${BASE_DIR}/reports/progress_$(date +%s).log"

{
    echo "╔════════════════════════════════════════════════════════════════════════╗"
    echo "║              📊 EPIC COMPLETION PROGRESS TRACKER                      ║"
    echo "║                    $(date '+%Y-%m-%d %H:%M:%S')                              ║"
    echo "╚════════════════════════════════════════════════════════════════════════╝"
    echo ""

    python3 << 'PYEOF'
import json
import os
from datetime import datetime

base_dir = "/Users/jimmymalhan/Documents/local-agent-runtime"

# Load projects
with open(f"{base_dir}/projects.json") as f:
    projects = json.load(f)["projects"]

now = datetime.now()

print("EPIC PROGRESS TRACKER")
print("=" * 80)
print()

completed_epics = 0
total_tasks = 0
completed_tasks = 0

for proj in projects:
    proj_name = proj["name"]
    proj_status = proj.get("status", "pending")
    
    tasks = proj.get("tasks", [])
    total_tasks += len(tasks)

    task_completed = sum(1 for t in tasks if t.get("status") == "completed")
    task_in_progress = sum(1 for t in tasks if t.get("status") == "in_progress")
    completed_tasks += task_completed

    # Status indicator
    if task_completed == len(tasks):
        status_icon = "✅"
        status_text = "COMPLETE"
        completed_epics += 1
    elif task_in_progress > 0:
        status_icon = "⧐"
        status_text = "IN PROGRESS"
    else:
        status_icon = "⧐"
        status_text = "PENDING"

    # ETA
    eta_str = proj.get("eta_completion", "unknown")
    try:
        eta_time = datetime.fromisoformat(eta_str.replace("Z", "+00:00"))
        eta_seconds = (eta_time - now).total_seconds()
        if eta_seconds > 0:
            eta_hours_remaining = eta_seconds / 3600
            eta_status = f"{eta_hours_remaining:.1f}h"
        else:
            eta_status = "DONE"
    except:
        eta_status = "?"

    print(f"{status_icon} {proj_name}")
    print(f"   {status_text} | {task_completed}/{len(tasks)} tasks | ETA {eta_status}")
    print()

print("=" * 80)
print(f"Overall: {completed_epics}/{len(projects)} epics complete")
print(f"Tasks: {completed_tasks}/{total_tasks}")
PYEOF

} | tee "${PROGRESS_LOG}"

# Keep only last 50 progress logs
ls -t ${BASE_DIR}/reports/progress_*.log 2>/dev/null | tail -n +50 | xargs rm -f 2>/dev/null || true

