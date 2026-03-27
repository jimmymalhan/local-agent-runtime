#!/usr/bin/env python3
"""
dashboard/board_init.py — Pre-populate dashboard with full work plan
====================================================================
Called by `nexus init` and `orchestrator/main.py` BEFORE any agent moves.

Writes ALL tasks to state.json as projects with subtasks so every
stakeholder — technical or not — can see the complete work plan on the
dashboard the moment the runtime starts.

This is the E10 operating principle:
  Board updates FIRST. Always. No agent moves without a board entry.

Usage:
    from dashboard.board_init import init_board
    init_board(tasks, version=1)   # writes plan to state.json immediately

    # Or standalone:
    python3 dashboard/board_init.py
"""
import os, sys, json
from pathlib import Path
from datetime import datetime

BASE_DIR   = str(Path(__file__).parent.parent)
DASH_DIR   = str(Path(__file__).parent)
STATE_FILE = os.path.join(DASH_DIR, "state.json")
sys.path.insert(0, BASE_DIR)


# Category → readable business domain
_CAT_LABELS = {
    "code_gen":     "Engineering",
    "bug_fix":      "Bug Fixes",
    "tdd":          "Test Driven Dev",
    "scaffold":     "Scaffolding",
    "arch":         "Architecture",
    "refactor":     "Refactoring",
    "e2e":          "End-to-End",
    "research":     "Research",
    "doc":          "Documentation",
    "test":         "Testing",
}

# Agent map for routing display
_AGENT_FOR_CAT = {
    "code_gen": "executor",
    "bug_fix":  "executor",
    "tdd":      "test_engineer",
    "scaffold": "architect",
    "arch":     "architect",
    "refactor": "refactor",
    "e2e":      "architect",
    "research": "researcher",
    "doc":      "doc_writer",
}


def _read_state() -> dict:
    try:
        with open(STATE_FILE) as f:
            return json.load(f)
    except Exception:
        return {}


def _write_state(state: dict):
    state["ts"] = datetime.now().isoformat()
    tmp = STATE_FILE + ".tmp"
    with open(tmp, "w") as f:
        json.dump(state, f, indent=2)
    os.replace(tmp, STATE_FILE)


def init_board(tasks: list = None, version: int = 1):
    """
    Write all tasks to state.json as projects with subtasks.
    Groups tasks by category → each category becomes a "project".
    Each task becomes a subtask with owner, status=pending, ETA.

    Call this BEFORE any agent touches work. Dashboard becomes live truth
    immediately — both technical and business stakeholders can see the plan.
    """
    if tasks is None:
        try:
            sys.path.insert(0, BASE_DIR)
            from tasks.task_suite import build_task_suite
            tasks = build_task_suite()
        except Exception as e:
            print(f"[BOARD] Could not load task suite: {e}")
            tasks = []

    state = _read_state()

    # ── Group tasks into projects by category ─────────────────────────────
    projects_map: dict = {}
    for task in tasks:
        cat = task.get("category", "code_gen")
        if cat not in projects_map:
            projects_map[cat] = {
                "id":          f"proj-{cat}",
                "name":        _CAT_LABELS.get(cat, cat.replace("_", " ").title()),
                "category":    cat,
                "agent":       _AGENT_FOR_CAT.get(cat, "executor"),
                "tasks":       [],
                "total":       0,
                "done":        0,
                "in_progress": 0,
                "failed":      0,
                "status":      "pending",
                "pct":         0,
            }
        projects_map[cat]["tasks"].append({
            "task_id":    task.get("id"),
            "title":      task.get("title", ""),
            "difficulty": task.get("difficulty", "hard"),
            "status":     "pending",
            "agent":      _AGENT_FOR_CAT.get(cat, "executor"),
            "quality":    0,
            "elapsed_s":  0,
        })
        projects_map[cat]["total"] += 1

    projects = list(projects_map.values())

    # ── Write board plan to state ─────────────────────────────────────────
    state["board_plan"] = {
        "version":       version,
        "total_tasks":   len(tasks),
        "total_projects": len(projects),
        "projects":      projects,
        "initialized_at": datetime.now().isoformat(),
        "status":        "planned",
    }

    # ── Also write recent_tasks so Jira board shows full backlog ──────────
    state["recent_tasks"] = [
        {
            "task_id":     t.get("id"),
            "title":       t.get("title", ""),
            "category":    t.get("category", "code_gen"),
            "agent_used":  _AGENT_FOR_CAT.get(t.get("category", "code_gen"), "executor"),
            "status":      "todo",
            "local_quality": 0,
        }
        for t in tasks
    ]

    # ── Update task_queue totals ──────────────────────────────────────────
    state.setdefault("task_queue", {})
    state["task_queue"].update({
        "total":       len(tasks),
        "completed":   state["task_queue"].get("completed", 0),
        "in_progress": 0,
        "failed":      state["task_queue"].get("failed", 0),
        "pending":     len(tasks) - state["task_queue"].get("completed", 0),
    })

    # ── Business summary for non-technical stakeholders ───────────────────
    done = state["task_queue"].get("completed", 0)
    pct  = round(done / max(len(tasks), 1) * 100, 1)
    state["business_summary"] = {
        "headline":        f"{done} of {len(tasks)} engineering tasks complete",
        "pct_complete":    pct,
        "projects_active": len([p for p in projects if p["status"] not in ("done",)]),
        "blockers_open":   len([t for t in state.get("failures", [])]),
        "version":         version,
        "updated_at":      datetime.now().isoformat(),
    }

    _write_state(state)
    print(f"[BOARD] Initialized — {len(tasks)} tasks across {len(projects)} projects → dashboard ready")
    return len(tasks), len(projects)


