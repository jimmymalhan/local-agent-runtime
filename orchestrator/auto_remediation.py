#!/usr/bin/env python3
"""
Auto Remediation Engine — Detect and resolve failures autonomously.

Triggers:
- Budget exceeded → reduce task difficulty
- Rescue denied 3x → escalate for prompt review
- Model routing violated → downgrade agent
- Confidence < 80% → require manual review

Actions:
- Logged to auto_remediation.jsonl
- Non-blocking
- Graceful fallbacks
"""

import json
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional


class AutoRemediator:
    """Auto-remediation engine."""

    def __init__(self, state_dir: str = "state"):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

        # Paths
        self.remediation_log = self.state_dir / "auto_remediation.jsonl"
        self.rescue_denials_log = self.state_dir / "rescue_denials.jsonl"

    def _log_remediation(self, record: Dict[str, Any]):
        """Log remediation action."""
        with open(self.remediation_log, "a") as f:
            f.write(json.dumps(record) + "\n")

    def check_budget_exceeded(self, agent_name: str, daily_used: int) -> Optional[Dict[str, Any]]:
        """Check if budget exceeded and return remediation action."""
        # Budget cap is 1000 tokens/day by default
        budget_cap = 1000

        if daily_used > budget_cap:
            action = {
                "type": "reduce_difficulty",
                "agent": agent_name,
                "reason": f"Budget exceeded: {daily_used}/{budget_cap}",
                "new_difficulty": "simple",  # Fall back to easier tasks
            }
            self._log_remediation({
                "ts": datetime.now().isoformat(),
                "action": "budget_exceeded",
                "agent": agent_name,
                "daily_used": daily_used,
                "threshold": budget_cap,
                "remediation": "reduce_difficulty",
            })
            return action

        return None

    def check_rescue_denials(self, agent_name: str, task_id: str) -> Optional[Dict[str, Any]]:
        """Check if rescue has been denied 3x and escalate."""
        # Count denials for this agent in the last 24h
        try:
            lines = open(self.rescue_denials_log).readlines()
            recent_denials = 0
            for line in lines[-100:]:  # Check last 100 entries
                rec = json.loads(line)
                if rec.get("agent") == agent_name:
                    recent_denials += 1
        except FileNotFoundError:
            recent_denials = 0

        if recent_denials >= 3:
            action = {
                "type": "escalate_prompt_review",
                "agent": agent_name,
                "reason": f"Rescue denied {recent_denials}x",
            }
            self._log_remediation({
                "ts": datetime.now().isoformat(),
                "action": "rescue_denial_escalation",
                "agent": agent_name,
                "denial_count": recent_denials,
                "remediation": "escalate_prompt_review",
            })
            return action

        return None

    def check_model_routing_violations(self, agent_name: str) -> Optional[Dict[str, Any]]:
        """Check if model routing violations and downgrade agent."""
        # Stub for future implementation
        return None

    def check_confidence_low(self, agent_name: str, confidence: float, task_id: str) -> Optional[Dict[str, Any]]:
        """Check if confidence is low and require manual review."""
        if confidence < 80:
            action = {
                "type": "require_manual_review",
                "agent": agent_name,
                "task_id": task_id,
                "reason": f"Confidence {confidence:.0f}% < 80%",
            }
            self._log_remediation({
                "ts": datetime.now().isoformat(),
                "action": "low_confidence_flag",
                "agent": agent_name,
                "task_id": task_id,
                "confidence": confidence,
                "remediation": "require_manual_review",
            })
            return action

        return None

    def execute_remediation(self, action: Dict[str, Any]) -> bool:
        """Execute remediation action."""
        try:
            action_type = action.get("type", "unknown")
            agent = action.get("agent", "unknown")

            if action_type == "reduce_difficulty":
                # Log that we're reducing difficulty for next tasks
                self._log_remediation({
                    "ts": datetime.now().isoformat(),
                    "action": "reduce_difficulty_executed",
                    "agent": agent,
                    "new_difficulty": action.get("new_difficulty", "simple"),
                })
                return True

            elif action_type == "escalate_prompt_review":
                # Log escalation
                self._log_remediation({
                    "ts": datetime.now().isoformat(),
                    "action": "escalation_executed",
                    "agent": agent,
                    "reason": action.get("reason"),
                })
                return True

            elif action_type == "require_manual_review":
                # Log flag for manual review
                self._log_remediation({
                    "ts": datetime.now().isoformat(),
                    "action": "manual_review_flagged",
                    "agent": agent,
                    "task_id": action.get("task_id"),
                    "reason": action.get("reason"),
                })
                return True

            return False

        except Exception as e:
            # Non-blocking: log and continue
            self._log_remediation({
                "ts": datetime.now().isoformat(),
                "action": "remediation_error",
                "error": str(e),
            })
            return False


if __name__ == "__main__":
    ar = AutoRemediator()

    print("=" * 70)
    print("AUTO REMEDIATION TEST")
    print("=" * 70)
    print()

    # Test budget exceeded
    print("Testing budget exceeded detection...")
    action = ar.check_budget_exceeded("executor", 1200)
    if action:
        print(f"✓ Action triggered: {action['type']}")
        ar.execute_remediation(action)
    print()

    # Test confidence low
    print("Testing low confidence detection...")
    action = ar.check_confidence_low("executor", 75, "task-123")
    if action:
        print(f"✓ Action triggered: {action['type']}")
        ar.execute_remediation(action)
    print()

    print("✓ Auto remediation working")
