"""
local-agents/providers — Provider abstraction layer
====================================================
All model backend access goes through this package.
Nexus picks the right provider. Users and agents never call Ollama or Claude directly.

Usage:
    from providers.router import get_provider
    provider = get_provider()               # auto-selects best available
    result   = provider.complete(prompt)    # unified interface

Public surface:
    NexusProvider  — base interface (providers/base.py)
    OllamaProvider — local inference (providers/ollama.py)
    ClaudeProvider — remote rescue/benchmark (providers/claude.py)
    ProviderRouter — routing logic (providers/router.py)
"""
from .base import NexusProvider, CompletionResult
from .router import get_provider, ProviderRouter

__all__ = ["NexusProvider", "CompletionResult", "get_provider", "ProviderRouter"]
