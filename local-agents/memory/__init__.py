from typing import Optional
from .episodic import EpisodicMemory
from .semantic import SemanticMemory
from .procedural import ProceduralMemory
from .store import MemoryStore
from .context_builder import ContextBuilder

_store: Optional[MemoryStore] = None

def get_store() -> MemoryStore:
    """Return the process-level MemoryStore singleton."""
    global _store
    if _store is None:
        _store = MemoryStore()
    return _store

def reset_store(db_path: Optional[str] = None):
    """Reset the singleton (useful in tests)."""
    global _store
    _store = MemoryStore(db_path=db_path) if db_path else None

__all__ = ["EpisodicMemory","SemanticMemory","ProceduralMemory","MemoryStore","ContextBuilder","get_store","reset_store"]
