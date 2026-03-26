"""
semantic.py — Codebase and domain knowledge store.

Stores facts about projects: file structures, API specs, framework versions, etc.
Table: facts(id, key, value, source, project_id, timestamp)
Table: project_maps(id, project_id, map_json, timestamp)
Table: api_specs(id, project_id, endpoint, spec_json, timestamp)
"""
import json
import sqlite3
import time
from typing import Optional


class SemanticMemory:
    """Stores facts about codebases and domains. Simple keyword index."""

    TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS semantic_facts (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        key         TEXT NOT NULL,
        value       TEXT NOT NULL,
        source      TEXT,
        project_id  TEXT,
        timestamp   REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_semantic_key        ON semantic_facts(key);
    CREATE INDEX IF NOT EXISTS idx_semantic_project    ON semantic_facts(project_id);

    CREATE TABLE IF NOT EXISTS semantic_project_maps (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  TEXT NOT NULL UNIQUE,
        map_json    TEXT NOT NULL,
        timestamp   REAL NOT NULL
    );

    CREATE TABLE IF NOT EXISTS semantic_api_specs (
        id          INTEGER PRIMARY KEY AUTOINCREMENT,
        project_id  TEXT NOT NULL,
        endpoint    TEXT NOT NULL,
        spec_json   TEXT NOT NULL,
        timestamp   REAL NOT NULL,
        UNIQUE(project_id, endpoint)
    );
    CREATE INDEX IF NOT EXISTS idx_api_project ON semantic_api_specs(project_id);
    """

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
    # Facts
    # ------------------------------------------------------------------

    def store_fact(self, key: str, value: str, source: str, project_id: Optional[str] = None):
        """Insert or replace a fact by key (per project_id if provided)."""
        with self._conn() as conn:
            # Replace existing fact with same key + project_id
            existing = conn.execute(
                "SELECT id FROM semantic_facts WHERE key = ? AND (project_id = ? OR (project_id IS NULL AND ? IS NULL))",
                (key, project_id, project_id),
            ).fetchone()
            if existing:
                conn.execute(
                    "UPDATE semantic_facts SET value = ?, source = ?, timestamp = ? WHERE id = ?",
                    (value, source, time.time(), existing["id"]),
                )
            else:
                conn.execute(
                    "INSERT INTO semantic_facts (key, value, source, project_id, timestamp) VALUES (?, ?, ?, ?, ?)",
                    (key, value, source, project_id, time.time()),
                )
            conn.commit()

    def recall_facts(self, query: str, project_id: Optional[str] = None, n: int = 10) -> list:
        """Find facts whose key or value contain any query keyword."""
        keywords = [w.strip().lower() for w in query.split() if len(w.strip()) > 2]
        if not keywords:
            return []

        conditions = " OR ".join(
            ["(LOWER(key) LIKE ? OR LOWER(value) LIKE ?)"] * len(keywords)
        )
        params = []
        for kw in keywords:
            params += [f"%{kw}%", f"%{kw}%"]

        project_filter = ""
        if project_id:
            project_filter = " AND project_id = ?"
            params.append(project_id)

        params.append(n)

        with self._conn() as conn:
            rows = conn.execute(
                f"""
                SELECT id, key, value, source, project_id, timestamp
                FROM semantic_facts
                WHERE ({conditions}){project_filter}
                ORDER BY timestamp DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        return [dict(r) for r in rows]

    # ------------------------------------------------------------------
    # Project maps
    # ------------------------------------------------------------------

    def store_project_map(self, project_id: str, project_map: dict):
        """Upsert a full project map (file tree, key files, stack info, etc.)."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO semantic_project_maps (project_id, map_json, timestamp)
                VALUES (?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET map_json = excluded.map_json, timestamp = excluded.timestamp
                """,
                (project_id, json.dumps(project_map), time.time()),
            )
            conn.commit()

    def get_project_map(self, project_id: str) -> dict:
        """Retrieve a stored project map. Returns {} if not found."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT map_json FROM semantic_project_maps WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        if row:
            try:
                return json.loads(row["map_json"])
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    # ------------------------------------------------------------------
    # API specs
    # ------------------------------------------------------------------

    def store_api_spec(self, project_id: str, endpoint: str, spec: dict):
        """Upsert an API endpoint spec (method, params, response shape, etc.)."""
        with self._conn() as conn:
            conn.execute(
                """
                INSERT INTO semantic_api_specs (project_id, endpoint, spec_json, timestamp)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(project_id, endpoint) DO UPDATE
                    SET spec_json = excluded.spec_json, timestamp = excluded.timestamp
                """,
                (project_id, endpoint, json.dumps(spec), time.time()),
            )
            conn.commit()

    def get_api_spec(self, project_id: str, endpoint: str) -> dict:
        """Retrieve a specific endpoint spec. Returns {} if not found."""
        with self._conn() as conn:
            row = conn.execute(
                "SELECT spec_json FROM semantic_api_specs WHERE project_id = ? AND endpoint = ?",
                (project_id, endpoint),
            ).fetchone()
        if row:
            try:
                return json.loads(row["spec_json"])
            except (json.JSONDecodeError, TypeError):
                return {}
        return {}

    def list_api_specs(self, project_id: str) -> list:
        """Return all endpoint specs for a project."""
        with self._conn() as conn:
            rows = conn.execute(
                "SELECT endpoint, spec_json, timestamp FROM semantic_api_specs WHERE project_id = ? ORDER BY endpoint",
                (project_id,),
            ).fetchall()
        result = []
        for row in rows:
            try:
                spec = json.loads(row["spec_json"])
            except (json.JSONDecodeError, TypeError):
                spec = {}
            result.append({"endpoint": row["endpoint"], "spec": spec, "timestamp": row["timestamp"]})
        return result
