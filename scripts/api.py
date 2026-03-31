"""
Business OS — FastAPI backend  port 8000
Full production implementation: CRUD, WebSocket, SSE, JWT, agent queue,
metrics, supervisor, notifications, APScheduler, LiteLLM fallback.
"""
import asyncio
import hashlib
import json
import os
import re
import subprocess
import time
import xmlrpc.client
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import aiosqlite
import httpx
import jwt
import psutil
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from croniter import croniter
from fastapi import (
    BackgroundTasks,
    Depends,
    FastAPI,
    HTTPException,
    Query,
    Request,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

from db import (
    DB_PATH,
    BOS_HOME,
    compute_eta,
    get_db,
    init_db,
    log_activity,
    log_task,
    next_sort_order,
    predict_actual,
    project_eta,
    resolve_model,
    sprint_velocity,
)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------
JWT_SECRET = os.environ.get("BOS_JWT_SECRET", "bos-dev-secret-change-in-prod")
JWT_ALGO = "HS256"
JWT_EXP_HOURS = 72
API_COST_WARN = 10.0

# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------
event_queue: asyncio.Queue = asyncio.Queue()
connections: Dict[str, List[WebSocket]] = {}  # board_id → [ws]
last_log_id: int = 0
scheduler = AsyncIOScheduler()


# ---------------------------------------------------------------------------
# Lifespan
# ---------------------------------------------------------------------------
@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    # Replay pending task_queue rows (crash recovery)
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT task_id FROM task_queue WHERE status='pending' ORDER BY created_at"
        )
        rows = await cursor.fetchall()
        for row in rows:
            await event_queue.put({"task_id": row["task_id"], "type": "run"})
    finally:
        await db.close()

    # Start 2 agent worker coroutines
    workers = [asyncio.create_task(_agent_worker(i)) for i in range(2)]

    # Load recurring tasks into APScheduler
    await _load_recurring_tasks()
    scheduler.start()

    # Daily summary at 8am
    scheduler.add_job(_daily_summary, "cron", hour=8, minute=0)

    yield

    scheduler.shutdown(wait=False)
    for w in workers:
        w.cancel()


app = FastAPI(title="Business OS API", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# JWT middleware — skip /auth/* /ws/*
# ---------------------------------------------------------------------------
@app.middleware("http")
async def jwt_middleware(request: Request, call_next):
    path = request.url.path
    if path.startswith("/auth/") or path.startswith("/ws/") or path.startswith("/docs") or path.startswith("/openapi"):
        return await call_next(request)
    # Optional auth — don't hard-block dev usage
    token = request.headers.get("Authorization", "").replace("Bearer ", "")
    if token:
        try:
            request.state.user = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGO])
        except jwt.ExpiredSignatureError:
            return JSONResponse({"detail": "Token expired"}, status_code=401)
        except jwt.InvalidTokenError:
            return JSONResponse({"detail": "Invalid token"}, status_code=401)
    else:
        request.state.user = {"sub": "anonymous", "name": "Anonymous"}
    return await call_next(request)


# ---------------------------------------------------------------------------
# Auth
# ---------------------------------------------------------------------------
class LoginBody(BaseModel):
    name: str
    api_key: str


@app.post("/auth/token")
async def auth_token(body: LoginBody):
    db = await get_db()
    try:
        key_hash = hashlib.sha256(body.api_key.encode()).hexdigest()
        cursor = await db.execute(
            "SELECT * FROM users WHERE name=? AND api_key_hash=?",
            (body.name, key_hash),
        )
        user = await cursor.fetchone()
        if not user:
            # Dev: create user if api_key is "dev"
            if body.api_key == "dev":
                cursor2 = await db.execute(
                    "SELECT * FROM users WHERE name=?", (body.name,)
                )
                user = await cursor2.fetchone()
                if not user:
                    c = await db.execute(
                        "INSERT INTO users (name, api_key_hash, color, avatar_initials) VALUES (?,?,?,?)",
                        (body.name, key_hash, "#6d28d9", body.name[:2].upper()),
                    )
                    await db.commit()
                    user = {"id": c.lastrowid, "name": body.name}
            else:
                raise HTTPException(status_code=401, detail="Invalid credentials")
        payload = {
            "sub": str(user["id"] if hasattr(user, "__getitem__") else user.get("id", 1)),
            "name": body.name,
            "exp": datetime.utcnow() + timedelta(hours=JWT_EXP_HOURS),
        }
        token = jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGO)
        return {"access_token": token, "token_type": "bearer"}
    finally:
        await db.close()


@app.get("/users/me")
async def get_me(request: Request):
    return request.state.user


# ---------------------------------------------------------------------------
# Projects
# ---------------------------------------------------------------------------
class ProjectBody(BaseModel):
    name: str
    description: Optional[str] = ""
    color: Optional[str] = "#6d28d9"
    codebase_path: Optional[str] = ""
    task_type_default: Optional[str] = "code"
    sprint_length_days: Optional[int] = 14
    wip_limit_in_progress: Optional[int] = 5


@app.get("/projects")
async def list_projects():
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM projects ORDER BY created_at")
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            p = dict(r)
            eta = await project_eta(p["id"])
            p.update(eta)
            # active sprint
            c2 = await db.execute(
                "SELECT * FROM sprints WHERE project_id=? AND status='active' LIMIT 1",
                (p["id"],),
            )
            sprint = await c2.fetchone()
            p["active_sprint"] = dict(sprint) if sprint else None
            result.append(p)
        return result
    finally:
        await db.close()


@app.post("/projects", status_code=201)
async def create_project(body: ProjectBody):
    if body.codebase_path and not Path(body.codebase_path).exists():
        raise HTTPException(400, f"Path does not exist: {body.codebase_path}")
    db = await get_db()
    try:
        c = await db.execute(
            """INSERT INTO projects (name, description, color, codebase_path,
               task_type_default, sprint_length_days, wip_limit_in_progress)
               VALUES (?,?,?,?,?,?,?)""",
            (body.name, body.description, body.color, body.codebase_path,
             body.task_type_default, body.sprint_length_days, body.wip_limit_in_progress),
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM projects WHERE id=?", (c.lastrowid,))
        row = await cursor.fetchone()
        return dict(row)
    finally:
        await db.close()


@app.get("/projects/{project_id}")
async def get_project(project_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM projects WHERE id=?", (project_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Project not found")
        p = dict(row)
        p.update(await project_eta(project_id))
        return p
    finally:
        await db.close()


@app.patch("/projects/{project_id}")
async def update_project(project_id: int, body: dict):
    if "codebase_path" in body and body["codebase_path"]:
        if not Path(body["codebase_path"]).exists():
            raise HTTPException(400, f"Path does not exist: {body['codebase_path']}")
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM projects WHERE id=?", (project_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Project not found")
        allowed = {"name","description","color","codebase_path","task_type_default","sprint_length_days","wip_limit_in_progress"}
        updates = {k: v for k, v in body.items() if k in allowed}
        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            await db.execute(
                f"UPDATE projects SET {set_clause} WHERE id=?",
                (*updates.values(), project_id),
            )
            await db.commit()
        cursor2 = await db.execute("SELECT * FROM projects WHERE id=?", (project_id,))
        return dict(await cursor2.fetchone())
    finally:
        await db.close()


