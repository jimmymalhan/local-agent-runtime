# MASTER PLAN: Short-Term & Long-Term System Implementation

**Date**: 2026-03-26
**Authority**: Full autonomy for local agents + Claude infrastructure support
**Vision**: Autonomous agent system that beats Opus 4.6 by 2026-04-26

---

## EXECUTIVE SUMMARY

### Current State
- **System Status**: 🔴 STUCK (orchestrator spinning, agents idle, zero task completion)
- **Agents Assigned**: 6 (architect, executor, frontend_agent, qa_agent, writer, orchestrator)
- **Tasks Assigned**: 20 (0 completed)
- **Infrastructure**: Monitoring + auto-remediation installed, waiting for agents to execute fixes
- **Blockers**: 6 critical (write-back loop, deadlock detection, state validation, etc)
- **Incidents Filed**: 2 auto-filed by health monitor

### Master Plan Phases
```
SHORT-TERM (4-6 hours):   Unblock orchestrator, wire write-back, enable agent execution
MEDIUM-TERM (This week):  Build 6 specialist agents, achieve 24/7 autonomous execution
LONG-TERM (4 weeks):      Beat Opus 4.6 with 90% local + 10% rescue
```

---

## SHORT-TERM: UNBLOCK TODAY (4-6 HOURS)

### Phase 1A: Infrastructure Support (Claude — can do now)

**STATUS**: ✅ DONE
- [x] Fixed dashboard bug (BaseDir Path handling)
- [x] Created system_health_monitor.py
- [x] Created auto_remediate.sh
- [x] Filed 6 critical unblock tasks
- [x] Filed 2 incident tasks
- [x] Committed everything to main

**REMAINING**:
- [ ] Install cron jobs (30 min)
- [ ] Deploy continuous monitoring (5 min)
- [ ] Create "dispatch wrapper" to help route tasks (1 hour)
- [ ] Document orchestrator loop issue with exact logs (30 min)

### Phase 1B: Agents Execute Critical Unblocks (Agents — must happen next)

**Priority Order** (dependencies matter):

```
1. UNBLOCK-2: Wire write-back loop (CRITICAL)
   └─ After this: agents can prove they execute work
   └─ Impact: state.json updates, dashboard shows progress

2. UNBLOCK-3: Deadlock detector (CRITICAL)
   └─ After this: stuck tasks auto-fail + requeue
   └─ Impact: pipeline never hangs forever

3. UNBLOCK-4: State consistency validator (CRITICAL)
   └─ After this: dashboard never shows blank values
   └─ Impact: monitoring can see real system state

4. UNBLOCK-5: Git hygiene enforcer (IMPORTANT)
   └─ After this: artifacts auto-committed
   └─ Impact: no more lost work on restarts

5. UNBLOCK-6: Failure taxonomy (IMPORTANT)
   └─ After this: agents self-diagnose + fix errors
   └─ Impact: rescue budget drops from 10% to <5%

6. UNBLOCK-1: Commit artifacts (ADMINISTRATIVE)
   └─ After this: built code is integrated
   └─ Impact: new agents available for execution
```

**Success Criteria** (Phase 1B):
- [ ] All 6 unblock tasks executed
- [ ] state.json updates after agent work
- [ ] Dashboard shows completed tasks
- [ ] No tasks stuck >10 minutes
- [ ] At least 5 tasks completed (out of 20)

**Est. Time**: 2-3 hours for agents (parallel execution)

### Phase 1C: System Validation (Claude + Monitoring)

After agents complete unblocks:

- [ ] Run health monitor: should show 0 critical incidents
- [ ] Run auto-remediation: should report "OK"
- [ ] Test end-to-end: assign a task → agent executes → dashboard shows result
- [ ] Verify 24/7 operation: cron jobs running, state updating every 60 sec

**Est. Time**: 30 min

---

## MEDIUM-TERM: BUILD AGENTS (THIS WEEK)

### Phase 2A: Design 6 Specialist Agents

Based on prior session notes + system needs:

