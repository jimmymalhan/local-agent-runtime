# AUTONOMY.md — The Handoff Contract

## What This Is

This document defines the moment when the local agent system becomes fully autonomous. After the 5-step unblock plan is complete, **Claude exits** and **local agents take full control**.

No external dependency. No Claude rescue. No human intervention required (except security/infrastructure).

## System Ownership Matrix

| Component | Owner | Triggers Manual Review |
|-----------|-------|------------------------|
| **Code changes** | Local agents | Security vulnerability, breaking API change |
| **Task execution** | Local agents | None (self-healing on failure) |
| **Failure recovery** | Local agents (self_heal.py) | Blocked task has 3+ strategies exhausted |
| **State management** | Local agents (state_writer) | State is invalid (schema violation) |
| **Prompt updates** | Local agents (after benchmarking) | Performance degrades >10% vs baseline |
| **Infrastructure** | Human | New dependency, credential rotation, scaling |
| **Security** | Human | API key compromise, access violation, audit finding |

## What Local Agents Own

### ✅ Full Authority

Local agents have complete authority to:

1. **Write code**
   - Create files, modify existing code
   - Commit and push to feature branches
   - Create PRs, request review, merge (after consensus)
   - No permission needed, no Claude approval required

2. **Execute tasks**
   - Read from projects.json, AGENT_TODO.md
   - Claim tasks, execute, mark done
   - Spawn sub-agents for parallelization
   - Skip tasks if blocked (mark [BLOCKED] in state)

3. **Manage state**
   - Update state.json with current progress
   - Write to state/failures.json when tasks fail
   - Maintain dashboard state with real-time updates
   - Clean up stale state/old checkpoints

4. **Self-improve**
   - Run benchmarks on their own output
   - Compare results to baseline
   - Update their own prompts in .claude/skills/
   - Store quality scores and lessons learned

