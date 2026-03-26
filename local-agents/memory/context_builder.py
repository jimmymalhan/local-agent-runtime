"""
context_builder.py — Inject relevant memory into agent prompts.

Usage:
    from memory.context_builder import ContextBuilder
    from memory import get_store

    builder = ContextBuilder(get_store())
    context_str = builder.build_context(task, max_tokens=2000)
    augmented_description = context_str + task["description"]
"""
from typing import Optional

from .store import MemoryStore


# Rough token estimate: 1 token ~= 4 chars
_CHARS_PER_TOKEN = 4


class ContextBuilder:
    """
    Builds a context string to prepend to any agent prompt.

    Includes:
      - Similar past tasks + outcomes (episodic)
      - Relevant reusable patterns (procedural)
      - Known facts about the codebase (semantic)
    """

    SECTION_HEADER = "=== MEMORY CONTEXT ==="
    SECTION_FOOTER = "=== END CONTEXT ==="

    def __init__(self, store: MemoryStore):
        self.store = store

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def build_context(self, task: dict, max_tokens: int = 2000) -> str:
        """
        Build a context string for the given task within the token budget.

        Format:
            === MEMORY CONTEXT ===
            Similar past tasks:
            - [Task] Fix FastAPI auth bug → quality 92: "Solution was to..."

            Relevant patterns:
            - fastapi-error-handling: Always use HTTPException with detail dict

            Known facts:
            - This project uses async SQLAlchemy (version 2.x)
            === END CONTEXT ===
        """
        ctx = self.store.get_context(task)

        similar   = ctx.get("similar_tasks", [])
        patterns  = ctx.get("relevant_patterns", [])
        facts     = ctx.get("codebase_facts", [])

        if not any([similar, patterns, facts]):
            return ""

        budget_chars = max_tokens * _CHARS_PER_TOKEN
        parts = []

        # --- Similar past tasks ---
        similar_lines = self._format_similar(similar)
        if similar_lines:
            parts.append("Similar past tasks:\n" + similar_lines)

        # --- Relevant patterns ---
        pattern_lines = self._format_patterns(patterns)
        if pattern_lines:
            parts.append("Relevant patterns:\n" + pattern_lines)

        # --- Known codebase facts ---
        fact_lines = self._format_facts(facts)
        if fact_lines:
            parts.append("Known facts:\n" + fact_lines)

        if not parts:
            return ""

        body = "\n\n".join(parts)

        # Trim to budget
        header = self.SECTION_HEADER + "\n"
        footer = "\n" + self.SECTION_FOOTER + "\n\n"
        overhead = len(header) + len(footer)
        max_body = budget_chars - overhead
        if len(body) > max_body:
            body = body[:max_body].rsplit("\n", 1)[0] + "\n... (truncated)"

        return header + body + footer

    def inject(self, task: dict, max_tokens: int = 2000) -> dict:
        """
        Return a copy of task with the memory context prepended to description.
        Safe to call even when memory is empty (returns task unchanged).
        """
        context = self.build_context(task, max_tokens=max_tokens)
        if not context:
            return task

        augmented = dict(task)
        augmented["description"] = context + (task.get("description") or "")
        return augmented

    # ------------------------------------------------------------------
    # Formatters
    # ------------------------------------------------------------------

    @staticmethod
    def _format_similar(items: list, max_items: int = 3) -> str:
        lines = []
        for item in items[:max_items]:
            title   = item.get("title", "Untitled")
            quality = item.get("quality", 0)
            result  = item.get("result") or {}
            summary = result.get("output", "")[:120].replace("\n", " ")
            lines.append(f'- [{title}] → quality {quality}: "{summary}"')
        return "\n".join(lines)

    @staticmethod
    def _format_patterns(items: list, max_items: int = 3) -> str:
        lines = []
        for pat in items[:max_items]:
            name = pat.get("name", "unnamed")
            desc = pat.get("description", "")[:100].replace("\n", " ")
            q    = pat.get("quality", 0)
            lines.append(f"- {name} (quality {q}): {desc}")
        return "\n".join(lines)

    @staticmethod
    def _format_facts(items: list, max_items: int = 5) -> str:
        lines = []
        for fact in items[:max_items]:
            key   = fact.get("key", "")
            value = fact.get("value", "")[:120].replace("\n", " ")
            lines.append(f"- {key}: {value}")
        return "\n".join(lines)
