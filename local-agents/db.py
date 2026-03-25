"""
Business OS — Database layer
aiosqlite + WAL, all tables, helpers, seed data.
"""
import asyncio
import json
import os
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional

import aiosqlite

BOS_HOME = os.environ.get("BOS_HOME", str(Path.home() / "business-os"))
DB_PATH = os.path.join(BOS_HOME, "business.db")

PRAGMAS = """
PRAGMA journal_mode=WAL;
PRAGMA busy_timeout=5000;
PRAGMA synchronous=NORMAL;
PRAGMA cache_size=-64000;
PRAGMA foreign_keys=ON;
PRAGMA mmap_size=268435456;
PRAGMA temp_store=MEMORY;
"""

SCHEMA = """
CREATE TABLE IF NOT EXISTS projects (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    description TEXT DEFAULT '',
    color TEXT DEFAULT '#6d28d9',
    codebase_path TEXT DEFAULT '',
    task_type_default TEXT DEFAULT 'code',
    sprint_length_days INTEGER DEFAULT 14,
    wip_limit_in_progress INTEGER DEFAULT 5,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS sprints (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    start_date TEXT,
    end_date TEXT,
    status TEXT DEFAULT 'planned' CHECK(status IN ('active','complete','planned')),
    goal TEXT DEFAULT '',
    velocity_points REAL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    sprint_id INTEGER REFERENCES sprints(id) ON DELETE SET NULL,
    parent_task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    title TEXT NOT NULL,
    description TEXT DEFAULT '',
    task_type TEXT DEFAULT 'code' CHECK(task_type IN ('code','write','research','design','ops','bug')),
    status TEXT DEFAULT 'backlog' CHECK(status IN ('backlog','todo','in_progress','review','done','blocked')),
    priority TEXT DEFAULT 'medium' CHECK(priority IN ('critical','high','medium','low')),
    assignee TEXT DEFAULT 'unassigned' CHECK(assignee IN ('human','local-agent','opus','unassigned')),
    agent_model TEXT DEFAULT 'auto',
    story_points INTEGER DEFAULT 2,
    estimated_hours REAL DEFAULT 2.0,
    actual_hours REAL,
    eta_date TEXT,
    started_at TEXT,
    completed_at TEXT,
    due_date TEXT,
    updated_at TEXT DEFAULT (datetime('now')),
    created_at TEXT DEFAULT (datetime('now')),
    retry_count INTEGER DEFAULT 0,
    git_branch TEXT DEFAULT '',
    commit_sha TEXT DEFAULT '',
    worktree_path TEXT DEFAULT '',
    sort_order REAL DEFAULT 0.0,
    is_recurring INTEGER DEFAULT 0,
    recurrence_cron TEXT DEFAULT '',
    template_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL
);

CREATE TABLE IF NOT EXISTS task_deps (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    depends_on_task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    dep_type TEXT DEFAULT 'blocks' CHECK(dep_type IN ('blocks','relates','duplicates')),
    UNIQUE(task_id, depends_on_task_id)
);

CREATE TABLE IF NOT EXISTS labels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    color TEXT DEFAULT '#6b7280'
);

CREATE TABLE IF NOT EXISTS task_labels (
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    label_id INTEGER NOT NULL REFERENCES labels(id) ON DELETE CASCADE,
    PRIMARY KEY(task_id, label_id)
);

CREATE TABLE IF NOT EXISTS task_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    message TEXT NOT NULL,
    source TEXT DEFAULT 'system' CHECK(source IN ('human','agent','system','error')),
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS activity_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    user TEXT DEFAULT 'system',
    field_changed TEXT,
    old_value TEXT,
    new_value TEXT,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS comments (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user TEXT DEFAULT 'human',
    body TEXT NOT NULL,
    mentions TEXT DEFAULT '[]',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS time_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    user TEXT DEFAULT 'human',
    started_at TEXT NOT NULL,
    ended_at TEXT,
    duration_seconds INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS task_templates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    project_id INTEGER REFERENCES projects(id) ON DELETE CASCADE,
    name TEXT NOT NULL,
    default_fields TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS agent_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    model_used TEXT,
    duration_seconds REAL DEFAULT 0,
    estimated_hours REAL DEFAULT 0,
    actual_hours REAL DEFAULT 0,
    success INTEGER DEFAULT 0,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS api_usage (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    model TEXT,
    input_tokens INTEGER DEFAULT 0,
    output_tokens INTEGER DEFAULT 0,
    cost_usd REAL DEFAULT 0.0,
    timestamp TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user TEXT DEFAULT 'human',
    type TEXT DEFAULT 'info',
    message TEXT NOT NULL,
    task_id INTEGER REFERENCES tasks(id) ON DELETE SET NULL,
    read INTEGER DEFAULT 0,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    api_key_hash TEXT DEFAULT '',
    color TEXT DEFAULT '#6d28d9',
    avatar_initials TEXT DEFAULT 'U',
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS task_queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id INTEGER NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    status TEXT DEFAULT 'pending' CHECK(status IN ('pending','processing','done')),
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS presence (
    user_id TEXT PRIMARY KEY,
    board_id TEXT DEFAULT '',
    task_id INTEGER,
    last_seen TEXT DEFAULT (datetime('now'))
);
"""

