#!/usr/bin/env python3
"""
Health Check — System status every 30 minutes
==============================================
Monitors:
1. Primary agents (10 agents)
2. Sub-agent count (spawned agents)
3. Orchestrator process health
4. Dashboard state validation
5. Blockers and alerts
6. Rescue gate status
7. ETA progress
"""

import json
import os
import sys
import subprocess
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List, Tuple

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)


class HealthCheck:
    def __init__(self):
        self.base_dir = BASE_DIR
        self.dashboard_file = os.path.join(BASE_DIR, "dashboard", "state.json")
        self.registry_file = os.path.join(BASE_DIR, "registry", "agents.json")
        self.runtime_lessons_file = os.path.join(BASE_DIR, "state", "runtime-lessons.json")
        self.timestamp = datetime.now().isoformat()

    def check_primary_agents(self) -> Dict[str, Any]:
        """Check 10 primary agents in registry."""
        try:
            with open(self.registry_file) as f:
                registry = json.load(f)
            agents = registry.get("agents", {})
            return {
                "count": len(agents),
                "names": list(agents.keys()),
                "agents": agents,
                "status": "ok" if len(agents) == 10 else f"warning: only {len(agents)}/10"
            }
        except Exception as e:
            return {"count": 0, "status": f"error: {e}"}

    def check_sub_agents(self) -> Dict[str, Any]:
        """Count spawned sub-agents from dashboard."""
        try:
            with open(self.dashboard_file) as f:
                state = json.load(f)

            sub_agent_count = 0
            sub_agents_by_parent = {}

            for agent_name, agent_state in state.get("agents", {}).items():
                sub_agents = agent_state.get("sub_agents", [])
                sub_agent_count += len(sub_agents)
                if len(sub_agents) > 0:
                    sub_agents_by_parent[agent_name] = len(sub_agents)

            return {
                "total": sub_agent_count,
                "by_parent": sub_agents_by_parent,
                "status": "ok" if sub_agent_count >= 0 else "warning"
            }
        except Exception as e:
            return {"total": 0, "status": f"error: {e}"}

    def check_orchestrator(self) -> Dict[str, Any]:
        """Check if orchestrator process is running."""
        try:
            result = subprocess.run(
                ["pgrep", "-f", "orchestrator"],
                capture_output=True,
                text=True
            )
            pids = result.stdout.strip().split('\n')
            pids = [p for p in pids if p]

            processes = []
            for pid in pids:
                try:
                    cmd_result = subprocess.run(
                        ["ps", "-o", "pid,command=", "-p", pid],
                        capture_output=True,
                        text=True
                    )
                    processes.append(cmd_result.stdout.strip())
                except:
                    pass

            return {
                "count": len(pids),
                "pids": pids,
                "processes": processes,
                "status": "ok" if len(pids) > 0 else "alert: no orchestrator running"
            }
        except Exception as e:
            return {"status": f"error: {e}"}

    def check_dashboard_state(self) -> Dict[str, Any]:
        """Validate dashboard state has no empty values."""
        try:
            with open(self.dashboard_file) as f:
                state = json.load(f)

            issues = []

            # Check required fields
            if not state.get("ts"):
                issues.append("ts is empty")
            if not state.get("version"):
                issues.append("version is empty")

            # Check agents
            agents = state.get("agents", {})
            if len(agents) == 0:
                issues.append("no agents in state")

            for agent_name, agent_state in agents.items():
                if not agent_state.get("status"):
                    issues.append(f"{agent_name}: status is empty")

            # Check task queue
            task_queue = state.get("task_queue", {})
            if not task_queue:
                issues.append("task_queue is empty")

            return {
                "valid": len(issues) == 0,
                "issues": issues,
                "status": "ok" if len(issues) == 0 else f"alert: {len(issues)} issue(s)"
            }
        except Exception as e:
            return {"valid": False, "status": f"error: {e}"}

    def check_rescue_gate(self) -> Dict[str, Any]:
        """Check rescue gate enforcement (3-attempt rule)."""
        try:
            with open(self.runtime_lessons_file) as f:
                lessons = json.load(f)

            # If it's a list (old format), return empty
            if isinstance(lessons, list):
                return {
                    "tracked_tasks": 0,
                    "escalated": 0,
                    "status": "not yet tracking (old format)"
                }

            # New format: task_id → attempts
            tracked_tasks = len(lessons)
            escalated = sum(1 for v in lessons.values() if v.get("rescue_escalated"))

            return {
                "tracked_tasks": tracked_tasks,
                "escalated": escalated,
                "status": f"ok: {tracked_tasks} tracked, {escalated} escalated"
            }
        except Exception as e:
            return {"status": f"error: {e}"}

    def check_eta(self) -> Dict[str, Any]:
        """Check ETA to beat Opus 4.6."""
        try:
            with open(self.dashboard_file) as f:
                state = json.load(f)

            version = state.get("version", {})
            eta = state.get("eta", {})

            return {
                "current_version": version.get("current", 0),
                "pct_complete": version.get("pct_complete", 0),
                "eta_version": eta.get("version"),
                "eta_hours": eta.get("hours"),
                "eta_days": eta.get("days"),
                "improvement_rate": eta.get("improvement_rate"),
                "confidence": eta.get("confidence"),
                "status": "ok"
            }
        except Exception as e:
            return {"status": f"error: {e}"}

    def identify_blockers(self) -> List[str]:
        """Identify active blockers preventing progress."""
        blockers = []

        # Check 1: Orchestrator not running
        orch_status = self.check_orchestrator()
        if orch_status.get("count", 0) == 0:
            blockers.append("❌ BLOCKER: Orchestrator not running")

        # Check 2: Dashboard state invalid
        dash_status = self.check_dashboard_state()
        if not dash_status.get("valid"):
            blockers.append(f"⚠️  WARNING: Dashboard state has issues: {dash_status.get('issues')}")

        # Check 3: Primary agents not all loaded
        agent_status = self.check_primary_agents()
        if agent_status.get("count", 0) < 10:
            blockers.append(f"⚠️  WARNING: Only {agent_status.get('count')}/10 primary agents loaded")

        # Check 4: Very few sub-agents (should be spawning)
        sub_status = self.check_sub_agents()
        if sub_status.get("total", 0) == 0 and agent_status.get("count", 0) > 0:
            blockers.append("⚠️  WARNING: No sub-agents spawned yet (check if tasks are available)")

        return blockers

    def generate_report(self) -> str:
        """Generate health check report."""
        primary = self.check_primary_agents()
        sub = self.check_sub_agents()
        orch = self.check_orchestrator()
        dash = self.check_dashboard_state()
        rescue = self.check_rescue_gate()
        eta = self.check_eta()
        blockers = self.identify_blockers()

        report = []
        report.append("=" * 80)
        report.append(f"🏥 HEALTH CHECK — {self.timestamp}")
        report.append("=" * 80)

        # Primary Agents
        report.append("")
        report.append("📊 PRIMARY AGENTS (10 total)")
        report.append(f"  Status: {primary.get('status')}")
        report.append(f"  Count: {primary.get('count')}/10")
        if primary.get('names'):
            report.append(f"  Active: {', '.join(primary.get('names', []))}")

        # Sub-Agents
        report.append("")
        report.append("🤖 SUB-AGENTS (parallel execution)")
        report.append(f"  Total spawned: {sub.get('total', 0)}")
        if sub.get('by_parent'):
            report.append(f"  By parent agent:")
            for parent, count in sub.get('by_parent', {}).items():
                report.append(f"    - {parent}: {count}")

        # Orchestrator
        report.append("")
        report.append("⚙️  ORCHESTRATOR")
        report.append(f"  Status: {orch.get('status')}")
        report.append(f"  Process count: {orch.get('count', 0)}")
        if orch.get('pids'):
            report.append(f"  PIDs: {', '.join(orch.get('pids'))}")
        if orch.get('processes'):
            for proc in orch.get('processes', [])[:3]:
                report.append(f"    {proc}")

        # Dashboard State
        report.append("")
        report.append("📡 DASHBOARD STATE")
        report.append(f"  Status: {dash.get('status')}")
        if dash.get('issues'):
            for issue in dash.get('issues', []):
                report.append(f"  ⚠️  {issue}")

        # Rescue Gate
        report.append("")
        report.append("🚨 RESCUE GATE (3-attempt rule)")
        report.append(f"  Status: {rescue.get('status')}")
        report.append(f"  Tasks tracked: {rescue.get('tracked_tasks', 0)}")
        report.append(f"  Tasks escalated: {rescue.get('escalated', 0)}")

        # ETA
        report.append("")
        report.append("📈 ETA TO OPUS 4.6")
        report.append(f"  Current: v{eta.get('current_version')} ({eta.get('pct_complete')}% complete)")
        report.append(f"  Target: v{eta.get('eta_version')}")
        report.append(f"  Time remaining: {eta.get('eta_hours')} hours ({eta.get('eta_days')} days)")
        report.append(f"  Improvement rate: {eta.get('improvement_rate')}% per version")
        report.append(f"  Confidence: {eta.get('confidence')}")

        # Blockers
        report.append("")
        if blockers:
            report.append("🚫 ACTIVE BLOCKERS/WARNINGS")
            for blocker in blockers:
                report.append(f"  {blocker}")
        else:
            report.append("✅ NO BLOCKERS — System operating normally")

        report.append("")
        report.append("=" * 80)
        report.append("24/7 Status: System running continuously (orchestrator spawned in background)")
        report.append("Next check: In 30 minutes")
        report.append("=" * 80)

        return "\n".join(report)

    def run(self) -> str:
        """Run health check and return report."""
        return self.generate_report()


if __name__ == "__main__":
    hc = HealthCheck()
    report = hc.run()
    print(report)

    # Write to file for Claude to read
    status_file = os.path.join(BASE_DIR, "state", "health_check_latest.txt")
    try:
        with open(status_file, "w") as f:
            f.write(report)
    except Exception as e:
        print(f"Warning: Could not write status file: {e}")
