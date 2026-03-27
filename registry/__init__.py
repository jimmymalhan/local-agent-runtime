"""
registry — Agent capability registry and configuration.

Provides:
  - Agent registry (agents.json) — available agents and their capabilities
  - Adaptive budgeting — auto-adjust token budgets per success rates
"""
try:
    from .adaptive_budgeting import AdaptiveBudgeting
except ImportError:
    AdaptiveBudgeting = None
