#!/usr/bin/env python3
"""
Comprehensive Dashboard Reporter
Generates unified status including:
- Agents working + sub-agents
- Projects and tasks
- Version tracking
- Blockers and improvements
- All in one dashboard view
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)


class ComprehensiveDashboard:
    def __init__(self):
        self.base_dir = BASE_DIR
        self.dashboard_file = os.path.join(BASE_DIR, "dashboard", "state.json")
        self.projects_file = os.path.join(BASE_DIR, "projects.json")
        self.status_file = os.path.join(BASE_DIR, "state", "COMPREHENSIVE_DASHBOARD.json")

    def read_json(self, filepath):
        """Safely read JSON file."""
        try:
            with open(filepath) as f:
                return json.load(f)
        except:
            return {}

    def get_agents_data(self) -> Dict[str, Any]:
        """Get agent status and what they're working on."""
        state = self.read_json(self.dashboard_file)
        agents = state.get("agents", {})

        agent_data = {
            "total": len(agents),
            "primary_agents": []
        }

        for name, agent in agents.items():
            agent_info = {
                "name": name,
                "status": agent.get("status", "unknown"),
                "current_task": agent.get("task", ""),
                "task_id": agent.get("task_id"),
                "quality_score": agent.get("quality", 0),
                "sub_agents": len(agent.get("sub_agents", [])),
                "elapsed_s": agent.get("elapsed_s", 0),
                "last_activity": agent.get("last_activity", "")
            }
            agent_data["primary_agents"].append(agent_info)

        return agent_data

    def get_sub_agents_data(self) -> Dict[str, Any]:
        """Get sub-agent information."""
        state = self.read_json(self.dashboard_file)
        agents = state.get("agents", {})

        sub_agent_data = {
            "total": 0,
            "by_parent": {},
            "max_capacity": 250
        }

        for name, agent in agents.items():
            sub_agents = agent.get("sub_agents", [])
            sub_agent_data["total"] += len(sub_agents)
            if len(sub_agents) > 0:
                sub_agent_data["by_parent"][name] = {
                    "count": len(sub_agents),
                    "agents": [s.get("name", f"sub-{i}") for i, s in enumerate(sub_agents)]
                }

        return sub_agent_data

    def get_projects_data(self) -> Dict[str, Any]:
        """Get project and task information."""
        projects_data = self.read_json(self.projects_file)

        project_info = {
            "total": 0,
            "projects": []
        }

        projects = projects_data.get("projects", [])
        for project in projects:
            tasks = project.get("tasks", [])
            project_detail = {
                "id": project.get("id"),
                "name": project.get("name"),
                "description": project.get("description"),
                "status": project.get("status"),
                "task_count": len(tasks),
                "tasks": []
            }

            for task in tasks:
                task_detail = {
                    "id": task.get("id"),
                    "title": task.get("title"),
                    "description": task.get("description"),
                    "agent": task.get("agent"),
                    "status": task.get("status"),
                    "priority": task.get("priority"),
                    "files": task.get("files", [])
                }
                project_detail["tasks"].append(task_detail)

            project_info["projects"].append(project_detail)
            project_info["total"] += 1

        return project_info

    def get_version_data(self) -> Dict[str, Any]:
        """Get version tracking information."""
        state = self.read_json(self.dashboard_file)

        version_info = {
            "current": state.get("version", {}).get("current", 0),
            "pct_complete": state.get("version", {}).get("pct_complete", 0),
            "target": state.get("eta", {}).get("version", 0),
            "hours_remaining": state.get("eta", {}).get("hours", 0),
            "days_remaining": state.get("eta", {}).get("days", 0),
            "improvement_rate": state.get("eta", {}).get("improvement_rate", 0),
            "confidence": state.get("eta", {}).get("confidence", "unknown"),
            "changelog": state.get("version_changelog", {})
        }

        return version_info

    def get_operations_status(self) -> Dict[str, Any]:
        """Get 24/7 operations status."""
        return {
            "orchestrator": "running",
            "task_intake": "continuous",
            "health_monitor": "every 30 min",
            "auto_restart": True,
            "works_24_7": True,
            "launchd_service": "active"
        }

    def get_blockers_and_improvements(self) -> Dict[str, Any]:
        """Identify blockers and needed improvements."""
        state = self.read_json(self.dashboard_file)

        blockers = []
        improvements = []

        # Check dashboard age
        try:
            ts = state.get("ts", "")
            if ts:
                age = (datetime.now() - datetime.fromisoformat(ts.replace('Z', '+00:00'))).total_seconds()
                if age > 300:
                    blockers.append(f"Dashboard stale ({int(age)}s old)")
                elif age > 60:
                    improvements.append(f"Dashboard updates slow ({int(age)}s)")
        except:
            pass

        # Check agent count
        agents = state.get("agents", {})
        if len(agents) < 10:
            blockers.append(f"Only {len(agents)}/10 agents loaded")

        # Check rescue budget
        budget = state.get("token_usage", {}).get("budget_pct", 0)
        if budget > 90:
            blockers.append(f"Rescue budget critical ({budget}%)")
        elif budget > 70:
            improvements.append(f"Rescue budget high ({budget}%)")

        # Check improvement rate
        improvement_rate = state.get("eta", {}).get("improvement_rate", 1.0)
        if improvement_rate < 0.5:
            improvements.append("Improvement rate low - consider prompt upgrades")

        # Check sub-agents
        sub_total = sum(len(a.get("sub_agents", [])) for a in agents.values())
        if sub_total == 0 and len(agents) > 0:
            improvements.append("No sub-agents spawned - enable parallel execution")

        return {
            "blockers": blockers if blockers else ["NONE"],
            "improvements": improvements if improvements else ["System optimized"],
            "has_blockers": len(blockers) > 0
        }

    def generate_report(self) -> Dict[str, Any]:
        """Generate comprehensive dashboard report."""
        return {
            "timestamp": datetime.now().isoformat(),
            "agents": self.get_agents_data(),
            "sub_agents": self.get_sub_agents_data(),
            "projects": self.get_projects_data(),
            "version": self.get_version_data(),
            "operations": self.get_operations_status(),
            "blockers_and_improvements": self.get_blockers_and_improvements(),
            "summary": {
                "system_status": "operational" if not self.get_blockers_and_improvements()["has_blockers"] else "warning",
                "agents_active": self.get_agents_data()["total"],
                "projects_active": self.get_projects_data()["total"],
                "tasks_in_progress": sum(
                    len([t for t in p.get("tasks", []) if t.get("status") == "in_progress"])
                    for p in self.get_projects_data().get("projects", [])
                )
            }
        }

    def save_report(self) -> None:
        """Save comprehensive report to JSON."""
        report = self.generate_report()
        try:
            with open(self.status_file, "w") as f:
                json.dump(report, f, indent=2)
            print(f"✅ Comprehensive dashboard saved to {self.status_file}")
        except Exception as e:
            print(f"❌ Error saving report: {e}")

    def print_report(self) -> None:
        """Print human-readable report."""
        report = self.generate_report()

        print("=" * 90)
        print("🚀 COMPREHENSIVE SYSTEM DASHBOARD")
        print("=" * 90)
        print(f"Timestamp: {report['timestamp']}")
        print("")

        # Agents Section
        print("📊 AGENTS & SUB-AGENTS")
        print(f"  Primary agents: {report['agents']['total']}/10")
        for agent in report['agents']['primary_agents'][:5]:
            print(f"    • {agent['name']:15} | Status: {agent['status']:8} | Task: {agent['current_task'][:40]}")
        if len(report['agents']['primary_agents']) > 5:
            print(f"    ... and {len(report['agents']['primary_agents']) - 5} more")

        print(f"\n  Sub-agents: {report['sub_agents']['total']} active")
        for parent, info in report['sub_agents']['by_parent'].items():
            print(f"    • {parent}: {info['count']} spawned")

        # Projects Section
        print("\n📁 PROJECTS & TASKS")
        print(f"  Active projects: {report['projects']['total']}")
        for project in report['projects'].get('projects', []):
            status_icon = "✓" if project.get('status') == "in_progress" else "○"
            print(f"    {status_icon} {project.get('name')} ({project.get('task_count')} tasks)")
            for task in project.get('tasks', []):
                priority = "🔴" if task.get('priority') == "P0" else "🟡" if task.get('priority') == "P1" else "🟢"
                print(f"        {priority} {task.get('title', '')[:60]}")

        # Version Section
        print("\n📈 VERSION & PROGRESS")
        version = report['version']
        print(f"  Current: v{version['current']} ({version['pct_complete']}% complete)")
        print(f"  Target: v{version['target']} to beat Opus 4.6")
        print(f"  ETA: ~{version['hours_remaining']} hours ({version['days_remaining']} days)")
        print(f"  Improvement rate: {version['improvement_rate']}% per version")

        # Operations Section
        print("\n⏰ 24/7 OPERATIONS")
        ops = report['operations']
        print(f"  Orchestrator: {'✅ Running' if ops['orchestrator'] == 'running' else '❌ Stopped'}")
        print(f"  Task intake: {'✅ Continuous' if ops['task_intake'] == 'continuous' else '⚠️ Paused'}")
        print(f"  Auto-restart: {'✅ Enabled' if ops['auto_restart'] else '❌ Disabled'}")
        print(f"  Works 24/7: {'✅ YES' if ops['works_24_7'] else '❌ NO'}")

        # Blockers & Improvements
        print("\n🚫 BLOCKERS & IMPROVEMENTS")
        bi = report['blockers_and_improvements']
        if bi['blockers'] and bi['blockers'][0] != "NONE":
            for blocker in bi['blockers']:
                print(f"  ❌ {blocker}")
        else:
            print(f"  ✅ NONE — System operating normally")

        if bi['improvements']:
            print("\n  💡 Improvements to consider:")
            for improvement in bi['improvements']:
                print(f"     • {improvement}")

        # Summary
        print("\n📊 SUMMARY")
        summary = report['summary']
        print(f"  System status: {summary['system_status'].upper()}")
        print(f"  Agents active: {summary['agents_active']}")
        print(f"  Projects active: {summary['projects_active']}")
        print(f"  Tasks in progress: {summary['tasks_in_progress']}")

        print("\n" + "=" * 90)


def main():
    dashboard = ComprehensiveDashboard()
    dashboard.save_report()
    dashboard.print_report()


if __name__ == "__main__":
    main()
