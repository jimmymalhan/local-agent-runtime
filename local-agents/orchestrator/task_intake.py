#!/usr/bin/env python3
"""
task_intake.py — New request → Project task, ready for agent pickup.

Any new request (from CLI, orchestrator, or external hook) runs through here.
It classifies the request, assigns it to the right project + epic, and inserts
it into projects.json as a pending SubTask. The continuous_loop picks it up
via next_project_task() without any human intervention.

Usage:
    python3 -m orchestrator.task_intake "Add dark mode toggle to dashboard"
    python3 -m orchestrator.task_intake --title "..." --description "..." --category ui

    from orchestrator.task_intake import intake
    task_ref = intake("Fix accessibility issues on JobCard")
"""
import os
import sys
import json
import argparse
import uuid
from pathlib import Path
from datetime import datetime

BASE_DIR = str(Path(__file__).parent.parent)
sys.path.insert(0, BASE_DIR)

# ── Project / Epic assignment rules ──────────────────────────────────────────
# category → (project_id, epic_id)
# Order matters: more specific entries first.

CATEGORY_TO_PROJECT_EPIC = {
    # ── Dashboard (Nexus local UI) ────────────────────────────────────────────
    "dashboard":     ("p-dashboard", "e-dash-uptime"),   # never-down work first
    # ── jobs.hil-tad.com ─────────────────────────────────────────────────────
    "frontend":      ("p-jobs", "e-jobs-core"),
    "react":         ("p-jobs", "e-jobs-core"),
    "component":     ("p-jobs", "e-jobs-core"),
    "state_mgmt":    ("p-jobs", "e-jobs-core"),
    "design_system": ("p-jobs", "e-jobs-core"),
    "build_tool":    ("p-jobs", "e-jobs-core"),
    "css":           ("p-jobs", "e-jobs-core"),
    "html":          ("p-jobs", "e-jobs-core"),
    "ui":            ("p-jobs", "e-jobs-core"),
    "ux":            ("p-jobs", "e-jobs-quality"),
    "accessibility": ("p-jobs", "e-jobs-quality"),
    "prototype":     ("p-jobs", "e-jobs-quality"),
    # ── Agent Infrastructure ──────────────────────────────────────────────────
    "arch":          ("p-infra", "e-infra-loop"),
    "infra":         ("p-infra", "e-infra-loop"),
    "memory":        ("p-infra", "e-infra-memory"),
    # ── Nexus Runtime Core (default for everything else) ─────────────────────
    "deploy":        ("p-nexus", "e-loop"),
    "monitor":       ("p-nexus", "e-loop"),
    "benchmark":     ("p-nexus", "e-loop"),
    "perf":          ("p-nexus", "e-agents"),
    "code_gen":      ("p-nexus", "e-agents"),
    "bug_fix":       ("p-nexus", "e-agents"),
    "refactor":      ("p-nexus", "e-agents"),
    "tdd":           ("p-nexus", "e-agents"),
    "debug":         ("p-nexus", "e-agents"),
    "review":        ("p-nexus", "e-agents"),
    "research":      ("p-nexus", "e-agents"),
    "doc":           ("p-nexus", "e-agents"),
    "scaffold":      ("p-nexus", "e-agents"),
    "test_gen":      ("p-nexus", "e-agents"),
    "analyze":       ("p-nexus", "e-agents"),
    "api_design":    ("p-infra", "e-infra-loop"),
    "db":            ("p-infra", "e-infra-loop"),
}

_DEFAULT_PROJECT_EPIC = ("p-nexus", "e-agents")

# keywords in title/description → override category
_KEYWORD_HINTS = [
    # (keyword, category)
    ("jobs.hil-tad", "component"),
    ("jobcard",      "component"),
    ("job card",     "component"),
    ("filter bar",   "state_mgmt"),
    ("search bar",   "state_mgmt"),
    ("zustand",      "state_mgmt"),
    ("tailwind",     "frontend"),
    ("storybook",    "prototype"),
    ("axe-core",     "accessibility"),
    ("wcag",         "accessibility"),
    ("dark mode",    "dashboard"),
    ("state.json",   "dashboard"),
    ("live_state",   "dashboard"),
    ("projects.json","code_gen"),
    ("continuous_loop", "code_gen"),
    ("dag",          "arch"),
    ("memory",       "memory"),
    ("scaffold",     "scaffold"),
    ("typescript",   "frontend"),
    (" ts ",         "frontend"),
    ("vite",         "build_tool"),
    ("webpack",      "build_tool"),
]


def _infer_category(title: str, description: str, given: str) -> str:
    """Return the best category from given hint, keyword match, or fallback."""
    if given and given in CATEGORY_TO_PROJECT_EPIC:
        return given

    combined = (title + " " + description).lower()
    for kw, cat in _KEYWORD_HINTS:
        if kw.lower() in combined:
            return cat

    # Try splitting words and matching ROUTING_TABLE
    try:
        from agents import ROUTING_TABLE
        for word in combined.split():
            word = word.strip(".,;:()[]")
            if word in ROUTING_TABLE:
                return word
    except ImportError:
        pass

    return given or "code_gen"