@app.delete("/projects/{project_id}", status_code=204)
async def delete_project(project_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM projects WHERE id=?", (project_id,))
        await db.commit()
    finally:
        await db.close()


@app.get("/projects/validate-path")
async def validate_path(path: str = Query(...)):
    return {"exists": Path(path).exists(), "path": path}


# ---------------------------------------------------------------------------
# Sprints
# ---------------------------------------------------------------------------
class SprintBody(BaseModel):
    project_id: int
    name: str
    start_date: Optional[str] = None
    end_date: Optional[str] = None
    status: Optional[str] = "planned"
    goal: Optional[str] = ""


@app.get("/sprints")
async def list_sprints(project_id: Optional[int] = None):
    db = await get_db()
    try:
        if project_id:
            cursor = await db.execute(
                "SELECT * FROM sprints WHERE project_id=? ORDER BY start_date", (project_id,)
            )
        else:
            cursor = await db.execute("SELECT * FROM sprints ORDER BY start_date")
        rows = await cursor.fetchall()
        result = []
        for r in rows:
            s = dict(r)
            s["velocity"] = await sprint_velocity(s["id"])
            result.append(s)
        return result
    finally:
        await db.close()


@app.post("/sprints", status_code=201)
async def create_sprint(body: SprintBody):
    db = await get_db()
    try:
        c = await db.execute(
            "INSERT INTO sprints (project_id, name, start_date, end_date, status, goal) VALUES (?,?,?,?,?,?)",
            (body.project_id, body.name, body.start_date, body.end_date, body.status, body.goal),
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM sprints WHERE id=?", (c.lastrowid,))
        return dict(await cursor.fetchone())
    finally:
        await db.close()


@app.get("/sprints/{sprint_id}")
async def get_sprint(sprint_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM sprints WHERE id=?", (sprint_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404)
        s = dict(row)
        s["velocity"] = await sprint_velocity(sprint_id)
        return s
    finally:
        await db.close()


@app.patch("/sprints/{sprint_id}")
async def update_sprint(sprint_id: int, body: dict):
    db = await get_db()
    try:
        allowed = {"name","start_date","end_date","status","goal","velocity_points"}
        updates = {k: v for k, v in body.items() if k in allowed}
        if updates:
            set_clause = ", ".join(f"{k}=?" for k in updates)
            await db.execute(
                f"UPDATE sprints SET {set_clause} WHERE id=?",
                (*updates.values(), sprint_id),
            )
            await db.commit()
        cursor = await db.execute("SELECT * FROM sprints WHERE id=?", (sprint_id,))
        return dict(await cursor.fetchone())
    finally:
        await db.close()


@app.delete("/sprints/{sprint_id}", status_code=204)
async def delete_sprint(sprint_id: int):
    db = await get_db()
    try:
        await db.execute("DELETE FROM sprints WHERE id=?", (sprint_id,))
        await db.commit()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Tasks
# ---------------------------------------------------------------------------
class TaskBody(BaseModel):
    project_id: int
    sprint_id: Optional[int] = None
    parent_task_id: Optional[int] = None
    title: str
    description: Optional[str] = ""
    task_type: Optional[str] = "code"
    status: Optional[str] = "backlog"
    priority: Optional[str] = "medium"
    assignee: Optional[str] = "unassigned"
    agent_model: Optional[str] = "auto"
    story_points: Optional[int] = 2
    estimated_hours: Optional[float] = 2.0
    due_date: Optional[str] = None
    is_recurring: Optional[bool] = False
    recurrence_cron: Optional[str] = ""
    template_id: Optional[int] = None


async def _task_row_to_dict(db, row) -> dict:
    t = dict(row)
    # labels
    c = await db.execute(
        """SELECT l.* FROM labels l
           JOIN task_labels tl ON tl.label_id=l.id
           WHERE tl.task_id=?""",
        (t["id"],),
    )
    t["labels"] = [dict(r) for r in await c.fetchall()]
    # subtasks count
    c2 = await db.execute(
        "SELECT COUNT(*) as cnt, SUM(CASE WHEN status='done' THEN 1 ELSE 0 END) as done FROM tasks WHERE parent_task_id=?",
        (t["id"],),
    )
    sub = await c2.fetchone()
    t["subtask_count"] = sub["cnt"] or 0
    t["subtask_done"] = sub["done"] or 0
    return t


@app.get("/tasks")
async def list_tasks(
    project_id: Optional[int] = None,
    sprint_id: Optional[int] = None,
    status: Optional[str] = None,
    assignee: Optional[str] = None,
    task_type: Optional[str] = None,
    parent_task_id: Optional[int] = None,
    search: Optional[str] = None,
):
    db = await get_db()
    try:
        wheres = []
        params = []
        if project_id:
            wheres.append("project_id=?")
            params.append(project_id)
        if sprint_id:
            wheres.append("sprint_id=?")
            params.append(sprint_id)
        if status:
            wheres.append("status=?")
            params.append(status)
        if assignee:
            wheres.append("assignee=?")
            params.append(assignee)
        if task_type:
            wheres.append("task_type=?")
            params.append(task_type)
        if parent_task_id is not None:
            wheres.append("parent_task_id=?")
            params.append(parent_task_id)
        if search:
            wheres.append("(title LIKE ? OR description LIKE ?)")
            params.extend([f"%{search}%", f"%{search}%"])
        where_clause = ("WHERE " + " AND ".join(wheres)) if wheres else ""
        cursor = await db.execute(
            f"SELECT * FROM tasks {where_clause} ORDER BY sort_order ASC, priority ASC, created_at ASC",
            params,
        )
        rows = await cursor.fetchall()
        return [await _task_row_to_dict(db, r) for r in rows]
    finally:
        await db.close()


@app.post("/tasks", status_code=201)
async def create_task(request: Request, background_tasks: BackgroundTasks):
    body_raw = await request.json()
    # Support single or bulk array
    items = body_raw if isinstance(body_raw, list) else [body_raw]
    created = []
    db = await get_db()
    try:
        for item in items:
            tb = TaskBody(**item)
            sort_ord = await next_sort_order(tb.status, tb.project_id)
            resolved = resolve_model({"task_type": tb.task_type, "assignee": tb.assignee, "agent_model": tb.agent_model})
            now = datetime.utcnow().isoformat()
            c = await db.execute(
                """INSERT INTO tasks (project_id, sprint_id, parent_task_id, title, description,
                   task_type, status, priority, assignee, agent_model, story_points,
                   estimated_hours, due_date, sort_order, is_recurring, recurrence_cron,
                   template_id, updated_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (tb.project_id, tb.sprint_id, tb.parent_task_id, tb.title, tb.description,
                 tb.task_type, tb.status, tb.priority, tb.assignee, resolved,
                 tb.story_points, tb.estimated_hours, tb.due_date, sort_ord,
                 int(tb.is_recurring), tb.recurrence_cron, tb.template_id, now),
            )
            task_id = c.lastrowid
            await compute_eta(task_id)
            await log_task(db, task_id, f"Task created: {tb.title}", "system")
            await log_activity(db, task_id, "system", "created", "", tb.title)
            await db.commit()

            cursor = await db.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
            row = await cursor.fetchone()
            t = await _task_row_to_dict(db, row)
            created.append(t)

            # Queue for agent if local-agent
            if tb.assignee == "local-agent":
                await db.execute(
                    "INSERT INTO task_queue (task_id, status) VALUES (?, 'pending')",
                    (task_id,),
                )
                await db.commit()
                await event_queue.put({"task_id": task_id, "type": "run"})

            background_tasks.add_task(_broadcast, {"type": "task_created", "task": t})

        return created[0] if len(created) == 1 else created
    finally:
        await db.close()


@app.get("/tasks/{task_id}")
async def get_task(task_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        row = await cursor.fetchone()
        if not row:
            raise HTTPException(404, "Task not found")
        return await _task_row_to_dict(db, row)
    finally:
        await db.close()


@app.patch("/tasks/{task_id}")
async def update_task(task_id: int, body: dict, background_tasks: BackgroundTasks):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        old = await cursor.fetchone()
        if not old:
            raise HTTPException(404)
        old_dict = dict(old)
        allowed = {
            "title","description","task_type","priority","assignee","agent_model",
            "story_points","estimated_hours","due_date","sprint_id","parent_task_id",
            "sort_order","is_recurring","recurrence_cron","template_id",
            "git_branch","commit_sha","worktree_path","retry_count",
        }
        updates = {k: v for k, v in body.items() if k in allowed}
        updates["updated_at"] = datetime.utcnow().isoformat()
        if updates:
            for field, new_val in updates.items():
                if field != "updated_at" and old_dict.get(field) != new_val:
                    await log_activity(db, task_id, "system", field, str(old_dict.get(field, "")), str(new_val))
            set_clause = ", ".join(f"{k}=?" for k in updates)
            await db.execute(
                f"UPDATE tasks SET {set_clause} WHERE id=?",
                (*updates.values(), task_id),
            )
            # Re-compute ETA if hours changed
            if "estimated_hours" in updates:
                await compute_eta(task_id)
            await db.commit()

        cursor2 = await db.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        t = await _task_row_to_dict(db, await cursor2.fetchone())
        background_tasks.add_task(_broadcast, {"type": "task_updated", "task": t})
        return t
    finally:
        await db.close()


@app.patch("/tasks/{task_id}/status")
async def update_task_status(task_id: int, body: dict, background_tasks: BackgroundTasks):
    new_status = body.get("status")
    if not new_status:
        raise HTTPException(400, "status required")
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        old = await cursor.fetchone()
        if not old:
            raise HTTPException(404)
        now = datetime.utcnow().isoformat()
        extra = {"updated_at": now}
        if new_status == "in_progress" and not old["started_at"]:
            extra["started_at"] = now
        if new_status == "done" and not old["completed_at"]:
            extra["completed_at"] = now
            extra["actual_hours"] = old["estimated_hours"]  # fallback

        set_items = {"status": new_status, **extra}
        set_clause = ", ".join(f"{k}=?" for k in set_items)
        await db.execute(
            f"UPDATE tasks SET {set_clause} WHERE id=?",
            (*set_items.values(), task_id),
        )
        await log_activity(db, task_id, "system", "status", old["status"], new_status)
        await log_task(db, task_id, f"Status changed: {old['status']} → {new_status}", "system")

        # Re-compute ETA
        await compute_eta(task_id)

        # Queue for agent if moved to todo with local-agent
        if new_status == "todo" and old["assignee"] == "local-agent":
            await db.execute(
                "INSERT OR IGNORE INTO task_queue (task_id, status) VALUES (?, 'pending')",
                (task_id,),
            )
            await event_queue.put({"task_id": task_id, "type": "run"})

        await db.commit()
        cursor2 = await db.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        t = await _task_row_to_dict(db, await cursor2.fetchone())
        background_tasks.add_task(_broadcast, {"type": "task_updated", "task": t})

        # Notifications
        if new_status == "done":
            background_tasks.add_task(_notify_task_complete, t)
        elif new_status == "blocked":
            background_tasks.add_task(_notify_task_blocked, t)

        return t
    finally:
        await db.close()


@app.patch("/tasks/{task_id}/move")
async def move_task(task_id: int, body: dict, background_tasks: BackgroundTasks):
    db = await get_db()
    try:
        allowed = {"project_id", "sprint_id", "parent_task_id"}
        updates = {k: v for k, v in body.items() if k in allowed}
        updates["updated_at"] = datetime.utcnow().isoformat()
        set_clause = ", ".join(f"{k}=?" for k in updates)
        await db.execute(
            f"UPDATE tasks SET {set_clause} WHERE id=?",
            (*updates.values(), task_id),
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        t = await _task_row_to_dict(db, await cursor.fetchone())
        background_tasks.add_task(_broadcast, {"type": "task_updated", "task": t})
        return t
    finally:
        await db.close()


@app.delete("/tasks/{task_id}", status_code=204)
async def delete_task(task_id: int, background_tasks: BackgroundTasks):
    db = await get_db()
    try:
        await db.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        await db.commit()
        background_tasks.add_task(_broadcast, {"type": "task_deleted", "task_id": task_id})
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Task logs, activity, comments
# ---------------------------------------------------------------------------
@app.get("/tasks/{task_id}/logs")
async def get_task_logs(task_id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM task_logs WHERE task_id=? ORDER BY timestamp DESC LIMIT 200",
            (task_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@app.post("/tasks/{task_id}/logs", status_code=201)
async def post_task_log(task_id: int, body: dict):
    msg = body.get("message", "")
    source = body.get("source", "system")
    db = await get_db()
    try:
        await log_task(db, task_id, msg, source)
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@app.get("/tasks/{task_id}/activity")
async def get_task_activity(task_id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM activity_log WHERE task_id=? ORDER BY timestamp DESC LIMIT 200",
            (task_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@app.get("/tasks/{task_id}/comments")
async def get_comments(task_id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM comments WHERE task_id=? ORDER BY created_at", (task_id,)
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@app.post("/tasks/{task_id}/comments", status_code=201)
async def post_comment(task_id: int, body: dict, background_tasks: BackgroundTasks):
    user = body.get("user", "human")
    comment_body = body.get("body", "")
    mentions = json.dumps(re.findall(r"@(\w+)", comment_body))
    db = await get_db()
    try:
        c = await db.execute(
            "INSERT INTO comments (task_id, user, body, mentions) VALUES (?,?,?,?)",
            (task_id, user, comment_body, mentions),
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM comments WHERE id=?", (c.lastrowid,))
        row = dict(await cursor.fetchone())
        background_tasks.add_task(_broadcast, {"type": "comment_added", "comment": row})
        return row
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Time tracking
# ---------------------------------------------------------------------------
@app.post("/tasks/{task_id}/time/start")
async def time_start(task_id: int, body: dict = None):
    user = (body or {}).get("user", "human")
    db = await get_db()
    try:
        c = await db.execute(
            "INSERT INTO time_entries (task_id, user, started_at) VALUES (?,?,?)",
            (task_id, user, datetime.utcnow().isoformat()),
        )
        await db.commit()
        return {"entry_id": c.lastrowid}
    finally:
        await db.close()


@app.post("/tasks/{task_id}/time/stop")
async def time_stop(task_id: int, body: dict = None):
    body = body or {}
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM time_entries WHERE task_id=? AND ended_at IS NULL ORDER BY started_at DESC LIMIT 1",
            (task_id,),
        )
        entry = await cursor.fetchone()
        if not entry:
            raise HTTPException(404, "No active time entry")
        now = datetime.utcnow()
        started = datetime.fromisoformat(entry["started_at"])
        duration = int((now - started).total_seconds())
        actual_hours = body.get("actual_hours") or round(duration / 3600, 2)
        await db.execute(
            "UPDATE time_entries SET ended_at=?, duration_seconds=? WHERE id=?",
            (now.isoformat(), duration, entry["id"]),
        )
        await db.execute(
            "UPDATE tasks SET actual_hours=?, updated_at=? WHERE id=?",
            (actual_hours, now.isoformat(), task_id),
        )
        await db.commit()
        return {"duration_seconds": duration, "actual_hours": actual_hours}
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------
@app.get("/labels")
async def list_labels(project_id: Optional[int] = None):
    db = await get_db()
    try:
        if project_id:
            cursor = await db.execute("SELECT * FROM labels WHERE project_id=?", (project_id,))
        else:
            cursor = await db.execute("SELECT * FROM labels")
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@app.post("/labels", status_code=201)
async def create_label(body: dict):
    db = await get_db()
    try:
        c = await db.execute(
            "INSERT INTO labels (project_id, name, color) VALUES (?,?,?)",
            (body["project_id"], body["name"], body.get("color", "#6b7280")),
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM labels WHERE id=?", (c.lastrowid,))
        return dict(await cursor.fetchone())
    finally:
        await db.close()


@app.patch("/tasks/{task_id}/labels")
async def set_task_labels(task_id: int, body: dict):
    label_ids = body.get("label_ids", [])
    db = await get_db()
    try:
        await db.execute("DELETE FROM task_labels WHERE task_id=?", (task_id,))
        for lid in label_ids:
            await db.execute(
                "INSERT OR IGNORE INTO task_labels (task_id, label_id) VALUES (?,?)",
                (task_id, lid),
            )
        await db.commit()
        return {"ok": True, "label_ids": label_ids}
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
@app.get("/users")
async def list_users():
    db = await get_db()
    try:
        cursor = await db.execute("SELECT id, name, color, avatar_initials, created_at FROM users")
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@app.post("/users", status_code=201)
async def create_user(body: dict):
    db = await get_db()
    try:
        api_key = body.get("api_key", "")
        key_hash = hashlib.sha256(api_key.encode()).hexdigest() if api_key else ""
        c = await db.execute(
            "INSERT INTO users (name, api_key_hash, color, avatar_initials) VALUES (?,?,?,?)",
            (body["name"], key_hash, body.get("color","#6d28d9"), body.get("avatar_initials","U")),
        )
        await db.commit()
        cursor = await db.execute("SELECT id, name, color, avatar_initials FROM users WHERE id=?", (c.lastrowid,))
        return dict(await cursor.fetchone())
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Task dependencies
# ---------------------------------------------------------------------------
@app.post("/tasks/{task_id}/deps", status_code=201)
async def add_dep(task_id: int, body: dict):
    db = await get_db()
    try:
        c = await db.execute(
            "INSERT OR IGNORE INTO task_deps (task_id, depends_on_task_id, dep_type) VALUES (?,?,?)",
            (task_id, body["depends_on_task_id"], body.get("dep_type","blocks")),
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@app.get("/tasks/{task_id}/deps")
async def get_deps(task_id: int):
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT td.*, t.title as dep_title FROM task_deps td
               JOIN tasks t ON t.id=td.depends_on_task_id
               WHERE td.task_id=?""",
            (task_id,),
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------
@app.get("/metrics")
async def get_metrics():
    db = await get_db()
    try:
        now = datetime.utcnow()
        today = now.date().isoformat()
        week_start = (now - timedelta(days=now.weekday())).date().isoformat()

        # Done today / this week
        c = await db.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='done' AND DATE(completed_at)=?", (today,)
        )
        done_today = (await c.fetchone())[0]
        c = await db.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='done' AND DATE(completed_at)>=?", (week_start,)
        )
        done_week = (await c.fetchone())[0]

        # ETA accuracy
        c = await db.execute(
            "SELECT AVG(ABS(actual_hours - estimated_hours)) FROM tasks WHERE actual_hours IS NOT NULL AND estimated_hours IS NOT NULL"
        )
        eta_acc = (await c.fetchone())[0] or 0.0

        # Agent vs human
        c = await db.execute("SELECT COUNT(*) FROM tasks WHERE assignee='local-agent' AND status='done'")
        agent_done = (await c.fetchone())[0]
        c = await db.execute("SELECT COUNT(*) FROM tasks WHERE assignee='human' AND status='done'")
        human_done = (await c.fetchone())[0]
        total_done = agent_done + human_done or 1
        agent_pct = round((agent_done / total_done) * 100, 1)

        # Velocity: active sprints
        c = await db.execute("SELECT id FROM sprints WHERE status='active'")
        active_sprints = await c.fetchall()
        velocities = []
        for s in active_sprints:
            v = await sprint_velocity(s["id"])
            velocities.append(v)
        avg_velocity = sum(velocities) / len(velocities) if velocities else 0

        # Burndown: active sprint remaining points
        burndown = []
        for s in active_sprints:
            c2 = await db.execute(
                "SELECT * FROM sprints WHERE id=?", (s["id"],)
            )
            sprint = await c2.fetchone()
            if sprint and sprint["start_date"] and sprint["end_date"]:
                c3 = await db.execute(
                    "SELECT COUNT(*) as total, SUM(story_points) as pts FROM tasks WHERE sprint_id=?",
                    (s["id"],),
                )
                r = await c3.fetchone()
                total_pts = r["pts"] or 0
                c4 = await db.execute(
                    "SELECT SUM(story_points) as pts FROM tasks WHERE sprint_id=? AND status='done'",
                    (s["id"],),
                )
                r2 = await c4.fetchone()
                done_pts = r2["pts"] or 0
                burndown.append({
                    "sprint_id": s["id"],
                    "total_points": total_pts,
                    "done_points": done_pts,
                    "remaining": total_pts - done_pts,
                })

        # API cost today
        c = await db.execute(
            "SELECT SUM(cost_usd) FROM api_usage WHERE DATE(timestamp)=?", (today,)
        )
        cost_today = (await c.fetchone())[0] or 0.0
        c = await db.execute("SELECT SUM(cost_usd) FROM api_usage")
        cost_total = (await c.fetchone())[0] or 0.0

        # Cycle time: avg time from in_progress to done
        c = await db.execute(
            """SELECT AVG((julianday(completed_at) - julianday(started_at)) * 24) as avg_hours
               FROM tasks WHERE started_at IS NOT NULL AND completed_at IS NOT NULL"""
        )
        cycle_time = (await c.fetchone())[0] or 0.0

        # Lead time: avg time from created to done
        c = await db.execute(
            """SELECT AVG((julianday(completed_at) - julianday(created_at)) * 24) as avg_hours
               FROM tasks WHERE completed_at IS NOT NULL"""
        )
        lead_time = (await c.fetchone())[0] or 0.0

        # Per-model breakdown
        c = await db.execute(
            """SELECT agent_model, COUNT(*) as cnt,
               AVG(estimated_hours) as avg_est, AVG(actual_hours) as avg_act
               FROM tasks WHERE actual_hours IS NOT NULL
               GROUP BY agent_model"""
        )
        model_breakdown = [dict(r) for r in await c.fetchall()]

        return {
            "done_today": done_today,
            "done_week": done_week,
            "eta_accuracy_hours": round(eta_acc, 2),
            "agent_pct": agent_pct,
            "human_pct": round(100 - agent_pct, 1),
            "velocity": avg_velocity,
            "burndown": burndown,
            "cycle_time_hours": round(cycle_time, 2),
            "lead_time_hours": round(lead_time, 2),
            "model_breakdown": model_breakdown,
            "api_cost_today": round(cost_today, 4),
            "api_cost_total": round(cost_total, 4),
        }
    finally:
        await db.close()


@app.get("/metrics/velocity")
async def metrics_velocity(project_id: Optional[int] = None):
    db = await get_db()
    try:
        if project_id:
            cursor = await db.execute(
                "SELECT id, name FROM sprints WHERE project_id=? ORDER BY start_date DESC LIMIT 6",
                (project_id,),
            )
        else:
            cursor = await db.execute(
                "SELECT id, name FROM sprints ORDER BY start_date DESC LIMIT 6"
            )
        sprints = await cursor.fetchall()
        result = []
        for s in sprints:
            v = await sprint_velocity(s["id"])
            result.append({"sprint_id": s["id"], "name": s["name"], "velocity": v})
        return result
    finally:
        await db.close()


@app.get("/metrics/burndown")
async def metrics_burndown(sprint_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM sprints WHERE id=?", (sprint_id,))
        sprint = await cursor.fetchone()
        if not sprint:
            raise HTTPException(404)
        c = await db.execute(
            """SELECT DATE(completed_at) as day, SUM(story_points) as pts
               FROM tasks WHERE sprint_id=? AND status='done' AND completed_at IS NOT NULL
               GROUP BY DATE(completed_at) ORDER BY day""",
            (sprint_id,),
        )
        completions = await c.fetchall()
        c2 = await db.execute(
            "SELECT SUM(story_points) as total FROM tasks WHERE sprint_id=?", (sprint_id,)
        )
        total = (await c2.fetchone())["total"] or 0
        return {
            "sprint": dict(sprint),
            "total_points": total,
            "completions": [dict(r) for r in completions],
        }
    finally:
        await db.close()


@app.get("/metrics/montecarlo")
async def metrics_montecarlo(project_id: Optional[int] = None, simulations: int = 1000):
    """Monte Carlo simulation for project completion date."""
    import random
    db = await get_db()
    try:
        where = "WHERE project_id=?" if project_id else ""
        params = (project_id,) if project_id else ()
        c = await db.execute(
            f"SELECT COUNT(*) FROM tasks {where} AND status NOT IN ('done','blocked')",
            params,
        )
        remaining = (await c.fetchone())[0] or 0
        # Throughput: tasks/day over last 30 days
        thirty_days_ago = (datetime.utcnow() - timedelta(days=30)).isoformat()
        c2 = await db.execute(
            f"SELECT COUNT(*) FROM tasks {where} AND status='done' AND completed_at>=?",
            (*params, thirty_days_ago),
        )
        done_30d = (await c2.fetchone())[0] or 1
        daily_throughput = done_30d / 30.0

        finish_days = []
        for _ in range(simulations):
            rate = max(random.gauss(daily_throughput, daily_throughput * 0.3), 0.1)
            days = remaining / rate
            finish_days.append(days)

        finish_days.sort()
        p50 = datetime.utcnow() + timedelta(days=finish_days[int(simulations * 0.50)])
        p85 = datetime.utcnow() + timedelta(days=finish_days[int(simulations * 0.85)])
        p95 = datetime.utcnow() + timedelta(days=finish_days[int(simulations * 0.95)])

        return {
            "remaining_tasks": remaining,
            "daily_throughput": round(daily_throughput, 2),
            "p50": p50.date().isoformat(),
            "p85": p85.date().isoformat(),
            "p95": p95.date().isoformat(),
            "histogram": [round(d, 1) for d in finish_days[::max(1, simulations//100)]],
        }
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Agent queue / heartbeat / status
# ---------------------------------------------------------------------------
@app.get("/agent/queue")
async def agent_queue():
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT t.*, p.codebase_path, p.name as project_name
               FROM tasks t JOIN projects p ON p.id=t.project_id
               WHERE t.assignee='local-agent' AND t.status='todo'
               ORDER BY
                 CASE t.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END,
                 t.eta_date ASC NULLS LAST
               LIMIT 1"""
        )
        row = await cursor.fetchone()
        if not row:
            return None
        t = dict(row)
        t["resolved_model"] = resolve_model(t)
        worktree = t.get("worktree_path") or ""
        t["worktree_path"] = worktree
        return t
    finally:
        await db.close()


@app.patch("/agent/heartbeat")
async def agent_heartbeat(body: dict):
    task_id = body.get("task_id", "")
    model = body.get("model", "")
    db = await get_db()
    try:
        now = datetime.utcnow().isoformat()
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('current_task_id', ?)", (str(task_id),)
        )
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('current_model', ?)", (str(model),)
        )
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('agent_status', 'active')"
        )
        await db.execute(
            "INSERT OR REPLACE INTO settings (key, value) VALUES ('agent_last_seen', ?)", (now,)
        )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@app.get("/agent/status")
async def agent_status():
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT key, value FROM settings WHERE key IN ('agent_status','current_task_id','current_model','agent_last_seen')"
        )
        rows = {r["key"]: r["value"] for r in await cursor.fetchall()}
        task_id = rows.get("current_task_id", "")
        current_task = None
        if task_id:
            c = await db.execute(
                "SELECT t.id, t.title, t.agent_model, p.codebase_path FROM tasks t JOIN projects p ON p.id=t.project_id WHERE t.id=?",
                (task_id,),
            )
            row = await c.fetchone()
            current_task = dict(row) if row else None
        # tasks done today
        today = datetime.utcnow().date().isoformat()
        c2 = await db.execute(
            "SELECT COUNT(*) FROM tasks WHERE assignee='local-agent' AND status='done' AND DATE(completed_at)=?",
            (today,),
        )
        done_today = (await c2.fetchone())[0]
        return {
            "status": rows.get("agent_status", "idle"),
            "model": rows.get("current_model", ""),
            "current_task": current_task,
            "tasks_done_today": done_today,
            "last_seen": rows.get("agent_last_seen", ""),
            "codebase_path": current_task["codebase_path"] if current_task else "",
        }
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Logs
# ---------------------------------------------------------------------------
@app.get("/tasks/logs/recent")
async def recent_logs():
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT tl.*, t.title as task_title, p.name as project_name
               FROM task_logs tl
               JOIN tasks t ON t.id=tl.task_id
               JOIN projects p ON p.id=t.project_id
               ORDER BY tl.timestamp DESC LIMIT 50"""
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@app.get("/logs/stream")
async def logs_stream(request: Request):
    global last_log_id

    async def event_generator():
        global last_log_id
        while True:
            if await request.is_disconnected():
                break
            db = await get_db()
            try:
                cursor = await db.execute(
                    """SELECT tl.*, t.title as task_title, p.name as project_name
                       FROM task_logs tl
                       JOIN tasks t ON t.id=tl.task_id
                       JOIN projects p ON p.id=t.project_id
                       WHERE tl.id > ?
                       ORDER BY tl.timestamp ASC LIMIT 20""",
                    (last_log_id,),
                )
                rows = await cursor.fetchall()
                for row in rows:
                    r = dict(row)
                    last_log_id = max(last_log_id, r["id"])
                    yield {"data": json.dumps(r)}
            finally:
                await db.close()
            await asyncio.sleep(0.5)

    return EventSourceResponse(event_generator())


@app.get("/logs/file")
async def logs_file(name: str = Query(...)):
    log_path = os.path.join(BOS_HOME, "logs", f"{name}.log")
    if not Path(log_path).exists():
        return {"lines": [], "path": log_path}
    try:
        with open(log_path, "r", errors="replace") as f:
            lines = f.readlines()
        return {"lines": lines[-100:], "path": log_path}
    except Exception as e:
        return {"lines": [], "error": str(e)}


# ---------------------------------------------------------------------------
# Supervisor status
# ---------------------------------------------------------------------------
@app.get("/supervisor/status")
async def supervisor_status_endpoint():
    result = []
    services = {
        "nexus": {"port": 11434, "check": ""},
        "bos-api": {"port": 8000, "check": None},
        "bos-frontend": {"port": 3000, "check": None},
        "bos-openwebui": {"port": 8080, "check": None},
        "ntfy": {"port": 2586, "check": None},
    }

    # Try supervisord XML-RPC
    supervisor_procs = {}
    try:
        server = xmlrpc.client.ServerProxy("http://localhost:9001/RPC2")
        procs = server.supervisor.getAllProcessInfo()
        for p in procs:
            supervisor_procs[p["name"]] = p
    except Exception:
        pass

    for proc_name, info in services.items():
        entry = {
            "name": proc_name,
            "port": info["port"],
            "status": "unknown",
            "pid": None,
            "rss_mb": None,
            "cpu_pct": None,
        }
        # Check via psutil
        for proc in psutil.process_iter(["pid", "name", "cmdline", "status"]):
            try:
                cmdline = " ".join(proc.info.get("cmdline") or [])
                if proc_name in cmdline or (proc_name == "nexus" and "nexus" in proc.info.get("name", "")):
                    entry["pid"] = proc.info["pid"]
                    entry["status"] = proc.info["status"]
                    try:
                        mem = proc.memory_info()
                        entry["rss_mb"] = round(mem.rss / 1024 / 1024, 1)
                        entry["cpu_pct"] = proc.cpu_percent(interval=0.1)
                    except Exception:
                        pass
                    break
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        if proc_name in supervisor_procs:
            sp = supervisor_procs[proc_name]
            entry["supervisor_state"] = sp.get("statename", "")
            entry["uptime"] = sp.get("now", 0) - sp.get("start", 0)

        result.append(entry)

    return result


# ---------------------------------------------------------------------------
# Notifications
# ---------------------------------------------------------------------------
@app.post("/notifications/webhook")
async def notifications_webhook(body: dict, background_tasks: BackgroundTasks):
    msg = body.get("message", "")
    title = body.get("title", "Business OS")
    ntype = body.get("type", "info")
    task_id = body.get("task_id")
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO notifications (user, type, message, task_id) VALUES (?,?,?,?)",
            ("system", ntype, msg, task_id),
        )
        await db.commit()
    finally:
        await db.close()
    background_tasks.add_task(_send_notification, title, msg, ntype)
    return {"ok": True}


@app.get("/notifications")
async def list_notifications(unread_only: bool = False):
    db = await get_db()
    try:
        if unread_only:
            cursor = await db.execute(
                "SELECT * FROM notifications WHERE read=0 ORDER BY created_at DESC LIMIT 50"
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM notifications ORDER BY created_at DESC LIMIT 50"
            )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


@app.patch("/notifications/{notif_id}/read")
async def mark_read(notif_id: int):
    db = await get_db()
    try:
        await db.execute("UPDATE notifications SET read=1 WHERE id=?", (notif_id,))
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


@app.post("/notifications/read-all")
async def mark_all_read():
    db = await get_db()
    try:
        await db.execute("UPDATE notifications SET read=1")
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Chat task parsing (Open WebUI integration)
# ---------------------------------------------------------------------------
@app.post("/chat/task")
async def chat_task(body: dict, background_tasks: BackgroundTasks):
    """Parse natural language → create task."""
    text = body.get("message", "")
    project_id = body.get("project_id", 1)
    # Simple NLP: extract title, priority, type from text
    priority = "medium"
    task_type = "code"
    if "urgent" in text.lower() or "critical" in text.lower():
        priority = "critical"
    elif "high" in text.lower():
        priority = "high"
    elif "low" in text.lower():
        priority = "low"
    for tt in ("code", "write", "research", "design", "ops", "bug"):
        if tt in text.lower():
            task_type = tt
            break
    title = text[:100].strip()
    task_body = {
        "project_id": project_id,
        "title": title,
        "description": text,
        "task_type": task_type,
        "priority": priority,
        "assignee": "local-agent",
        "estimated_hours": 2.0,
    }
    db = await get_db()
    try:
        tb = TaskBody(**task_body)
        sort_ord = await next_sort_order(tb.status, tb.project_id)
        resolved = resolve_model({"task_type": tb.task_type, "assignee": tb.assignee, "agent_model": tb.agent_model})
        now = datetime.utcnow().isoformat()
        c = await db.execute(
            """INSERT INTO tasks (project_id, sprint_id, title, description, task_type, status,
               priority, assignee, agent_model, story_points, estimated_hours, sort_order, updated_at)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (tb.project_id, tb.sprint_id, tb.title, tb.description, tb.task_type, "todo",
             tb.priority, tb.assignee, resolved, tb.story_points, tb.estimated_hours,
             sort_ord, now),
        )
        task_id = c.lastrowid
        await compute_eta(task_id)
        await log_task(db, task_id, f"Task created via chat: {tb.title}", "system")
        await db.execute(
            "INSERT INTO task_queue (task_id, status) VALUES (?, 'pending')", (task_id,)
        )
        await db.commit()
        await event_queue.put({"task_id": task_id, "type": "run"})
        cursor = await db.execute("SELECT * FROM tasks WHERE id=?", (task_id,))
        t = await _task_row_to_dict(db, await cursor.fetchone())
        background_tasks.add_task(_broadcast, {"type": "task_created", "task": t})
        return {"task": t, "message": f"Task #{task_id} created: {tb.title}"}
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# WebSocket
# ---------------------------------------------------------------------------
@app.websocket("/ws/{board_id}")
async def websocket_endpoint(websocket: WebSocket, board_id: str):
    await websocket.accept()
    if board_id not in connections:
        connections[board_id] = []
    connections[board_id].append(websocket)
    try:
        while True:
            data = await asyncio.wait_for(websocket.receive_json(), timeout=30)
            # Handle presence heartbeat
            if data.get("type") == "presence":
                db = await get_db()
                try:
                    user_id = data.get("user_id", "anonymous")
                    await db.execute(
                        """INSERT OR REPLACE INTO presence (user_id, board_id, task_id, last_seen)
                           VALUES (?,?,?,?)""",
                        (user_id, board_id, data.get("task_id"), datetime.utcnow().isoformat()),
                    )
                    await db.commit()
                finally:
                    await db.close()
                # Broadcast presence to all on board
                await _broadcast({"type": "presence", "data": data}, board_id)
    except (WebSocketDisconnect, asyncio.TimeoutError):
        pass
    except Exception:
        pass
    finally:
        if board_id in connections:
            connections[board_id] = [c for c in connections[board_id] if c != websocket]


async def _broadcast(message: dict, board_id: Optional[str] = None):
    dead = []
    target_boards = [board_id] if board_id else list(connections.keys())
    for bid in target_boards:
        for ws in connections.get(bid, []):
            try:
                await ws.send_json(message)
            except Exception:
                dead.append((bid, ws))
    for bid, ws in dead:
        if bid in connections:
            connections[bid] = [c for c in connections[bid] if c != ws]


# ---------------------------------------------------------------------------
# Agent worker coroutine
# ---------------------------------------------------------------------------
_agent_semaphore = asyncio.Semaphore(2)


async def _agent_worker(worker_id: int):
    while True:
        try:
            event = await event_queue.get()
            task_id = event.get("task_id")
            if not task_id:
                continue
            async with _agent_semaphore:
                db = await get_db()
                try:
                    await db.execute(
                        "UPDATE task_queue SET status='processing' WHERE task_id=? AND status='pending'",
                        (task_id,),
                    )
                    await db.commit()
                finally:
                    await db.close()
                # Signal the shell agent — we just update queue status here
                # The shell agent-loop.sh polls /agent/queue
        except asyncio.CancelledError:
            break
        except Exception as e:
            pass  # Log but continue
        finally:
            try:
                event_queue.task_done()
            except Exception:
                pass


# ---------------------------------------------------------------------------
# Recurring tasks
# ---------------------------------------------------------------------------
async def _load_recurring_tasks():
    db = await get_db()
    try:
        cursor = await db.execute(
            "SELECT * FROM tasks WHERE is_recurring=1 AND recurrence_cron != ''"
        )
        rows = await cursor.fetchall()
        for row in rows:
            t = dict(row)
            try:
                cron = croniter(t["recurrence_cron"])
                next_run = cron.get_next(datetime)
                scheduler.add_job(
                    _spawn_recurring_task,
                    "date",
                    run_date=next_run,
                    args=[t["id"]],
                    id=f"recurring_{t['id']}",
                    replace_existing=True,
                )
            except Exception:
                pass
    finally:
        await db.close()


async def _spawn_recurring_task(template_task_id: int):
    db = await get_db()
    try:
        cursor = await db.execute("SELECT * FROM tasks WHERE id=?", (template_task_id,))
        tmpl = await cursor.fetchone()
        if not tmpl:
            return
        t = dict(tmpl)
        # Find active sprint
        c2 = await db.execute(
            "SELECT id FROM sprints WHERE project_id=? AND status='active' LIMIT 1",
            (t["project_id"],),
        )
        sprint = await c2.fetchone()
        sprint_id = sprint["id"] if sprint else None
        sort_ord = await next_sort_order("todo", t["project_id"])
        c3 = await db.execute(
            """INSERT INTO tasks (project_id, sprint_id, title, description, task_type,
               status, priority, assignee, agent_model, story_points, estimated_hours,
               sort_order, template_id)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (t["project_id"], sprint_id, t["title"], t["description"], t["task_type"],
             "todo", t["priority"], t["assignee"], t["agent_model"], t["story_points"],
             t["estimated_hours"], sort_ord, template_task_id),
        )
        new_task_id = c3.lastrowid
        await compute_eta(new_task_id)
        await log_task(db, new_task_id, f"Recurring task spawned from template #{template_task_id}", "system")
        await db.commit()
        await event_queue.put({"task_id": new_task_id, "type": "run"})
        # Re-schedule next occurrence
        await _load_recurring_tasks()
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Notification helpers
# ---------------------------------------------------------------------------
async def _send_notification(title: str, message: str, ntype: str = "info"):
    db = await get_db()
    try:
        c = await db.execute("SELECT value FROM settings WHERE key='ntfy_url'")
        row = await c.fetchone()
        ntfy_url = (row["value"] if row else None) or "http://localhost:2586"
        c2 = await db.execute("SELECT value FROM settings WHERE key='ntfy_topic'")
        r2 = await c2.fetchone()
        ntfy_topic = (r2["value"] if r2 else None) or "business-os"
        c3 = await db.execute("SELECT value FROM settings WHERE key='slack_webhook'")
        r3 = await c3.fetchone()
        slack_url = r3["value"] if r3 else ""
    finally:
        await db.close()

    priority_map = {"error": "urgent", "info": "default", "warning": "high"}
    ntfy_priority = priority_map.get(ntype, "default")

    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.post(
                f"{ntfy_url}/{ntfy_topic}",
                content=message.encode(),
                headers={"Title": title, "Priority": ntfy_priority},
            )
        except Exception:
            pass

        # macOS notification
        try:
            subprocess.Popen(
                ["osascript", "-e", f'display notification "{message}" with title "{title}"'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except Exception:
            pass

        if slack_url:
            try:
                await client.post(slack_url, json={"text": f"*{title}*: {message}"})
            except Exception:
                pass


async def _notify_task_complete(task: dict):
    title = task.get("title", "Task")
    await _send_notification(f"✓ Done: {title}", f"Task #{task['id']} completed", "info")
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO notifications (user, type, message, task_id) VALUES (?,?,?,?)",
            ("system", "task_complete", f"Task completed: {title}", task["id"]),
        )
        await db.commit()
    finally:
        await db.close()


async def _notify_task_blocked(task: dict):
    title = task.get("title", "Task")
    db = await get_db()
    try:
        c = await db.execute("SELECT value FROM settings WHERE key='slack_webhook'")
        r = await c.fetchone()
        slack_url = r["value"] if r else ""
    finally:
        await db.close()
    await _send_notification(
        f"⚠ Blocked: {title}",
        f"Task #{task['id']} is blocked",
        "warning",
    )
    db = await get_db()
    try:
        await db.execute(
            "INSERT INTO notifications (user, type, message, task_id) VALUES (?,?,?,?)",
            ("system", "task_blocked", f"Task blocked: {title}", task["id"]),
        )
        await db.commit()
    finally:
        await db.close()


async def _daily_summary():
    db = await get_db()
    try:
        today = datetime.utcnow().date().isoformat()
        c = await db.execute(
            "SELECT COUNT(*) FROM tasks WHERE status='done' AND DATE(completed_at)=?", (today,)
        )
        done = (await c.fetchone())[0]
        c2 = await db.execute("SELECT COUNT(*) FROM tasks WHERE status='blocked'")
        blocked = (await c2.fetchone())[0]
        c3 = await db.execute("SELECT SUM(cost_usd) FROM api_usage WHERE DATE(timestamp)=?", (today,))
        cost = (await c3.fetchone())[0] or 0.0
    finally:
        await db.close()
    await _send_notification(
        "Daily Summary",
        f"Done: {done} | Blocked: {blocked} | Cost: ${cost:.2f}",
        "info",
    )


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
@app.get("/settings")
async def get_settings():
    db = await get_db()
    try:
        cursor = await db.execute("SELECT key, value FROM settings")
        return {r["key"]: r["value"] for r in await cursor.fetchall()}
    finally:
        await db.close()


@app.patch("/settings")
async def update_settings(body: dict):
    db = await get_db()
    try:
        for k, v in body.items():
            await db.execute(
                "INSERT OR REPLACE INTO settings (key, value) VALUES (?,?)", (k, str(v))
            )
        await db.commit()
        return {"ok": True}
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Task queue
# ---------------------------------------------------------------------------
@app.get("/task-queue")
async def get_task_queue():
    db = await get_db()
    try:
        cursor = await db.execute(
            """SELECT tq.*, t.title, t.status as task_status, t.assignee
               FROM task_queue tq JOIN tasks t ON t.id=tq.task_id
               ORDER BY tq.created_at DESC LIMIT 50"""
        )
        return [dict(r) for r in await cursor.fetchall()]
    finally:
        await db.close()


# ---------------------------------------------------------------------------
# Health
# ---------------------------------------------------------------------------
@app.get("/health")
async def health():
    return {"status": "ok", "time": datetime.utcnow().isoformat()}
