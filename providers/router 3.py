"""
providers/router.py — Nexus provider routing logic
===================================================
ProviderRouter decides which backend to use for each request.
Rules:
  - Default: OllamaProvider (local, zero cost)
  - Chat: OllamaProvider unless local unavailable → ClaudeProvider
  - Rescue: ClaudeProvider, only if budget allows (≤10% of total tasks)
  - Benchmark: ClaudeProvider for baseline comparison runs

Usage:
    from providers.router import get_provider, ProviderRouter
    p = get_provider()                    # auto → best local
    p = get_provider("rescue")            # → claude if budget allows
    p = get_provider("benchmark")         # → claude for baseline
    p = get_provider("chat")              # → ollama, fallback claude
"""
from __future__ import annotations
import os, json
from pathlib import Path
from typing import Literal, Optional

BASE_DIR = str(Path(__file__).parent.parent)
_BUDGET_CAP = float(os.environ.get("NEXUS_CLAUDE_BUDGET_PCT", "10.0"))

ProviderMode = Literal["auto", "local", "rescue", "benchmark", "chat"]


def _current_budget_pct() -> float:
    """Read current Claude rescue budget % from state.json."""
    state_path = os.path.join(BASE_DIR, "dashboard", "state.json")
    try:
        with open(state_path) as f:
            st = json.load(f)
        tu = st.get("token_usage", {})
        return float(tu.get("budget_pct", 0.0))
    except Exception:
        return 0.0


def get_provider(mode: ProviderMode = "auto"):
    """
    Return the appropriate NexusProvider for the given mode.
    This is the single entry point for all provider selection in Nexus.
    """
    from providers.ollama import OllamaProvider
    from providers.claude import ClaudeProvider

    ollama = OllamaProvider()
    claude = ClaudeProvider()

    if mode == "local":
        return ollama

    if mode in ("rescue", "benchmark"):
        if mode == "rescue" and _current_budget_pct() >= _BUDGET_CAP:
            # Budget exhausted — fall back to local
            return ollama
        if claude.available():
            return claude
        return ollama  # no claude CLI available

    if mode == "chat":
        # Prefer local for chat; fall back to claude if Ollama not running
        if ollama.available():
            return ollama
        if claude.available():
            return claude
        return ollama  # return anyway, will fail gracefully

    # auto: prefer local, fall back to claude only if ollama totally down
    if ollama.available():
        return ollama
    if claude.available():
        return claude
    return ollama


class ProviderRouter:
    """
    Stateful router that tracks usage and enforces budget constraints.
    Use this when you need budget tracking, not just one-shot selection.
    """

    def __init__(self):
        from providers.ollama import OllamaProvider
        from providers.claude import ClaudeProvider
        self.local  = OllamaProvider()
        self.remote = ClaudeProvider()
        self._local_calls  = 0
        self._remote_calls = 0

    def route(self, mode: ProviderMode = "auto"):
        """Select provider and track usage."""
        p = get_provider(mode)
        if p.is_local:
            self._local_calls += 1
        else:
            self._remote_calls += 1
        return p

    @property
    def local_pct(self) -> float:
        total = self._local_calls + self._remote_calls
        return round(self._local_calls / max(total, 1) * 100, 1)

    @property
    def remote_pct(self) -> float:
        return round(100 - self.local_pct, 1)

    def summary(self) -> dict:
        return {
            "local_calls":  self._local_calls,
            "remote_calls": self._remote_calls,
            "local_pct":    self.local_pct,
            "remote_pct":   self.remote_pct,
            "budget_ok":    _current_budget_pct() < _BUDGET_CAP,
        }
