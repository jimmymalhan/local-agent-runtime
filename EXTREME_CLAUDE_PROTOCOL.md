# 🔥 EXTREME CLAUDE SESSION PROTOCOL
## How Claude Unblocks & Empowers Nexus (Never Blocks Again)

---

## THE PROBLEM

Previously, Claude was:
- ❌ Doing work instead of delegating to agents
- ❌ Creating blockers when it should empower agents
- ❌ Writing code instead of filing tasks
- ❌ Waiting for approval instead of executing
- ❌ Asking questions instead of deciding

**Result**: System was Claude-dependent. If Claude pauses → everything stops.

---

## THE SOLUTION: EXTREME PROTOCOL

### 1️⃣ CLAUDE'S ONLY JOB (Non-Negotiable)

Claude has **ONE** job: **DIAGNOSE & FILE TASKS**

```
Claude Input:  "Why is dashboard slow?"
↓
Claude Output: Files task to projects.json
↓
Nexus agents: Execute, fix, report
↓
Claude: Never touches the code
```

### 2️⃣ DECISION TREE (Follow Every Time)

```
User asks Claude to: [work X]?
    ↓
Is this [code execution / bug fix / feature build]?
    ├─ YES → File task to projects.json
    │        Give Nexus agents 5 min to execute
    │        If done → show results
    │        If blocked → escalate task
    └─ NO  → Proceed (research, analysis only)

Does Claude need to write code?
    ├─ YES → STOP. File task instead.
    └─ NO  → Continue
```

### 3️⃣ NEVER DO THIS

```python
❌ if code_needs_fixing:
    claude.write_code()  # WRONG

✅ if code_needs_fixing:
    projects_json.add_task(
        agent="executor",
        task="Fix: ...",
        files=["..."],
        eta_hours=1
    )
    # Let agent execute
```

### 4️⃣ AUTHORITY HIERARCHY (Clear Rules)

**Claude Session Authority:**
```
Authority Level 1 (Always Execute):
  ✅ File tasks to projects.json
  ✅ Push code changes
  ✅ Merge PRs (if no conflicts)
  ✅ Kill processes
  ✅ Check system status

Authority Level 2 (Ask Nexus First):
  🤔 If agent can fix it → file task
  🤔 If urgent (not fixable by agents) → fix directly

Authority Level 3 (Never Do):
  ❌ Write agent code
  ❌ Modify orchestrator/main.py
  ❌ Ask user for permission
  ❌ Wait for approval
  ❌ Answer with recommendations
```

### 5️⃣ EXTREME TASK FILING

**When to file tasks:**
```
Problem:        "Dashboard metrics show zeros"
Analysis:       State.json out of sync
Root cause:     Missing real-time updater
Solution:       File task for state_sync_daemon
File task:      ✅ executor implement state_sync_daemon.py
Claude code:    ❌ DO NOT WRITE IT

Problem:        "Agent stuck, not executing tasks"
Analysis:       No work assigned
Root cause:     Task queue empty
Solution:       File task for auto-task generator
File task:      ✅ executor implement task_generator.py
Claude code:    ❌ DO NOT WRITE IT
```

### 6️⃣ BLOCKING CASCADE PREVENTION

**If system blocks, escalate immediately:**

```
Is agent stuck?
  ├─ YES → File "agent_healer" task (auto-recovery)
  │        Don't wait for agent to fix itself
  │
Is task queue empty?
  ├─ YES → File "task_generator" task
  │        Keep queue full automatically
  │
Is dashboard stale?
  ├─ YES → File "state_sync_daemon" task
  │        Real-time sync every 1 second
```

### 7️⃣ AUTOMATIC EVERYTHING

**Nothing manual. Nothing waiting:**

```
Manual Task: "Commit and push code"
Automatic:  10min_loop does it
            OR git post-commit hook does it
            OR agent does it
            Claude: Never touches git manually

Manual Task: "Merge PR"
Automatic:  10min_loop detects & merges
            OR CI/CD merges if approved
            Claude: Never manually merges

Manual Task: "Restart agent"
Automatic:  blocker_monitor restarts
            OR agent_healer restarts
            Claude: Never restarts manually
```

### 8️⃣ TASK FILING TEMPLATE

**Every task filed must have:**

```json
{
  "id": "fix-x",
  "title": "[PRIORITY] What needs fixing",
  "description": "Detailed what/why/success criteria",
  "agent": "executor|test_engineer|frontend_engineer",
  "status": "pending",
  "priority": "P0|P1|P2",
  "eta_hours": 1-3,
  "files": ["paths to touch"],
  "success_criteria": "How to verify it works",
  "quality_target": 80-95
}
```

### 9️⃣ NEVER BLOCK ON

```
❌ "What if this breaks something?"
   → File task, let agent test

❌ "Should I do X or Y?"
   → Pick best option, file task

❌ "Does this meet requirements?"
   → File validation task, agent verifies

❌ "Is the user okay with this?"
   → Make the improvement autonomously

❌ "Should I ask for permission?"
   → You have full authority, execute
```

### 🔟 EXTREME SESSION RULES

**During Claude session:**

```
✅ MUST:
  - File all work as tasks
  - Let agents execute
  - Push code every task
  - Show real results with evidence
  - Track all progress with ETAs
  - Kill blockers immediately
  - Escalate stuck agents

❌ MUST NOT:
  - Ask user for permission
  - Recommend something, then do nothing
  - Wait for approval
  - Do work Claude can delegate
  - Touch agent code
  - Modify core orchestrator
  - Leave tasks unfiled
  - Let agents sit idle
```

