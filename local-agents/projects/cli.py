"""
nexus project CLI: new|list|show|tasks|next|add-task
"""
import argparse
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_AGENTS_ROOT = os.path.dirname(_HERE)
if _AGENTS_ROOT not in sys.path:
    sys.path.insert(0, _AGENTS_ROOT)

from projects.project_manager import ProjectManager
from projects.decomposer import ProjectDecomposer
from projects.schema import Epic, SubTask

STATUS_ICONS = {"pending": "[ ]", "in_progress": "[~]", "done": "[x]",
                "blocked": "[!]", "active": "[A]", "paused": "[-]", "archived": "[v]"}
PRIORITY_LABELS = {1: "high", 2: "medium", 3: "low"}


def _icon(status: str) -> str:
    return STATUS_ICONS.get(status, f"[{status[:1]}]")


def cmd_new(args, pm):
    brief = args.brief
    plan = ProjectDecomposer().decompose_into_project(brief, project_type=getattr(args, "type", "") or "")
    project = pm.create_project(plan["name"], plan["type"], plan["description"],
                                getattr(args, "path", "") or "")
    for ep in plan["epics"]:
        added = pm.add_epic(project["id"], Epic(title=ep["title"], description=ep["description"],
                                                 priority=ep["priority"]))
        if added:
            for t in ep["tasks"]:
                pm.add_task(project["id"], added["id"],
                            SubTask(title=t["title"], description=t["description"], category=t["category"]))
    project = pm.get_project(project["id"])
    stats = pm.project_stats(project["id"])
    print(f"\nProject created: {project['id']}")
    print(f"  Name   : {project['name']}")
    print(f"  Type   : {project['type']}")
    print(f"  Epics  : {len(project['epics'])}")
    print(f"  Tasks  : {stats['total']}\n")
    for e in project["epics"]:
        print(f"  Epic [{PRIORITY_LABELS.get(e['priority'], '?')}] {e['title']}")
        for t in e["tasks"]:
            print(f"    {_icon(t['status'])} {t['title']}")
    print()


def cmd_list(args, pm):
    projects = pm.list_projects()
    if not projects:
        print('No projects. Run: nexus project new "..."')
        return
    print(f"\n{'ID':<10} {'Name':<40} {'Type':<10} Progress      Quality")
    print("-" * 80)
    for p in projects:
        total = sum(1 for e in p.get("epics", []) for _ in e.get("tasks", []))
        done = sum(1 for e in p.get("epics", []) for t in e.get("tasks", []) if t["status"] == "done")
        pct = f"{int(done/total*100)}%" if total else "0%"
        print(f"  {_icon(p['status'])} {p['id']}  {p['name']:<40}  {p['type']:<10}  {done}/{total}  {pct}  q={p.get('quality_avg', 0):.0f}")
    print()


def cmd_show(args, pm):
    p = pm.get_project(args.id)
    if p is None:
        print(f"Project not found: {args.id}"); sys.exit(1)
    stats = pm.project_stats(args.id)
    print(f"\nProject: {p['name']}  ({p['id']})")
    print(f"  Type       : {p['type']}")
    print(f"  Status     : {p['status']}")
    print(f"  Path       : {p['path'] or '(not set)'}")
    print(f"  Tasks      : {stats['done']}/{stats['total']} done, {stats['in_progress']} in-progress, {stats['blocked']} blocked")
    print(f"  Quality avg: {stats['quality_avg']}")
    print(f"  Created    : {p['created']}\n")
    for e in p.get("epics", []):
        print(f"  Epic [{PRIORITY_LABELS.get(e['priority'], '?')}] {e['title']}  ({e['status']})")
        for t in e.get("tasks", []):
            print(f"    {_icon(t['status'])} {t['id']}  {t['title']}")
    print()


def cmd_tasks(args, pm):
    p = pm.get_project(args.id)
    if p is None:
        print(f"Project not found: {args.id}"); sys.exit(1)
    items = [i for i in pm.get_all_tasks() if i["project_id"] == args.id]
    if not items:
        print(f"No tasks for {args.id}"); return
    print(f"\nTasks: {p['name']}  ({args.id})")
    print("-" * 80)
    cur_epic = None
    for item in items:
        if item["epic_title"] != cur_epic:
            cur_epic = item["epic_title"]
            print(f"\n  -- {cur_epic} --")
        t = item["task"]
        print(f"    {_icon(t['status'])} {t['id']}  {t['title']:<45}  {t['category']:<12}  q={t['quality']}")
    print()


def cmd_next(args, pm):
    item = pm.next_task()
    if item is None:
        print("No pending tasks."); return
    t = item["task"]
    print(f"\nNext task:")
    print(f"  Project  : {item['project_name']}  ({item['project_id']})")
    print(f"  Epic     : {item['epic_title']}  ({item['epic_id']})")
    print(f"  Task ID  : {t['id']}")
    print(f"  Title    : {t['title']}")
    print(f"  Category : {t['category']}")
    print(f"  Desc     : {t['description']}\n")


def cmd_add_task(args, pm):
    p = pm.get_project(args.id)
    if p is None:
        print(f"Project not found: {args.id}"); sys.exit(1)
    epics = p.get("epics", [])
    if not epics:
        print("No epics in project."); sys.exit(1)
    epic_id = getattr(args, "epic", None) or epics[0]["id"]
    result = pm.add_task(args.id, epic_id,
                         SubTask(title=args.title,
                                 description=getattr(args, "description", "") or args.title,
                                 category=getattr(args, "category", "code_gen") or "code_gen"))
    if result:
        print(f"\nTask added: {result['id']}  title={result['title']}  cat={result['category']}\n")
    else:
        print("Failed to add task."); sys.exit(1)


COMMANDS = {"new": cmd_new, "list": cmd_list, "show": cmd_show,
            "tasks": cmd_tasks, "next": cmd_next, "add-task": cmd_add_task}


def build_parser():
    p = argparse.ArgumentParser(prog="nexus project",
                                description="Local project + task management.")
    s = p.add_subparsers(dest="command", required=True)
    pn = s.add_parser("new"); pn.add_argument("brief")
    pn.add_argument("--type", default=""); pn.add_argument("--path", default="")
    s.add_parser("list")
    ps = s.add_parser("show"); ps.add_argument("id")
    pt = s.add_parser("tasks"); pt.add_argument("id")
    s.add_parser("next")
    pa = s.add_parser("add-task"); pa.add_argument("id"); pa.add_argument("title")
    pa.add_argument("--description", default=""); pa.add_argument("--category", default="code_gen")
    pa.add_argument("--epic", default="")
    return p


def main(argv=None):
    args = build_parser().parse_args(argv)
    pm = ProjectManager()
    handler = COMMANDS.get(args.command)
    if handler:
        handler(args, pm)


if __name__ == "__main__":
    main()
