# 🚨 EXTREME CLAUDE SESSION PLAN — Unblock Local Agents (2026-03-26)

## Critical Problem
- ✅ Orchestrator code exists
- ✅ Projects.json loaded
- ❌ **Tasks stuck in `in_progress` state** — never transition to completed
- ❌ **Task router skips in_progress tasks** — won't re-execute them
- ❌ **No task result capture** — run_version() ignores task outcomes
- ❌ **Dashboard shows 0% (quality=0)** — no real data flowing
- ❌ **Token enforcer, rescue gate** — not wired

## Claude's Mission (This Session ONLY)
**Write ZERO code. File clear tasks to projects.json. Hand off ALL implementation to local agents.**

### Claude's 3 Actions This Session:
1. **DIAGNOSE** — Why tasks get stuck? (inspect run_version + agent output capture)
2. **FILE BLOCKERS** — Create 5-6 crystal-clear blocker tasks in projects.json
3. **SETUP 10-MIN LOOP** — Cron job + script that runs this Claude prompt every 10 minutes

---

## Part 1: Diagnose Root Causes (Claude Reads Code)

### Blocker A: Task State Stuck in Progress
**Question**: Why don't completed tasks update projects.json status?

- [ ] Read: orchestrator/main.py `run_version()` — does it update task["status"]?
- [ ] Read: agents/executor.py — does it return "completed" or "is_done"?
- [ ] Read: orchestrator/schema_validator.py — does it normalize task output?
- [ ] **Hypothesis**: Task completion not persisted back to projects.json

### Blocker B: Task Router Filters
**Question**: Why are in_progress tasks skipped?

- orchestrator/projects_loader.py line 20ish: `if task["status"] == "in_progress": continue`
- **Fix needed**: Don't skip in_progress; instead check: has it been in_progress > 5 min? If yes, reset to pending.
- **OR**: Add retry mechanism for stuck tasks (timeout + re-execute)

### Blocker C: Agent Output Not Captured
**Question**: Where do agent results go?

- [ ] run_version() calls agents.run_task(task)
- [ ] Does it capture return value?
- [ ] Does it update task["status"] and task["quality"]?
- [ ] **Hypothesis**: Results discarded, state never updates

---

## Part 2: File Blocker Tasks to projects.json (Claude Creates Tasks)

**File 6 tasks (one per blocker) so local agents execute them:**

### Task 1: Orchestrator State Update Loop
**File to projects.json:**
```json
{
  "id": "task-fix-state-update",
  "title": "Fix: Orchestrator must persist task results to projects.json",
  "description": "After each agent completes a task, update projects.json with: status, quality_score, elapsed_time, result. Currently task results are lost. Test: run_version() completes a task, verify projects.json updated.",
  "agent": "orchestrator",
  "files": ["orchestrator/main.py", "projects.json"],
  "success_criteria": "At least 1 task transitions from pending→completed in projects.json after orchestrator runs",
  "priority": "P0",
  "eta_hours": 4
}
```

### Task 2: Task Router Unstuck Logic
**File to projects.json:**
```json
{
  "id": "task-fix-task-router",
  "title": "Fix: Task router should retry stuck in_progress tasks",
  "description": "Currently projects_loader.py skips in_progress tasks forever. They get stuck. Add: if task in_progress > 300s, reset to pending and re-execute. Test: Create stuck task, verify it retries after 5 min.",
  "agent": "orchestrator",
  "files": ["orchestrator/projects_loader.py", "tests/integration/test_task_retry.py"],
  "success_criteria": "Stuck task retried after timeout; new test passes",
  "priority": "P0",
  "eta_hours": 3
}
```

