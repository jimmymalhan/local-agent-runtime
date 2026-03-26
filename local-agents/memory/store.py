import os, sqlite3
from pathlib import Path
from typing import Optional
from .episodic import EpisodicMemory
from .semantic import SemanticMemory
from .procedural import ProceduralMemory

_DEFAULT_DB = str(Path(__file__).parent / "memory.db")

class MemoryStore:
    def __init__(self, db_path=None):
        db_path = db_path or os.environ.get("AGENT_MEMORY_DB", _DEFAULT_DB)
        if db_path != ":memory:": Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(db_path, check_same_thread=False)
        conn.row_factory = sqlite3.Row
        self.episodic   = EpisodicMemory(db_path, shared_conn=conn)
        self.semantic   = SemanticMemory(db_path, shared_conn=conn)
        self.procedural = ProceduralMemory(db_path, shared_conn=conn)
        self._db_path = db_path
        self._conn = conn
    def remember_task(self, task: dict, result: dict, quality: int) -> int:
        row_id = self.episodic.store(task, result, quality)
        if quality >= ProceduralMemory.QUALITY_THRESHOLD:
            output = result.get("output", "")
            if output:
                cat = task.get("category", "general")
                name = f"{cat}/{task.get('title', 'untitled')[:60]}"
                self.procedural.store_pattern(name=name, category=cat, description=task.get("description","")[:300], content=output[:2000], quality=quality)
        return row_id
    def recall_similar(self, task_description: str, n: int = 5) -> list:
        return self.episodic.recall(task_description, n=n, min_quality=0)
    def learn_pattern(self, pattern_name: str, pattern_code: str, quality: int, category: str = "general", description: str = ""):
        return self.procedural.store_pattern(name=pattern_name, category=category, description=description, content=pattern_code, quality=quality)
    def get_patterns(self, category=None) -> list:
        return self.procedural._by_category(category) if category else self.procedural.top_patterns(n=20)
    def store_fact(self, key: str, value: str, source: str = "agent", project_id=None):
        self.semantic.store_fact(key, value, source, project_id)
    def recall_facts(self, query: str, project_id=None) -> list:
        return self.semantic.recall_facts(query, project_id=project_id)
    def get_context(self, task: dict) -> dict:
        query = f"{task.get('title','')} {task.get('description','')}"
        pid = task.get("project_id") or task.get("codebase_path")
        return {
            "similar_tasks":     self.episodic.recall(query, n=5, min_quality=60),
            "relevant_patterns": self.procedural.search_patterns(query, category=task.get("category")),
            "codebase_facts":    self.semantic.recall_facts(query, project_id=pid),
        }
    def stats(self) -> dict: return self.episodic.stats()
    @property
    def db_path(self) -> str: return self._db_path
