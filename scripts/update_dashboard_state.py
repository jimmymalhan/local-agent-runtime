#!/usr/bin/env python3
"""
update_dashboard_state.py — Merge comprehensive dashboard data into dashboard/state.json

Reads state/COMPREHENSIVE_DASHBOARD.json and updates dashboard/state.json
with agent status, project data, task tracking, blockers, and improvements.

Called every 30 minutes by health_check_action.sh after comprehensive_dashboard.py runs.
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

COMPREHENSIVE_FILE = os.path.join(BASE_DIR, "state", "COMPREHENSIVE_DASHBOARD.json")
DASHBOARD_STATE = os.path.join(BASE_DIR, "dashboard", "state.json")


def read_json(path):
    """Safely read JSON file."""
    try:
        if os.path.exists(path):
            with open(path) as f:
                return json.load(f)
    except Exception as e:
        print(f"[WARN] Failed to read {path}: {e}")
    return {}


def merge_comprehensive_into_dashboard():
    """
    Merge comprehensive dashboard data into dashboard/state.json.

    Preserves existing fields like token_usage, benchmark_scores, hardware
    while updating agents, projects, tasks, version, and blockers.
    """

    # Read sources
    comprehensive = read_json(COMPREHENSIVE_FILE)
    dashboard_state = read_json(DASHBOARD_STATE)

    if not comprehensive:
        print("[WARN] No comprehensive dashboard data found")
        return False

    print(f"[MERGE] Merging comprehensive data ({len(comprehensive.get('agents', {}))} agents)")

    # Update version info
    if "version" in comprehensive:
        version_info = comprehensive["version"]
        dashboard_state["version"] = {
            "current": version_info.get("current", 0),
            "total": version_info.get("target", 100),
            "pct_complete": version_info.get("pct_complete", 0),
            "label": f"v{version_info.get('current', 0)} → v{version_info.get('target', 0)}"
        }

    # Update agents (convert primary_agents list to dict format)
    primary_agents = comprehensive.get("agents", {}).get("primary_agents", [])
    agents_dict = {}
    for agent in primary_agents:
        name = agent.get("name", "unknown")
        agents_dict[name] = {
            "status": agent.get("status", "unknown"),
            "task": agent.get("current_task", ""),
            "task_id": agent.get("task_id"),
            "quality": agent.get("quality_score", 0),
            "elapsed_s": agent.get("elapsed_s", 0),
            "last_activity": agent.get("last_activity", ""),
            "sub_agents": [
                {
                    "id": i,
                    "status": "running",
                    "task": f"sub-agent {i}",
                    "model": "",
                    "elapsed_s": 0.0,
                    "quality": 0
                }
                for i in range(agent.get("sub_agents", 0))
            ],
            "worker_count": agent.get("sub_agents", 0),
        }
    dashboard_state["agents"] = agents_dict if agents_dict else dashboard_state.get("agents", {})

    # Update task_queue from projects
    projects = comprehensive.get("projects", {}).get("projects", [])
    total_tasks = 0
    in_progress_tasks = 0
    for project in projects:
        for task in project.get("tasks", []):
            total_tasks += 1
            if task.get("status") == "in_progress":
                in_progress_tasks += 1

    if total_tasks > 0:
        dashboard_state["task_queue"] = {
            "total": total_tasks,
            "completed": total_tasks - in_progress_tasks,
            "in_progress": in_progress_tasks,
            "failed": 0,
            "pending": 0
        }

    # Add blockers and improvements to research_feed
    bi = comprehensive.get("blockers_and_improvements", {})
    feed = dashboard_state.get("research_feed", [])

    # Add blockers
    for blocker in bi.get("blockers", []):
        if blocker != "NONE":
            feed.append({
                "ts": datetime.now().isoformat(),
                "finding": f"🚫 BLOCKER: {blocker}",
                "message": f"🚫 BLOCKER: {blocker}",
                "agent": "system"
            })

    # Add improvements
    for improvement in bi.get("improvements", []):
        if improvement != "System optimized":
            feed.append({
                "ts": datetime.now().isoformat(),
                "finding": f"💡 IMPROVEMENT: {improvement}",
                "message": f"💡 IMPROVEMENT: {improvement}",
                "agent": "system"
            })

    dashboard_state["research_feed"] = feed[-20:]  # Keep last 20

    # Add comprehensive data sections for frontend to display
    dashboard_state["comprehensive"] = {
        "agents_count": comprehensive.get("agents", {}).get("total", 0),
        "sub_agents_count": comprehensive.get("sub_agents", {}).get("total", 0),
        "projects_count": comprehensive.get("projects", {}).get("total", 0),
        "operations": comprehensive.get("operations", {}),
        "blockers": bi.get("blockers", []),
        "improvements": bi.get("improvements", []),
        "summary": comprehensive.get("summary", {}),
    }

    # Update timestamp
    dashboard_state["ts"] = datetime.now().isoformat()

    # Write back to dashboard/state.json
    try:
        os.makedirs(os.path.dirname(DASHBOARD_STATE), exist_ok=True)
        with open(DASHBOARD_STATE, "w") as f:
            json.dump(dashboard_state, f, indent=2)
        print(f"[OK] Updated {DASHBOARD_STATE}")
        return True
    except Exception as e:
        print(f"[ERROR] Failed to write {DASHBOARD_STATE}: {e}")
        return False


if __name__ == "__main__":
    success = merge_comprehensive_into_dashboard()
    sys.exit(0 if success else 1)
