from .store import MemoryStore
_CHARS_PER_TOKEN = 4

class ContextBuilder:
    SECTION_HEADER = "=== MEMORY CONTEXT ==="
    SECTION_FOOTER = "=== END CONTEXT ==="
    def __init__(self, store: MemoryStore):
        self.store = store
    def build_context(self, task: dict, max_tokens: int = 2000) -> str:
        ctx = self.store.get_context(task)
        similar  = ctx.get("similar_tasks", [])
        patterns = ctx.get("relevant_patterns", [])
        facts    = ctx.get("codebase_facts", [])
        if not any([similar, patterns, facts]): return ""
        parts = []
        sl = self._fmt_similar(similar)
        if sl: parts.append("Similar past tasks:\n" + sl)
        pl = self._fmt_patterns(patterns)
        if pl: parts.append("Relevant patterns:\n" + pl)
        fl = self._fmt_facts(facts)
        if fl: parts.append("Known facts:\n" + fl)
        if not parts: return ""
        body = "\n\n".join(parts)
        header = self.SECTION_HEADER + "\n"
        footer = "\n" + self.SECTION_FOOTER + "\n\n"
        max_body = max_tokens * _CHARS_PER_TOKEN - len(header) - len(footer)
        if len(body) > max_body:
            body = body[:max_body].rsplit("\n", 1)[0] + "\n... (truncated)"
        return header + body + footer
    def inject(self, task: dict, max_tokens: int = 2000) -> dict:
        context = self.build_context(task, max_tokens=max_tokens)
        if not context: return task
        augmented = dict(task)
        augmented["description"] = context + (task.get("description") or "")
        return augmented
    @staticmethod
    def _fmt_similar(items, n=3) -> str:
        lines = []
        for item in items[:n]:
            r = item.get("result") or {}
            summary = r.get("output","")[:120].replace("\n"," ")
            lines.append(f'- [{item.get("title","Untitled")}] -> quality {item.get("quality",0)}: "{summary}"')
        return "\n".join(lines)
    @staticmethod
    def _fmt_patterns(items, n=3) -> str:
        return "\n".join([f'- {p.get("name","?")} (quality {p.get("quality",0)}): {p.get("description","")[:100].replace(chr(10)," ")}' for p in items[:n]])
    @staticmethod
    def _fmt_facts(items, n=5) -> str:
        return "\n".join([f'- {f.get("key","")}: {f.get("value","")[:120].replace(chr(10)," ")}' for f in items[:n]])
