#!/usr/bin/env python3
"""
CEO Orchestrator Check — runs every 10 s (--loop) or via 60-s cron.

Checks as CEO:
  - How many agents / sub-agents (0-1000s) are active and what are they doing
  - Are they showing real-time progress on the dashboard
  - Do any sub-agents need Claude rescue
  - Classifies tasks by real project category (not just leetcode)
  - Updates memory, workflow, skills on every lesson learned
  - Writes structured todo_board to state.json (the dashboard Jira board)
  - Every 60 min: checks docs, README, architecture are in sync

Outputs:
  local-agents/dashboard/state.json  — ceo_report + todo_board + business_summary
  state/todo.md                      — CEO Jira board section
  local-agents/reports/ceo_check.jsonl
  memory/ceo_lessons.md              — lessons from stuck/rescued sub-agents
"""
from __future__ import annotations

import argparse
import json
import pathlib
import sys
import time
import urllib.request
from datetime import datetime, timezone

REPO_ROOT  = pathlib.Path(__file__).resolve().parents[1]
STATE_FILE = REPO_ROOT / "local-agents" / "dashboard" / "state.json"
TODO_FILE  = REPO_ROOT / "state" / "todo.md"
REPORTS    = REPO_ROOT / "local-agents" / "reports"
LOG_FILE   = REPORTS / "ceo_check.jsonl"
MEMORY_DIR = (
    pathlib.Path.home()
    / ".claude" / "projects"
    / "-Users-jimmymalhan-Documents-local-agent-runtime"
    / "memory"
)

CLAUDE_BUDGET_CAP   = 10.0
RESCUE_QUALITY_GATE = 50
STUCK_SECONDS       = 120
DASHBOARD_URL       = "http://localhost:3001/api/state"
DOC_CHECK_INTERVAL  = 3600   # seconds — check docs/README/arch once per hour

CATEGORY_KEYWORDS = {
    "memory":       ["memory", "remember", "learn", "lesson", "knowledge"],
    "workflow":     ["workflow", "pipeline", "orchestrat", "coordination"],
    "skill":        ["skill", "role", "capability", "upgrade prompt"],
    "architecture": ["architect", "design", "schema", "structure", "refactor"],
    "feature":      ["implement", "add", "build", "create", "feature"],
    "bugfix":       ["fix", "bug", "error", "repair", "patch", "broken"],
    "benchmark":    ["benchmark", "eval", "opus", "compare", "score", "gap"],
    "test":         ["test", "validate", "verify", "check", "qa"],
    "docs":         ["doc", "readme", "explain", "write up"],
    "research":     ["research", "search", "find", "discover", "study",
                     "improve quality", "qa audit", "frontend quality",
                     "backend quality", "ai/ml quality"],
    "leetcode":     ["leetcode", "rain water", "dijkstra", "binary search",
                     "lru cache", "trie", "bloom", "merge sort",
                     "sorting", "trapping", "skyline", "n.queen",
                     "burst balloo", "alien dict", "word break"],
}

# Researcher improvement tasks — always injected when researcher is idle
RESEARCHER_IMPROVEMENT_TASKS = [
    "Audit local model output quality: compare Nexus vs Opus 4.6 on last 10 tasks",
    "QA sweep: run full test suite, identify flaky tests and coverage gaps",
    "Frontend quality audit: check all UI states (loading/error/empty/success)",
    "Backend quality audit: verify all API endpoints handle edge cases correctly",
    "AI/ML quality audit: measure prompt quality, token efficiency, retry rates",
    "Memory consolidation: merge duplicate lessons, remove stale entries",
    "Workflow improvement: identify bottlenecks in agent coordination pipeline",
    "Skill upgrade: find skills with lowest quality scores, generate improvements",
    "Architecture review: check for drift between registry, orchestrator, agents",
    "Docs sync: update README, AGENTS.md, architecture diagram if stale",
]

CAT_ICON = {
    "rescue":"🚨","blocked":"⚠️","ops":"⚙️","memory":"🧠","workflow":"🔄",
    "skill":"💡","architecture":"🏗️","feature":"✨","bugfix":"🐛",
    "benchmark":"📊","test":"🧪","docs":"📝","research":"🔍",
    "leetcode":"🔢","general":"•",
}

_last_doc_check: float = 0.0


# ── Helpers ────────────────────────────────────────────────────────────────────

def _read_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _write_state(state: dict) -> None:
    try:
        STATE_FILE.write_text(json.dumps(state, indent=2))
    except Exception:
        pass