def update_task_status(task_id: int, status: str, quality: int = 0,
                       elapsed_s: float = 0.0, agent: str = ""):
    """
    Update a single task's status on the board after an agent completes it.
    status: todo | running | done | blocked | failed

    Call this every time a task transitions state so the board is always current.
    """
    state = _read_state()
    plan  = state.get("board_plan", {})
    projects = plan.get("projects", [])

    # Update in projects
    for proj in projects:
        for t in proj.get("tasks", []):
            if t["task_id"] == task_id:
                prev = t["status"]
                t["status"]   = status
                t["quality"]  = quality
                t["elapsed_s"] = elapsed_s
                if agent:
                    t["agent"] = agent
                # Update project counters
                proj["done"]        = len([x for x in proj["tasks"] if x["status"] == "done"])
                proj["in_progress"] = len([x for x in proj["tasks"] if x["status"] == "running"])
                proj["failed"]      = len([x for x in proj["tasks"] if x["status"] in ("failed", "blocked")])
                proj["pct"]         = round(proj["done"] / max(proj["total"], 1) * 100, 1)
                proj["status"]      = ("done" if proj["done"] == proj["total"]
                                       else "running" if proj["in_progress"] > 0
                                       else "blocked" if proj["failed"] > 0
                                       else "pending")
                break

    state["board_plan"]["projects"] = projects

    # Update recent_tasks list
    for t in state.get("recent_tasks", []):
        if t["task_id"] == task_id:
            t["status"]       = status
            t["local_quality"] = quality
            if agent:
                t["agent_used"] = agent
            break

    # Refresh business summary
    done = state["task_queue"].get("completed", 0)
    total = state["task_queue"].get("total", 100)
    state["business_summary"] = {
        "headline":        f"{done} of {total} engineering tasks complete",
        "pct_complete":    round(done / max(total, 1) * 100, 1),
        "projects_active": len([p for p in projects if p["status"] == "running"]),
        "blockers_open":   len([p for p in projects if p["status"] == "blocked"]),
        "version":         plan.get("version", 1),
        "updated_at":      datetime.now().isoformat(),
    }

    _write_state(state)


if __name__ == "__main__":
    n, p = init_board()
    print(f"Board initialized: {n} tasks, {p} projects")
    print(f"Dashboard: http://localhost:3001")
