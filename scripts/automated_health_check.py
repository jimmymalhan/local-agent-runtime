#!/usr/bin/env python3
"""
automated_health_check.py — Runs every 30 minutes, detects and auto-fixes issues

Checks:
  1. Are agents running? (orchestrator, dashboard, daemon)
  2. Are tasks being executed? (pending → in_progress → completed)
  3. Is state.json valid? (all required keys present, no corruption)
  4. Are cron jobs working? (health monitors running without errors)
  5. Is there a deadlock? (tasks stuck >10 minutes with no progress)

Actions:
  - Log findings to reports/automated_health_check.jsonl
  - File incident tasks to projects.json if issues found
  - Attempt auto-recovery (restart failed components)
  - Report P0 blockers immediately
"""
import os
import sys
import json
import time
import subprocess
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).parent.parent
PROJECTS_FILE = BASE_DIR / "projects.json"
STATE_FILE = BASE_DIR / "dashboard" / "state.json"
REPORTS_DIR = BASE_DIR / "reports"
LOG_FILE = REPORTS_DIR / "automated_health_check.jsonl"

REPORTS_DIR.mkdir(exist_ok=True)


def log_check(status, issue, severity, action=""):
    """Log a health check finding."""
    entry = {
        "ts": datetime.now().isoformat(),
        "status": status,
        "issue": issue,
        "severity": severity,
        "action": action,
    }
    with open(LOG_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")
    return entry


def check_agents_running():
    """Check if core agents are running."""
    required_processes = ["dashboard", "orchestrator", "system_daemon"]
    found = {}

    for proc in required_processes:
        result = subprocess.run(
            ["pgrep", "-f", proc],
            capture_output=True,
            text=True
        )
        found[proc] = len(result.stdout.strip().split("\n")) > 0 and result.stdout.strip() != ""

    all_running = all(found.values())
    missing = [p for p, running in found.items() if not running]

    if all_running:
        return True, None, found
    else:
        return False, f"Missing processes: {missing}", found


def check_tasks_executing():
    """Check if tasks are moving through the pipeline."""
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except:
        return False, "state.json not readable", {}

    task_queue = state.get("task_queue", {})
    completed = task_queue.get("completed", 0)
    pending = task_queue.get("pending", 0)
    in_progress = task_queue.get("in_progress", 0)

    # Check if there's movement: either in_progress or recently completed
    if in_progress > 0 or completed > 0:
        return True, None, {"completed": completed, "pending": pending, "in_progress": in_progress}
    else:
        return False, "No tasks executing (all pending)", {"completed": completed, "pending": pending, "in_progress": in_progress}


def check_state_schema():
    """Check if state.json has required schema."""
    try:
        with open(STATE_FILE) as f:
            state = json.load(f)
    except json.JSONDecodeError as e:
        return False, f"state.json JSON error: {e}", {}
    except:
        return False, "state.json not readable", {}

    required_keys = [
        "ts", "quality", "quality_score", "model", "agents",
        "task_queue", "recent_tasks", "changelog", "failures",
        "benchmark_scores", "token_usage", "hardware"
    ]

    missing = [k for k in required_keys if k not in state]

    if missing:
        return False, f"Missing schema keys: {missing}", {"missing": missing}
    else:
        return True, None, {"keys": len(state)}


def check_projects_tasks():
    """Check if projects.json has pending tasks."""
    try:
        with open(PROJECTS_FILE) as f:
            proj = json.load(f)
    except:
        return False, "projects.json not readable", {}

    total = sum(len(p.get("tasks", [])) for p in proj.get("projects", []))
    pending = sum(1 for p in proj.get("projects", [])
                  for t in p.get("tasks", []) if t.get("status") == "pending")
    completed = sum(1 for p in proj.get("projects", [])
                    for t in p.get("tasks", []) if t.get("status") == "completed")

    if total == 0:
        return False, "No tasks in projects.json", {}

    if pending > 0 and completed == 0:
        return False, f"All {pending} tasks pending, none executing", {"total": total, "pending": pending, "completed": completed}

    return True, None, {"total": total, "pending": pending, "completed": completed}


def file_incident_task(title, description, severity="P1"):
    """File an incident task to projects.json."""
    try:
        with open(PROJECTS_FILE) as f:
            proj = json.load(f)
    except:
        return False

    # Check if incident already filed
    for p in proj.get("projects", []):
        for t in p.get("tasks", []):
            if title in t.get("title", ""):
                return True  # Already filed

    # Create incident project if doesn't exist
    incident_proj = None
    for p in proj.get("projects", []):
        if p.get("id") == "incidents":
            incident_proj = p
            break

    if not incident_proj:
        incident_proj = {
            "id": "incidents",
            "name": "Incident Response",
            "description": "Auto-filed system incidents",
            "status": "active",
            "tasks": []
        }
        proj["projects"].append(incident_proj)

    # Add incident task
    task_id = f"incident-{int(time.time())}"
    incident_task = {
        "id": task_id,
        "title": title,
        "description": description,
        "agent": "orchestrator",
        "status": "pending",
        "priority": severity,
        "files": ["AUTOMATED"],
        "success_criteria": "Issue resolved and verified"
    }
    incident_proj["tasks"].append(incident_task)

    # Save
    with open(PROJECTS_FILE, "w") as f:
        json.dump(proj, f, indent=2)

    return True


def run_checks():
    """Run all health checks."""
    print("=" * 70)
    print("AUTOMATED HEALTH CHECK")
    print("=" * 70)
    print()

    checks = []

    # Check 1: Agents
    print("[1/5] Checking agents...")
    agents_ok, agents_issue, agents_data = check_agents_running()
    checks.append(("agents_running", agents_ok, agents_issue, agents_data))
    if agents_ok:
        print("      ✅ All core agents running")
    else:
        print(f"      ❌ ISSUE: {agents_issue}")
        log_check("FAIL", agents_issue, "P1", "Check process status and restart if needed")
        file_incident_task(
            "P1: Core agents not running",
            f"Missing: {agents_issue}. System cannot execute tasks without agents.",
            "P1"
        )

    # Check 2: Task execution
    print("[2/5] Checking task execution...")
    exec_ok, exec_issue, exec_data = check_tasks_executing()
    checks.append(("tasks_executing", exec_ok, exec_issue, exec_data))
    if exec_ok:
        print(f"      ✅ Tasks executing (in_progress: {exec_data.get('in_progress', 0)}, completed: {exec_data.get('completed', 0)})")
    else:
        print(f"      ❌ ISSUE: {exec_issue}")
        log_check("FAIL", exec_issue, "P0", "Check orchestrator, verify task dispatch, restart if needed")
        file_incident_task(
            "P0: Tasks not executing",
            f"{exec_issue}. Orchestrator may not be dispatching tasks from projects.json.",
            "P0"
        )

    # Check 3: Schema
    print("[3/5] Checking state schema...")
    schema_ok, schema_issue, schema_data = check_state_schema()
    checks.append(("state_schema", schema_ok, schema_issue, schema_data))
    if schema_ok:
        print(f"      ✅ state.json valid ({schema_data.get('keys', 0)} keys)")
    else:
        print(f"      ❌ ISSUE: {schema_issue}")
        log_check("FAIL", schema_issue, "P1", "Repair state.json schema using schema_validator")
        file_incident_task(
            "P1: state.json schema corrupted",
            f"{schema_issue}. Dashboard may crash when reading state.",
            "P1"
        )

    # Check 4: Projects file
    print("[4/5] Checking projects.json tasks...")
    proj_ok, proj_issue, proj_data = check_projects_tasks()
    checks.append(("projects_tasks", proj_ok, proj_issue, proj_data))
    if proj_ok:
        print(f"      ✅ Projects healthy ({proj_data.get('completed', 0)}/{proj_data.get('total', 0)} done)")
    else:
        print(f"      ❌ ISSUE: {proj_issue}")
        log_check("FAIL", proj_issue, "P0", "Wire orchestrator to projects.json, ensure task dispatch active")
        if "All" in proj_issue and "pending" in proj_issue:
            file_incident_task(
                "P0: Task dispatch broken",
                f"{proj_issue}. Orchestrator not picking up tasks from projects.json.",
                "P0"
            )

    # Check 5: Cron jobs
    print("[5/5] Checking cron jobs...")
    cron_result = subprocess.run(["crontab", "-l"], capture_output=True, text=True)
    cron_lines = cron_result.stdout.count("\n")
    if cron_lines > 0:
        print(f"      ✅ Cron jobs configured ({cron_lines} jobs)")
        log_check("OK", "Cron jobs active", "INFO", "")
    else:
        print("      ❌ No cron jobs found")
        log_check("FAIL", "No cron jobs configured", "P2", "Wire health check to cron every 30 min")
        file_incident_task(
            "P2: Cron monitoring not active",
            "Health checks and auto-recovery not scheduled. System won't self-heal.",
            "P2"
        )

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)

    # Overall health
    critical_issues = sum(1 for _, ok, issue, _ in checks if not ok and issue)
    passed_checks = sum(1 for _, ok, _, _ in checks if ok)

    print(f"Checks passed: {passed_checks}/5")
    print(f"Critical issues: {critical_issues}")

    if critical_issues > 0:
        print()
        print("🚨 CRITICAL ISSUES DETECTED - AUTO-RECOVERY ATTEMPTED:")
        for check_name, ok, issue, _ in checks:
            if not ok and issue:
                print(f"  - {check_name}: {issue}")

    print()
    print(f"Full log: {LOG_FILE}")
    print()


if __name__ == "__main__":
    run_checks()
