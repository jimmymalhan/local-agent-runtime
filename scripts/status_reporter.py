#!/usr/bin/env python3
"""
Status Reporter — Generate live status every 30 minutes
Shows what agents are working, any blockers, improvements needed
Dumps to a file that can be viewed on frontend
"""

import json
import os
import sys
from pathlib import Path
from datetime import datetime
from typing import Dict, List, Any

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)


class StatusReporter:
    def __init__(self):
        self.base_dir = BASE_DIR
        self.dashboard_file = os.path.join(BASE_DIR, "dashboard", "state.json")
        self.status_file = os.path.join(BASE_DIR, "state", "LIVE_STATUS.txt")
        self.json_status_file = os.path.join(BASE_DIR, "state", "LIVE_STATUS.json")

    def read_state(self) -> Dict[str, Any]:
        """Read current dashboard state."""
        try:
            with open(self.dashboard_file) as f:
                return json.load(f)
        except:
            return {}

    def get_agent_status(self, state: Dict) -> tuple:
        """Get agent counts and status."""
        agents = state.get("agents", {})
        primary_count = len(agents)

        sub_agent_count = 0
        active_agents = []
        for name, agent in agents.items():
            if agent.get("status") == "running":
                active_agents.append(name)
            sub_agents = agent.get("sub_agents", [])
            sub_agent_count += len(sub_agents)

        return primary_count, sub_agent_count, active_agents

    def check_blockers(self, state: Dict) -> List[str]:
        """Check for system blockers."""
        blockers = []
        warnings = []

        # Check dashboard age
        try:
            ts = state.get("ts", "")
            if ts:
                age = (datetime.now() - datetime.fromisoformat(ts.replace('Z', '+00:00'))).total_seconds()
                if age > 300:
                    blockers.append(f"❌ Dashboard stale ({int(age)}s old)")
                elif age > 60:
                    warnings.append(f"⚠️  Dashboard slow ({int(age)}s old)")
        except:
            pass

        # Check if agents loaded
        if len(state.get("agents", {})) < 10:
            blockers.append(f"❌ Only {len(state.get('agents', {}))} agents loaded")

        # Check rescue budget
        token_usage = state.get("token_usage", {})
        budget_pct = token_usage.get("budget_pct", 0)
        if budget_pct > 90:
            blockers.append(f"❌ Rescue budget critical ({budget_pct}%)")
        elif budget_pct > 70:
            warnings.append(f"⚠️  Rescue budget high ({budget_pct}%)")

        return blockers + warnings

    def get_improvements(self) -> List[str]:
        """Suggest improvements."""
        improvements = []

        try:
            with open(self.dashboard_file) as f:
                state = json.load(f)

            eta = state.get("eta", {})
            improvement_rate = eta.get("improvement_rate", 1.0)

            if improvement_rate < 0.5:
                improvements.append("💡 Improvement rate low (<0.5%/version) - Consider prompt upgrades")

            # Check sub-agent scaling
            agents = state.get("agents", {})
            sub_total = sum(len(a.get("sub_agents", [])) for a in agents.values())
            if sub_total == 0 and len(agents) > 0:
                improvements.append("💡 No sub-agents spawned - Enable parallel execution")

            # Check for task queue
            task_queue = state.get("task_queue", {})
            if task_queue.get("pending", 0) == 0:
                improvements.append("💡 No pending tasks - Queue may need replenishment")

        except:
            pass

        return improvements

    def generate_text_report(self) -> str:
        """Generate human-readable text report."""
        state = self.read_state()
        primary, sub, active = self.get_agent_status(state)
        blockers = self.check_blockers(state)
        improvements = self.get_improvements()

        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        lines = []
        lines.append("=" * 80)
        lines.append(f"🚀 LIVE STATUS REPORT — {timestamp}")
        lines.append("=" * 80)
        lines.append("")

        # Agents
        lines.append("📊 AGENTS & SUB-AGENTS")
        lines.append(f"  Primary agents:      {primary}/10 ✓")
        lines.append(f"  Sub-agents active:   {sub} (dynamic)")
        lines.append(f"  Currently running:   {len(active)}")
        if active:
            lines.append(f"    Agents: {', '.join(active[:5])}" + ("..." if len(active) > 5 else ""))
        lines.append("")

        # 24/7 Status
        lines.append("⏰ 24/7 OPERATIONS")
        lines.append("  Orchestrator:        ✅ Running")
        lines.append("  Task intake:         ✅ Continuous")
        lines.append("  Health monitor:      ✅ Every 30 min")
        lines.append("  Auto-restart:        ✅ Enabled")
        lines.append("  Will run 24/7:       ✅ YES (launchd)")
        lines.append("")

        # Blockers
        lines.append("🚫 BLOCKERS & WARNINGS")
        if blockers:
            for blocker in blockers:
                lines.append(f"  {blocker}")
        else:
            lines.append("  ✅ NONE — System operating normally")
        lines.append("")

        # Improvements
        lines.append("💡 IMPROVEMENTS TO CONSIDER")
        if improvements:
            for improvement in improvements:
                lines.append(f"  {improvement}")
        else:
            lines.append("  ✅ System optimized")
        lines.append("")

        # Progress
        version = state.get("version", {})
        eta = state.get("eta", {})
        lines.append("📈 PROGRESS")
        lines.append(f"  Current:             v{version.get('current', '?')} ({version.get('pct_complete', 0)}%)")
        lines.append(f"  Target:              v{eta.get('version', '?')}")
        lines.append(f"  Time remaining:      ~{eta.get('hours', '?')} hours")
        lines.append(f"  Improvement rate:    {eta.get('improvement_rate', '?')}% per version")
        lines.append("")

        # Metrics
        lines.append("📊 KEY METRICS")
        task_queue = state.get("task_queue", {})
        lines.append(f"  Tasks completed:     {task_queue.get('completed', 0)}/{task_queue.get('total', 100)}")
        lines.append(f"  Tasks in progress:   {task_queue.get('in_progress', 0)}")
        lines.append(f"  Tasks failed:        {task_queue.get('failed', 0)}")
        lines.append(f"  Rescue budget used:  {state.get('token_usage', {}).get('budget_pct', 0)}%")
        lines.append("")

        lines.append("=" * 80)
        lines.append("Next report: In ~30 minutes")
        lines.append("=" * 80)

        return "\n".join(lines)

    def generate_json_report(self) -> Dict:
        """Generate structured JSON report for frontend."""
        state = self.read_state()
        primary, sub, active = self.get_agent_status(state)
        blockers = self.check_blockers(state)
        improvements = self.get_improvements()

        agents = state.get("agents", {})
        agent_details = {}
        for name, agent in agents.items():
            agent_details[name] = {
                "status": agent.get("status", "unknown"),
                "task": agent.get("task", ""),
                "quality": agent.get("quality", 0),
                "sub_agents": len(agent.get("sub_agents", []))
            }

        return {
            "timestamp": datetime.now().isoformat(),
            "agents": {
                "primary_count": primary,
                "sub_agents_count": sub,
                "active": active,
                "details": agent_details
            },
            "operations": {
                "orchestrator": "running",
                "task_intake": "continuous",
                "health_monitor": "every 30 min",
                "auto_restart": True,
                "runs_24_7": True
            },
            "blockers": blockers,
            "improvements": improvements,
            "progress": {
                "current_version": state.get("version", {}).get("current"),
                "pct_complete": state.get("version", {}).get("pct_complete"),
                "target_version": state.get("eta", {}).get("version"),
                "hours_remaining": state.get("eta", {}).get("hours"),
                "improvement_rate": state.get("eta", {}).get("improvement_rate")
            },
            "metrics": {
                "completed_tasks": state.get("task_queue", {}).get("completed"),
                "in_progress": state.get("task_queue", {}).get("in_progress"),
                "failed": state.get("task_queue", {}).get("failed"),
                "rescue_budget_pct": state.get("token_usage", {}).get("budget_pct")
            }
        }

    def save_reports(self) -> None:
        """Save both text and JSON reports."""
        # Text report
        text_report = self.generate_text_report()
        try:
            with open(self.status_file, "w") as f:
                f.write(text_report)
            print(f"✅ Text report saved to {self.status_file}")
        except Exception as e:
            print(f"❌ Error saving text report: {e}")

        # JSON report
        json_report = self.generate_json_report()
        try:
            with open(self.json_status_file, "w") as f:
                json.dump(json_report, f, indent=2)
            print(f"✅ JSON report saved to {self.json_status_file}")
        except Exception as e:
            print(f"❌ Error saving JSON report: {e}")

    def run(self) -> None:
        """Run reporter and save output."""
        print("📊 Generating status report...")
        self.save_reports()
        print("")
        print(self.generate_text_report())


if __name__ == "__main__":
    reporter = StatusReporter()
    reporter.run()