def _dashboard_live() -> bool:
    try:
        with urllib.request.urlopen(DASHBOARD_URL, timeout=2) as r:
            return r.status == 200
    except Exception:
        return False


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _classify(task: str) -> str:
    tl = task.lower()
    for cat, kws in CATEGORY_KEYWORDS.items():
        if any(k in tl for k in kws):
            return cat
    return "general"


# ── Doc/README/arch sync check (every 60 min) ─────────────────────────────────

def check_docs_sync() -> list[str]:
    global _last_doc_check
    if time.time() - _last_doc_check < DOC_CHECK_INTERVAL:
        return []
    _last_doc_check = time.time()
    issues: list[str] = []
    readme = REPO_ROOT / "README.md"
    agents_md = REPO_ROOT / "AGENTS.md"
    try:
        if readme.exists():
            age_days = (time.time() - readme.stat().st_mtime) / 86400
            if age_days > 7:
                issues.append(f"README.md not updated in {age_days:.0f} days")
        if agents_md.exists():
            age_days = (time.time() - agents_md.stat().st_mtime) / 86400
            if age_days > 7:
                issues.append(f"AGENTS.md not updated in {age_days:.0f} days")
        # Check local-agents/orchestrator/main.py matches registry
        registry = REPO_ROOT / "local-agents" / "registry" / "agents.json"
        if not registry.exists():
            issues.append("local-agents/registry/agents.json missing — run nexus init")
    except Exception:
        pass
    return issues


# ── Core analysis ──────────────────────────────────────────────────────────────

def analyse(state: dict) -> dict:
    agents: dict = state.get("agents", {})
    tq: dict     = state.get("task_queue", {})
    tu: dict     = state.get("token_usage", {})
    hw: dict     = state.get("hardware", {})
    now          = time.time()

    active_agents: list[str] = []
    stuck_agents:  list[str] = []
    sub_agent_summary: list[dict] = []

    for name, a in agents.items():
        status   = a.get("status", "idle")
        task     = a.get("task", "")[:100]
        quality  = int(a.get("quality", 0))
        subs     = a.get("sub_agents", [])
        last_upd = a.get("last_updated", 0)
        cat      = _classify(task)

        if status not in ("idle", "", None):
            active_agents.append(name)
        if status not in ("idle", "", None) and isinstance(last_upd, (int, float)):
            if (now - float(last_upd)) > STUCK_SECONDS:
                stuck_agents.append(name)

        running_subs = [w for w in subs if w.get("status") == "running"]
        done_subs    = [w for w in subs if w.get("status") == "done"]
        failed_subs  = [w for w in subs if w.get("status") == "failed"]

        sub_agent_summary.append({
            "agent":              name,
            "status":             status,
            "task":               task,
            "category":           cat,
            "quality":            quality,
            "sub_agents_total":   len(subs),
            "sub_agents_running": len(running_subs),
            "sub_agents_done":    len(done_subs),
            "sub_agents_failed":  len(failed_subs),
            "stuck":              name in stuck_agents,
        })

    budget_pct    = float(tu.get("budget_pct", 0.0))
    budget_warn   = budget_pct >= CLAUDE_BUDGET_CAP
    rescue_needed = ([] if budget_warn else
                     [a for a in stuck_agents
                      if agents[a].get("quality", 100) < RESCUE_QUALITY_GATE])

    done    = int(tq.get("completed", 0))
    total   = int(tq.get("total", 100))
    in_prog = int(tq.get("in_progress", 0))
    failed  = int(tq.get("failed", 0))
    pct     = round(done / total * 100, 1) if total else 0.0

    projects = [
        {"name": p.get("name",""), "done": p.get("done",0),
         "total": p.get("total",0), "status": p.get("status","pending")}
        for p in state.get("board_plan", {}).get("projects", [])
    ]

    health = max(0, min(100, int(
        100 - len(stuck_agents)*15 - len(rescue_needed)*10
            - failed*2 - min(int(budget_pct*2), 20)
    )))

    doc_issues = check_docs_sync()

    return {
        "ts":                 _now_iso(),
        "total_agents":       len(agents),
        "active_agents":      active_agents,
        "active_count":       len(active_agents),
        "total_sub_agents":   sum(s["sub_agents_total"]   for s in sub_agent_summary),
        "running_sub_agents": sum(s["sub_agents_running"] for s in sub_agent_summary),
        "stuck_agents":       stuck_agents,
        "rescue_needed":      rescue_needed,
        "dashboard_live":     _dashboard_live(),
        "tasks_done":         done,
        "tasks_total":        total,
        "tasks_in_progress":  in_prog,
        "tasks_failed":       failed,
        "pct_complete":       pct,
        "claude_budget_pct":  budget_pct,
        "budget_warning":     budget_warn,
        "health_score":       health,
        "cpu_pct":            hw.get("cpu_pct", 0),
        "ram_pct":            hw.get("ram_pct", 0),
        "sub_agent_summary":  sub_agent_summary,
        "project_breakdown":  projects,
        "doc_issues":         doc_issues,
    }


