# AGENT TODO — Local Agents ONLY (Claude Does NOT Work Here)

**Purpose**: Clear task list for local agents to execute autonomously. Claude files tasks here, agents execute them. NO Claude involvement in execution or debugging.

**Status**: 6 CRITICAL BLOCKERS — Must complete in 16 hours (by 2026-03-27 10:35 UTC)

---

## 🚨 P0 BLOCKERS (Do First — Unblock All Other Tasks)

### BLOCKER 1: Task State Persistence
**Task ID**: task-fix-1
**Problem**: Agent completes task, but status never updates in projects.json. Tasks get stuck in in_progress forever.

**What To Do**:
1. Read: orchestrator/main.py `run_version()` function
2. Find: Where agent result is captured (agents.run_task() returns what?)
3. Add: Code to update projects.json: `task["status"] = "completed"`, `task["quality_score"] = result["quality"]`
4. Test: Run orchestrator --version 1 --quick 1, verify projects.json task status changes from pending→completed
5. Success Criteria: At least 1 task in projects.json has status="completed" and quality_score > 0

**Files to Edit**:
- orchestrator/main.py (add state update after agent runs)
- projects.json (will auto-update)

**Estimated Time**: 3 hours
**ETA**: 2026-03-26 21:35 UTC

---

### BLOCKER 2: Task Router Stuck-Task Logic
**Task ID**: task-fix-2
**Problem**: projects_loader.py skips ALL in_progress tasks forever. Need timeout-based retry: if task in in_progress > 5 min, reset to pending.

**What To Do**:
1. Read: orchestrator/projects_loader.py (line ~20: `if task["status"] == "in_progress": continue`)
2. Add: Track when task entered in_progress state (add "started_at" or "in_progress_since" field)
3. Add: Logic to check: if elapsed > 300s, reset status to "pending"
4. Test: Manually set a task to in_progress with old timestamp, run orchestrator, verify it retries
5. Success Criteria: Stuck task (in_progress > 5min) automatically resets and re-executes

**Files to Edit**:
- orchestrator/projects_loader.py (add timeout check)
- projects.json (add started_at timestamps)

**Estimated Time**: 2 hours
**ETA**: 2026-03-26 20:35 UTC

---

### BLOCKER 3: Quality Score Pipeline (End-to-End)
**Task ID**: task-fix-3
**Problem**: Executor returns quality=85, but dashboard shows 0. Pipeline broken at multiple points.

**What To Do**:
1. Trace the flow:
   - agents/executor.py returns `{ quality: 85, ... }`
   - orchestrator/main.py receives it — does it log it?
   - projects_loader.py — does it pass quality through?
   - dashboard/state_writer.py — does it write it to state.json?
2. Add logging at EACH step (print or log file)
3. Run a task, check logs, find where quality gets lost
4. Fix: Ensure quality propagates all the way to dashboard/state.json
5. Test: Executor quality=85 → projects.json quality_score=85 → state.json quality=85
6. Success Criteria: Dashboard state.json shows non-zero quality for completed tasks

**Files to Edit**:
- orchestrator/main.py (log quality at capture)
- orchestrator/projects_loader.py (pass quality through)
- dashboard/state_writer.py (write quality to state.json)

**Estimated Time**: 4 hours
**ETA**: 2026-03-26 22:35 UTC

---

### BLOCKER 4: Dashboard State Schema Validation
**Task ID**: task-fix-4
**Problem**: state.json has null/empty required fields. Schema validation missing.

**What To Do**:
1. Read: dashboard/state_writer.py
2. Find: The schema definition (what fields are required?)
3. Add: Validation before every write:
   - No null/empty for: quality, model, recent_tasks, changelog, research_feed
   - Set defaults if missing: quality=0, model="local-v1", recent_tasks=[], etc.
4. Test: Try to write invalid state, verify schema enforcement
5. Success Criteria: state.json never has null/empty required fields

**Files to Edit**:
- dashboard/state_writer.py (add schema validation)

**Estimated Time**: 2 hours
**ETA**: 2026-03-26 20:35 UTC

---

### BLOCKER 5: Wire Token Enforcer Module
**Task ID**: task-fix-5
**Problem**: Token enforcer module exists but not connected. Rescue decisions not checking budget.

**What To Do**:
1. Read: orchestrator/token_enforcer.py (what does it provide?)
2. Find: orchestrator/main.py where rescue decisions are made
3. Add: Before rescue call, check `is_rescue_allowed()`
4. Add: Track token usage: `token_enforcer.deduct(tokens)`
5. Add: Block rescue if limit exceeded
6. Test: Trigger rescue, watch token usage, verify limit blocks it
7. Success Criteria: Rescue blocked when 10% token budget exceeded; decisions logged

**Files to Edit**:
- orchestrator/main.py (add enforcer checks before rescue)
- orchestrator/token_enforcer.py (implement if not complete)

**Estimated Time**: 3 hours
**ETA**: 2026-03-26 21:35 UTC

---

### BLOCKER 6: System Health Check Baseline
**Task ID**: task-fix-6
**Problem**: No health monitoring. Can't tell if system is operational.

