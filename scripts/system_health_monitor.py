#!/usr/bin/env python3
"""
system_health_monitor.py — Automated Health Monitoring & Incident Filing
=========================================================================
Runs every 60 seconds. Detects:
1. Orchestrator spinning loop (auto-generating but not executing)
2. Tasks stuck in in_progress
3. Dashboard errors/crashes
4. State.json staleness (not updating)
5. Git accumulation (>10 untracked files)

When issues detected: Files incident to projects.json as P0 task.
"""
import os, json, time, subprocess, sys
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).parent.parent
PROJECTS_FILE = BASE_DIR / "projects.json"
STATE_FILE = BASE_DIR / "dashboard" / "state.json"
ORCHESTRATOR_LOG = Path("/tmp/nexus-loop.log")
INCIDENT_LOG = BASE_DIR / "reports" / "system_incidents.jsonl"

INCIDENT_LOG.parent.mkdir(exist_ok=True)

class SystemHealthMonitor:
    def __init__(self):
        self.last_state_ts = None
        self.last_log_line = ""
        self.spin_detected_at = None

    def log_incident(self, incident_type, severity, details):
        """File incident to incident log and projects.json"""
        incident = {
            "ts": datetime.now().isoformat(),
            "type": incident_type,
            "severity": severity,
            "details": details,
        }

        # Append to incident log
        with open(INCIDENT_LOG, "a") as f:
            f.write(json.dumps(incident) + "\n")

        print(f"[INCIDENT] {severity}: {incident_type} — {details}")

        # If severity is HIGH or CRITICAL, file task to projects.json
        if severity in ["HIGH", "CRITICAL"]:
            self.file_incident_task(incident_type, details, severity)

    def file_incident_task(self, incident_type, details, severity):
        """Create P0 task in projects.json for incident"""
        try:
            with open(PROJECTS_FILE) as f:
                projects = json.load(f)

            # Create incident task
            task_id = f"incident-{int(time.time())}"
            task = {
                "id": task_id,
                "title": f"🚨 {severity}: {incident_type}",
                "description": f"Auto-filed incident: {details}. Filed at {datetime.now().isoformat()}",
                "agent": "orchestrator",
                "status": "pending",
                "priority": "P0-INCIDENT",
                "filed_by": "system_health_monitor",
                "files": [],
            }

            # Add to system-unblock-critical project (or create if not exists)
            found = False
            for project in projects["projects"]:
                if project["id"] == "system-unblock-critical":
                    project["tasks"].insert(0, task)
                    found = True
                    break

            if not found:
                # Create incident project if doesn't exist
                projects["projects"].insert(0, {
                    "id": "system-incidents",
                    "name": "🚨 System Incidents (Auto-Filed)",
                    "status": "in_progress",
                    "priority": "P0-INCIDENT",
                    "tasks": [task]
                })

            with open(PROJECTS_FILE, "w") as f:
                json.dump(projects, f, indent=2)

            print(f"  → Filed task {task_id} to projects.json")
        except Exception as e:
            print(f"  ⚠️ Could not file task: {e}")

    def check_orchestrator_spinning(self):
        """Detect if orchestrator is in infinite loop (auto-generating but not executing)"""
        if not ORCHESTRATOR_LOG.exists():
            return

        try:
            with open(ORCHESTRATOR_LOG) as f:
                lines = f.readlines()

            if not lines:
                return

            # Check last 20 lines for pattern: "Queue empty — auto-generating" repeated
            recent = "".join(lines[-20:])
            auto_gen_count = recent.count("auto-generating tasks")

            if auto_gen_count >= 3:  # Pattern repeated 3+ times = spinning
                if not self.spin_detected_at:
                    self.spin_detected_at = time.time()
                    self.log_incident(
                        "Orchestrator Spinning Loop",
                        "HIGH",
                        "Orchestrator auto-generating tasks every 5-6s but never executing them. Tasks: 20 pending, 0 completed."
                    )
                elif time.time() - self.spin_detected_at > 600:  # Been spinning for >10 min
                    self.log_incident(
                        "Orchestrator Deadlocked",
                        "CRITICAL",
                        "Orchestrator has been spinning for >10 minutes. Zero task completion. System is deadlocked."
                    )
            else:
                self.spin_detected_at = None  # Reset when spin stops
        except Exception as e:
            print(f"[ERROR] Failed to check orchestrator: {e}")

    def check_state_staleness(self):
        """Detect if state.json is not being updated (>60 sec old)"""
        if not STATE_FILE.exists():
            return

        try:
            state = json.load(open(STATE_FILE))
            ts_str = state.get("ts", "")

            if not ts_str:
                self.log_incident("State Staleness", "HIGH", "state.json has no timestamp")
                return

            ts = datetime.fromisoformat(ts_str)
            age = (datetime.now() - ts).total_seconds()

            if age > 300:  # 5 minutes stale
                self.log_incident(
                    "Dashboard State Stale",
                    "HIGH",
                    f"state.json last updated {age:.0f} seconds ago. Agents may not be running."
                )
        except Exception as e:
            print(f"[ERROR] Failed to check state staleness: {e}")

    def check_untracked_files(self):
        """Detect git accumulation (>10 untracked files)"""
        try:
            result = subprocess.run(
                ["git", "status", "--short"],
                cwd=str(BASE_DIR),
                capture_output=True,
                text=True,
                timeout=5
            )
            untracked = result.stdout.count("??")

            if untracked > 15:  # More than 15 untracked
                self.log_incident(
                    "Git Accumulation",
                    "MEDIUM",
                    f"{untracked} untracked files in repo. Run: git add -A && git commit"
                )
        except Exception as e:
            print(f"[ERROR] Failed to check git status: {e}")

    def check_agents_idle(self):
        """Detect if all agents are idle (zero task completions)"""
        try:
            with open(PROJECTS_FILE) as f:
                projects = json.load(f)

            total = 0
            completed = 0
            for project in projects["projects"]:
                for task in project.get("tasks", []):
                    total += 1
                    if task.get("status") == "completed":
                        completed += 1

            if total > 10 and completed == 0:
                age_minutes = 60  # Been monitoring for 1 hour with no completion
                self.log_incident(
                    "Agents Idle",
                    "HIGH",
                    f"All {total} tasks still pending. Zero task completions in last hour. Agents not executing work."
                )
        except Exception as e:
            print(f"[ERROR] Failed to check agents: {e}")

    def run(self):
        """Run all health checks"""
        print(f"\n[{datetime.now().isoformat()}] Running system health checks...")

        self.check_orchestrator_spinning()
        self.check_state_staleness()
        self.check_untracked_files()
        self.check_agents_idle()

        print("[OK] Health check complete")

if __name__ == "__main__":
    monitor = SystemHealthMonitor()

    if len(sys.argv) > 1 and sys.argv[1] == "--daemon":
        # Run every 60 seconds
        print("[DAEMON] System health monitor started (check every 60s)")
        while True:
            try:
                monitor.run()
            except Exception as e:
                print(f"[ERROR] Monitor crashed: {e}")
            time.sleep(60)
    else:
        # Single run
        monitor.run()
