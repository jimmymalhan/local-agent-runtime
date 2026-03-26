"""
local-agents/memory - Persistent agent memory system.

Three memory types:
  EpisodicMemory   - past task results (what was tried, what worked)
  SemanticMemory   - codebase + domain facts (project maps, API specs)
  ProceduralMemory - reusable patterns from high-quality completions (quality >= 80)

Quick start:
    from memory import get_store
    store = get_store()
    store.remember_task(task, result, quality=88)
    similar = store.recall_similar("Fix FastAPI auth bug")
    from memory.context_builder import ContextBuilder
    ctx = ContextBuilder(store).build_context(task)
"""
from typing import Optional
from .episodic import EpisodicMemory
from .semantic import SemanticMemory
from .procedural import ProceduralMemory
from .store import MemoryStore
from .context_builder import ContextBuilder

_store: Optional[MemoryStore] = None

def get_store() -> MemoryStore:
    """Return the process-level MemoryStore singleton, creating it if needed."""
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store

def reset_store(db_path: Optional[str] = None):
    """Reset the singleton (useful in tests or when switching DB paths)."""
    global _store
    _store = MemoryStore(db_path=db_path) if db_path else None

__all__ = [
    "EpisodicMemory", "SemanticMemory", "ProceduralMemory",
    "MemoryStore", "ContextBuilder", "get_store", "reset_store",
]
