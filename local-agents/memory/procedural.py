import sqlite3, time
from typing import Optional

class ProceduralMemory:
    TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS procedural_patterns (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL UNIQUE,
        category TEXT, description TEXT, content TEXT NOT NULL,
        quality INTEGER DEFAULT 80, uses INTEGER DEFAULT 0, last_used REAL
    );
    CREATE INDEX IF NOT EXISTS idx_pc ON procedural_patterns(category);
    CREATE INDEX IF NOT EXISTS idx_pq ON procedural_patterns(quality);
    CREATE INDEX IF NOT EXISTS idx_pu ON procedural_patterns(uses);
    """
    QUALITY_THRESHOLD = 80
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
    def store_pattern(self, name: str, category: str, description: str, content: str, quality: int):
        if quality < self.QUALITY_THRESHOLD: return None
        c = self._conn()
        ex = c.execute("SELECT id,quality FROM procedural_patterns WHERE name=?", (name,)).fetchone()
        if ex:
            if quality >= ex["quality"]:
                c.execute("UPDATE procedural_patterns SET category=?,description=?,content=?,quality=? WHERE id=?", (category, description, content, quality, ex["id"]))
                c.commit()
            return ex["id"]
        cur = c.execute("INSERT INTO procedural_patterns (name,category,description,content,quality,uses,last_used) VALUES (?,?,?,?,?,0,NULL)", (name, category, description, content, quality))
        c.commit()
        return cur.lastrowid
    def get_pattern(self, name: str) -> dict:
        row = self._conn().execute("SELECT * FROM procedural_patterns WHERE name=?", (name,)).fetchone()
        return dict(row) if row else {}
    def search_patterns(self, query: str, category=None) -> list:
        kw = [w.strip().lower() for w in query.split() if len(w.strip()) > 2]
        if not kw: return self.top_patterns(5) if not category else self._by_category(category)
        cond = " OR ".join(["(LOWER(name) LIKE ? OR LOWER(description) LIKE ? OR LOWER(content) LIKE ?)"] * len(kw))
        params = [x for k in kw for x in (f"%{k}%", f"%{k}%", f"%{k}%")]
        cf = ""
        if category: params.append(category); cf = " AND category=?"
        rows = self._conn().execute(f"SELECT * FROM procedural_patterns WHERE ({cond}){cf} ORDER BY quality DESC, uses DESC LIMIT 10", params).fetchall()
        return [dict(r) for r in rows]
    def increment_uses(self, pattern_id) -> bool:
        c = self._conn()
        affected = c.execute("UPDATE procedural_patterns SET uses=uses+1,last_used=? WHERE id=?", (time.time(), pattern_id)).rowcount
        c.commit()
        return affected > 0
    def top_patterns(self, n: int = 10) -> list:
        rows = self._conn().execute("SELECT * FROM procedural_patterns ORDER BY quality DESC, uses DESC LIMIT ?", (n,)).fetchall()
        return [dict(r) for r in rows]
    def _by_category(self, category: str, n: int = 10) -> list:
        rows = self._conn().execute("SELECT * FROM procedural_patterns WHERE category=? ORDER BY quality DESC, uses DESC LIMIT ?", (category, n)).fetchall()
        return [dict(r) for r in rows]