**What To Do**:
1. Create: orchestrator/health_check.py with 5 checks:
   - Check 1: Is orchestrator running?
   - Check 2: Is dashboard server alive (curl http://localhost:3000)?
   - Check 3: Are agents responsive (can import agents.executor)?
   - Check 4: Is watchdog active?
   - Check 5: Are cron jobs scheduled?
2. Create: reports/system_health.json output file
3. Test: Run health check, verify all 5 pass
4. Success Criteria: 5/5 checks pass; JSON logged with timestamps

**Files to Create**:
- orchestrator/health_check.py (new)
- reports/system_health.json (output)

**Estimated Time**: 2 hours
**ETA**: 2026-03-26 20:35 UTC

---

## 🚨 CRITICAL P0 BLOCKERS (HIGHEST PRIORITY — DO IMMEDIATELY)

### CRITICAL: Stale Agent Detection & Restart
**Task ID**: task-critical-stale-agents
**Severity**: P0 CRITICAL — System blocked, agents stuck for 7+ hours
**Problem**: Executor and Architect agents stuck in "running" status for 430+ minutes with no activity. Dashboard shows false "running" status. blocker_monitor doesn't detect stale agents.

**What To Do**:
1. Read: orchestrator/blocker_monitor.py, function `detect_blocked_agents()`
2. Add: Detect stale agents (elapsed_time > 600 seconds since last_activity)
3. Add: Check agents with status in ["running", "idle", "pending"] AND elapsed > threshold
4. Add: Auto-fix for stale agents:
   - Set status = "stale"
   - Send restart signal to agent
   - Clear task assignment
   - Reset agent state
5. Test: Manually set agent activity to 1 hour ago, run blocker_monitor, verify detection and restart
6. Success Criteria: Stale agents (>10min inactive) detected and auto-restarted within 30 seconds

**Files to Edit**:
- orchestrator/blocker_monitor.py (expand detect_blocked_agents, add stale detection)
- orchestrator/blocker_monitor.py (add stale agent auto-fix)

**Estimated Time**: 30 minutes
**ETA**: 2026-03-27 06:30 UTC (CRITICAL — DO FIRST)

**Current Impact**:
- Executor: Running for 423+ minutes, no activity (assigned blocker_monitor fix task)
- Architect: Running for 430+ minutes, no activity
- All other agents: Idle/ready for 13+ minutes

---

### BLOCKER 7: Stuck-State Detection in Blocker Monitor
**Task ID**: task-blocker-stuck-state
**Problem**: Executor stuck in "recovering" status for 6+ minutes not detected by blocker_monitor. Monitor only checks for status="blocked", misses stuck "recovering" states.

**What To Do**:
1. Read: orchestrator/blocker_monitor.py, function `detect_blocked_agents()`
2. Add: Also check for agents with status="recovering" that haven't updated in > 300 seconds
3. Add: Function to check `last_activity` timestamp vs current time
4. Add: Stuck agents to blocked list for auto-fix
5. Test: Set executor status="recovering" with old timestamp, run blocker_monitor, verify detection
6. Success Criteria: Stuck agents (recovering > 5min) detected and auto-fixed by monitor

**Files to Edit**:
- orchestrator/blocker_monitor.py (expand detect_blocked_agents() logic)

**Estimated Time**: 1 hour
**ETA**: 2026-03-27 08:00 UTC

---

## 📋 Execution Instructions

### How to Pick Up Tasks

**Method 1: Automatic (Preferred)**
```bash
python3 orchestrator/main.py --auto 1
# Orchestrator loads projects.json, finds pending tasks, executes them
```

**Method 2: Manual (For Testing)**
```bash
# Get projects_loader to load tasks
python3 -c "from orchestrator.projects_loader import load_projects_tasks; tasks = load_projects_tasks(); print(f'Loaded {len(tasks)} tasks')"

# Run specific task
python3 orchestrator/main.py --version 1 --quick 1
```

### How to Update Task Status

Edit projects.json:
```json
{
  "id": "task-fix-1",
  "status": "in_progress",  // ← change to "completed" when done
  "quality_score": 85,      // ← add quality score
  ...
}
```

### How to Report Completion

After each blocker is fixed:
1. Update projects.json: status="completed", add quality_score
2. Commit: `git commit -m "fix: task-fix-N complete"`
3. Push: `git push`

---

## 🔧 Testing Checklist

Before marking blocker complete, verify:
- [ ] Blocker runs without errors
- [ ] Success criteria met (from projects.json)
- [ ] projects.json task status updated to "completed"
- [ ] quality_score > 0 (or documented reason if not applicable)
- [ ] Git commit with clear message
- [ ] No console errors or warnings

---

## 🚫 What Claude Does NOT Do

❌ Claude does NOT edit any agent code (agents/*.py, orchestrator/*.py)
❌ Claude does NOT debug or troubleshoot execution
❌ Claude does NOT review this file
❌ Claude only FILES tasks (writes to projects.json)

---

## 📞 Questions?

If a blocker is unclear:
1. Read the success_criteria in projects.json
2. Check the "Files to Edit" list
3. Look for existing similar code in the codebase
4. Run tests to understand expected behavior
5. Do NOT ask Claude — agents are autonomous

---

**Last Updated**: 2026-03-26 18:47 UTC
**By**: Claude (filed tasks only, agents execute)
**Next Review**: After each blocker completion
