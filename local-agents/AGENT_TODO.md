# Local Agent Runtime — TODO by Project
# Owner: local agents (Nexus runtime) — Claude main session NEVER picks up tasks here
# Task source: projects/projects.json → next_project_task() → run_project_task()
# Claude rescue: cron every 5 min — fires ONLY when agent fails 3× + budget <10%
#
# ══════════════════════════════════════════════════════════════════
# CLAUDE MAIN SESSION POLICY: DIAGNOSE + ASSIGN ONLY. NEVER FIX CODE.
# ALL code fixes and new features → local agents via projects.json queue.
# File a task: python3 -m orchestrator.task_intake "description" --category dashboard
# ══════════════════════════════════════════════════════════════════
#
# DASHBOARD NEVER-DOWN + NEVER-BLANK GUARANTEE:
#   Poll: every 2s via setInterval(poll,2000)
#   WS:   auto-reconnects in 3s on drop
#   Stale banner: fires after 10s — _checkStaleness() every 3s
#   Fallback: seed() shows demo state if /api/state unreachable (never blank)
#   Updater: live_state_updater.py writes state.json every 2s; cron restarts on crash
#   ALL dashboard/frontend work → frontend_agent ONLY. Claude main: NEVER.
#
# KNOWN EMPTY VALUE ROOT CAUSES (tasks queued for local agents to fix):
#   t-ce5ff84a: state_writer.update_agent() missing quality field → agent cards blank
#   t-644865cf: sub_agents[].model empty string → model chips blank
#   t-ab37fb1d: live_state_updater never writes recent_tasks → Tasks tab empty
#   t-811f198d: orchestrator never calls update_version_changelog() → CEO changelog empty
#   t-7a48cbf1: agents never call add_research_finding() → Logs tab empty
#   t-545cf9fe: live_state_updater never reads projects.json → Projects tab empty counts
#
# SKILL: .claude/skills/dashboard-state-writer.md — every agent must read this
# AUDIT: python3 -c "import json; s=json.load(open('dashboard/state.json')); ..."
#        (full audit command in dashboard-state-writer.md skill)

# ═══════════════════════════════════════════════════════════════════
# PROJECT 1 — Nexus Runtime Core  (p-nexus)
# File: local-agents/orchestrator/  model: executor, benchmarker
# Loop: run_task({"category": "deploy"|"code_gen"|"monitor", ...})
# ═══════════════════════════════════════════════════════════════════

## Epic: v1→v100 Continuous Loop  [priority: 1 — unblocked]
- [ ] t-loop-01: Launch continuous task loop (v6→v1000)
  → agent: executor  category: deploy
  → cmd: python3 orchestrator/main.py --auto 6
- [ ] t-loop-02: Switch task suite to real-world 100 tasks
  → agent: executor  category: code_gen
