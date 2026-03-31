"""
providers/base.py — Abstract provider interface
================================================
Every model backend (Nexus engine, Claude, etc.) implements this interface.
Nexus only speaks to NexusProvider — never to provider internals.
"""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any


@dataclass
class CompletionResult:
    """Unified output from any provider."""
    text: str                          # generated text
    model: str                         # model name used
    provider: str                      # "nexus" | "nexus-remote" | "mock"
    tokens_used: int  = 0
    quality: float    = 0.0            # 0–100 if scorer ran
    elapsed_s: float  = 0.0
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    @property
    def ok(self) -> bool:
        return self.error is None and bool(self.text)


class NexusProvider(ABC):
    """
    Base interface every provider adapter must implement.
    Nexus routes all model calls through this interface.
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Provider identifier, e.g. 'nexus' or 'nexus-remote'."""

    @property
    @abstractmethod
    def is_local(self) -> bool:
        """True for local inference (Nexus engine), False for remote (Nexus remote)."""

    @abstractmethod
    def available(self) -> bool:
        """Return True if this provider can accept requests right now."""

    @abstractmethod
    def complete(
        self,
        prompt: str,
        system: str = "",
        model: str = "",
        max_tokens: int = 4096,
        temperature: float = 0.2,
        timeout: int = 120,
    ) -> CompletionResult:
        """
        Run a single completion. Must be synchronous and safe to call from any thread.
        Returns CompletionResult — never raises on model error; sets result.error instead.
        """

    def chat(
        self,
        messages: List[Dict[str, str]],
        system: str = "",
        model: str = "",
        max_tokens: int = 4096,
    ) -> CompletionResult:
        """
        Multi-turn chat. Default implementation serializes messages and calls complete().
        Override for providers with native chat APIs.
        """
        prompt = "\n".join(
            f"{'User' if m['role'] == 'user' else 'Assistant'}: {m['content']}"
            for m in messages
        )
        return self.complete(prompt, system=system, model=model, max_tokens=max_tokens)

    def __repr__(self) -> str:
        status = "available" if self.available() else "unavailable"
        return f"<{self.__class__.__name__} name={self.name} local={self.is_local} {status}>"