# ── Todo board ─────────────────────────────────────────────────────────────────

def build_todo_board(report: dict) -> list[dict]:
    items: list[dict] = []

    for agent in report["rescue_needed"]:
        items.append({"id": f"rescue-{agent}", "priority": 0, "category": "rescue",
                      "title": f"[RESCUE] {agent} — stuck, quality below threshold",
                      "status": "blocked", "agent": agent, "sub_agents": 0})

    for agent in report["stuck_agents"]:
        task = next((s["task"] for s in report["sub_agent_summary"]
                     if s["agent"] == agent), "")
        items.append({"id": f"stuck-{agent}", "priority": 1, "category": "blocked",
                      "title": f"[STUCK] {agent}: {task[:60]}",
                      "status": "blocked", "agent": agent, "sub_agents": 0})

    if report["budget_warning"]:
        items.append({"id": "budget-cap", "priority": 1, "category": "ops",
                      "title": f"Claude budget at cap ({report['claude_budget_pct']:.1f}%) — local-only mode",
                      "status": "blocked", "agent": "ceo", "sub_agents": 0})

    for di in report["doc_issues"]:
        items.append({"id": f"doc-{len(items)}", "priority": 2, "category": "docs",
                      "title": f"[DOCS] {di}", "status": "todo",
                      "agent": "ceo", "sub_agents": 0})

    for s in report["sub_agent_summary"]:
        if s["status"] not in ("idle", "", None):
            items.append({"id": f"active-{s['agent']}", "priority": 2,
                          "category": s["category"],
                          "title": s["task"] or f"{s['agent']} running",
                          "status": "blocked" if s["stuck"] else "running",
                          "agent": s["agent"],
                          "sub_agents": s["sub_agents_running"]})

    # Researcher improvement: if researcher agent is idle, inject quality-improvement tasks
    researcher_active = any(
        s["agent"] == "researcher" and s["status"] not in ("idle", "", None)
        for s in report["sub_agent_summary"]
    )
    if not researcher_active:
        import random
        # Pick 3 random improvement tasks (rotate so board stays fresh)
        seed = int(time.time() / 3600)  # changes hourly
        rng  = random.Random(seed)
        tasks = rng.sample(RESEARCHER_IMPROVEMENT_TASKS, min(3, len(RESEARCHER_IMPROVEMENT_TASKS)))
        for t in tasks:
            items.append({"id": f"researcher-{len(items)}", "priority": 2,
                          "category": "research", "title": t,
                          "status": "todo", "agent": "researcher", "sub_agents": 0})

    try:
        todo_text = TODO_FILE.read_text() if TODO_FILE.exists() else ""
        in_ceo = False
        for line in todo_text.splitlines():
            if line.startswith("## CEO Orchestrator"):
                in_ceo = True; continue
            if in_ceo and line.startswith("## "):
                in_ceo = False
            if in_ceo:
                continue
            ln = line.strip()
            if ln.startswith("- [ ]") or ln.startswith("- [x]"):
                done_item = ln.startswith("- [x]")
                text = ln[5:].strip()
                if len(text) < 4:
                    continue
                items.append({"id": f"todo-{len(items)}", "priority": 4,
                               "category": _classify(text), "title": text[:120],
                               "status": "done" if done_item else "todo",
                               "agent": "", "sub_agents": 0})
    except Exception:
        pass

    return items


# ── Dashboard update ───────────────────────────────────────────────────────────

