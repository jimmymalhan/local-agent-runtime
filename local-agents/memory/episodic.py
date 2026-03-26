import json, sqlite3, time
from datetime import datetime
from typing import Optional

class EpisodicMemory:
    TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS episodic_tasks (
        id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL,
        category TEXT, description TEXT, result_json TEXT,
        quality INTEGER DEFAULT 0, agent TEXT, timestamp REAL NOT NULL, tags TEXT
    );
    CREATE INDEX IF NOT EXISTS idx_ec ON episodic_tasks(category);
    CREATE INDEX IF NOT EXISTS idx_eq ON episodic_tasks(quality);
    CREATE INDEX IF NOT EXISTS idx_et ON episodic_tasks(timestamp);
    """
    def __init__(self, db_path: str, shared_conn=None):
        self.db_path = db_path
        self._shared_conn = shared_conn
        self._own_conn = None
        self._init_schema()
    def _conn(self):
        if self._shared_conn is not None: return self._shared_conn
        if self._own_conn is None:
            self._own_conn = sqlite3.connect(self.db_path, check_same_thread=False)
            self._own_conn.row_factory = sqlite3.Row
        return self._own_conn
    def _init_schema(self):
        c = self._conn()
        for s in self.TABLE_DDL.strip().split(";"):
            s = s.strip()
            if s: c.execute(s)
        c.commit()
    def store(self, task: dict, result: dict, quality: int) -> int:
        tags = task.get("tags")
        if isinstance(tags, (list, dict)): tags = json.dumps(tags)
        c = self._conn()
        cur = c.execute(
            "INSERT INTO episodic_tasks (title,category,description,result_json,quality,agent,timestamp,tags) VALUES (?,?,?,?,?,?,?,?)",
            (task.get("title",""), task.get("category",""), task.get("description",""),
             json.dumps(result), quality, result.get("agent_name") or task.get("agent",""),
             time.time(), tags))
        c.commit()
        return cur.lastrowid
    def recall(self, query: str, n: int = 5, min_quality: int = 0) -> list:
        kw = [w.strip().lower() for w in query.split() if len(w.strip()) > 2]
        if not kw: return []
        cond = " OR ".join(["(LOWER(title) LIKE ? OR LOWER(description) LIKE ?)"] * len(kw))
        params = [x for k in kw for x in (f"%{k}%", f"%{k}%")] + [min_quality, n]
        rows = self._conn().execute(
            f"SELECT * FROM episodic_tasks WHERE ({cond}) AND quality >= ? ORDER BY quality DESC, timestamp DESC LIMIT ?",
            params).fetchall()
        return [self._to_dict(r) for r in rows]
    def get_failures(self, category=None) -> list:
        c = self._conn()
        if category: rows = c.execute("SELECT * FROM episodic_tasks WHERE quality < 50 AND category = ? ORDER BY timestamp DESC", (category,)).fetchall()
        else: rows = c.execute("SELECT * FROM episodic_tasks WHERE quality < 50 ORDER BY timestamp DESC").fetchall()
        return [self._to_dict(r) for r in rows]
    def get_successes(self, min_quality: int = 80) -> list:
        rows = self._conn().execute("SELECT * FROM episodic_tasks WHERE quality >= ? ORDER BY quality DESC, timestamp DESC", (min_quality,)).fetchall()
        return [self._to_dict(r) for r in rows]
    def stats(self) -> dict:
        c = self._conn()
        total = c.execute("SELECT COUNT(*) FROM episodic_tasks").fetchone()[0]
        avg_q = c.execute("SELECT AVG(quality) FROM episodic_tasks").fetchone()[0] or 0
        by_cat = {}
        for row in c.execute("SELECT category, COUNT(*), AVG(quality) FROM episodic_tasks GROUP BY category").fetchall():
            by_cat[row[0] or "unknown"] = {"count": row[1], "avg_quality": round(row[2] or 0, 1)}
        top_agents = {}
        for row in c.execute("SELECT agent, COUNT(*), AVG(quality) FROM episodic_tasks GROUP BY agent ORDER BY AVG(quality) DESC LIMIT 10").fetchall():
            top_agents[row[0] or "unknown"] = {"count": row[1], "avg_quality": round(row[2] or 0, 1)}
        return {"total": total, "avg_quality": round(avg_q, 1), "by_category": by_cat, "top_agents": top_agents}
    @staticmethod
    def _to_dict(row) -> dict:
        d = dict(row)
        if d.get("result_json"):
            try: d["result"] = json.loads(d["result_json"])
            except: d["result"] = {}
        d.pop("result_json", None)
        d["date"] = datetime.fromtimestamp(d.get("timestamp", 0)).strftime("%Y-%m-%d %H:%M")
        return d