- [ ] t-loop-03: Auto-merge passing PRs (#27-#34)
  → agent: executor  category: deploy
  → cmd: scripts/auto_merge_pr.sh
- [ ] t-loop-04: Track velocity per version → reports/velocity.jsonl
  → agent: executor  category: monitor

## Epic: Agent Quality & Capabilities  [priority: 2 — depends on: e-loop]
- [ ] t-agents-01: Deploy context_optimizer.py for token compression
  → agent: executor  category: perf
- [ ] t-agents-02: Project scaffolding agent (scaffolder.py)
  → agent: executor  category: code_gen
- [ ] t-agents-03: ProceduralMemory + context injector
  → agent: executor  category: code_gen

# ═══════════════════════════════════════════════════════════════════
# PROJECT 2 — Nexus Dashboard  (p-dashboard)
# File: local-agents/dashboard/  agent: frontend_agent ONLY
# NEVER: Claude main session  NEVER: manual edits by operator
# Loop: run_task({"category": "dashboard"|"react", ...})
# ═══════════════════════════════════════════════════════════════════

## Epic: Never-Down Guarantee  [priority: 1 — unblocked]
#   Rules:
#   1. Poll loop (poll every 2s) must always be active
#   2. WS reconnect in 3s on drop
#   3. Stale banner fires at 10s — always visible
#   4. seed() fallback — dashboard never blank
#   5. live_state_updater.py must run; cron restarts on crash
#
- [ ] t-dash-01: Keep state.json updated every 2s (live_state_updater.py daemon)
  → agent: frontend_agent  category: dashboard
- [ ] t-dash-02: Cron: restart live_state_updater.py on crash (every 1 min)
  → agent: frontend_agent  category: dashboard
- [ ] t-dash-03: Stale-data test — verify banner appears after 15s server kill
  → agent: frontend_agent  category: dashboard

## Epic: Dashboard UI Features  [priority: 2 — depends on: e-dash-uptime]
- [ ] t-dash-04: Company projects panel — poll /api/projects every 2s
  → agent: frontend_agent  category: react
- [ ] t-dash-05: frontend_agent status card in Agents tab
  → agent: frontend_agent  category: dashboard

# ═══════════════════════════════════════════════════════════════════
# PROJECT 3 — jobs.hil-tad.com  (p-jobs)
# Stack: React 18, TypeScript, Tailwind, Vite, Zustand
# agent: frontend_agent ONLY  NEVER: Claude main
# Loop: run_task({"category": "component"|"state_mgmt"|"design_system"|..., ...})
# ═══════════════════════════════════════════════════════════════════

## Epic: Core Components  [priority: 1 — unblocked]
- [ ] t-jobs-01: JobCard component (React/TS, Tailwind)
  → agent: frontend_agent  category: component
- [ ] t-jobs-02: JobList — responsive grid with pagination
  → agent: frontend_agent  category: component
- [ ] t-jobs-03: FilterBar + Zustand store with URL sync
  → agent: frontend_agent  category: state_mgmt
- [ ] t-jobs-04: Design system tokens (colors, spacing, typography)
  → agent: frontend_agent  category: design_system

## Epic: Quality & Accessibility  [priority: 2 — depends on: e-jobs-core]
- [ ] t-jobs-05: Accessibility audit + WCAG AA fixes
  → agent: frontend_agent  category: accessibility
- [ ] t-jobs-06: Usability prototype — 5 user flows
  → agent: frontend_agent  category: prototype

# ═══════════════════════════════════════════════════════════════════
# PROJECT 4 — Agent Infrastructure  (p-infra)
# File: local-agents/orchestrator/  agents: executor, architect
# Loop: run_task({"category": "code_gen"|"arch", ...})
# ═══════════════════════════════════════════════════════════════════

## Epic: Continuous Loop Engine  [priority: 1 — unblocked]
- [ ] t-infra-01: Wire continuous_loop.py to pull from projects.json
  → agent: executor  category: code_gen
  → calls: next_project_task() → run_project_task()
- [ ] t-infra-02: DAG task ordering — respect epic depends_on
  → agent: architect  category: arch
- [ ] t-infra-03: Parallel executor — run up to 3 tasks concurrently
  → agent: executor  category: code_gen

## Epic: Memory System  [priority: 2 — depends on: e-infra-loop]
- [ ] t-infra-04: ProceduralMemory class (save/load/rank)
  → agent: executor  category: code_gen
- [ ] t-infra-05: Context injector — prepend top-3 memories to agent prompts
  → agent: executor  category: code_gen

# ═══════════════════════════════════════════════════════════════════
# PERMANENT — Rescue & Ops
# ═══════════════════════════════════════════════════════════════════

## Rescue Protocol (PERMANENT — never remove)
- [x] Cron rescue: */5 * * * * scripts/cron_claude_rescue.sh
  - Fires when: reports/rescue_needed.json exists + budget < 10%
  - Action: upgrade agent prompt only — never fix tasks directly
  - frontend_agent failures → rescue upgrades frontend_agent prompt only

## How Agents Pick Up Tasks Autonomously
# 1. continuous_loop.py calls next_project_task() every iteration
# 2. ProjectManager returns highest-priority pending task from projects.json
# 3. run_project_task(item) routes to correct agent via ROUTING_TABLE
# 4. Agent runs, writes result, marks task done via complete_task()
# 5. Loop continues to next task — never stops unless .stop file exists
# 6. On failure: rescue_needed.json written → cron upgrades prompt → agent retries

## How New Requests Enter the Queue (INTAKE WORKFLOW)
# Any new request → task_intake.py → auto-classified → projects.json → agent picks up
#
#   CLI:   python3 -m orchestrator.task_intake "Add dark mode to dashboard"
#   Code:  from orchestrator.task_intake import intake
#          intake("Fix accessibility on JobCard", category="accessibility")
#
# Classification rules (in order):
#   1. Explicit --category flag → maps directly
#   2. Keyword match in title/description (jobs.hil-tad, WCAG, Zustand, etc.)
#   3. Word match against ROUTING_TABLE categories
#   4. Default → p-nexus / e-agents
#
# Category → Project mapping:
#   dashboard, live_state       → p-dashboard / e-dash-uptime
#   component, react, frontend  → p-jobs / e-jobs-core
#   ux, accessibility, prototype→ p-jobs / e-jobs-quality
#   arch, dag, infra            → p-infra / e-infra-loop
#   memory                      → p-infra / e-infra-memory
#   everything else             → p-nexus / e-agents
#
# List all pending:  python3 -m orchestrator.task_intake --list

## DONE
- [x] Dashboard state updated with E10 plan + CEO view
- [x] VERSION synced to 0.5.0
- [x] Repo cleaned — scattered files moved to generated/projects/
- [x] CI fixed — removed Co-Authored-By from auto_commit_pr.sh
- [x] Supervisor + auto-heal wired in orchestrator
- [x] frontend_agent created — owns all dashboard + jobs.hil-tad.com work
- [x] 14 frontend categories wired in ROUTING_TABLE
- [x] Stale-data banner added to dashboard (fires at 10s, shows age, retry button)
- [x] WS reconnect now sets _wsAlive flag + updates stale message
- [x] projects.json populated — 4 projects, 8 epics, 18 tasks ready for pickup