### Task 3: Quality Score Pipeline
**File to projects.json:**
```json
{
  "id": "task-fix-quality-scoring",
  "title": "Wire quality score capture: agent output → projects.json → dashboard",
  "description": "Agent returns quality=85, but dashboard shows 0. Pipeline broken. Trace flow: executor → main.py → projects_loader → state.json update. Add capture at each step. Test: executor returns quality=85, verify it appears in state.json.",
  "agent": "orchestrator",
  "files": ["orchestrator/main.py", "dashboard/state_writer.py", "tests/integration/test_quality_capture.py"],
  "success_criteria": "Dashboard state.json shows non-zero quality for completed tasks",
  "priority": "P1",
  "eta_hours": 5
}
```

### Task 4: Token Enforcer Module
**File to projects.json:**
```json
{
  "id": "task-wire-token-enforcer",
  "title": "Implement: Token budget enforcement (10% rescue, 200 tokens max)",
  "description": "Module exists but not wired. Wire it into: orchestrator/main.py before any rescue decision. Check: is_rescue_allowed(), deduct tokens on rescue, block if limit exceeded. Log all decisions to reports/token_decisions.jsonl.",
  "agent": "orchestrator",
  "files": ["orchestrator/token_enforcer.py", "orchestrator/main.py", "providers/router.py"],
  "success_criteria": "Rescue decisions logged, token budget tracked, hard limit enforced",
  "priority": "P1",
  "eta_hours": 6
}
```

### Task 5: Dashboard State Writer Schema
**File to projects.json:**
```json
{
  "id": "task-fix-dashboard-schema",
  "title": "Implement: Dashboard state writer with schema validation",
  "description": "state.json shows empty quality, model, recent_tasks fields. Writer needs to enforce schema on every write: no null values, defaults for missing fields, validated types. Test: write invalid state, verify schema correction.",
  "agent": "frontend_agent",
  "files": ["dashboard/state_writer.py", "dashboard/state.json", ".claude/skills/dashboard-state-writer.md"],
  "success_criteria": "state.json never has null/empty required fields; schema validation passes",
  "priority": "P1",
  "eta_hours": 4
}
```

### Task 6: System Health Check Baseline
**File to projects.json:**
```json
{
  "id": "task-system-health-baseline",
  "title": "Establish: System health baseline (all 5 checks pass)",
  "description": "Verify: orchestrator running, dashboard server alive, task router functional, agents responsive, watchdog active. Create reports/system_health.json with all 5 checks. Document expected values. Test: run each check independently.",
  "agent": "orchestrator",
  "files": ["orchestrator/health_check.py", "reports/system_health.json", "scripts/watchdog_daemon.py"],
  "success_criteria": "5/5 health checks pass; results logged to reports/system_health.json",
  "priority": "P0",
  "eta_hours": 2
}
```

---

## Part 3: Setup 10-Minute Automation Loop

### Step 1: Create `.claude/10min_loop.sh`
```bash
#!/bin/bash
# Runs every 10 minutes via cron
# Executes this Claude prompt → agent tasks → push + merge

cd /Users/jimmymalhan/Documents/local-agent-runtime

# 1. Run this prompt in Claude session (stdin from trig_...)
echo "🔄 [10min] Running Claude prompt..."
# Triggered via remote cron (trig_...)

# 2. Poll projects.json for completed tasks
echo "📊 [10min] Checking task status..."
python3 -c "
import json
with open('projects.json') as f:
    data = json.load(f)
    completed = sum(1 for p in data['projects'] for t in p.get('tasks', []) if t['status'] == 'completed')
    total = sum(1 for p in data['projects'] for t in p.get('tasks', []))
    print(f'Progress: {completed}/{total} tasks completed')
"

# 3. If tasks done, commit + push + create PR
git status --short | grep -v "^??" | wc -l | {
    read count
    if [ "$count" -gt 0 ]; then
        git checkout -b "auto/10min-$(date +%s)" 2>/dev/null || git checkout main
        git add -A
        git commit -m "chore: auto-update from 10-minute loop ($(date -u +%Y-%m-%dT%H:%M:%SZ))"
        git push -u origin $(git rev-parse --abbrev-ref HEAD) 2>/dev/null
        gh pr create --title "Auto: 10-min loop $(date +%H:%M)" --body "Auto-generated from loop" 2>/dev/null
    fi
}

echo "✅ [10min] Loop complete"
```