INDEXES = """
CREATE INDEX IF NOT EXISTS idx_tasks_project_status_priority ON tasks(project_id, status, priority);
CREATE INDEX IF NOT EXISTS idx_tasks_assignee_status ON tasks(assignee, status);
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id);
CREATE INDEX IF NOT EXISTS idx_tasks_sprint ON tasks(sprint_id);
CREATE INDEX IF NOT EXISTS idx_tasks_updated ON tasks(updated_at);
CREATE INDEX IF NOT EXISTS idx_activity_task_ts ON activity_log(task_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_task_logs_task ON task_logs(task_id, timestamp);
CREATE INDEX IF NOT EXISTS idx_task_queue_status ON task_queue(status, created_at);
"""


async def get_db() -> aiosqlite.Connection:
    db = await aiosqlite.connect(DB_PATH)
    db.row_factory = aiosqlite.Row
    for pragma in PRAGMAS.strip().split("\n"):
        pragma = pragma.strip()
        if pragma:
            await db.execute(pragma)
    return db


async def init_db():
    """Create tables + seed only if DB is brand new."""
    db_exists = Path(DB_PATH).exists()
    db = await get_db()
    try:
        async with db.executescript(SCHEMA + INDEXES):
            pass
        await db.commit()

        # Check if already seeded
        cursor = await db.execute("SELECT COUNT(*) FROM projects")
        count = (await cursor.fetchone())[0]
        if count == 0:
            await _seed_db(db)
    finally:
        await db.close()


