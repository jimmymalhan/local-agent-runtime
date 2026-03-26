"""
nexus project CLI — project + task management commands.

Usage:
  nexus project new "Build a FastAPI todo app with auth and PostgreSQL"
  nexus project list
  nexus project show <id>
  nexus project tasks <id>
  nexus project next
  nexus project add-task <id> "Task title"
"""
import argparse
import json
import os
import sys

# Allow running from any cwd by ensuring the local-agents package root is on the path
_HERE = os.path.dirname(os.path.abspath(__file__))
_AGENTS_ROOT = os.path.dirname(_HERE)
if _AGENTS_ROOT not in sys.path:
    sys.path.insert(0, _AGENTS_ROOT)

from projects.project_manager import ProjectManager
from projects.decomposer import ProjectDecomposer
from projects.schema import Epic, SubTask


# ---------------------------------------------------------------------------
# Formatting helpers
# ---------------------------------------------------------------------------

STATUS_ICONS = {
    "pending":     "[ ]",
    "in_progress": "[~]",
    "done":        "[x]",
    "blocked":     "[!]",
    "active":      "[A]",
    "paused":      "[-]",
    "archived":    "[v]",
}

PRIORITY_LABELS = {1: "high", 2: "medium", 3: "low"}


def _icon(status: str) -> str:
    return STATUS_ICONS.get(status, f"[{status[:1]}]")


def _print_project_row(p: dict) -> None:
    stats_parts = []
    total = done = 0
    for e in p.get("epics", []):
        for t in e.get("tasks", []):
            total += 1
            if t["status"] == "done":
                done += 1
    pct = f"{int(done/total*100)}%" if total else "0%"
    print(f"  {_icon(p['status'])} {p['id']}  {p['name']:<40}  {p['type']:<10}  {done}/{total} tasks  {pct}  q={p.get('quality_avg', 0):.0f}")


def _print_task_row(item: dict, indent: int = 4) -> None:
    t = item["task"]
    prefix = " " * indent
    print(f"{prefix}{_icon(t['status'])} {t['id']}  {t['title']:<45}  cat={t['category']:<12}  q={t['quality']}")


# ---------------------------------------------------------------------------
# Command handlers
# ---------------------------------------------------------------------------

def cmd_new(args, pm: ProjectManager) -> None:
    brief = args.brief
    decomposer = ProjectDecomposer()
    plan = decomposer.decompose_into_project(brief, project_type=getattr(args, "type", ""))

    project = pm.create_project(
        name=plan["name"],
        type=plan["type"],
        description=plan["description"],
        path=getattr(args, "path", "") or "",
    )

    # Add epics + tasks
    from dataclasses import asdict
    for ep_data in plan["epics"]:
        epic = Epic(
            title=ep_data["title"],
            description=ep_data["description"],
            priority=ep_data["priority"],
        )
        added_epic = pm.add_epic(project["id"], epic)
        if added_epic:
            for t_data in ep_data["tasks"]:
                task = SubTask(
                    title=t_data["title"],
                    description=t_data["description"],
                    category=t_data["category"],
                )
                pm.add_task(project["id"], added_epic["id"], task)

    # Reload to show final state
    project = pm.get_project(project["id"])
    stats = pm.project_stats(project["id"])

    print(f"\nProject created: {project['id']}")
    print(f"  Name   : {project['name']}")
    print(f"  Type   : {project['type']}")
    print(f"  Epics  : {len(project['epics'])}")
    print(f"  Tasks  : {stats['total']}")
    print()
    for e in project["epics"]:
        print(f"  Epic [{PRIORITY_LABELS.get(e['priority'], '?')}] {e['title']}")
        for t in e["tasks"]:
            print(f"    {_icon(t['status'])} {t['title']}")
    print()


def cmd_list(args, pm: ProjectManager) -> None:
    projects = pm.list_projects()
    if not projects:
        print("No projects found. Run: nexus project new \"...\"")
        return
    print(f"\n{'ID':<10} {'Name':<40} {'Type':<10} {'Progress':<14} {'Quality'}")
    print("-" * 90)
    for p in projects:
        _print_project_row(p)
    print()


