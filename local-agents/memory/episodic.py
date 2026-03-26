"""
episodic.py - Past task execution history.

Stores what was tried, what worked, what failed.
Table: episodic_tasks(id, title, category, description, result_json, quality, agent, timestamp, tags)
"""
import json
import sqlite3
import time
from datetime import datetime
from typing import Optional


class EpisodicMemory:
    """Stores task execution history: what was tried, what worked, what did not."""

    TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS episodic_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
        category TEXT, description TEXT, result_json TEXT,
        quality INTEGER DEFAULT 0, agent TEXT, timestamp REAL NOT NULL, tags TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_episodic_category  ON episodic_tasks(category);
    CREATE INDEX IF NOT EXISTS idx_episodic_quality   ON episodic_tasks(quality);
    CREATE INDEX IF NOT EXISTS idx_episodic_timestamp ON episodic_tasks(timestamp);
    """

    def __init__(self, db_path: str, shared_conn: Optional[sqlite3.Connection] = None):
        self.db_path = db_path
        self._shared_conn: Optional[sqlite3.Connection] = shared_conn
        self._own_conn: Optional[sqlite3.Connection] = None
        self._init_schema()

    def _conn(self) -> sqlite3.Connection:
        if self._shared_conn is not None:
            return self._shared_conn
        if self._own_conn is None:
            self._own_conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._own_conn.row_factory = sqlite3.Row
        return self._own_conn

    def _init_schema(self):
        conn = self._conn()
        for stmt in self.TABLE_DDL.strip().split(";"):
            stmt = stmt.strip()
            if stmt:
                conn.execute(stmt)
        conn.commit()

    def store(self, task: dict, result: dict, quality: int) -> int:
        """Persist a completed task and its result. Returns the new row id."""
        tags = task.get("tags")
        if isinstance(tags, (list, dict)):
            tags = json.dumps(tags)
        conn = self._conn()
        cursor = conn.execute(
            "INSERT INTO episodic_tasks "
            "(title, category, description, result_json, quality, agent, timestamp, tags) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (task.get("title", ""), task.get("category", ""), task.get("description", ""),
             json.dumps(result), quality, result.get("agent_name") or task.get("agent", ""),
             time.time(), tags),
        )
        conn.commit()
        return cursor.lastrowid

    def recall(self, query: str, n: int = 5, min_quality: int = 0) -> list:
        """Find similar past tasks by keyword matching. Returns list ordered by quality desc."""
        keywords = [w.strip().lower() for w in query.split() if len(w.strip()) > 2]
        if not keywords:
            return []
        conditions = " OR ".join(["(LOWER(title) LIKE ? OR LOWER(description) LIKE ?)"] * len(keywords))
        params = [x for k in keywords for x in (f"%{k}%", f"%{k}%")] + [min_quality, n]
        rows = self._conn().execute(
            f"SELECT * FROM episodic_tasks WHERE ({conditions}) AND quality >= ? "
            f"ORDER BY quality DESC, timestamp DESC LIMIT ?",
            params,
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_failures(self, category: Optional[str] = None) -> list:
        """Return tasks with quality < 50, optionally filtered by category."""
        conn = self._conn()
        if category:
            rows = conn.execute(
                "SELECT * FROM episodic_tasks WHERE quality < 50 AND category = ? ORDER BY timestamp DESC",
                (category,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM episodic_tasks WHERE quality < 50 ORDER BY timestamp DESC"
            ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def get_successes(self, min_quality: int = 80) -> list:
        """Return tasks above quality threshold, most recent first."""
        rows = self._conn().execute(
            "SELECT * FROM episodic_tasks WHERE quality >= ? ORDER BY quality DESC, timestamp DESC",
            (min_quality,),
        ).fetchall()
        return [self._row_to_dict(r) for r in rows]

    def stats(self) -> dict:
        """Return aggregate stats: total, avg_quality, by_category, top_agents."""
        conn = self._conn()
        total = conn.execute("SELECT COUNT(*) FROM episodic_tasks").fetchone()[0]
        avg_q = conn.execute("SELECT AVG(quality) FROM episodic_tasks").fetchone()[0] or 0
        by_cat = {}
        for row in conn.execute(
            "SELECT category, COUNT(*), AVG(quality) FROM episodic_tasks GROUP BY category"
        ).fetchall():
            by_cat[row[0] or "unknown"] = {"count": row[1], "avg_quality": round(row[2] or 0, 1)}
        top_agents = {}
        for row in conn.execute(
            "SELECT agent, COUNT(*), AVG(quality) FROM episodic_tasks GROUP BY agent "
            "ORDER BY AVG(quality) DESC LIMIT 10"
        ).fetchall():
            top_agents[row[0] or "unknown"] = {"count": row[1], "avg_quality": round(row[2] or 0, 1)}
        return {"total": total, "avg_quality": round(avg_q, 1), "by_category": by_cat, "top_agents": top_agents}

    @staticmethod
    def _row_to_dict(row) -> dict:
        d = dict(row)
        if d.get("result_json"):
            try:
                d["result"] = json.loads(d["result_json"])
            except Exception:
                d["result"] = {}
        d.pop("result_json", None)
        if d.get("tags") and isinstance(d["tags"], str) and d["tags"].startswith("["):
            try:
                d["tags"] = json.loads(d["tags"])
            except Exception:
                pass
        d["date"] = datetime.fromtimestamp(d.get("timestamp", 0)).strftime("%Y-%m-%d %H:%M")
        return d
