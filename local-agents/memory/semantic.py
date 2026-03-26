import json, sqlite3, time
from typing import Optional

class SemanticMemory:
    TABLE_DDL = """
    CREATE TABLE IF NOT EXISTS semantic_facts (
        id INTEGER PRIMARY KEY AUTOINCREMENT, key TEXT NOT NULL,
        value TEXT NOT NULL, source TEXT, project_id TEXT, timestamp REAL NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_sk ON semantic_facts(key);
    CREATE INDEX IF NOT EXISTS idx_sp ON semantic_facts(project_id);
    CREATE TABLE IF NOT EXISTS semantic_project_maps (
        id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL UNIQUE,
        map_json TEXT NOT NULL, timestamp REAL NOT NULL
    );
    CREATE TABLE IF NOT EXISTS semantic_api_specs (
        id INTEGER PRIMARY KEY AUTOINCREMENT, project_id TEXT NOT NULL,
        endpoint TEXT NOT NULL, spec_json TEXT NOT NULL, timestamp REAL NOT NULL,
        UNIQUE(project_id, endpoint)
    );
    CREATE INDEX IF NOT EXISTS idx_ap ON semantic_api_specs(project_id);
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
    def store_fact(self, key: str, value: str, source: str, project_id=None):
        c = self._conn()
        ex = c.execute("SELECT id FROM semantic_facts WHERE key = ? AND (project_id = ? OR (project_id IS NULL AND ? IS NULL))", (key, project_id, project_id)).fetchone()
        if ex: c.execute("UPDATE semantic_facts SET value=?,source=?,timestamp=? WHERE id=?", (value, source, time.time(), ex["id"]))
        else: c.execute("INSERT INTO semantic_facts (key,value,source,project_id,timestamp) VALUES (?,?,?,?,?)", (key, value, source, project_id, time.time()))
        c.commit()
    def recall_facts(self, query: str, project_id=None, n: int = 10) -> list:
        kw = [w.strip().lower() for w in query.split() if len(w.strip()) > 2]
        if not kw: return []
        cond = " OR ".join(["(LOWER(key) LIKE ? OR LOWER(value) LIKE ?)"] * len(kw))
        params = [x for k in kw for x in (f"%{k}%", f"%{k}%")]
        pf = ""
        if project_id: params.append(project_id); pf = " AND project_id = ?"
        params.append(n)
        rows = self._conn().execute(f"SELECT id,key,value,source,project_id,timestamp FROM semantic_facts WHERE ({cond}){pf} ORDER BY timestamp DESC LIMIT ?", params).fetchall()
        return [dict(r) for r in rows]
    def store_project_map(self, project_id: str, project_map: dict):
        c = self._conn()
        c.execute("INSERT INTO semantic_project_maps (project_id,map_json,timestamp) VALUES (?,?,?) ON CONFLICT(project_id) DO UPDATE SET map_json=excluded.map_json,timestamp=excluded.timestamp", (project_id, json.dumps(project_map), time.time()))
        c.commit()
    def get_project_map(self, project_id: str) -> dict:
        row = self._conn().execute("SELECT map_json FROM semantic_project_maps WHERE project_id=?", (project_id,)).fetchone()
        if row:
            try: return json.loads(row["map_json"])
            except: return {}
        return {}
    def store_api_spec(self, project_id: str, endpoint: str, spec: dict):
        c = self._conn()
        c.execute("INSERT INTO semantic_api_specs (project_id,endpoint,spec_json,timestamp) VALUES (?,?,?,?) ON CONFLICT(project_id,endpoint) DO UPDATE SET spec_json=excluded.spec_json,timestamp=excluded.timestamp", (project_id, endpoint, json.dumps(spec), time.time()))
        c.commit()
    def get_api_spec(self, project_id: str, endpoint: str) -> dict:
        row = self._conn().execute("SELECT spec_json FROM semantic_api_specs WHERE project_id=? AND endpoint=?", (project_id, endpoint)).fetchone()
        if row:
            try: return json.loads(row["spec_json"])
            except: return {}
        return {}
    def list_api_specs(self, project_id: str) -> list:
        rows = self._conn().execute("SELECT endpoint,spec_json,timestamp FROM semantic_api_specs WHERE project_id=? ORDER BY endpoint", (project_id,)).fetchall()
        result = []
        for row in rows:
            try: spec = json.loads(row["spec_json"])
            except: spec = {}
            result.append({"endpoint": row["endpoint"], "spec": spec, "timestamp": row["timestamp"]})
        return result
