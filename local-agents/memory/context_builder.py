"""
context_builder.py - Inject relevant memory into agent prompts.

Usage:
    builder = ContextBuilder(store)
    ctx = builder.build_context(task, max_tokens=2000)
    augmented = builder.inject(task, max_tokens=2000)
"""
from .store import MemoryStore

_CHARS_PER_TOKEN = 4


class ContextBuilder:
    """Builds a context string to prepend to any agent prompt."""

    SECTION_HEADER = "=== MEMORY CONTEXT ==="
    SECTION_FOOTER = "=== END CONTEXT ==="

    def __init__(self, store: MemoryStore):
        self.store = store

    def build_context(self, task: dict, max_tokens: int = 2000) -> str:
        """
        Build a context string for the given task within the token budget.

        Format:
            === MEMORY CONTEXT ===
            Similar past tasks:
            - [Fix FastAPI auth bug] -> quality 92: "Added dependency injection..."

            Relevant patterns:
            - fastapi-error-handling (quality 88): Always use HTTPException...

            Known facts:
            - framework: FastAPI 0.111, async SQLAlchemy 2.x
            === END CONTEXT ===
        """
        ctx = self.store.get_context(task)
        similar  = ctx.get("similar_tasks", [])
        patterns = ctx.get("relevant_patterns", [])
        facts    = ctx.get("codebase_facts", [])
        if not any([similar, patterns, facts]):
            return ""
        parts = []
        sl = self._format_similar(similar)
        if sl:
            parts.append("Similar past tasks:\n" + sl)
        pl = self._format_patterns(patterns)
        if pl:
            parts.append("Relevant patterns:\n" + pl)
        fl = self._format_facts(facts)
        if fl:
            parts.append("Known facts:\n" + fl)
        if not parts:
            return ""
        body = "\n\n".join(parts)
        header = self.SECTION_HEADER + "\n"
        footer = "\n" + self.SECTION_FOOTER + "\n\n"
        max_body = max_tokens * _CHARS_PER_TOKEN - len(header) - len(footer)
        if len(body) > max_body:
            body = body[:max_body].rsplit("\n", 1)[0] + "\n... (truncated)"
        return header + body + footer

    def inject(self, task: dict, max_tokens: int = 2000) -> dict:
        """Return a copy of task with memory context prepended to description."""
        context = self.build_context(task, max_tokens=max_tokens)
        if not context:
            return task
        augmented = dict(task)
        augmented["description"] = context + (task.get("description") or "")
        return augmented

    @staticmethod
    def _format_similar(items: list, max_items: int = 3) -> str:
        lines = []
        for item in items[:max_items]:
            title   = item.get("title", "Untitled")
            quality = item.get("quality", 0)
            result  = item.get("result") or {}
            summary = result.get("output", "")[:120].replace("\n", " ")
            lines.append(f'- [{title}] -> quality {quality}: "{summary}"')
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
