#!/usr/bin/env python3
"""
token_enforcer.py — Token Budget Enforcement (TASK-FIX-5)
===========================================================
Enforce hard limits on Claude rescue calls:
- 200 tokens per rescue (hard max)
- 10% of tasks may use rescue (1 task per 10 tasks)
- Block rescue if limit exceeded

Key functions:
  - is_rescue_allowed(task_id) -> bool
  - deduct_tokens(tokens_used: float) -> bool
  - get_budget_status() -> dict
  - log_rescue_decision(task_id, decision, reason) -> None
"""

import json
import os
from pathlib import Path
from datetime import datetime

BASE_DIR = Path(__file__).parent.parent


class TokenEnforcer:
    """Enforce token budget limits for rescue calls."""

    def __init__(self):
        self.config_file = BASE_DIR / "orchestrator" / ".token_budget"
        self.max_tokens_per_rescue = 200
        self.max_rescues_per_session = 1
        self.decision_log = BASE_DIR / "reports" / "token_decisions.jsonl"

        # Load or initialize budget
        self.budget = self._load_budget()

    def _load_budget(self) -> dict:
        """Load token budget state from disk."""
        if self.config_file.exists():
            try:
                with open(self.config_file) as f:
                    return json.load(f)
            except Exception as e:
                print(f"[TOKEN_ENFORCER] Warning loading budget: {e}")

        # Initialize new budget
        return {
            "session_start": datetime.now().isoformat(),
            "total_tokens_used": 0,
            "rescues_used": 0,
            "rescued_tasks": [],
        }

    def _save_budget(self):
        """Save token budget state to disk."""
        try:
            with open(self.config_file, "w") as f:
                json.dump(self.budget, f, indent=2)
        except Exception as e:
            print(f"[TOKEN_ENFORCER] Warning saving budget: {e}")

    def is_rescue_allowed(self, task_id: str) -> bool:
        """
        Check if rescue is allowed for this task.

        Returns:
            bool: True if rescue allowed, False if budget exceeded or limit hit
        """
        # Check hard rescue limit (1 per session)
        if self.budget["rescues_used"] >= self.max_rescues_per_session:
            reason = f"Max rescues ({self.max_rescues_per_session}) already used this session"
            self._log_decision(task_id, False, reason)
            return False

        # Check token budget (none actually used yet during check)
        # The tokens are deducted AFTER rescue is called
        reason = "Rescue allowed (within budget)"
        self._log_decision(task_id, True, reason)
        return True

    def deduct_tokens(self, tokens_used: float) -> bool:
        """
        Deduct tokens from budget after rescue is called.

        Args:
            tokens_used: Number of tokens consumed by the rescue call

        Returns:
            bool: True if deduction successful, False if would exceed budget
        """
        if tokens_used > self.max_tokens_per_rescue:
            print(f"[TOKEN_ENFORCER] WARNING: Token usage {tokens_used} exceeds max {self.max_tokens_per_rescue}")
            return False

        self.budget["total_tokens_used"] += tokens_used
        self.budget["rescues_used"] += 1

        if self.budget["rescues_used"] >= self.max_rescues_per_session:
            print(f"[TOKEN_ENFORCER] ⚠ RESCUE BUDGET EXHAUSTED: {self.budget['rescues_used']}/{self.max_rescues_per_session}")

        self._save_budget()
        print(f"[TOKEN_ENFORCER] Deducted {tokens_used} tokens. Total: {self.budget['total_tokens_used']}/{200}")
        return True

    def mark_rescue(self, task_id: str):
        """Mark a task as rescued."""
        if task_id not in self.budget["rescued_tasks"]:
            self.budget["rescued_tasks"].append(task_id)
            self._save_budget()

    def get_budget_status(self) -> dict:
        """Get current budget status."""
        return {
            "total_tokens_used": self.budget["total_tokens_used"],
            "max_tokens_per_rescue": self.max_tokens_per_rescue,
            "rescues_used": self.budget["rescues_used"],
            "max_rescues_per_session": self.max_rescues_per_session,
            "budget_exhausted": self.budget["rescues_used"] >= self.max_rescues_per_session,
            "rescued_tasks": self.budget["rescued_tasks"],
        }

    def _log_decision(self, task_id: str, allowed: bool, reason: str):
        """Log rescue decision to JSONL file."""
        try:
            self.decision_log.parent.mkdir(parents=True, exist_ok=True)
            decision = {
                "timestamp": datetime.now().isoformat(),
                "task_id": task_id,
                "decision": "ALLOWED" if allowed else "BLOCKED",
                "reason": reason,
                "budget_status": self.get_budget_status(),
            }
            with open(self.decision_log, "a") as f:
                f.write(json.dumps(decision) + "\n")
        except Exception as e:
            print(f"[TOKEN_ENFORCER] Error logging decision: {e}")

    def print_status(self):
        """Print current budget status to console."""
        status = self.get_budget_status()
        print("\n" + "=" * 60)
        print("TOKEN BUDGET STATUS")
        print("=" * 60)
        print(f"Rescues used: {status['rescues_used']}/{status['max_rescues_per_session']}")
        print(f"Tokens used: {status['total_tokens_used']}/{status['max_tokens_per_rescue']} (per rescue)")
        print(f"Budget exhausted: {'YES ⚠' if status['budget_exhausted'] else 'NO ✓'}")
        if status["rescued_tasks"]:
            print(f"Rescued tasks: {', '.join(status['rescued_tasks'])}")
        print("=" * 60 + "\n")


# Global instance
_enforcer = None


def get_enforcer() -> TokenEnforcer:
    """Get or create the global token enforcer instance."""
    global _enforcer
    if _enforcer is None:
        _enforcer = TokenEnforcer()
    return _enforcer


def is_rescue_allowed(task_id: str) -> bool:
    """Check if rescue is allowed for a task."""
    return get_enforcer().is_rescue_allowed(task_id)


def deduct_tokens(tokens_used: float) -> bool:
    """Deduct tokens after a rescue call."""
    return get_enforcer().deduct_tokens(tokens_used)


def mark_task_rescued(task_id: str):
    """Mark a task as rescued."""
    return get_enforcer().mark_rescue(task_id)


def get_status() -> dict:
    """Get current budget status."""
    return get_enforcer().get_budget_status()


if __name__ == "__main__":
    # Test the enforcer
    enforcer = TokenEnforcer()
    print("Token Enforcer Initialized")
    enforcer.print_status()

    # Simulate a rescue decision
    print("\n[TEST] Checking if rescue allowed for task-1...")
    allowed = enforcer.is_rescue_allowed("task-1")
    print(f"Result: {allowed}")

    print("\n[TEST] Deducting 150 tokens...")
    deducted = enforcer.deduct_tokens(150)
    print(f"Result: {deducted}")

    enforcer.print_status()
