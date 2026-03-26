# Local Agent Handoff — 5 Critical Tasks

**Date**: 2026-03-26
**Status**: All PRs closed, main branch clean, ready for local agent execution
**Authority**: Full autonomy — local agents execute without Claude intervention

---

## System State

- ✅ **Main branch**: Clean, refactor committed (flatten local-agents/ → root)
- ✅ **Open PRs**: 0 (all closed and merged into main)
- ✅ **Open Issues**: 0
- ✅ **Feature branches**: All deleted (35 branches removed)
- ⚠️ **Orchestrator**: Verify running, may be idle
- ⚠️ **Dashboard**: May have stale/missing state fields
- ⚠️ **Policy enforcement**: NOT wired yet (no budget checks)
- ⚠️ **Multi-loop**: Single-pass only (DAG/parallel not active)

---

## 5 Tasks for Local Agents

### Task #1: System Health Check
**Owner**: Orchestrator Agent
**Files**: `orchestrator/main.py`, `dashboard/state.json`, `scripts/watchdog_daemon.py`

**What to do**:
1. Verify orchestrator/main.py is running: `ps aux | grep orchestrator`
2. Check dashboard server: `curl -s http://localhost:3000 | head -20`
3. Read dashboard/state.json — verify all fields present (quality, model, recent_tasks, etc.)
4. Check watchdog PID file: `cat .watchdog.pid` (should exist and be running)
5. Verify cron jobs: `crontab -l | grep -E "auto_merge|agent_loop"`

**Success**: All 5 checks pass, write results to `reports/system_health.json`

---

### Task #2: Dashboard State Schema Fix
**Owner**: Frontend Agent
**Files**: `dashboard/state_writer.py`, `dashboard/state.json`, `.claude/skills/dashboard-state-writer.md`

**What to do**:
1. Read current `dashboard/state.json` — identify missing fields
2. Update `dashboard/state_writer.py`:
   - Add `_enforce_schema()` function
   - Define required fields: quality (default 0), model (default 'local'), recent_tasks (default []), changelog (default []), research_feed (default [])
   - Call `_enforce_schema()` on every write (before returning JSON)
   - Type-check numeric fields, reset invalid values to defaults
3. Test: Call state_writer with missing fields, verify defaults are added
4. Integrate: Update all places that write to state.json to use state_writer

**Success**: `dashboard/state.json` always has all 5+ required fields on write, no nulls/empties

**Related tasks queued**: t-ce5ff84a, t-2a5d4c2f, t-3b8c9d1e, t-4d9e0f2g, t-5e0f1g2h, t-545cf9fe

---

### Task #3: Policy Enforcement (Budget + Model Routing)
**Owner**: Orchestrator Agent
**Files**: `orchestrator/token_enforcer.py`, `orchestrator/rescue_enforcer.py`, `providers/router.py`, `orchestrator/main.py`

**What to do**:
1. Create `orchestrator/token_enforcer.py`:
   - Track tokens used per session
   - Enforce 10% budget cap (200 tokens max per session)
   - Log usage to `reports/token_usage.jsonl`

2. Create `orchestrator/rescue_enforcer.py`:
   - Check if rescue_needed and budget < 10%
   - If true: block rescue, log reason
   - Return error to calling agent

3. Update `providers/router.py`:
   - Add model_selection() function
   - Rule: 90% local agents, 10% Claude (rescue only)
   - Read budget before deciding local vs Claude
   - If budget exhausted: force local-only mode

4. Wire into `orchestrator/main.py`:
   - Before dispatching task: call `token_enforcer.check_budget()`
   - Before using Claude: call `rescue_enforcer.can_use_rescue()`
   - On task complete: call `token_enforcer.record_usage(tokens_used)`

**Success**: Orchestrator enforces budget, logs all decisions to `reports/policy_enforcement.jsonl`

---