5. **Coordinate**
   - Read/write agent-coordination.json for file locks
   - Spawn parallel agents for independent tasks
   - Use shared memory patterns (memory/*.md)
   - Escalate to higher-level agents if blocked

### ❌ What Agents Cannot Do

Local agents **cannot** and **should not**:

- ❌ Call Claude or external APIs for task execution
- ❌ Modify CLAUDE.md or .claude/CLAUDE.md (these are read-only contracts)
- ❌ Delete security credentials or infrastructure files
- ❌ Push directly to main (all changes via PR)
- ❌ Force-push or destructively modify git history
- ❌ Ignore error messages — log and skip instead

## What Claude Owns

### ✅ When Invoked by Local Agents

Claude is invoked **only** in these cases:

1. **New skill template generation** (once per new capability)
   - Local agent identifies new task type that has no skill
   - Files request to .claude/skills/new_skill_request.md
   - Claude generates prompt template
   - Local agent uses template for future tasks of that type

2. **Prompt version upgrade** (after benchmarking)
   - Local agent runs benchmark, scores drop >10% vs baseline
   - Writes failing examples to state/prompt_upgrade_request.json
   - Claude generates improved prompt version
   - Local agent adopts new prompt

3. **Validation of critical changes** (optional, not forced)
   - Local agent can request review for high-stakes decisions
   - Claude provides feedback (informational only)
   - Agent makes final decision

### ❌ What Claude NEVER Does

Claude **never**:
- ❌ Executes tasks (agents do this)
- ❌ Fixes bugs in agent runtime code
- ❌ Runs the event loop or orchestrator
- ❌ Makes decisions (agents own all decisions)
- ❌ Escalates for rescue (local failure handling only)

## The Failure Loop (Local Recovery)

When a task fails:

```
Attempt 1 → Success? Done.
         → Fail? Log to failures.json, try again with backoff

Attempt 2 → Success? Done.
         → Fail? Log to failures.json, try different strategy

Attempt 3 → Success? Done.
         → Fail? Mark [BLOCKED], move to next task

Next Hour (self_heal.py) → Retry with 3 more strategies
                        → If all exhausted, mark for manual review
```

**No Claude. No external rescue. Just local tactics.**

## The Heartbeat Promise

Every 2 minutes, `scripts/auto_recover.sh` runs:

1. ✓ Checks all agent processes are running
2. ✓ Restarts any that crashed
3. ✓ Commits any untracked files
4. ✓ Writes state/watchdog_heartbeat.json with timestamp
5. ✓ Validates dashboard state.json

**Guarantee:** If the system is alive, `watchdog_heartbeat.json` timestamp is never >2 minutes old.

## The Self-Improvement Loop

Local agents improve their own performance:

```
1. Agent executes task → logs result to state
2. Benchmarking script compares to baseline
3. If quality drops >10%:
     - Write failing examples to state/prompt_upgrade_request.json
     - Claude generates improved prompt
     - Agent adopts new prompt
     - Retry task with new prompt
4. If quality improves or stays same:
     - Keep current prompt
     - Update baseline
     - Continue
```

This is self-correcting without external intervention.

## The Autonomy Phases

### Phase 0: Bootstrap (You are here)
- Local agents running for <1 hour
- Some tasks may be queued/unstarted
- Dashboard state may show partial data
- **Action:** Run auto_recover.sh, start self_heal.py loop

### Phase 1: Self-Healing (First hour to 24 hours)
- auto_recover.sh commits untracked progress
- self_heal.py retries blocked tasks
- Dashboard state updates in real-time
- Prompt improvements happening on 1-hour cycle
- **Expected:** 80%+ tasks completed, <3% permanently blocked

### Phase 2: Steady State (After 24 hours)
- System runs autonomously
- <1% task failure rate
- Dashboard shows real-time progress
- Prompts continuously improving
- No human intervention needed
- **Expected:** Full autonomy, zero external dependency

## Triggers for Manual Intervention

### 🟢 No Intervention Required
- Task fails 1-3 times, then self-heals ✓
- Agent crashes, auto_recover.sh restarts it ✓
- Prompt performance dips, benchmarking improves it ✓
- Agent skips task due to missing dependency ✓

### 🟡 Log & Monitor (No Action Yet)
- Dashboard shows empty values → state_writer validates it away
- Failure rate spikes >5% → self_heal attempts recovery
- Untracked files accumulate → auto_recover.sh commits them
- Heartbeat timestamp stale → processes restarted automatically

### 🔴 Manual Review Required
- Security vulnerability discovered in code
- API key / credential leaked or rotated
- Infrastructure needs scaling / new dependencies
- Agent behavior violates compliance requirement
- >10 blocked tasks exhausted all strategies
- Performance baseline corrupted / needs reset

In these cases:
1. Human investigates
2. Makes decision
3. Commits fix to main (or PR for agent review)
4. Continues monitoring

## Key Files & Responsibilities

### Scripts (Run automatically)
- `scripts/auto_recover.sh` — Runs every 2 min, keeps system alive
- `local-agents/orchestrator/self_heal.py` — Runs every 1 hour, retries blocked tasks
- `scripts/live_dashboard.py` — Runs continuously, serves UI

### State Files (Written by agents)
- `state/watchdog_heartbeat.json` — Timestamp of last heartbeat
- `state/failures.json` — Blocked tasks, retry history
- `dashboard/state.json` — Current system state (always valid)
- `state/runtime-lessons.json` — Learned patterns

### Configuration (Read-only)
- `CLAUDE.md` — Project rules (read-only)
- `.claude/CLAUDE.md` — Workflow rules (read-only)
- `.claude/skills/` — Agent prompts (read by agents, updated after benchmarking)

## Testing the Autonomy

### Day 1: Verify Bootstrap
```bash
# Kill all processes
pkill -f "live_dashboard\|continuous_loop\|self_heal"

# Run auto_recover
bash scripts/auto_recover.sh

# Check heartbeat is fresh
cat state/watchdog_heartbeat.json

# Expected: timestamp is within last 2 minutes
```

### Day 2: Verify Self-Healing
```bash
# Check failures.json
cat state/failures.json | jq '.blocked_tasks | length'

# Expected: some tasks may be blocked, but none >3 hours old

# Run self_heal manually to verify recovery
python3 local-agents/orchestrator/self_heal.py --once

# Check failures again
cat state/failures.json

# Expected: some tasks recovered, failure_history updated
```

### Day 3+: Verify Autonomy
```bash
# Check dashboard is running
curl http://localhost:3001/api/status

# Check state.json is valid
python3 -c "from state.dashboard_schema import validate_and_fix_state, is_valid_state; import json; s=json.load(open('dashboard/state.json')); print('VALID' if is_valid_state(s) else 'INVALID')"

# Expected: state is always valid, no manual fixes needed
```

## Metrics of Success

| Metric | Phase 0 | Phase 1 | Phase 2 |
|--------|---------|---------|---------|
| **Uptime** | <1h | >95% | >99.5% |
| **Task Completion Rate** | <50% | 80-95% | 98%+ |
| **Blocked Task Rate** | 10-20% | <5% | <1% |
| **Auto-Recovery Success** | — | >70% | >95% |
| **Heartbeat Freshness** | — | <2 min | <2 min |
| **Dashboard Validity** | — | >80% | 100% |
| **Claude Invocations** | 0 | <5/day | <1/day (if at all) |

## The Contract, Summarized

| Who | Owns | Constraints |
|-----|------|-------------|
| **Local Agents** | Everything execution | No external APIs, no destructive git, log failures |
| **Claude** | Nothing runtime, new prompts only | Only on request, never for rescue |
| **Human** | Security & infrastructure | Only if triggered by red lights above |

**Bottom Line:** This system should run indefinitely without human interaction, improving its own prompts and recovering from failures automatically.

Once auto_recover.sh and self_heal.py are running, **Claude has nothing left to do.**

---

## Implementation Checklist

- [ ] `scripts/auto_recover.sh` exists and is executable
- [ ] `scripts/failure_handler.py` exists and handles failures locally
- [ ] `local-agents/orchestrator/self_heal.py` exists and runs on 1-hour loop
- [ ] `state/dashboard_schema.py` defines strict schema with TypedDict
- [ ] `dashboard/state_writer.py` imports and uses dashboard_schema for validation
- [ ] `state/watchdog_heartbeat.json` is written every 2 minutes
- [ ] `state/failures.json` exists and tracks blocked tasks
- [ ] `AUTONOMY.md` is documented (this file)
- [ ] Auto-recover is running via cron or watchdog
- [ ] Self-heal loop is running via cron or watchdog

Once all items are checked, the handoff is complete. **The system is autonomous.**

---

## Questions?

Refer to:
- **CLAUDE.md** — Project rules and session policy
- **.claude/CLAUDE.md** — Workflow and agent meta-rules
- **state/dashboard_schema.py** — State structure and validation
- **scripts/auto_recover.sh** — Heartbeat and process restart logic
- **local-agents/orchestrator/self_heal.py** — Failure recovery strategy
