#!/usr/bin/env python3
"""
Adaptive Budgeting — Auto-adjust agent token budgets based on success rates.

Strategy:
- Base budget: 1,000 tokens/agent/day
- Min: 500, Max: 2,000 tokens/day
- High success (>85%) → +10% budget (reward good performers)
- Low success (<50%) → -10% budget (focus easy wins)
- Runs daily (on-demand or scheduled)

Usage:
    from registry.adaptive_budgeting import AdaptiveBudgeting

    ab = AdaptiveBudgeting()

    # Record task outcome
    ab.update_success_rate("executor", successful=True, tokens_used=150)

    # Check for adjustments
    adjustments = ab.check_and_adjust()
    # Returns: {agent: (old_budget, new_budget, reason)}
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Tuple, Optional


class AdaptiveBudgeting:
    """Adaptive budget manager for agents."""

    def __init__(self, state_dir: str = "local-agents/state"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Config
        self.base_budget = 1000
        self.min_budget = 500
        self.max_budget = 2000
        self.high_success_threshold = 0.85  # >85% → +10%
        self.low_success_threshold = 0.50   # <50% → -10%
        self.budget_adjustment_pct = 0.10   # ±10%

        # Paths
        self.budgets_file = self.state_dir / "agent_budgets.json"
        self.history_file = self.state_dir / "budget_history.jsonl"
        self.stats_file = self.state_dir / "agent_success_stats.json"

        # Load existing state
        self._load_state()

    def _load_state(self):
        """Load agent budgets and success stats from disk."""
        # Budgets
        if self.budgets_file.exists():
            with open(self.budgets_file) as f:
                self.budgets = json.load(f)
        else:
            self.budgets = {}

        # Stats (success count, total, tokens used)
        if self.stats_file.exists():
            with open(self.stats_file) as f:
                self.stats = json.load(f)
        else:
            self.stats = {}

    def _save_state(self):
        """Persist budgets and stats to disk."""
        with open(self.budgets_file, "w") as f:
            json.dump(self.budgets, f, indent=2)
        with open(self.stats_file, "w") as f:
            json.dump(self.stats, f, indent=2)

    def _log_history(self, record: Dict):
        """Log budget adjustment to audit trail."""
        with open(self.history_file, "a") as f:
            f.write(json.dumps(record) + "\n")

    def get_budget(self, agent_name: str) -> int:
        """Get today's token budget for agent."""
        if agent_name not in self.budgets:
            self.budgets[agent_name] = {
                "current": self.base_budget,
                "last_adjusted": datetime.now().isoformat(),
            }
            self._save_state()

        return self.budgets[agent_name].get("current", self.base_budget)

    def update_success_rate(self, agent_name: str, successful: bool, tokens_used: int = 0):
        """Record task outcome for agent success rate tracking."""
        if agent_name not in self.stats:
            self.stats[agent_name] = {
                "success": 0,
                "total": 0,
                "tokens": 0,
                "success_rate": 0.0,
            }

        stats = self.stats[agent_name]
        stats["total"] += 1
        if successful:
            stats["success"] += 1
        stats["tokens"] += tokens_used
        stats["success_rate"] = round(stats["success"] / stats["total"], 2)

        self._save_state()

    def check_and_adjust(self) -> Dict[str, Tuple[int, int, str]]:
        """
        Check success rates and adjust budgets if needed.

        Returns:
            {agent: (old_budget, new_budget, reason)}
        """
        adjustments = {}

        for agent_name, stats in self.stats.items():
            success_rate = stats.get("success_rate", 0.5)

            # Determine if adjustment needed
            old_budget = self.get_budget(agent_name)
            new_budget = old_budget
            reason = ""

            if success_rate >= self.high_success_threshold:
                # High performer → give more budget
                new_budget = int(old_budget * (1 + self.budget_adjustment_pct))
                new_budget = min(new_budget, self.max_budget)
                reason = f"High success ({success_rate:.0%}) — reward"
            elif success_rate <= self.low_success_threshold:
                # Low performer → reduce budget, focus on easy wins
                new_budget = int(old_budget * (1 - self.budget_adjustment_pct))
                new_budget = max(new_budget, self.min_budget)
                reason = f"Low success ({success_rate:.0%}) — focus easy wins"
            else:
                continue  # No adjustment needed

            # Apply adjustment
            if new_budget != old_budget:
                self.budgets[agent_name] = {
                    "current": new_budget,
                    "last_adjusted": datetime.now().isoformat(),
                    "previous": old_budget,
                    "reason": reason,
                }
                adjustments[agent_name] = (old_budget, new_budget, reason)

                # Log to history
                self._log_history({
                    "ts": datetime.now().isoformat(),
                    "agent": agent_name,
                    "old_budget": old_budget,
                    "new_budget": new_budget,
                    "success_rate": success_rate,
                    "reason": reason,
                })

        # Save updated budgets
        if adjustments:
            self._save_state()

        return adjustments

    def get_agent_summary(self, agent_name: str) -> Dict:
        """Get full summary for an agent."""
        budget = self.get_budget(agent_name)
        stats = self.stats.get(agent_name, {})

        return {
            "agent": agent_name,
            "budget": budget,
            "success_rate": stats.get("success_rate", 0.0),
            "tasks_run": stats.get("total", 0),
            "tasks_succeeded": stats.get("success", 0),
            "tokens_used": stats.get("tokens", 0),
        }


if __name__ == "__main__":
    # Test adaptive budgeting
    ab = AdaptiveBudgeting()

    print("=" * 70)
    print("ADAPTIVE BUDGETING TEST")
    print("=" * 70)
    print()

    # Simulate task outcomes
    print("Simulating task outcomes...")
    for i in range(10):
        # Executor: high success
        ab.update_success_rate("executor", successful=(i % 3 != 0), tokens_used=100 + i * 10)

        # Researcher: low success
        ab.update_success_rate("researcher", successful=(i % 5 == 0), tokens_used=120 + i * 5)

        # Planner: medium success
        ab.update_success_rate("planner", successful=(i % 2 == 0), tokens_used=90 + i * 8)

    print()
    print("Budget adjustments:")
    adjustments = ab.check_and_adjust()
    for agent, (old, new, reason) in adjustments.items():
        print(f"  {agent}: {old} → {new} ({reason})")

    print()
    print("Agent summaries:")
    for agent in ["executor", "researcher", "planner"]:
        summary = ab.get_agent_summary(agent)
        print(f"  {agent}:")
        print(f"    Budget: {summary['budget']} tokens")
        print(f"    Success rate: {summary['success_rate']:.0%}")
        print(f"    Tasks: {summary['tasks_succeeded']}/{summary['tasks_run']}")
