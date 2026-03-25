#!/usr/bin/env python3
"""
CEO Orchestrator Check — runs every 60 s via cron.

Reads the live dashboard state and answers:
  1. How many agents / sub-agents are active right now?
  2. What is each one doing?
  3. Is real-time progress visible on the dashboard?
  4. Does any agent need Claude rescue?

Writes results back to:
  • local-agents/dashboard/state.json  (ceo_report block + business_summary)
  • state/todo.md                      (CEO section at top)
  • local-agents/reports/ceo_check.jsonl (append-only audit log)
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time
import urllib.request
from datetime import datetime, timezone

REPO_ROOT = pathlib.Path(__file__).resolve().parents[1]
STATE_FILE = REPO_ROOT / "local-agents" / "dashboard" / "state.json"
TODO_FILE  = REPO_ROOT / "state" / "todo.md"
REPORTS    = REPO_ROOT / "local-agents" / "reports"
LOG_FILE   = REPORTS / "ceo_check.jsonl"

CLAUDE_BUDGET_CAP  = 10.0   # percent — hard cap; trigger rescue flag above this
RESCUE_ELIGIBLE_PCTS = 90.0 # only rescue if local quality is poor
STUCK_SECONDS      = 120    # agent with in-progress status but no update for this long
DASHBOARD_URL      = "http://localhost:3001/api/state"


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


def _now_ts() -> float:
    return time.time()


# ── Core analysis ──────────────────────────────────────────────────────────────

def analyse(state: dict) -> dict:
    agents: dict = state.get("agents", {})
    tq: dict     = state.get("task_queue", {})
    tu: dict     = state.get("token_usage", {})
    hw: dict     = state.get("hardware", {})
    now          = _now_ts()

    # Agent counts
    total_agents   = len(agents)
    active_agents  = [n for n, a in agents.items()
                      if a.get("status") not in ("idle", "", None)]
    stuck_agents   = []
    rescue_needed  = []
    worker_summary = []

    for name, a in agents.items():
        status      = a.get("status", "idle")
        task        = a.get("task", "")[:80]
        quality     = a.get("quality", 0)
        sub_agents  = a.get("sub_agents", [])
        worker_cnt  = a.get("worker_count", len([w for w in sub_agents
                             if w.get("status") == "running"]))
        last_upd    = a.get("last_updated", 0)

        # Stuck detection: in-progress but no update for STUCK_SECONDS
        if status not in ("idle", "", None) and isinstance(last_upd, (int, float)):
            if (now - float(last_upd)) > STUCK_SECONDS:
                stuck_agents.append(name)

        # Sub-agent roster
        total_subs  = len(sub_agents)
        running_subs = [w for w in sub_agents if w.get("status") == "running"]
        done_subs    = [w for w in sub_agents if w.get("status") == "done"]

        if total_subs > 0 or status not in ("idle", "", None):
            worker_summary.append({
                "agent": name,
                "status": status,
                "task": task,
                "quality": quality,
                "workers_total": total_subs,
                "workers_running": len(running_subs),
                "workers_done": len(done_subs),
                "stuck": name in stuck_agents,
            })

    # Claude budget
    budget_pct     = float(tu.get("budget_pct", 0.0))
    budget_warning = budget_pct >= CLAUDE_BUDGET_CAP

    # Rescue candidates: stuck agents where Claude budget still has room
    if not budget_warning:
        rescue_needed = [a for a in stuck_agents
                         if agents[a].get("quality", 100) < RESCUE_ELIGIBLE_PCTS]

    # Task progress
    done    = int(tq.get("completed", 0))
    total   = int(tq.get("total", 100))
    in_prog = int(tq.get("in_progress", 0))
    failed  = int(tq.get("failed", 0))
    pct     = round(done / total * 100, 1) if total else 0.0

    # Health score 0–100
    health = 100
    health -= len(stuck_agents) * 15
    health -= len(rescue_needed) * 10
    health -= failed * 2
    health -= (budget_pct / 10) if budget_warning else 0
    health = max(0, min(100, int(health)))

    # Dashboard live check
    dash_live = _dashboard_live()

    return {
        "ts": _now_iso(),
        "total_agents": total_agents,
        "active_agents": active_agents,
        "active_count": len(active_agents),
        "total_sub_agents": sum(w["workers_total"] for w in worker_summary),
        "running_sub_agents": sum(w["workers_running"] for w in worker_summary),
        "stuck_agents": stuck_agents,
        "rescue_needed": rescue_needed,
        "dashboard_live": dash_live,
        "tasks_done": done,
        "tasks_total": total,
        "tasks_in_progress": in_prog,
        "tasks_failed": failed,
        "pct_complete": pct,
        "claude_budget_pct": budget_pct,
        "budget_warning": budget_warning,
        "health_score": health,
        "cpu_pct": hw.get("cpu_pct", 0),
        "ram_pct": hw.get("ram_pct", 0),
        "worker_summary": worker_summary,
    }


# ── Dashboard state update ─────────────────────────────────────────────────────

def update_dashboard(state: dict, report: dict) -> None:
    state["ceo_report"] = {
        "ts": report["ts"],
        "active_agents": report["active_count"],
        "total_sub_agents": report["total_sub_agents"],
        "running_sub_agents": report["running_sub_agents"],
        "stuck_agents": report["stuck_agents"],
        "rescue_needed": report["rescue_needed"],
        "health_score": report["health_score"],
        "claude_budget_pct": report["claude_budget_pct"],
        "budget_warning": report["budget_warning"],
        "dashboard_live": report["dashboard_live"],
    }
    state["business_summary"] = {
        "headline": (
            f"{report['tasks_done']} of {report['tasks_total']} tasks complete "
            f"({report['pct_complete']}%)"
        ),
        "pct_complete": report["pct_complete"],
        "agents_active": report["active_count"],
        "sub_agents_running": report["running_sub_agents"],
        "blockers_open": len(report["stuck_agents"]),
        "rescue_pending": len(report["rescue_needed"]),
        "claude_budget_pct": report["claude_budget_pct"],
        "health_score": report["health_score"],
        "dashboard_live": report["dashboard_live"],
        "version": state.get("version", {}).get("current", 1)
            if isinstance(state.get("version"), dict) else state.get("version", 1),
        "updated_at": report["ts"],
    }
    _write_state(state)


# ── Todo.md update ─────────────────────────────────────────────────────────────

def update_todo(report: dict) -> None:
    try:
        existing = TODO_FILE.read_text() if TODO_FILE.exists() else ""
        # Remove any previous CEO section
        lines = existing.splitlines()
        filtered = []
        skip = False
        for line in lines:
            if line.startswith("## CEO Orchestrator Status"):
                skip = True
            elif skip and line.startswith("## "):
                skip = False
            if not skip:
                filtered.append(line)
        existing = "\n".join(filtered).strip()

        # Build CEO section
        r = report
        rescue_block = ""
        if r["rescue_needed"]:
            rescue_block = "\n".join(
                f"  - [ ] 🚨 RESCUE: `{a}` needs Claude — stuck + quality below threshold"
                for a in r["rescue_needed"]
            )
        stuck_block = ""
        if r["stuck_agents"]:
            stuck_block = "\n".join(
                f"  - [ ] ⚠️  STUCK: `{a}` — no update for >{STUCK_SECONDS}s"
                for a in r["stuck_agents"]
            )

        workers_block = ""
        for w in r["worker_summary"]:
            icon = "🏃" if w["status"] not in ("idle","") else "💤"
            workers_block += (
                f"  - {icon} `{w['agent']}` [{w['status']}] "
                f"workers={w['workers_running']}/{w['workers_total']} "
                f"quality={w['quality']}  {w['task'][:60]}\n"
            )

        budget_line = (
            f"⛔ HARD CAP HIT ({r['claude_budget_pct']:.1f}%)"
            if r["budget_warning"]
            else f"{r['claude_budget_pct']:.1f}% used"
        )
        dash_line = "✅ LIVE" if r["dashboard_live"] else "❌ NOT RUNNING — run `nexus dashboard`"

        ceo_section = f"""## CEO Orchestrator Status