### Step 2: Wire to Cron / Remote Trigger
```bash
# Option A: Local cron (runs on machine)
*/10 * * * * cd /Users/jimmymalhan/Documents/local-agent-runtime && bash .claude/10min_loop.sh >> /tmp/10min_loop.log 2>&1

# Option B: Remote Claude trigger (already set up)
# trig_011sLANs2MtSJRissMX4T5r4 runs hourly
# Hook it to run THIS prompt every 10 min
```

---

## Part 4: Token Efficiency Restructure (Architecture)

### Current: 33K tokens/session → **Target: 2.7K tokens/session (91.9% reduction)**

**Restructure via:**

1. **CLAUDE_CORE (500 tokens)**
   - Only: CLAUDE.md, .claude/CLAUDE.md, MEMORY.md
   - Skip: Full rule files, examples, docs
   - Use: Links only ("see .claude/rules/backend.md for details")

2. **Output Contract (200 tokens)**
   - Always return: JSON structure, not prose
   - Format: `{ tasks: [...], priority_blocker: "...", eta_hours: N }`
   - Cuts: verbose explanations, preamble

3. **Task Registry API (300 tokens)**
   - Local: /task-registry endpoint
   - Returns: All tasks, filters (status, agent, priority)
   - Claude calls: GET /task-registry → JSON response
   - Skip: Reading projects.json directly (50 tokens/read)

4. **Event Bus (100 tokens)**
   - Local: /events endpoint
   - Returns: Last 10 events (task_completed, test_passed, blocker_found)
   - Claude: Poll for status, not interrogate files

5. **State Compressor (200 tokens)**
   - Local: /state endpoint
   - Returns: { progress: 3/7, next_task: "task-5", blockers: [...] }
   - Claude: Read summary, not full state.json

**Result**: Claude reads local APIs (100 tokens) instead of files (1000s tokens)

---

## Part 5: Extreme Suggestions for Unblocking

### Suggestion 1: Autonomous Task Dispatch (No Claude Needed)
**Setup**: Local watchdog continuously:
- ✅ Load projects.json every 30s
- ✅ For each pending task: dispatch to correct agent
- ✅ Capture agent result: status, quality, output
- ✅ Update projects.json (persist state)
- ✅ If task stuck > 5min: retry with different agent
- ✅ Push updates every 10 min (no Claude review)

**Benefit**: Tasks execute WITHOUT any Claude input.

### Suggestion 2: Self-Healing Stuck Tasks
**Setup**: Agent detects stuck task (in_progress > 5min) → Automatically:
1. Log failure reason
2. Try different approach (different agent, different parameters)
3. If 3 attempts fail: escalate to Claude (rescue)
4. If rescue: execute once, then auto-retry improved version

**Benefit**: 99% of failures self-resolve; Claude only on unrecoverable issues (1% budget).

### Suggestion 3: Distributed Agent Pool
**Setup**: Instead of one orchestrator, 5 parallel task workers:
- Worker 1: Handles pending tasks from projects.json
- Worker 2: Monitors in_progress (timeout → retry)
- Worker 3: Captures quality scores → state.json
- Worker 4: Health check + watchdog
- Worker 5: Push + merge PRs

**Benefit**: No bottleneck; parallel execution; faster feedback.

### Suggestion 4: Zero-Claude Mode
**For 90% of tasks**: Local agents execute, no Claude involvement
- Read: projects.json
- Execute: agent.run_task(task)
- Update: projects.json + state.json
- Push: every 10 min
- Merge: if tests pass

**Claude only on**:
- Rescue (task blocked 3× with different approaches)
- Prompt upgrade (apply findings from agents)

---

## Part 6: ETA Tracking for All Epics

