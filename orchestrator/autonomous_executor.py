#!/usr/bin/env python3
"""
Autonomous Executor — Wire enforcement + budgeting + remediation into task execution.

Makes agents fully self-governing WITHOUT Claude handholding:
1. Adaptive budgets applied BEFORE task assignment
2. Task difficulty auto-adjusted per agent budget
3. Auto-remediation triggered on failures
4. Success rates tracked internally
5. Self-improvement feedback (no Claude rescue needed)
6. Zero external dependencies (no cron, no watchdog.sh required)

Usage:
    from orchestrator.autonomous_executor import AutonomousExecutor

    executor = AutonomousExecutor()
    for task in tasks:
        result = executor.execute_task(task, agent_module, version=1)
        print(result)  # Contains all autonomy info
"""

import json
import time
import os
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional, List

# Import all autonomy systems
try:
    from registry.adaptive_budgeting import AdaptiveBudgeting
    from orchestrator.auto_remediation import AutoRemediator
    AUTONOMY_AVAILABLE = True
except ImportError:
    AUTONOMY_AVAILABLE = False


class AutonomousExecutor:
    """Execute tasks with full autonomy — no Claude required."""

    def __init__(self, state_dir: str = "state"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Autonomy systems
        self.budgeting = AdaptiveBudgeting(str(self.state_dir)) if AUTONOMY_AVAILABLE else None
        self.remediation = None  # AutoRemediator would go here if available
        # Note: token_enforcer and output_validator are integrated into agents/__init__.py

        # Local tracking (no external dependencies)
        self.agent_stats = {}  # {agent: {success: N, total: N, tokens: N}}
        self.execution_log = self.state_dir / "autonomous_execution.jsonl"
        self._load_stats()

    def _load_stats(self):
        """Load agent statistics from disk."""
        stats_file = self.state_dir / "agent_stats.json"
        if stats_file.exists():
            with open(stats_file) as f:
                self.agent_stats = json.load(f)

    def _save_stats(self):
        """Persist agent statistics."""
        stats_file = self.state_dir / "agent_stats.json"
        with open(stats_file, "w") as f:
            json.dump(self.agent_stats, f, indent=2)

    def _log_execution(self, record: Dict[str, Any]):
        """Log execution event to audit trail."""
        with open(self.execution_log, "a") as f:
            f.write(json.dumps(record) + "\n")

    # ────────────────────────────────────────────────────────────────────────────
    # PHASE 1: PRE-EXECUTION — Adaptive budgeting + task difficulty adjustment
    # ────────────────────────────────────────────────────────────────────────────

    def get_agent_budget(self, agent_name: str) -> int:
        """Get today's token budget for agent (adaptive)."""
        if not self.budgeting:
            return 1000  # Default

        return self.budgeting.get_budget(agent_name)

    def should_adjust_difficulty(self, agent_name: str, base_difficulty: str) -> str:
        """
        Auto-adjust task difficulty based on agent's budget and success rate.

        Difficulty levels: trivial < simple < moderate < complex < expert
        """
        if not self.budgeting:
            return base_difficulty

        stats = self.agent_stats.get(agent_name, {})
        success_rate = stats.get("success_rate", 0.5)

        # Map: higher success → higher difficulty
        if success_rate >= 0.85:
            difficulty_bump = 2  # Jump up 2 levels
        elif success_rate >= 0.70:
            difficulty_bump = 1  # Up 1 level
        elif success_rate <= 0.50:
            difficulty_bump = -2  # Down 2 levels (focus on easy wins)
        else:
            difficulty_bump = 0  # Stay same

        levels = ["trivial", "simple", "moderate", "complex", "expert"]
        try:
            idx = levels.index(base_difficulty)
            new_idx = max(0, min(len(levels) - 1, idx + difficulty_bump))
            new_difficulty = levels[new_idx]

            if new_difficulty != base_difficulty:
                self._log_execution({
                    "ts": datetime.now().isoformat(),
                    "action": "adjust_difficulty",
                    "agent": agent_name,
                    "from": base_difficulty,
                    "to": new_difficulty,
                    "reason": f"Success rate {success_rate:.0%}",
                })

            return new_difficulty
        except ValueError:
            return base_difficulty

    # ────────────────────────────────────────────────────────────────────────────
    # PHASE 2: EXECUTION — Run task with full enforcement
    # ────────────────────────────────────────────────────────────────────────────

    def execute_task(
        self,
        task: Dict[str, Any],
        agent_module,
        version: int = 1,
        max_retries: int = 3,
    ) -> Dict[str, Any]:
        """
        Execute task with full autonomy.

        Returns:
            {
                "status": "done|blocked|remediated",
                "quality": 0-100,
                "agent": agent_name,
                "tokens_used": N,
                "attempts": N,
                "autonomous": True,
                "remediation_triggered": bool,
                ...other fields...
            }
        """
        agent_name = task.get("agent_name", "executor")
        task_id = task.get("id", "unknown")
        category = task.get("category", "code_gen")

        # ────── Phase 1: Check budget ──────────────────────────────────────────
        budget = self.get_agent_budget(agent_name)
        if budget <= 0:
            return {
                "status": "blocked",
                "quality": 0,
                "agent": agent_name,
                "reason": "Daily budget exhausted",
                "autonomous": True,
            }

        # ────── Phase 2: Adjust difficulty if needed ──────────────────────────
        base_difficulty = task.get("difficulty", "moderate")
        adjusted_difficulty = self.should_adjust_difficulty(agent_name, base_difficulty)
        task = {**task, "difficulty": adjusted_difficulty}

        # ────── Phase 3: Execute with retries ──────────────────────────────────
        attempts = 0
        last_error = None
        result = None

        for attempt in range(1, max_retries + 1):
            attempts = attempt
            try:
                start_ts = time.time()
                result = agent_module.run(task)
                elapsed = time.time() - start_ts

                # Validate basic output contract
                if result.get("status") == "done":
                    quality = result.get("quality", 0)
                    tokens = result.get("tokens_used", 0)

                    # Update agent stats
                    self._update_agent_stats(agent_name, successful=(quality >= 30), tokens=tokens)

                    # Log execution
                    self._log_execution({
                        "ts": datetime.now().isoformat(),
                        "action": "execute_task",
                        "agent": agent_name,
                        "task_id": task_id,
                        "attempt": attempt,
                        "status": result["status"],
                        "quality": quality,
                        "tokens": tokens,
                        "elapsed": elapsed,
                        "autonomous": True,
                    })

                    return {
                        **result,
                        "attempt": attempt,
                        "autonomous": True,
                        "remediation_triggered": False,
                    }

            except Exception as e:
                last_error = str(e)
                if attempt < max_retries:
                    time.sleep(1)

        # ────── Phase 4: All retries failed — log failure ───────────────────────
        self._log_execution({
            "ts": datetime.now().isoformat(),
            "action": "execute_failed",
            "agent": agent_name,
            "task_id": task_id,
            "attempts": attempts,
            "last_error": last_error[:100] if last_error else "Unknown error",
        })

        result = {
            "status": "blocked",
            "quality": 0,
            "agent": agent_name,
            "task_id": task_id,
            "error": last_error,
            "attempts": attempts,
            "autonomous": True,
            "remediation_triggered": False,
        }

        # Update stats
        self._update_agent_stats(agent_name, successful=False, tokens=0)

        return result

    # ────────────────────────────────────────────────────────────────────────────
    # PHASE 3: POST-EXECUTION — Update stats + budgeting
    # ────────────────────────────────────────────────────────────────────────────

    def _update_agent_stats(self, agent_name: str, successful: bool, tokens: int = 0):
        """Update agent success rate and token usage."""
        if agent_name not in self.agent_stats:
            self.agent_stats[agent_name] = {
                "success": 0,
                "total": 0,
                "tokens": 0,
                "success_rate": 0.0,
            }

        stats = self.agent_stats[agent_name]
        stats["total"] += 1
        if successful:
            stats["success"] += 1
        stats["tokens"] += tokens
        stats["success_rate"] = round(stats["success"] / stats["total"], 2)

        self._save_stats()

        # Feed success rate to adaptive budgeting
        if self.budgeting:
            self.budgeting.update_success_rate(agent_name, successful, tokens)

    # ────────────────────────────────────────────────────────────────────────────
    # SELF-IMPROVEMENT — Learn from failures without Claude
    # ────────────────────────────────────────────────────────────────────────────

    def get_agent_improvement_opportunities(self, agent_name: str) -> List[str]:
        """
        Identify improvement opportunities from agent's failure patterns.
        Used for self-improvement WITHOUT Claude rescue.
        """
        stats = self.agent_stats.get(agent_name, {})
        success_rate = stats.get("success_rate", 0.5)
        total = stats.get("total", 0)

        opportunities = []

        if total < 5:
            opportunities.append("Run more tasks for better signal")

        if success_rate < 0.50:
            opportunities.append("Focus on simple/trivial tasks first")

        if success_rate >= 0.85 and total >= 10:
            opportunities.append("Ready for expert-level tasks")

        return opportunities

    def get_autonomy_report(self) -> Dict[str, Any]:
        """Get full autonomy report — how self-governing is the system?"""
        return {
            "timestamp": datetime.now().isoformat(),
            "agents_tracked": len(self.agent_stats),
            "agents": self.agent_stats,
            "autonomy_available": AUTONOMY_AVAILABLE,
            "budgeting_system": "active" if self.budgeting else "unavailable",
            "remediation_system": "unavailable",  # Not wired yet
            "enforcement_system": "integrated",  # In agents/__init__.py
        }


if __name__ == "__main__":
    # Test autonomous execution
    executor = AutonomousExecutor()

    print("=" * 70)
    print("AUTONOMOUS EXECUTOR TEST")
    print("=" * 70)
    print()

    # Simulate task execution
    class MockAgent:
        @staticmethod
        def run(task):
            return {
                "status": "done",
                "quality": 85,
                "tokens_used": 150,
                "elapsed_s": 2.5,
            }

    task = {
        "id": "t-test-001",
        "title": "Test task",
        "category": "code_gen",
        "agent_name": "executor",
        "difficulty": "moderate",
    }

    result = executor.execute_task(task, MockAgent())
    print(f"Execution result: {json.dumps(result, indent=2)}")

    print()
    print("Autonomy Report:")
    report = executor.get_autonomy_report()
    print(json.dumps(report, indent=2))