_Last check: {r['ts']}_

### Summary
- **Progress**: {r['tasks_done']}/{r['tasks_total']} tasks ({r['pct_complete']}%)
- **Active agents**: {r['active_count']} / {r['total_agents']} total
- **Sub-agents running**: {r['running_sub_agents']} (total registered: {r['total_sub_agents']})
- **Health score**: {r['health_score']}/100
- **Dashboard**: {dash_line}
- **Claude budget**: {budget_line}
- **CPU**: {r['cpu_pct']:.0f}%  RAM: {r['ram_pct']:.0f}%

### Agent Board (Jira)
{workers_block or '  _All agents idle_'}
### Blockers
{stuck_block or rescue_block or '  _None_'}

### Actions Needed
{"  - [ ] 🚨 Claude rescue required for: " + ", ".join(r["rescue_needed"]) if r["rescue_needed"] else "  - [x] No rescue needed"}
{"  - [ ] Dashboard is offline — start with `nexus dashboard`" if not r["dashboard_live"] else "  - [x] Dashboard is live"}
{"  - [ ] ⛔ Claude budget at cap — switch all tasks to local agents only" if r["budget_warning"] else "  - [x] Claude budget within 10% cap"}

"""
        new_todo = ceo_section + "\n" + existing
        TODO_FILE.write_text(new_todo)
    except Exception as e:
        print(f"[ceo_check] todo update failed: {e}", file=sys.stderr)


# ── Audit log ──────────────────────────────────────────────────────────────────

def log_report(report: dict) -> None:
    try:
        REPORTS.mkdir(parents=True, exist_ok=True)
        entry = {k: v for k, v in report.items() if k != "worker_summary"}
        with open(LOG_FILE, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


# ── Stdout summary ─────────────────────────────────────────────────────────────

def print_summary(report: dict) -> None:
    r = report
    print(f"\n[CEO Check] {r['ts']}")
    print(f"  Agents active : {r['active_count']}/{r['total_agents']}")
    print(f"  Sub-agents    : {r['running_sub_agents']} running / {r['total_sub_agents']} total")
    print(f"  Tasks         : {r['tasks_done']}/{r['tasks_total']} done ({r['pct_complete']}%)")
    print(f"  Health        : {r['health_score']}/100")
    print(f"  Dashboard     : {'live ✓' if r['dashboard_live'] else 'OFFLINE ✗'}")
    print(f"  Claude budget : {r['claude_budget_pct']:.1f}%"
          + (" ⛔ CAP HIT" if r["budget_warning"] else ""))
    if r["stuck_agents"]:
        print(f"  ⚠️  Stuck      : {', '.join(r['stuck_agents'])}")
    if r["rescue_needed"]:
        print(f"  🚨 Rescue     : {', '.join(r['rescue_needed'])}")
    if r["worker_summary"]:
        print()
        for w in r["worker_summary"]:
            run = w["workers_running"]
            tot = w["workers_total"]
            print(f"    {w['agent']:<18} [{w['status']:<10}] "
                  f"workers={run}/{tot}  q={w['quality']}  {w['task'][:50]}")
    print()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    state  = _read_state()
    report = analyse(state)
    update_dashboard(state, report)
    update_todo(report)
    log_report(report)
    print_summary(report)


if __name__ == "__main__":
    main()