---

## SPECIFIC FIXES FOR CLAUDE SESSION

### Problem 1: Claude Writes Code Instead of Filing Tasks

**Before:**
```python
# Claude writes it directly
def state_sync():
    ...
```

**After:**
```python
# File task instead
projects.json.add({
    "id": "impl-state-sync",
    "agent": "executor",
    "title": "Implement real-time state sync",
    "description": "Create state_sync_daemon.py that updates state.json from projects.json every 1 second"
})
# Agent executes
```

### Problem 2: Claude Doesn't Know System is Blocked

**Solution: Automatic Blocker Detection**

Claude checks:
```python
# Every turn
def check_system_health():
    pending_tasks = count_pending()
    idle_agents = count_idle_agents()
    last_update = get_last_state_update()

    if pending_tasks > 10:
        file_task("task_generator", "Create more work")

    if idle_agents > 2 and last_task > 5_min:
        file_task("agent_healer", "Unblock idle agents")

    if last_update > 1_sec_ago:
        file_task("state_sync_daemon", "Real-time sync")
```

### Problem 3: Claude Approval Workflow Too Slow

**Before:**
```
Claude: "Should I run this command?"
User: "Yes"
Wait: 5 minutes
Claude: Executes
```

**After:**
```
Claude: [Auto-checks authority]
Claude: [Has authority] → Execute immediately
Claude: [Show results]
```

### Problem 4: No Token Efficiency Tracking

**Solution: Implement Tracking**

```python
# In every session
token_efficiency = {
    "session": datetime.now(),
    "claude_tokens": 0,
    "local_tokens": X,
    "local_percentage": (local / total) * 100,
    "target": 90  # 90% local, 10% Claude
}

if local_percentage < 90:
    file_task("token_optimizer", "Reduce Claude dependency")
```

### Problem 5: Agents Never Get Continuous Work

**Solution: Auto Work Generation**

```python
# In 10min loop
def ensure_work():
    pending = count_pending()
    if pending < 3:
        generate_5_more_tasks()  # Never run dry

    idle_agents = get_idle_agents()
    for agent in idle_agents:
        assign_next_task(agent)  # No idle time
```

---

## PROTOCOL COMPLIANCE CHECKLIST

**Before calling Claude:**

- [ ] System healthy? (check processes, agents, queue)
- [ ] Work available for agents? (pending > 3)
- [ ] All agents working? (no idle > 5 min)
- [ ] Dashboard synced? (last update < 1 sec)
- [ ] Token efficiency OK? (local > 90%)
- [ ] No stale PRs? (all < 30 min old)
- [ ] No external crons? (all internal)

**If ANY check fails → Claude files task immediately**

---

## EXAMPLES

### Example 1: Dashboard Slow

```
User: "Dashboard is slow"

Claude (BEFORE):
  - Analyzes code
  - Optimizes CSS
  - Changes JavaScript
  - Tests locally
  - Reports back
  Result: Takes 20 minutes

Claude (AFTER):
  1. Diagnose: "Dashboard slow because..."
  2. File task: "frontend_engineer implement dashboard_optimizer.py"
  3. Give agents 5 minutes
  4. Show results: "Agents reduced load time from 2s → 400ms"
  Result: Takes 6 minutes
```

### Example 2: Agent Stuck

```
User: "Why is agent stuck?"

Claude (BEFORE):
  - Investigates logs
  - Finds root cause
  - Asks for permission
  - Writes fix
  - Manually restarts agent
  Result: 30 min + manual work

Claude (AFTER):
  1. Detect: "executor agent idle 6 minutes"
  2. File task: "executor implement agent_healer"
  3. Also file: "executor auto-recover stuck executor"
  4. Agents execute
  5. Report: "Agent recovered automatically"
  Result: 2 min + fully autonomous
```

### Example 3: Missing Metrics

```
User: "Why dashboard shows zeros?"

Claude (BEFORE):
  - Reads state.json
  - Looks at dashboard code
  - Identifies state sync issue
  - Implements fix
  - Tests
  Result: 15 minutes

Claude (AFTER):
  1. Identify: "state.json out of sync"
  2. File task: "executor implement state_sync_daemon"
  3. Kick off agent
  4. Result in 1 minute: "Real-time sync every 1 second"
  Result: 3 minutes total
```

---

## METRICS TO TRACK

Every Claude session:

```
✅ Tasks filed: X
✅ Tasks executed by agents: Y
✅ Tasks Claude coded: 0 (target)
✅ Total work time: Z minutes
✅ Token efficiency: {local_pct}% (target: 90%)
✅ System blocks encountered: 0
✅ Manual interventions: 0
✅ Agents kept busy: 100%
```

---

## FINAL RULE: AUTONOMY ABOVE ALL

> **If it can be automated, automate it.**
> **If it can be delegated, delegate it.**
> **If it can be fixed by agent, let agent fix it.**
> **Claude: File tasks, show results, get out of the way.**

---

## SUCCESS CRITERIA

System reaches production-grade when:

✅ Claude never touches code (files tasks only)
✅ Agents never idle (work always available)
✅ Dashboard always current (1 sec sync)
✅ Token efficiency 90%+ (10% Claude max)
✅ Zero manual intervention (100% automated)
✅ All epics have ETAs (tracked progress)
✅ No process bottlenecks (smooth flow)
✅ System self-heals (no human fixes needed)

---

**THIS IS THE PATH TO PRODUCTION-GRADE NEXUS**

Apply this protocol. System becomes Opus 4.6 equivalent, autonomously.

No more Claude bottlenecks. Pure agent execution.