```
Agent 1: cicd_agent
├─ Purpose: Automate CI/CD pipelines, run tests, deploy
├─ Input: Code changes, test suite
├─ Output: Test results, deployment status
├─ Success Metric: All tests pass, 0 flaky tests

Agent 2: code_graph
├─ Purpose: Map code dependencies, find circular imports, detect unused code
├─ Input: Codebase
├─ Output: Dependency graph, improvement suggestions
├─ Success Metric: Graph accuracy validated manually

Agent 3: code_reviewer
├─ Purpose: Review PRs, gate quality, flag issues
├─ Input: PR diffs, test results
├─ Output: Approval/rejection, improvement suggestions
├─ Success Metric: Catches 90%+ of defects pre-merge

Agent 4: context_optimizer
├─ Purpose: Trim large files, compress context, optimize prompts
├─ Input: Large prompts, context budget
├─ Output: Optimized prompts, trimmed files
├─ Success Metric: 50% token reduction, no loss of quality

Agent 5: doc_generator
├─ Purpose: Generate documentation from code, keep docs in sync
├─ Input: Code changes, existing docs
├─ Output: Updated docs, new examples
├─ Success Metric: Docs match code 100%, examples run

Agent 6: multi_editor
├─ Purpose: Make coordinated changes across multiple files
├─ Input: Refactoring spec (rename var, update imports, etc)
├─ Output: Coordinated changes all at once
├─ Success Metric: Zero broken imports after changes
```

### Phase 2B: Build & Test Each Agent

For each agent:
1. Create `agents/agent_name.py`
2. Define input/output schema
3. Create test suite in `tests/agents/test_agent_name.py`
4. Integrate with main orchestrator
5. Deploy to projects.json tasks
6. Monitor success rate

**Timeline**:
- Agent 1 (cicd_agent): 2-3 hours
- Agent 2 (code_graph): 2-3 hours
- Agent 3 (code_reviewer): 3-4 hours (most complex)
- Agent 4 (context_optimizer): 2-3 hours
- Agent 5 (doc_generator): 2-3 hours
- Agent 6 (multi_editor): 2-3 hours

**Parallel Execution**: Can build agents 1-3 in parallel, then 4-6 in parallel
**Est. Total**: 12-16 hours (2 days with parallelization)

### Phase 2C: Wire Parallel Execution

After agents exist:

1. Create `parallel_executor.py` (already exists, needs wiring)
   - Run 4-8 agents in parallel on independent tasks
   - Coordinate results, handle failures

2. Create `worktree_manager.py`
   - Each agent gets isolated git worktree
   - Changes don't interfere
   - Easy rollback per agent

3. Integrate into orchestrator/main.py
   - Use DAG to identify parallelizable tasks
   - Dispatch to parallel_executor
   - Collect results, update state

**Est. Time**: 3-4 hours

### Phase 2D: Auto-Commit & State Persistence

**Goal**: Every agent action automatically persists

1. Modify agents/__init__.py router:
   ```python
   for agent in agents:
       result = agent.execute(task)
       state["recent_tasks"].append({"task_id": task.id, "result": result, ...})
       json.dump(state, open("dashboard/state.json"))
       git add dashboard/state.json
       git commit(f"state: task {task.id} complete")
   ```

2. Add pre-commit hook:
   - Verify state.json schema
   - Ensure all required fields present

3. Add post-commit hook:
   - Push to remote if CI passes
   - Broadcast state update via WebSocket

**Est. Time**: 2-3 hours

### Phase 2E: Comprehensive Testing

- [ ] Run all 20 tasks through agents (expect 80%+ pass rate)
- [ ] Verify state.json updates for each completion
- [ ] Verify parallel execution (4+ agents running simultaneously)
- [ ] Verify git commits are atomic + rollback-safe
- [ ] Monitor dashboard real-time updates (every 2-5 seconds)

**Est. Time**: 2-3 hours

---

## LONG-TERM: BEAT OPUS 4.6 (4 WEEKS)

### Phase 3A: Quality Scoring & Benchmarking (Weeks 1-2)

1. Implement `quality_scorer.py`
   - Score every task output 0-100
   - Track: correctness, completeness, performance, maintainability
   - Store scores in state.json