async def _seed_db(db: aiosqlite.Connection):
    """Seed one project + one sprint + 3 sample tasks."""
    now = datetime.utcnow().isoformat()
    sprint_start = datetime.utcnow().date().isoformat()
    sprint_end = (datetime.utcnow() + timedelta(days=14)).date().isoformat()

    cursor = await db.execute(
        """INSERT INTO projects (name, description, color, codebase_path, task_type_default)
           VALUES (?, ?, ?, ?, ?)""",
        ("My Business", "Default project for Business OS", "#6d28d9", BOS_HOME, "code"),
    )
    project_id = cursor.lastrowid

    cursor = await db.execute(
        """INSERT INTO sprints (project_id, name, start_date, end_date, status, goal)
           VALUES (?, ?, ?, ?, ?, ?)""",
        (project_id, "Sprint 1", sprint_start, sprint_end, "active", "Get BOS running"),
    )
    sprint_id = cursor.lastrowid

    tasks = [
        (project_id, sprint_id, "Set up Business OS infrastructure", "Install and configure all services", "ops", "done", "high", "human", "none", 3, 4.0, 4.0),
        (project_id, sprint_id, "Build agent loop worker", "Implement autonomous aider agent loop", "code", "todo", "high", "local-agent", "qwen2.5-coder:7b", 5, 8.0, None),
        (project_id, sprint_id, "Write project documentation", "Create README and CLAUDE.md for the project", "write", "backlog", "medium", "local-agent", "deepseek-r1:14b", 2, 3.0, None),
    ]

    for i, t in enumerate(tasks):
        await db.execute(
            """INSERT INTO tasks (project_id, sprint_id, title, description, task_type, status,
               priority, assignee, agent_model, story_points, estimated_hours, actual_hours, sort_order)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (*t, float(i)),
        )

    # Default user
    await db.execute(
        "INSERT INTO users (name, color, avatar_initials) VALUES (?, ?, ?)",
        ("Admin", "#6d28d9", "AD"),
    )

    # Default settings
    defaults = [
        ("slack_webhook", ""),
        ("discord_webhook", ""),
        ("ntfy_topic", "business-os"),
        ("ntfy_url", "http://localhost:2586"),
        ("api_cost_warn_usd_day", "10.0"),
        ("current_task_id", ""),
        ("current_model", ""),
        ("agent_status", "idle"),
    ]
    for key, val in defaults:
        await db.execute(
            "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (key, val)
        )

    await db.commit()


# ---------------------------------------------------------------------------
# Model routing
# ---------------------------------------------------------------------------

MODEL_MAP = {
    "code": "qwen2.5-coder:7b",
    "bug": "qwen2.5-coder:7b",
    "research": "deepseek-r1:14b",
    "write": "deepseek-r1:14b",
    "ops": "llama3.1:8b",
    "design": "llama3.1:8b",
}


def resolve_model(task: dict) -> str:
    """Return the ollama model string for a task dict."""
    if task.get("assignee") == "opus":
        return "claude-sonnet-4-6"
    model = task.get("agent_model", "auto")
    if model and model not in ("auto", "none", ""):
        return model
    task_type = task.get("task_type", "code")
    return MODEL_MAP.get(task_type, "llama3.1:8b")


# ---------------------------------------------------------------------------
# ETA helpers
# ---------------------------------------------------------------------------

async def compute_eta(task_id: int) -> Optional[str]:
    """Compute eta_date from estimated_hours, fallback to avg last 10."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT estimated_hours, task_type, agent_model FROM tasks WHERE id=?",
            (task_id,),
        )
        row = await cursor.fetchone()
        if not row:
            return None

        hours = row["estimated_hours"]
        if not hours:
            # fallback: avg of last 10 same type+model
            cursor2 = await db.execute(
                """SELECT AVG(actual_hours) FROM tasks
                   WHERE task_type=? AND agent_model=? AND actual_hours IS NOT NULL
                   ORDER BY completed_at DESC LIMIT 10""",
                (row["task_type"], row["agent_model"]),
            )
            avg_row = await cursor2.fetchone()
            hours = (avg_row[0] if avg_row and avg_row[0] else None) or 2.0

        eta = datetime.utcnow() + timedelta(hours=float(hours))
        eta_str = eta.isoformat()
        await db.execute(
            "UPDATE tasks SET eta_date=?, estimated_hours=? WHERE id=?",
            (eta_str, hours, task_id),
        )
        await db.commit()
        return eta_str
    finally:
        await db.close()


