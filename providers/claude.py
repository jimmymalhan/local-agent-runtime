"""
providers/claude.py — Remote rescue / benchmark provider via Claude CLI
=======================================================================
Wraps the existing opus_runner.py behind the NexusProvider interface.
Used ONLY for:
  1. Agent rescue when local fails 3× (≤10% budget, 200-token cap)
  2. Benchmark baseline comparison
  3. Nexus chat when user explicitly chooses best-available

Users never call Claude directly — Nexus routes here transparently.
"""
from __future__ import annotations
import os, sys, time
from pathlib import Path
from typing import Optional

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

from providers.base import NexusProvider, CompletionResult

_DEFAULT_MODEL  = os.environ.get("NEXUS_REMOTE_MODEL", "claude-sonnet-4-6")
_TOKEN_HARD_CAP = int(os.environ.get("NEXUS_CLAUDE_TOKEN_CAP", "200"))


def _claude_cli_available() -> bool:
    """Check if the `claude` CLI is accessible."""
    try:
        import subprocess
        r = subprocess.run(["claude", "--version"], capture_output=True, timeout=3)
        return r.returncode == 0
    except Exception:
        return False


class ClaudeProvider(NexusProvider):
    """
    Remote provider — Claude via CLI.
    Nexus routes here only under rescue or benchmark conditions.
    Hard cap: 200 tokens per call; ≤10% of tasks may use this provider.
    """

    def __init__(self, model: str = "", token_cap: int = 0):
        self._model     = model or _DEFAULT_MODEL
        self._token_cap = token_cap or _TOKEN_HARD_CAP

    @property
    def name(self) -> str:
        return "claude"

    @property
    def is_local(self) -> bool:
        return False

    def available(self) -> bool:
        return _claude_cli_available()

    def complete(
        self,
        prompt: str,
        system: str = "",
        model: str = "",
        max_tokens: int = 0,
        temperature: float = 0.1,
        timeout: int = 60,
    ) -> CompletionResult:
        # Enforce hard token cap for rescue calls
        effective_cap = min(max_tokens or self._token_cap, self._token_cap)
        m = model or self._model
        start = time.time()
        try:
            return self._via_cli(prompt, system, m, effective_cap, timeout, start)
        except Exception as e:
            return CompletionResult(
                text="", model=m, provider="claude",
                elapsed_s=round(time.time() - start, 1),
                error=str(e),
            )

    def _via_cli(self, prompt, system, model, max_tokens, timeout, start):
        """Fallback: direct claude CLI call."""
        import subprocess
        full_prompt = f"{system}\n\n{prompt}".strip() if system else prompt
        r = subprocess.run(
            ["claude", "-p", full_prompt[:1000], "--max-tokens", str(max_tokens)],
            capture_output=True, text=True, timeout=timeout,
        )
        text = r.stdout.strip()
        return CompletionResult(
            text=text, model=model, provider="claude",
            tokens_used=len(text.split()) * 2,  # rough estimate
            elapsed_s=round(time.time() - start, 1),
            error=r.stderr.strip() if r.returncode != 0 else None,
        )