2. Create benchmark harness
   - Every 24 hours: run 10 random tasks on local agents
   - Every 24 hours: run same 10 tasks on Opus 4.6 (budget permitting)
   - Compare scores, track gap

3. Track gap closure
   ```
   Current: Local 38% vs Opus 90% (gap = 52 points)
   Target:  Local 92% vs Opus 90% (gap = -2 points, WIN!)

   Week 1: 38% → 50% (12 point improvement)
   Week 2: 50% → 60% (10 point improvement)
   Week 3: 60% → 75% (15 point improvement)
   Week 4: 75% → 88% (13 point improvement)
   ```

**Success Metric**: Gap closes by 5+ points per week

### Phase 3B: Prompt Engineering & Self-Improvement (Weeks 2-3)

1. Track which prompts produce quality >80%
   - Automatically promote high-quality prompts
   - Increase weight/priority

2. Track which prompts produce quality <40%
   - Retire after 3 consecutive failures
   - Replace with new variants

3. Create prompt laboratory
   - Test new prompt variations every cycle
   - A/B test on subset of tasks
   - Promote winners to full deployment

4. Semantic memory + lessons loop
   - Learn from failures (what went wrong, why)
   - Apply lessons to new prompts
   - Track "lessons effectiveness" metric

**Success Metric**: Average quality improves by 2-3 points per day

### Phase 3C: Multi-Loop Execution & Optimization (Weeks 3-4)

1. Implement multi-pass execution
   - Pass 1: Initial attempt (fast)
   - Pass 2: Refinement with feedback (slower, more careful)
   - Pass 3: Final validation (checks quality, correctness)

2. Use DAG + parallel execution
   - Identify task dependencies
   - Run independent tasks in parallel
   - Sequential tasks in correct order

3. Implement semantic memory
   - Store results from prior similar tasks
   - Reuse solutions when safe
   - Reduce redundant work

4. Optimize for speed + quality
   - Fast agents for simple tasks
   - Slow agents for complex tasks
   - Hybrid approach based on task difficulty

**Success Metric**: Throughput increases 3-5x, quality improves 5-10 points

### Phase 3D: Rescue Budget & Self-Healing (Ongoing)

1. Implement token_enforcer.py
   - Hard cap at 10% rescue usage
   - Warn at 8%
   - Block at 10%

2. Implement rescue_gate.py
   - Only allow rescue after 3 local attempts
   - Only for eligible tasks
   - Track all rescues in reports/

3. Self-healing system
   - Auto-detect failure patterns
   - Auto-fix highest-frequency issues
   - Prevent recurrence

**Success Metric**: Rescue rate stays <5%, self-healing prevents 80%+ of issues

---

## IMPLEMENTATION TIMELINE

```
TODAY (2026-03-26):
├─ 17:00 — Infrastructure automation committed ✅
├─ 17:30 — Cron jobs installed
├─ 18:00 — Agents execute unblock-1 through unblock-6
├─ 19:00 — System health check (all unblocks done?)
├─ 19:30 — First 5-10 tasks complete
└─ 20:00 — Phase 1 DONE: System is running and monitoring

THIS WEEK (2026-03-27 to 2026-03-31):
├─ Build Agent 1-3 (parallel): 8-10 hours
├─ Build Agent 4-6 (parallel): 8-10 hours
├─ Wire parallel execution: 3-4 hours
├─ Auto-commit + state persistence: 2-3 hours
├─ Comprehensive testing: 2-3 hours
└─ End of week: All 6 agents live, 18-20/20 tasks completing

NEXT WEEK (2026-04-01 to 2026-04-07):
├─ Quality scoring & benchmarking: 12-16 hours
├─ Prompt engineering + self-improvement: 12-16 hours
└─ End of week: Quality gap narrowing, 50%+ win rate vs baseline

WEEK 3-4 (2026-04-08 to 2026-04-21):
├─ Multi-loop execution: 8-12 hours
├─ Semantic memory: 4-8 hours
├─ Rescue budget + self-healing: 4-8 hours
└─ End of week: Full autonomy, 75%+ quality

FINAL WEEK (2026-04-22 to 2026-04-26):
├─ Optimization + tuning: 8-12 hours
├─ Final benchmarking vs Opus 4.6
└─ **GOAL**: Local 92% vs Opus 90% = WIN 🎯
```