def _agent_for_category(category: str) -> str:
    """Return the agent name for a category via ROUTING_TABLE."""
    try:
        from agents import ROUTING_TABLE
        return ROUTING_TABLE.get(category, "executor")
    except ImportError:
        return "executor"


def intake(
    title: str,
    description: str = "",
    category: str = "",
    priority=None,
) -> dict:
    """
    Classify and insert a new task into projects.json.

    Returns:
        {project_id, epic_id, task_id, project_name, epic_title, agent, category}
    """
    category = _infer_category(title, description, category)
    project_id, epic_id = CATEGORY_TO_PROJECT_EPIC.get(category, _DEFAULT_PROJECT_EPIC)
    agent = _agent_for_category(category)

    task = {
        "id": "t-" + str(uuid.uuid4())[:8],
        "title": title,
        "description": description or title,
        "status": "pending",
        "category": category,
        "agent": agent,
        "result": {},
        "quality": 0,
        "created": datetime.utcnow().isoformat(),
        "updated": datetime.utcnow().isoformat(),
    }

    # Insert via ProjectManager
    try:
        from projects.project_manager import ProjectManager
        pm = ProjectManager()
        from projects.schema import SubTask
        st = SubTask(
            id=task["id"],
            title=task["title"],
            description=task["description"],
            status="pending",
            category=category,
            agent=agent,
        )
        result = pm.add_task(project_id, epic_id, st)
        if result is None:
            # Epic or project not found — append directly to JSON
            _append_raw(project_id, epic_id, task)
    except Exception as e:
        _append_raw(project_id, epic_id, task)

    proj_name, epic_title = _lookup_names(project_id, epic_id)

    summary = {
        "project_id":   project_id,
        "project_name": proj_name,
        "epic_id":      epic_id,
        "epic_title":   epic_title,
        "task_id":      task["id"],
        "title":        title,
        "category":     category,
        "agent":        agent,
    }
    _print_summary(summary)
    return summary


def _append_raw(project_id: str, epic_id: str, task: dict) -> None:
    """Direct JSON write fallback when ProjectManager can't find the epic."""
    pfile = os.path.join(BASE_DIR, "projects", "projects.json")
    with open(pfile) as f:
        data = json.load(f)
    for p in data["projects"]:
        if p["id"] == project_id:
            for e in p["epics"]:
                if e["id"] == epic_id:
                    e["tasks"].append(task)
                    p["updated"] = datetime.utcnow().isoformat()
                    break
            break
    tmp = pfile + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
    os.replace(tmp, pfile)


def _lookup_names(project_id: str, epic_id: str):
    try:
        pfile = os.path.join(BASE_DIR, "projects", "projects.json")
        with open(pfile) as f:
            data = json.load(f)
        for p in data["projects"]:
            if p["id"] == project_id:
                for e in p["epics"]:
                    if e["id"] == epic_id:
                        return p["name"], e["title"]
                return p["name"], epic_id
    except Exception:
        pass
    return project_id, epic_id


def _print_summary(s: dict) -> None:
    print(f"\n✅ Task added to queue")
    print(f"   Project : {s['project_name']} ({s['project_id']})")
    print(f"   Epic    : {s['epic_title']} ({s['epic_id']})")
    print(f"   Task ID : {s['task_id']}")
    print(f"   Title   : {s['title']}")
    print(f"   Category: {s['category']}  →  agent: {s['agent']}")
    print(f"   Status  : pending — continuous_loop will pick it up automatically\n")


def list_pending() -> None:
    """Print all pending tasks grouped by project."""
    try:
        from projects.project_manager import ProjectManager
        pm = ProjectManager()
        tasks = pm.get_all_tasks(status="pending")
    except Exception:
        print("Could not load projects.json")
        return

    by_project: dict = {}
    for item in tasks:
        pname = item["project_name"]
        by_project.setdefault(pname, []).append(item)

    print(f"\n{'═'*60}")
    print(f"  PENDING TASKS — {len(tasks)} total")
    print(f"{'═'*60}")
    for pname, items in by_project.items():
        print(f"\n▸ {pname}  ({len(items)} tasks)")
        for item in items:
            t = item["task"]
            print(f"  [{t['id']}] {t['title']}")
            print(f"    epic: {item['epic_title']}  agent: {t['agent']}  cat: {t['category']}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Add a task to the agent queue")
    parser.add_argument("title", nargs="?", default="", help="Task title (positional)")
    parser.add_argument("--title", dest="title_kw", default="", help="Task title")
    parser.add_argument("--description", "-d", default="", help="Full description")
    parser.add_argument("--category", "-c", default="", help="Category hint")
    parser.add_argument("--list", "-l", action="store_true", help="List all pending tasks")
    args = parser.parse_args()

    if args.list:
        list_pending()
        sys.exit(0)

    title = args.title or args.title_kw
    if not title:
        parser.print_help()
        sys.exit(1)

    intake(title, description=args.description, category=args.category)
