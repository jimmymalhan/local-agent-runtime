"""
procedural.py — Learned reusable patterns.

Stores code snippets, prompt templates, and workflows that produced quality >= 80.
Table: patterns(id, name, category, description, content, quality, uses, last_used)
"""
import sqlite3
import time
from typing import Optional


class ProceduralMemory:
    """Stores reusable patterns that worked well (quality >= 80)."""

    TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS procedural_patterns (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        name        TEXT NOT NULL UNIQUE,
        category    TEXT,
        description TEXT,
        content     TEXT NOT NULL,
        quality     INTEGER DEFAULT 80,
        uses        INTEGER DEFAULT 0,
        last_used   REAL
    );
    CREATE INDEX IF NOT EXISTS idx_patterns_category ON procedural_patterns(category);
    CREATE INDEX IF NOT EXISTS idx_patterns_quality  ON procedural_patterns(quality);
    CREATE INDEX IF NOT EXISTS idx_patterns_uses     ON procedural_patterns(uses);
    """

    # Minimum quality to auto-store a pattern
    QUALITY_THRESHOLD = 80

    def __init__(self, db_path: str, shared_conn: Optional[sqlite3.Connection] = None):
        self.db_path = db_path
        self._shared_conn = shared_conn
        self._init_schema()

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _conn(self) -> sqlite3.Connection:
        if self._shared_conn is not None:
            return self._shared_conn
        if not hasattr(self, "_own_conn") or self._own_conn is None:
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

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def store_pattern(
        self,
        name: str,
        category: str,
        description: str,
        content: str,
        quality: int,
    ) -> Optional[int]:
        """
        Store a pattern if quality >= threshold.
        If a pattern with the same name already exists, update it only if
        the new quality is higher or equal.
        Returns row id, or None if below threshold.
        """
        if quality < self.QUALITY_THRESHOLD:
            return None

        with self._conn() as conn:
            existing = conn.execute(
                "SELECT id, quality FROM procedural_patterns WHERE name = ?", (name,)
            ).fetchone()

            if existing:
                if quality >= existing["quality"]:
                    conn.execute(
                        """
                        UPDATE procedural_patterns
                        SET category = ?, description = ?, content = ?, quality = ?
                        WHERE id = ?
                        """,
                        (category, description, content, quality, existing["id"]),
                    )
                    conn.commit()
                return existing["id"]
            else:
                cursor = conn.execute(
                    """
                    INSERT INTO procedural_patterns
                        (name, category, description, content, quality, uses, last_used)
                    VALUES (?, ?, ?, ?, ?, 0, NULL)
                    """,
                    (name, category, description, content, quality),
                )
                conn.commit()
                return cursor.lastrowid

    def get_pattern(self, name: str) -> dict:
        """Retrieve a pattern by exact name. Returns {} if not found."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT * FROM procedural_patterns WHERE name = ?", (name,)
            ).fetchone()
        return dict(row) if row else {}

    def search_patterns(self, query: str, category: Optional[str] = None) -> list:
        """
        Keyword search across name, description, and content.
        Optionally filter by category.
        """
        keywords = [w.strip().lower() for w in query.split() if len(w.strip()) > 2]
        if not keywords:
            # No useful keywords — return top patterns for the category
            return self.top_patterns(n=5) if not category else self._by_category(category)

        conditions = " OR ".join(
            ["(LOWER(name) LIKE ? OR LOWER(description) LIKE ? OR LOWER(content) LIKE ?)"]
            * len(keywords)
        )
        params = []
        for kw in keywords:
            params += [f"%{kw}%", f"%{kw}%", f"%{kw}%"]

        cat_filter = ""
        if category:
            cat_filter = " AND category = ?"
            params.append(category)

        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT * FROM procedural_patterns
                WHERE ({conditions}){cat_filter}
                ORDER BY quality DESC, uses DESC
                LIMIT 10
                """,
                params,
            ).fetchall()

        return [dict(r) for r in rows]

    def increment_uses(self, pattern_id) -> bool:
        """Increment use counter and update last_used timestamp."""
        with self._conn() as conn:
            affected = conn.execute(
                "UPDATE procedural_patterns SET uses = uses + 1, last_used = ? WHERE id = ?",
                (time.time(), pattern_id),
            ).rowcount
            conn.commit()
        return affected > 0

    def top_patterns(self, n: int = 10) -> list:
        """Return the top-N patterns ranked by (quality * uses) or quality alone."""
        with self._conn() as conn:
            rows = conn.execute(
                """
                SELECT * FROM procedural_patterns
                ORDER BY quality DESC, uses DESC
                LIMIT ?
                """,
                (n,),
            ).fetchall()
        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Private
    # ------------------------------------------------------------------

    def _by_category(self, category: str, n: int = 10) -> list:
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT * FROM procedural_patterns WHERE category = ? ORDER BY quality DESC, uses DESC LIMIT ?",
                (category, n),
            ).fetchall()
        return [dict(r) for r in rows]