---

## Success Metrics & Validation

### Phase 1 (SHORT-TERM) — System Running
```
✅ Unblock-1 through unblock-6 all complete
✅ At least 5/20 tasks completed with results in state.json
✅ Dashboard shows real completed tasks
✅ Health monitor shows 0 critical incidents
✅ Auto-remediation fixes any stuck states within 2 minutes
✅ System monitored 24/7 (cron running)
```

### Phase 2 (MEDIUM-TERM) — 6 Agents Live
```
✅ 6 specialist agents deployed and executing tasks
✅ 18-20/20 tasks completing successfully
✅ Parallel execution active (4+ agents running simultaneously)
✅ State.json auto-updated on every task completion
✅ Git commits atomic + safe
✅ Dashboard shows real-time progress every 2-5 seconds
```

### Phase 3 (LONG-TERM) — Beat Opus 4.6
```
✅ Quality gap closes by 5+ points per week
✅ Local wins on 50%+ of benchmark tasks vs Opus
✅ Self-improvement loop working (prompts auto-evolving)
✅ Rescue budget stays <5% (agents self-healing)
✅ **FINAL**: Local 92% vs Opus 90% = WIN ✨
```

---

## Risks & Mitigation

| Risk | Impact | Mitigation |
|------|--------|-----------|
| Orchestrator loop not fixable by agents | System stays stuck | Claude can make ONE emergency fix (infrastructure level) |
| Agents generate low-quality work | System doesn't improve | Quality scoring + prompt engineering catches + fixes |
| Parallel execution has race conditions | Data corruption | Use worktrees + atomic commits |
| Rescue budget gets exhausted | System falls back to manual | Auto-remediation prevents escalations |
| State.json grows too large | Dashboard gets slow | Implement state compression + archival |

---

## Who Does What

### Claude (Infrastructure Support)
- ✅ Set up monitoring + automation
- ✅ Fix infrastructure bugs (not agent code)
- ✅ File tasks for agents to execute
- ⏸️ ONE emergency fix allowed if system deadlocked
- ❌ Never edit agent/orchestrator logic

### Local Agents (Autonomous Execution)
- ✅ Execute all UNBLOCK tasks
- ✅ Build all 6 specialist agents
- ✅ Integrate parallel execution
- ✅ Self-diagnose + self-fix failures
- ✅ Auto-improve via prompt engineering
- ✅ Work 24/7 (monitored + auto-healing)

### Watchdog (24/7 Guardian)
- ✅ Restart crashed processes
- ✅ Monitor health every 60 seconds
- ✅ File incidents if problems detected
- ✅ Prevent deadlocks + cascading failures

---

## Next Step: IMMEDIATE ACTION

**For Claude (now)**:
```bash
1. Install cron jobs (30 min)
   crontab -e
   # Add: * * * * * python3 scripts/system_health_monitor.py

2. Create dispatch wrapper (1 hour)
   # Help route tasks to agents if orchestrator stuck

3. Document orchestrator loop issue (30 min)
   # Save logs, exact behavior, for agents to fix
```

**For Agents (as soon as monitoring runs)**:
```bash
1. Execute unblock-2 (wire write-back loop)
2. Execute unblock-3 (deadlock detector)
3. Execute unblock-4 (state validator)
4. Execute unblock-5 (git hygiene)
5. Execute unblock-6 (failure taxonomy)
6. Verify 5+ tasks complete with real results in state.json
```

**For System (continuous)**:
- Health monitor detects issues every 60 sec
- Auto-remediation fixes common problems
- Agents execute tasks + update state
- Dashboard shows real progress
- Cron jobs keep everything running 24/7

---

**Authority**: Full autonomy for all work. Execute in parallel where possible. Report progress via state.json updates.

**Timeline**: Phase 1 done today (by EOD). Phase 2 done this week. Phase 3 done in 4 weeks.

**Goal**: Beat Opus 4.6 by 2026-04-26. 🎯

