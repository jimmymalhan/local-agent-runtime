"""
store.py — Unified memory interface (MemoryStore).

Single entry point that composes EpisodicMemory, SemanticMemory,
and ProceduralMemory behind a clean API.

Singleton usage (per process):
    from memory import get_store
    store = get_store()
    store.remember_task(task, result, quality)
    ctx = store.get_context(task)
"""
import os
import sqlite3
from pathlib import Path
from typing import Optional

from .episodic import EpisodicMemory
from .semantic import SemanticMemory
from .procedural import ProceduralMemory

# Default DB lives next to this file so it's easy to locate / back up
_DEFAULT_DB = str(Path(__file__).parent / "memory.db")


class MemoryStore:
    """
    Unified memory interface.

    Composes all three memory types behind a single shared SQLite connection,
    so in-memory (':memory:') and file-based DBs both work correctly.
    """

    def __init__(self, db_path: Optional[str] = None):
        db_path = db_path or os.environ.get("AGENT_MEMORY_DB", _DEFAULT_DB)
        # Ensure parent directory exists (skip for :memory:)
        if db_path != ":memory:":
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)

        # One shared connection — all sub-stores share it
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row

        self.episodic   = EpisodicMemory(db_path, shared_conn=conn)
        self.semantic   = SemanticMemory(db_path, shared_conn=conn)
        self.procedural = ProceduralMemory(db_path, shared_conn=conn)

        self._db_path = db_path
        self._conn = conn

    # ------------------------------------------------------------------
    # Episodic shortcuts
    # ------------------------------------------------------------------

    def remember_task(self, task: dict, result: dict, quality: int) -> int:
        """Store a completed task result in episodic memory. Returns row id."""
        row_id = self.episodic.store(task, result, quality)

        # Auto-promote high-quality tasks into procedural memory as patterns
        if quality >= ProceduralMemory.QUALITY_THRESHOLD:
            output = result.get("output", "")
            if output:
                category = task.get("category", "general")
                name = f"{category}/{task.get('title', 'untitled')[:60]}"
                self.procedural.store_pattern(
                    name=name,
                    category=category,
                    description=task.get("description", "")[:300],
                    content=output[:2000],
                    quality=quality,
                )

        return row_id

    def recall_similar(self, task_description: str, n: int = 5) -> list:
        """
        Find similar past tasks by keyword matching.
        Returns list of {task, result, quality, date}.
        """
        return self.episodic.recall(task_description, n=n, min_quality=0)

    # ------------------------------------------------------------------
    # Procedural shortcuts
    # ------------------------------------------------------------------

    def learn_pattern(self, pattern_name: str, pattern_code: str, quality: int, category: str = "general", description: str = "") -> Optional[int]:
        """Store a successful pattern in procedural memory."""
        return self.procedural.store_pattern(
            name=pattern_name,
            category=category,
            description=description,
            content=pattern_code,
            quality=quality,
        )

    def get_patterns(self, category: Optional[str] = None) -> list:
        """Get learned patterns, optionally filtered by category."""
        if category:
            return self.procedural._by_category(category)
        return self.procedural.top_patterns(n=20)

    # ------------------------------------------------------------------
    # Semantic shortcuts
    # ------------------------------------------------------------------

    def store_fact(self, key: str, value: str, source: str = "agent", project_id: Optional[str] = None):
        """Store a codebase or domain fact."""
        self.semantic.store_fact(key, value, source, project_id)

    def recall_facts(self, query: str, project_id: Optional[str] = None) -> list:
        """Retrieve relevant facts for a query."""
        return self.semantic.recall_facts(query, project_id=project_id)

    # ------------------------------------------------------------------
    # Context builder shortcut
    # ------------------------------------------------------------------

    def get_context(self, task: dict) -> dict:
        """
        Get relevant memory context for a task — used as prompt injection.

        Returns:
            {
                "similar_tasks": [...],      # past similar tasks
                "relevant_patterns": [...],  # matching procedural patterns
                "codebase_facts": [...],     # semantic facts for this project
            }
        """
        query = f"{task.get('title', '')} {task.get('description', '')}"
        project_id = task.get("project_id") or task.get("codebase_path")

        similar_tasks    = self.episodic.recall(query, n=5, min_quality=60)
        relevant_patterns = self.procedural.search_patterns(query, category=task.get("category"))
        codebase_facts   = self.semantic.recall_facts(query, project_id=project_id)

        return {
            "similar_tasks": similar_tasks,
            "relevant_patterns": relevant_patterns,
            "codebase_facts": codebase_facts,
        }

    # ------------------------------------------------------------------
    # Stats / maintenance
    # ------------------------------------------------------------------

    def stats(self) -> dict:
        """Return aggregate stats from episodic memory."""
        return self.episodic.stats()

    @property
    def db_path(self) -> str:
        return self._db_path