def cmd_show(args, pm: ProjectManager) -> None:
    p = pm.get_project(args.id)
    if p is None:
        print(f"Project not found: {args.id}")
        sys.exit(1)
    stats = pm.project_stats(args.id)
    print(f"\nProject: {p['name']}  ({p['id']})")
    print(f"  Type       : {p['type']}")
    print(f"  Status     : {p['status']}")
    print(f"  Path       : {p['path'] or '(not set)'}")
    print(f"  Tasks      : {stats['done']}/{stats['total']} done, {stats['in_progress']} in-progress, {stats['blocked']} blocked")
    print(f"  Quality avg: {stats['quality_avg']}")
    print(f"  Created    : {p['created']}")
    print()
    for e in p.get("epics", []):
        prio = PRIORITY_LABELS.get(e["priority"], "?")
        print(f"  Epic [{prio}] {e['title']}  ({e['status']})")
        for t in e.get("tasks", []):
            print(f"    {_icon(t['status'])} {t['id']}  {t['title']}")
    print()


def cmd_tasks(args, pm: ProjectManager) -> None:
    p = pm.get_project(args.id)
    if p is None:
        print(f"Project not found: {args.id}")
        sys.exit(1)
    tasks = pm.get_all_tasks()
    project_tasks = [item for item in tasks if item["project_id"] == args.id]
    if not project_tasks:
        print(f"No tasks for project {args.id}")
        return

    print(f"\nTasks for: {p['name']}  ({args.id})")
    print(f"{'ID':<10} {'Title':<45} {'Category':<14} {'Status':<12} {'Quality'}")
    print("-" * 90)
    current_epic = None
    for item in project_tasks:
        if item["epic_title"] != current_epic:
            current_epic = item["epic_title"]
            print(f"\n  -- {current_epic} --")
        _print_task_row(item)
    print()


def cmd_next(args, pm: ProjectManager) -> None:
    item = pm.next_task()
    if item is None:
        print("No pending tasks. All done or no active projects.")
        return
    t = item["task"]
    print(f"\nNext task:")
    print(f"  Project  : {item['project_name']}  ({item['project_id']})")
    print(f"  Epic     : {item['epic_title']}  ({item['epic_id']})")
    print(f"  Task ID  : {t['id']}")
    print(f"  Title    : {t['title']}")
    print(f"  Category : {t['category']}")
    print(f"  Desc     : {t['description']}")
    print()


def cmd_add_task(args, pm: ProjectManager) -> None:
    p = pm.get_project(args.id)
    if p is None:
        print(f"Project not found: {args.id}")
        sys.exit(1)

    epics = p.get("epics", [])
    if not epics:
        print("Project has no epics. Please add an epic first.")
        sys.exit(1)

    # Default: add to first epic (or user can specify --epic)
    epic_id = getattr(args, "epic", None) or epics[0]["id"]

    task = SubTask(
        title=args.title,
        description=getattr(args, "description", "") or args.title,
        category=getattr(args, "category", "code_gen") or "code_gen",
    )
    result = pm.add_task(args.id, epic_id, task)
    if result:
        print(f"\nTask added: {result['id']}")
        print(f"  Title    : {result['title']}")
        print(f"  Category : {result['category']}")
        print(f"  Epic     : {epic_id}")
        print()
    else:
        print(f"Failed to add task. Check project ID ({args.id}) and epic ID ({epic_id}).")
        sys.exit(1)


# ---------------------------------------------------------------------------
# Argument parsing + dispatch
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="nexus project",
        description="Local project + task management for the agent runtime.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    # new
    p_new = sub.add_parser("new", help="Create a project from a brief")
    p_new.add_argument("brief", help="Plain-English project brief")
    p_new.add_argument("--type", default="", help="Override detected project type")
    p_new.add_argument("--path", default="", help="Absolute path to project on disk")

    # list
    sub.add_parser("list", help="List all projects")

    # show
    p_show = sub.add_parser("show", help="Show project details")
    p_show.add_argument("id", help="Project ID")

    # tasks
    p_tasks = sub.add_parser("tasks", help="Show all tasks for a project")
    p_tasks.add_argument("id", help="Project ID")

    # next
    sub.add_parser("next", help="Show the next pending task across all projects")

    # add-task
    p_add = sub.add_parser("add-task", help="Manually add a task to a project")
    p_add.add_argument("id", help="Project ID")
    p_add.add_argument("title", help="Task title")
    p_add.add_argument("--description", default="", help="Task description")
    p_add.add_argument("--category", default="code_gen", help="Task category (code_gen|tdd|scaffold|...)")
    p_add.add_argument("--epic", default="", help="Epic ID to add task to (default: first epic)")

    return parser


COMMANDS = {
    "new":      cmd_new,
    "list":     cmd_list,
    "show":     cmd_show,
    "tasks":    cmd_tasks,
    "next":     cmd_next,
    "add-task": cmd_add_task,
}


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    pm = ProjectManager()
    handler = COMMANDS.get(args.command)
    if handler:
        handler(args, pm)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