### Task #4: Multi-Loop Optimization (DAG + Parallel + Self-Improve)
**Owner**: Orchestrator Agent
**Files**: `orchestrator/continuous_loop.py`, `orchestrator/dag.py`, `orchestrator/parallel_executor.py`, `agents/self_improver.py`

**What to do**:
1. Update `orchestrator/continuous_loop.py`:
   - Load DAG at startup: `dag = DAG(load_from_projects.json)`
   - In main loop: get task batch via `dag.get_parallel_batch()`
   - If batch size > 1: dispatch via `parallel_executor.run_parallel_tasks(batch)`
   - If batch size = 1: dispatch single task
   - Every 50 task completions: call `self_improver.run()` to analyze patterns
   - Persist learnings to `orchestrator/semantic_memory.json`
   - Loop back (don't exit after 1 batch)

2. Verify `orchestrator/dag.py` exists and has:
   - `get_parallel_batch()` — returns tasks with no dependencies
   - `mark_done(task_id)` — updates DAG after completion
   - `get_next_sequential()` — gets dependent tasks

3. Verify `orchestrator/parallel_executor.py` exists and has:
   - `run_parallel_tasks(batch)` — spawns threads for each task
   - Returns list of results with task_id + status + metrics

4. Verify `agents/self_improver.py` exists and has:
   - `run()` — analyzes last 50 task outcomes
   - `extract_patterns()` — identifies success/failure causes
   - `upgrade_prompts()` — auto-updates skill prompts in `.claude/skills/`

**Success**:
- Orchestrator runs multi-pass loops (2-3 passes per session)
- Parallel tasks execute simultaneously
- Self-improvement activates every 50 completions
- Success rate improves (measure via quality scores in state.json)

---

### Task #5: Local Agent Handoff Setup
**Owner**: Orchestrator Agent
**Files**: `agents/__init__.py`, `projects.json`, `HANDOFF.md` (this file)

**What to do**:
1. Verify `agents/__init__.py` has router() function that:
   - Reads projects.json
   - Maps tasks to agents by category (dashboard → frontend_agent, orchestrator → executor, etc.)
   - Dispatches via `agent.run(task)`
   - Updates task status in ProjectManager

2. Verify `projects.json` has all 5 tasks:
   ```json
   {
     "tasks": [
       {"id": "task-1", "title": "System health check", "agent": "orchestrator", "status": "pending"},
       {"id": "task-2", "title": "Dashboard state fix", "agent": "frontend_agent", "status": "pending"},
       {"id": "task-3", "title": "Policy enforcement", "agent": "orchestrator", "status": "pending"},
       {"id": "task-4", "title": "Multi-loop optimization", "agent": "orchestrator", "status": "pending"},
       {"id": "task-5", "title": "Handoff setup", "agent": "orchestrator", "status": "pending"}
     ]
   }
   ```

3. Start orchestrator:
   ```bash
   python3 orchestrator/main.py --auto 5
   ```
   This will pick up all 5 tasks and execute them in order.

4. Monitor progress:
   - Check `dashboard/state.json` for `active_agent` and `quality_score`
   - Check `reports/` for execution logs
   - Check `state/agent_stats.json` for completion rates

**Success**: All 5 tasks complete, agents work autonomously, no manual intervention needed

---

## Emergency Contacts

- **Orchestrator stuck?** → Run `bash scripts/watchdog_daemon.py` to restart
- **Dashboard broken?** → Check `reports/system_health.json` for errors
- **Out of budget?** → Check `reports/token_usage.jsonl`, wait for next session reset
- **Need human?** → Check `.claude/CLAUDE.md` for Claude rescue path (10% budget only)

---

## Success Criteria (All Tasks)

✅ All 5 tasks complete and passing
✅ `dashboard/state.json` has all required fields
✅ `reports/system_health.json` shows all checks passing
✅ `reports/policy_enforcement.jsonl` shows budget enforcement active
✅ `reports/agent_stats.json` shows multi-loop execution (2-3 passes per session)
✅ Orchestrator runs 24/7 without manual intervention

---

## EPIC 2: FIRST_PAYING_CUSTOMER_REVENUE_TRACK

**Status**: Created 2026-03-26, ready for local agent pickup.

**Separation Rule**: Revenue-track work is separate from Infra Epic #1 (5 tasks above). Both tracks run in parallel. No mixing. No deletion of infra work.

**Revenue-Track Tasks** (9 total):
1. **EXISTING_ASSET_AUDIT** — Audit CLI, dashboard, demo, QA, GTM for reuse. Mark reuse/improve/ignore.
2. **DEMO_HAPPY_PATH** — Define exact 3-minute demo flow, commands, outputs, proof points.
3. **CLI_MVP** — Verify nexus install/run/output works. Update README.
4. **DASHBOARD_TRUTH** — Verify live state, tasks, proof, CTA, readiness score visible.
5. **DEMO_PROOF** — Capture before/after, sample repo, screenshots, value explanation.
6. **PAID_PILOT_OFFER** — Create offer copy, scope, pricing, CTA, objection handling.
7. **GTM_ASSETS** — Create Reddit post, landing copy, demo script, outreach, FAQ, founder + technical posts.
8. **INTERACTIVE_QA_10X** — Run 10 user journeys (install→demo→dashboard→task→proof→CTA). All 10 must pass.
9. **CONVERSION_READINESS** — Define ICP, pain, value metric, trial path, call-to-action, first call prep.

**Reused Assets** (high ROI):
- `.claude/skills/qa-validation.md` → Interactive QA 10x
- `.claude/skills/generate-marketing-plan.md` → GTM assets
- `.claude/skills/sales-outreach.md` → Paid pilot offer
- `nexus` CLI → Demo flow (existing)
- `dashboard/` → Revenue-track dashboard sections
- `examples/` → Demo artifacts (reuse)

**New Files Created**:
- `projects.json` — Added FIRST_PAYING_CUSTOMER_REVENUE_TRACK epic with 9 tasks
- All output goes to `reports/` with revenue-track prefixes (revenue_asset_audit.json, demo_happy_path.json, etc.)

**Dashboard Sections** (must be visible):
- Demo readiness score
- Paying customer readiness score
- Revenue-track task board (Backlog / Running / Done / Blocked)
- Proof artifacts list
- QA pass count (0-10)
- GTM asset status
- Paid pilot offer status
- Next highest ROI task

---

## Next Steps for Local Agents

### Infra Epic #1 (5 tasks in original projects.json):
1. System health check → orchestrator agent
2. Dashboard state fix → frontend_agent
3. Policy enforcement → orchestrator agent
4. Multi-loop optimization → orchestrator agent
5. Handoff setup → orchestrator agent

**Start**: `python3 orchestrator/main.py --auto 5`

### Revenue Epic #2 (9 tasks, new):
1. Asset audit → architect agent
2. Demo flow → architect agent
3. CLI MVP → executor agent
4. Dashboard truth → frontend_agent
5. Demo proof → executor agent
6. Paid pilot offer → writer agent
7. GTM assets → writer agent
8. Interactive QA 10x → qa_agent
9. Conversion readiness → architect agent

**Start**: `python3 orchestrator/main.py --auto 9 --track revenue`

---

## Critical Rules for Local Agents

1. **Do not mix tracks**: Infra work stays separate from revenue work.
2. **Do not delete infra**: The 5 original tasks are in progress. Keep them running.
3. **Do reuse existing assets**: Skills, CLI, dashboard, examples are reusable. Build on them.
4. **Do report on dashboard**: Every task update → dashboard/state.json before assignment.
5. **Do write proof back**: Test results, asset audit findings, demo proof → `reports/` directory.
6. **Interactive QA is mandatory**: Revenue-track demo is NOT ready until QA passes 10 times in a row.
7. **Do NOT wait for Claude**: Full autonomy. Commit, push, PR, merge. Update HANDOFF.md as you go.

---

## Blocker Escalation

If a task is blocked:
1. Log blocker to `reports/blocker.json` with reason
2. Update task status to `blocked_by_<blocker_id>`
3. File a sub-task to resolve blocker
4. Do NOT wait for Claude approval — agents have full authority

Example blocker: "Dashboard state.json missing revenue-track sections" → File task "Add revenue-track dashboard sections" to frontend_agent

---

## Success Criteria for Both Epics

**Infra Epic #1** (5 tasks):
✅ All 5 tasks complete and passing
✅ `dashboard/state.json` has all required fields
✅ `reports/system_health.json` shows all checks passing
✅ `reports/policy_enforcement.jsonl` shows budget enforcement active
✅ `reports/agent_stats.json` shows multi-loop execution (2-3 passes/session)
✅ Orchestrator runs 24/7 without manual intervention

**Revenue Epic #2** (9 tasks):
✅ All 9 tasks complete
✅ Asset audit shows reuse/improve/ignore flags
✅ Demo runs in < 3 minutes end-to-end
✅ Dashboard shows revenue-track readiness score
✅ Interactive QA passes 10 times in a row
✅ Paid pilot offer is customer-ready
✅ GTM assets are sharable (Reddit, landing, outreach)
✅ Conversion readiness plan is defined
✅ First paying customer path is clear

---

---

## EPIC BOARD — Live Dashboard (2026-03-26)

**Location**: `http://localhost:3001` → Epic Board tab (📊)

**What You See**:
- **Epic 1 (Infra)**: 5 projects, 5 tasks, 1 agent each (orchestrator, frontend_agent)
- **Epic 2 (Revenue)**: 1 project, 9 tasks, 5 agents (architect, executor, frontend_agent, writer, qa_agent)
- **System Status**: Orchestrator running · Task intake continuous · 24/7 enabled
- **Blockers & Improvements**: Live feed from reports/epic_board_report.json

**Board Updates**:
- Epic board refreshes every 5 seconds via WebSocket
- Task counts update as agents change status
- Agent assignments visible per epic
- Progress percentage per epic (0% until first task done)

**Reports Generated**:
- `reports/epic_board_report.json` — Full board state with readiness %
- `reports/revenue_asset_audit.json` — Created by architect (task revenue-audit-1)
- `reports/demo_happy_path.json` — Created by architect (task revenue-demo-2)
- CLI, Dashboard, GTM, QA reports — Created by assigned agents

---

## Execution Order for Fastest Time to First Customer

**Phase 1 — Infra Unblock (Days 1-2)**
1. System health check (orchestrator) → reports/system_health.json
2. Dashboard state fix (frontend_agent) → epic_board shows all fields
3. Policy enforcement (orchestrator) → budget tracking visible
4. Multi-loop optimization (orchestrator) → parallel task execution ready
5. Handoff setup (orchestrator) → router picks up tasks from projects.json

**Phase 2 — Revenue Track Parallel (Days 2-5)**
While Infra #1-5 run:
1. Asset audit (architect) → finds CLI, dashboard, QA, GTM reuse
2. Demo flow (architect) → defines exact 3-minute path
3. CLI MVP verify (executor) → confirms nexus run command works
4. Dashboard truth (frontend_agent) → revenue sections visible
5. Demo proof (executor) → captures before/after + value statement

**Phase 3 — GTM & QA (Days 5-7)**
1. Paid pilot offer (writer) → scope, pricing, CTA ready
2. GTM assets (writer) → Reddit, landing, outreach, FAQ ready
3. Interactive QA 10x (qa_agent) → Must pass 10 times before demo ready
4. Conversion readiness (architect) → ICP, pain, value metric, call prep

**Phase 4 — First Customer (Day 8+)**
- Demo passes QA 10x
- GTM assets sharable
- Paid pilot offer ready
- Cold outreach begins (Reddit, Slack, email)

---

**Local agents: Execute both epics in parallel. Infra keeps running. Revenue track ramps up. You have full authority. Report progress via dashboard/state.json + reports/. Good luck! 🚀**