async def project_eta(project_id: int) -> dict:
    """Return percent_complete, estimated_completion, is_on_track, agents_assigned."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT COUNT(*) as total, SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done FROM tasks WHERE project_id=?",
            (project_id,),
        )
        row = await cursor.fetchone()
        total = row["total"] or 1
        done = row["done"] or 0
        pct = round((done / total) * 100, 1)

        cursor2 = await db.execute(
            """SELECT SUM(estimated_hours) as remaining FROM tasks
               WHERE project_id=? AND status NOT IN ('done','blocked')""",
            (project_id,),
        )
        r2 = await cursor2.fetchone()
        remaining_hours = r2["remaining"] or 0

        cursor3 = await db.execute(
            "SELECT COUNT(DISTINCT assignee) FROM tasks WHERE project_id=? AND assignee='local-agent' AND status='in_progress'",
            (project_id,),
        )
        r3 = await cursor3.fetchone()
        agents = r3[0] or 0

        # Estimate: assume 1 agent works 8h/day
        days_remaining = remaining_hours / 8.0 if remaining_hours else 0
        estimated_completion = (datetime.utcnow() + timedelta(days=days_remaining)).date().isoformat()

        # Check against sprint end
        cursor4 = await db.execute(
            "SELECT end_date FROM sprints WHERE project_id=? AND status='active' LIMIT 1",
            (project_id,),
        )
        r4 = await cursor4.fetchone()
        is_on_track = True
        if r4 and r4["end_date"]:
            sprint_end = datetime.fromisoformat(r4["end_date"]).date()
            est_end = datetime.fromisoformat(estimated_completion).date()
            is_on_track = est_end <= sprint_end

        return {
            "percent_complete": pct,
            "estimated_completion": estimated_completion,
            "is_on_track": is_on_track,
            "agents_assigned": agents,
        }
    finally:
        await db.close()


async def sprint_velocity(sprint_id: int) -> float:
    """Return story_points_done / sprint_days."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT start_date, end_date FROM sprints WHERE id=?", (sprint_id,)
        )
        row = await cursor.fetchone()
        if not row or not row["start_date"] or not row["end_date"]:
            return 0.0

        start = datetime.fromisoformat(row["start_date"])
        end = datetime.fromisoformat(row["end_date"])
        days = max((end - start).days, 1)

        cursor2 = await db.execute(
            "SELECT SUM(story_points) FROM tasks WHERE sprint_id=? AND status='done'",
            (sprint_id,),
        )
        r2 = await cursor2.fetchone()
        points = r2[0] or 0
        return round(points / days, 2)
    finally:
        await db.close()


async def predict_actual(task_type: str, model: str) -> float:
    """OLS regression on historical estimated vs actual hours."""
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT estimated_hours, actual_hours FROM tasks
               WHERE task_type=? AND agent_model=? AND actual_hours IS NOT NULL
               AND estimated_hours IS NOT NULL LIMIT 100""",
            (task_type, model),
        )
        rows = await cursor.fetchall()
        if len(rows) < 2:
            return 2.0

        n = len(rows)
        xs = [r["estimated_hours"] for r in rows]
        ys = [r["actual_hours"] for r in rows]
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
        den = sum((x - mean_x) ** 2 for x in xs) or 1
        slope = num / den
        intercept = mean_y - slope * mean_x
        # Predict for mean_x as a representative point
        return round(max(slope * mean_x + intercept, 0.25), 2)
    finally:
        await db.close()


async def next_sort_order(status_col: str, project_id: int) -> float:
    """Fractional indexing: return max sort_order + 1.0 for given status."""
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT MAX(sort_order) FROM tasks WHERE project_id=? AND status=?",
            (project_id, status_col),
        )
        row = await cursor.fetchone()
        current_max = row[0] if row and row[0] is not None else 0.0
        return current_max + 1.0
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Utility: log a task action
# ---------------------------------------------------------------------------

async def log_task(db: aiosqlite.Connection, task_id: int, message: str, source: str = "system"):
    await db.execute(
        "INSERT INTO task_logs (task_id, message, source) VALUES (?, ?, ?)",
        (task_id, message, source),
    )


async def log_activity(
    db: aiosqlite.Connection,
    task_id: int,
    user: str,
    field: str,
    old_val: str,
    new_val: str,
):
    await db.execute(
        "INSERT INTO activity_log (task_id, user, field_changed, old_value, new_value) VALUES (?,?,?,?,?)",
        (task_id, user, field, str(old_val), str(new_val)),
    )