def update_dashboard(state: dict, report: dict, todo_items: list[dict]) -> None:
    state["ceo_report"] = {
        "ts":                 report["ts"],
        "active_agents":      report["active_count"],
        "total_agents":       report["total_agents"],
        "total_sub_agents":   report["total_sub_agents"],
        "running_sub_agents": report["running_sub_agents"],
        "stuck_agents":       report["stuck_agents"],
        "rescue_needed":      report["rescue_needed"],
        "health_score":       report["health_score"],
        "claude_budget_pct":  report["claude_budget_pct"],
        "budget_warning":     report["budget_warning"],
        "dashboard_live":     report["dashboard_live"],
        "project_breakdown":  report["project_breakdown"],
        "doc_issues":         report["doc_issues"],
    }
    counts = {s: sum(1 for i in todo_items if i["status"] == s)
              for s in ("blocked", "running", "todo", "done")}
    state["todo_board"] = {
        "updated_at": report["ts"],
        "items":      todo_items,
        "counts":     counts,
    }
    state["business_summary"] = {
        "headline":           (f"{report['tasks_done']} of {report['tasks_total']} "
                               f"tasks complete ({report['pct_complete']}%)"),
        "pct_complete":       report["pct_complete"],
        "agents_active":      report["active_count"],
        "sub_agents_running": report["running_sub_agents"],
        "blockers_open":      len(report["stuck_agents"]),
        "rescue_pending":     len(report["rescue_needed"]),
        "claude_budget_pct":  report["claude_budget_pct"],
        "health_score":       report["health_score"],
        "dashboard_live":     report["dashboard_live"],
        "version":            (state.get("version", {}).get("current", 1)
                               if isinstance(state.get("version"), dict)
                               else state.get("version", 1)),
        "updated_at":         report["ts"],
    }
    _write_state(state)


# ── Memory / lesson update ─────────────────────────────────────────────────────

def update_memory(report: dict) -> None:
    lessons: list[str] = []
    for agent in report["stuck_agents"]:
        task = next((s["task"] for s in report["sub_agent_summary"]
                     if s["agent"] == agent), "unknown task")
        q   = next((s["quality"] for s in report["sub_agent_summary"]
                    if s["agent"] == agent), 0)
        cat = next((s["category"] for s in report["sub_agent_summary"]
                    if s["agent"] == agent), "general")
        lessons.append(
            f"- `{agent}` [{cat}] stuck on `{task[:60]}` (quality={q}) "
            f"— split task or route differently"
        )
    if report["budget_warning"]:
        lessons.append(
            f"- Claude budget hit {report['claude_budget_pct']:.1f}% cap "
            f"— all work local-only, no rescue available"
        )
    for di in report["doc_issues"]:
        lessons.append(f"- Docs drift: {di}")
    if not lessons:
        return
    try:
        MEMORY_DIR.mkdir(parents=True, exist_ok=True)
        lf = MEMORY_DIR / "ceo_lessons.md"
        header = ("---\nname: CEO orchestrator lessons\n"
                  "description: Stuck agents, rescues, budget caps, doc drift — patterns for improvement\n"
                  "type: feedback\n---\n\n"
                  "**Why:** CEO check observations — inform future task routing and sub-agent sizing.\n"
                  "**How to apply:** Prefer splitting large tasks; avoid pure leetcode tasks in production.\n\n")
        existing = lf.read_text() if lf.exists() else header
        lf.write_text(existing + f"\n### {report['ts']}\n" + "\n".join(lessons) + "\n")
    except Exception:
        pass


# ── Todo.md update ─────────────────────────────────────────────────────────────

