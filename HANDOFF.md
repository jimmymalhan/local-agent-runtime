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

## Next Steps for Claude

1. Wait 30 minutes for local agents to pick up tasks
2. Check dashboard at localhost:3000
3. Review `reports/` directory for results
4. If any task blocks: check logs, update HANDOFF.md with notes for agents
5. Do NOT edit runtime code — only local agents touch orchestrator/

---

**Local agents: Execute tasks in order. You have full authority. Report progress via dashboard/state.json + reports/. Good luck! 🚀**