### EPIC 1: System Reliability (6 hours, complete by 2026-03-27 00:35)
- ✅ Task 1: System health check (2h, P0)
- ⏳ Task 2: Fix state update loop (4h, P0)
- 📋 Dependencies: Task 2 → Task 1
- **ETA**: 2026-03-27 00:35

### EPIC 2: Dashboard Quality (12 hours, complete by 2026-03-27 06:35)
- ⏳ Task 3: Fix quality score pipeline (5h, P1)
- ⏳ Task 5: Dashboard schema validation (4h, P1)
- ⏳ Task 1 (from Epic 1): blocker
- **ETA**: 2026-03-27 06:35

### EPIC 3: Policy Enforcement (18 hours, complete by 2026-03-27 12:35)
- ⏳ Task 4: Wire token enforcer (6h, P1)
- 📋 Depends on: Token enforcer module exists
- **ETA**: 2026-03-27 12:35

### EPIC 4: Multi-Loop Execution (30 hours, complete by 2026-03-28 00:35)
- 📋 Depends on: Epics 1-3 (system stable, quality flowing, policy enforced)
- 📋 Work: DAG + parallel + self-improve loop
- **ETA**: 2026-03-28 00:35

### EPIC 5: Agent Autonomy (36 hours, complete by 2026-03-28 06:35)
- 📋 Depends on: Epics 1-4
- 📋 Work: Full autonomous execution with zero Claude input
- **ETA**: 2026-03-28 06:35

### 🎯 MASTER ETA: All Epics Complete
**Target**: 2026-03-28 18:35 (66 hours from now)

---

## Part 7: Automation Plan (Never Happens Again)

### Pre-Execution Checks
```bash
# Before every 10-minute loop:
1. Check: orchestrator running?
2. Check: dashboard server alive?
3. Check: projects.json valid JSON?
4. Check: Git repo clean (no stray uncommitted files)?
```

### Task Dispatch (Automatic)
```bash
# Every 10 minutes:
1. Load projects.json
2. For each pending task: route to correct agent
3. Capture result: status, quality, output
4. Update projects.json
5. If any task completed: push + create PR
6. Log cycle to reports/10min_loop_{timestamp}.log
```

### Quality Assurance (Automatic)
```bash
# After each task:
1. Schema validation: output matches expected shape
2. Status check: did task transition to completed?
3. Quality score: is it in 0-100 range?
4. Artifact check: did it create expected files?
```

### Escalation (Rare)
```bash
# Only if task fails 3× with different approaches:
1. Log to rescue_queue.json
2. Trigger Claude (once per cycle)
3. Claude upgrades agent prompt (200 tokens max)
4. Local agent retries with improved prompt
```

---

## Summary: What Claude Does This Session

1. ✅ **Diagnose** (read code, 5-10 min)
2. ✅ **File 6 Blocker Tasks** (update projects.json, 5 min)
3. ✅ **Setup 10-Min Loop** (cron + script, 10 min)
4. ✅ **Provide ETAs** (all epics, 5 min)
5. ❌ **DO NOT EDIT** orchestrator/*.py, agents/*.py, etc.

**Total Claude Time**: ~30 min per 10-minute cycle

**Then**: Local agents execute tasks autonomously. Claude re-runs at +10, +20, +30 min only to:
- ✅ Check task status
- ✅ File new blockers if discovered
- ✅ Upgrade prompts on rescue (rare)

---

## How to Run This Plan

```bash
# 1. Claude diagnoses & files tasks (this session)
# 2. Orchestrator picks up tasks from projects.json
# 3. Agents execute in parallel
# 4. Every 10 min: Claude runs again to check status + file new blockers
# 5. Local agents push + merge PRs automatically

# Start: bash .claude/10min_loop.sh
# Then: Watch reports/10min_loop_*.log for progress
```

---

**Status**: 🚨 Blocked → Tasks in projects.json → 🚀 Autonomous execution within 30 min