def update_todo(report: dict, todo_items: list[dict]) -> None:
    try:
        existing = TODO_FILE.read_text() if TODO_FILE.exists() else ""
        lines = existing.splitlines()
        filtered, skip = [], False
        for line in lines:
            if line.startswith("## CEO Orchestrator"):
                skip = True
            elif skip and line.startswith("## "):
                skip = False
            if not skip:
                filtered.append(line)
        existing = "\n".join(filtered).strip()

        r = report
        blocked = [i for i in todo_items if i["status"] == "blocked"]
        running = [i for i in todo_items if i["status"] == "running"]

        def _line(item: dict) -> str:
            icon = CAT_ICON.get(item.get("category", ""), "•")
            ag   = f" [{item['agent']}]" if item.get("agent") else ""
            sa   = (f" ({item['sub_agents']} sub-agents)"
                    if item.get("sub_agents") else "")
            return f"  - [ ] {icon} {item['title'][:90]}{ag}{sa}"

        cats: dict[str, int] = {}
        for i in todo_items:
            c = i.get("category", "general")
            cats[c] = cats.get(c, 0) + 1
        cat_line = " · ".join(f"{k}:{v}" for k, v in sorted(cats.items()) if v > 0)

        bline = (f"⛔ CAP ({r['claude_budget_pct']:.1f}%) — local-only"
                 if r["budget_warning"]
                 else f"{r['claude_budget_pct']:.1f}% used (cap: 10%)")
        dline = "✅ live" if r["dashboard_live"] else "❌ offline — run `nexus dashboard`"
        doc_block = ("\n".join(f"  - [ ] 📝 {di}" for di in r["doc_issues"])
                     if r["doc_issues"] else "")

        newline = "\n"
        blocked_lines = newline.join(_line(i) for i in blocked) or '  - None'
        running_lines = newline.join(_line(i) for i in running) or '  - None'
        doc_section = ("### 📝 Doc Drift (every 60 min)\n" + doc_block) if doc_block else ""
        section = (
            "## CEO Orchestrator Status\n"
            f"_Updated: {r['ts']} · checks every 10 s_\n\n"
            "| Metric | Value |\n"
            "|--------|---------|\n"
            f"| Progress | {r['tasks_done']}/{r['tasks_total']} tasks · {r['pct_complete']}% |\n"
            f"| Agents active | {r['active_count']}/{r['total_agents']} |\n"
            f"| Sub-agents running | {r['running_sub_agents']} / {r['total_sub_agents']} registered |\n"
            f"| Health | {r['health_score']}/100 |\n"
            f"| Dashboard | {dline} |\n"
            f"| Claude budget | {bline} |\n"
            f"| CPU / RAM | {r['cpu_pct']:.0f}% / {r['ram_pct']:.0f}% |\n\n"
            f"**Task categories:** {cat_line or 'none'}\n\n"
            "### 🚨 Blocked / Needs Action\n"
            f"{blocked_lines}\n\n"
            "### 🏃 Running Now\n"
            f"{running_lines}\n"
            f"{doc_section}\n"
        )
        TODO_FILE.write_text(section + "\n" + existing)
    except Exception as e:
        print(f"[ceo_check] todo update failed: {e}", file=sys.stderr)


# ── Audit log ──────────────────────────────────────────────────────────────────

def log_report(report: dict) -> None:
    try:
        REPORTS.mkdir(parents=True, exist_ok=True)
        entry = {k: v for k, v in report.items()
                 if k not in ("sub_agent_summary", "project_breakdown")}
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ── Stdout summary ─────────────────────────────────────────────────────────────

def print_summary(report: dict) -> None:
    r = report
    print(f"\n[CEO Check] {r['ts']}")
    print(f"  Agents active  : {r['active_count']}/{r['total_agents']}")
    print(f"  Sub-agents     : {r['running_sub_agents']} running / {r['total_sub_agents']} registered")
    print(f"  Tasks          : {r['tasks_done']}/{r['tasks_total']} done ({r['pct_complete']}%)")
    print(f"  Health         : {r['health_score']}/100")
    print(f"  Dashboard      : {'live ✓' if r['dashboard_live'] else 'OFFLINE ✗'}")
    print(f"  Claude budget  : {r['claude_budget_pct']:.1f}%"
          + (" ⛔ CAP HIT" if r["budget_warning"] else ""))
    if r["stuck_agents"]:
        print(f"  ⚠️  Stuck       : {', '.join(r['stuck_agents'])}")
    if r["rescue_needed"]:
        print(f"  🚨 Rescue      : {', '.join(r['rescue_needed'])}")
    if r["doc_issues"]:
        print(f"  📝 Doc drift   : {len(r['doc_issues'])} issue(s)")
    active = [s for s in r["sub_agent_summary"] if s["status"] not in ("idle","",None)]
    if active:
        print()
        for s in active:
            print(f"    {s['agent']:<18} {s['status']:<12} [{s['category']:<12}] "
                  f"sub-agents={s['sub_agents_running']}/{s['sub_agents_total']}  "
                  f"q={s['quality']}  {s['task'][:50]}")
    print()


# ── Main ───────────────────────────────────────────────────────────────────────

def run_once() -> None:
    state      = _read_state()
    report     = analyse(state)
    todo_items = build_todo_board(report)
    update_dashboard(state, report, todo_items)
    update_todo(report, todo_items)
    update_memory(report)
    log_report(report)
    print_summary(report)


def main() -> None:
    parser = argparse.ArgumentParser(description="CEO Orchestrator Check")
    parser.add_argument("--loop", action="store_true",
                        help="Run continuously at --interval seconds (default: 10)")
    parser.add_argument("--interval", type=int, default=10)
    args = parser.parse_args()

    if args.loop:
        print(f"[CEO] Loop mode — every {args.interval}s  Ctrl-C to stop")
        while True:
            try:
                run_once()
            except Exception as e:
                print(f"[CEO] Error: {e}", file=sys.stderr)
            time.sleep(args.interval)
    else:
        run_once()


if __name__ == "__main__":
    main()
