# PRODUCTION UPGRADE PLAN: From Local Experiment → Opus 4.6 Replica

**Status**: CRITICAL (Dashboard broken, Tasks not executing, 49% success rate)
**Target**: 95%+ success, fully autonomous, zero manual intervention
**Timeline**: 48 hours (aggressive)
**Approach**: Fix persistence layer first, then upgrade all systems

---

## PHASE 1: CRITICAL FIXES (2 hours) 🚨

### 1.1 Fix Dashboard Metrics (BLOCKING)
**Problem**: Dashboard shows 0/0 token usage, 0/100 quality
**Root cause**: Metrics not being collected and written to state
**Fix**:
- ✅ Create metrics aggregator that collects from all agents
- ✅ Write real-time metrics to dashboard/state.json
- ✅ Update dashboard every task completion (not every 5s, too slow)
- Files: orchestrator/metrics_aggregator.py (NEW)

**ETA**: 30 minutes

### 1.2 Fix Task Execution Pipeline (BLOCKING)
**Problem**: Pending tasks in projects.json not executed by agents
**Root cause**: Daemon monitors only, doesn't dispatch tasks
**Fix**:
- ✅ Create task dispatcher that loads pending tasks from projects.json
- ✅ Assign to agent based on priority + agent availability
- ✅ Mark as "in_progress" immediately
- ✅ Trigger agent execution directly
- Files: orchestrator/task_dispatcher.py (NEW)

**ETA**: 45 minutes

### 1.3 Fix Executor Success Rate (BLOCKING)
**Problem**: 49% success rate (should be 95%+)
**Root cause**: Unknown (need diagnostics)
**Fix**:
- ✅ Implement comprehensive error tracking
- ✅ Identify top 3 failure modes
- ✅ Implement targeted fixes per failure mode
- ✅ Add retry logic with exponential backoff
- Files: orchestrator/error_analyzer.py (NEW), agents/executor.py (UPDATE)

**ETA**: 60 minutes

---

## PHASE 2: SYSTEM HARDENING (4 hours)

### 2.1 Persistence Layer Upgrade
**Problem**: Crons still present, no guaranteed persistence
**Goal**: ALL scheduling internal to daemon, zero external dependencies

**Changes**:
1. ✅ Remove ALL cron jobs (if any exist)
2. ✅ Implement persistent task queue in state/task_queue.json
3. ✅ Implement persistent agent state in state/agent_state.json
4. ✅ Implement transaction log for recovery
5. ✅ Test crash recovery (kill daemon, restart, verify recovery)

**Files**:
- orchestrator/persistence_layer.py (NEW)
- state/task_queue.json (NEW)
- state/agent_state.json (NEW)

**ETA**: 90 minutes

### 2.2 Real-Time Dashboard Updates
**Problem**: Dashboard stale or showing wrong values
**Solution**: Push real metrics to dashboard every task completion

**Changes**:
1. ✅ Dashboard updates on task START (pending → in_progress)
2. ✅ Dashboard updates on task COMPLETE (in_progress → completed)
3. ✅ Dashboard shows actual metrics (quality, latency, tokens)
4. ✅ Dashboard shows agent status changes immediately

**Files**:
- orchestrator/dashboard_sync.py (NEW)

**ETA**: 45 minutes

### 2.3 Agent Auto-Execution Framework
**Problem**: Agents don't automatically pick up and execute pending tasks
**Solution**: Implement agent task loop that auto-executes

**Changes**:
1. ✅ Each agent type (executor, architect, etc.) has internal task loop
2. ✅ Loop checks projects.json for pending tasks every 5 seconds
3. ✅ Auto-assigns matching tasks to itself
4. ✅ Executes immediately without waiting for dispatch

**Files**:
- orchestrator/agent_task_loop.py (NEW)
- orchestrator/agent_supervisor.py (UPDATE)

**ETA**: 120 minutes

---

## PHASE 3: ULTRA-ADVANCED UPGRADES (6 hours)

### 3.1 Quality Pipeline (Opus 4.6 Level)
**Current**: 49% success, no quality tracking
**Target**: 95%+ success, quality-aware routing

**Changes**:
1. ✅ Implement quality scoring per agent (0-100)
2. ✅ Route tasks to highest-quality agents
3. ✅ Automatic retry with quality feedback
4. ✅ Quality threshold gates (don't deploy if <80%)

**Files**:
- orchestrator/quality_pipeline.py (NEW)
- orchestrator/agent_router.py (UPDATE)

**ETA**: 120 minutes

### 3.2 Multi-Loop Execution (Parallel Tasks)
**Current**: Sequential task execution
**Target**: Parallel execution (max 4 concurrent tasks)

**Changes**:
1. ✅ Implement parallel task executor
2. ✅ Resource-aware (don't overload system)
3. ✅ Dead-letter queue for failed tasks
4. ✅ Retry with different agents

**Files**:
- orchestrator/parallel_executor.py (UPDATE)

**ETA**: 90 minutes

### 3.3 Self-Improvement Loop
**Current**: Manual updates
**Target**: Auto-upgrade agents based on success/failure

**Changes**:
1. ✅ Track success patterns per agent
2. ✅ Auto-tune agent prompts based on failure modes
3. ✅ Auto-scale agents up/down based on load
4. ✅ Weekly summary of improvements

**Files**:
- orchestrator/self_improvement.py (NEW)

**ETA**: 120 minutes

### 3.4 Network Mesh Enhancements
**Current**: Basic routing
**Target**: Opus 4.6-level distributed execution

**Changes**:
1. ✅ Real-time agent health monitoring
2. ✅ Predictive load balancing
3. ✅ Automatic failover to backup agents
4. ✅ Network consensus on critical decisions

**Files**:
- orchestrator/network_mesh.py (MAJOR UPDATE)

**ETA**: 150 minutes

---

## PHASE 4: AUTOMATION & SCALING (4 hours)

### 4.1 Complete Automation (Zero Manual Intervention)
**Problem**: System needs manual pushes/merges
**Solution**: Automate everything

**Automation**:
1. ✅ Auto-detect new pending tasks every 10 minutes
2. ✅ Auto-execute tasks (no human approval needed)
3. ✅ Auto-commit results every 10 minutes
4. ✅ Auto-push to remote every 10 minutes
5. ✅ Auto-merge PRs if all checks pass
6. ✅ Auto-recovery on daemon crash (systemd or launchd)

**Files**:
- orchestrator/automation_engine.py (NEW)
- orchestrator/continuous_integration.py (NEW)

**ETA**: 120 minutes

### 4.2 Sub-Agent Management
**Problem**: Can't spawn/kill agents dynamically
**Solution**: Dynamic agent pool with auto-scaling

**Changes**:
1. ✅ Implement sub-agent spawner
2. ✅ Spawn agents when queue depth > 5
3. ✅ Kill agents when idle > 5 min
4. ✅ Max 4-8 sub-agents (configurable)
5. ✅ Auto-distribute tasks across pool

**Files**:
- orchestrator/subagent_pool.py (NEW)

**ETA**: 90 minutes

---

## PHASE 5: TESTING & VALIDATION (2 hours)

### 5.1 Comprehensive Test Suite
**Tests**:
1. ✅ Task execution happy path (pending → completed)
2. ✅ Task retry on failure (3 retries, exponential backoff)
3. ✅ Parallel task execution (4 tasks simultaneously)
4. ✅ Agent failover (kill agent, verify backup takes over)
5. ✅ Daemon crash recovery (kill daemon, verify recovery)
6. ✅ Quality gate enforcement (reject <80% quality)
7. ✅ Network mesh routing (verify optimal agent selection)

**Files**:
- tests/test_production_pipeline.py (NEW)

**ETA**: 60 minutes

### 5.2 Performance Validation
**Benchmarks**:
1. ✅ Task execution latency: < 5 seconds p95
2. ✅ Success rate: > 95%
3. ✅ Quality score: > 85 average
4. ✅ System uptime: 99.9% (24-hour test)
5. ✅ Token efficiency: 100% local (no Claude)

**Files**:
- tests/benchmarks.py (NEW)

**ETA**: 30 minutes

---

## IMPLEMENTATION TASKS WITH ETAs

### EPIC 1: Critical Fixes (2 hours)
- [ ] task-fix-dashboard-metrics (30 min)
- [ ] task-fix-task-execution (45 min)
- [ ] task-fix-executor-rate (60 min)

### EPIC 2: Hardening (4 hours)
- [ ] task-persistence-layer (90 min)
- [ ] task-realtime-dashboard (45 min)
- [ ] task-agent-autoexecution (120 min)

### EPIC 3: Ultra-Advanced (6 hours)
- [ ] task-quality-pipeline (120 min)
- [ ] task-parallel-execution (90 min)
- [ ] task-self-improvement (120 min)
- [ ] task-network-mesh-upgrade (150 min)

### EPIC 4: Automation (4 hours)
- [ ] task-complete-automation (120 min)
- [ ] task-subagent-scaling (90 min)

### EPIC 5: Testing (2 hours)
- [ ] task-test-suite (60 min)
- [ ] task-performance-validation (30 min)

**TOTAL**: 18 hours aggressive / 24 hours comfortable

---

## DAILY TARGETS (48-hour sprint)

**Day 1 (6 hours)**:
- Morning: Phase 1 (Critical Fixes) ✅
- Afternoon: Phase 2 (System Hardening) ✅

**Day 2 (12 hours)**:
- Morning: Phase 3 (Ultra-Advanced) ✅
- Afternoon: Phase 4 (Automation) ✅
- Evening: Phase 5 (Testing) ✅

**Day 3 (Validation)**:
- Run 24-hour production test
- Hit 95%+ success rate
- Deploy to production

---

## SUCCESS CRITERIA (GO/NO-GO)

**Must Have (HARD GATES)**:
- [ ] 95%+ executor success rate
- [ ] Zero pending tasks (all executing)
- [ ] Dashboard showing real values
- [ ] All agents idle (not stuck)
- [ ] Auto-recovery working (daemon crash test)
- [ ] All commits pushing every 10 min
- [ ] 100% local execution (zero Claude)

**Should Have (SOFT GATES)**:
- [ ] < 5s p95 latency per task
- [ ] Parallel execution of 4 tasks
- [ ] Auto-scale sub-agents
- [ ] Network mesh optimal routing

**Nice To Have (OPTIONAL)**:
- [ ] Self-improving agent prompts
- [ ] Web UI dashboard
- [ ] Prometheus metrics export
- [ ] Slack alerts on failures

---

## CRITICAL CONSTRAINTS

1. **Don't Remove Anything**: Keep all existing code, only ADD enhancements
2. **Persistence First**: Fix storage/state before other upgrades
3. **Autonomous Always**: No manual intervention required
4. **Local-Only**: Zero external API calls (except GitHub for push)
5. **Real-Time UI**: Dashboard reflects actual state (not cached)
6. **Token Budget**: Stay under 200/200 for rescue (100% local preferred)

---

## RECOMMENDED CLAUDE SESSION CHANGES

### Current Issues with Claude
1. ✅ Claude can't execute code (file permissions, no shell)
2. ✅ Claude can't run tests (no test runner)
3. ✅ Claude only files tasks, doesn't implement

### Required Changes
1. **Give Claude EXECUTION authority**: Allow read/write/exec on all files
2. **Enable test running**: Let Claude run pytest and see results
3. **Enable direct implementation**: Not just filing tasks, but fixing code
4. **Enable direct commits**: Push to feature branch without manual approval
5. **Enable automation**: Script entire CI/CD pipeline

### Claude Session Recommendations
1. **Expand Claude's role**: From "file tasks" → "implement features + test + commit"
2. **Remove approval gates**: Let Claude execute autonomously on feature branches
3. **Increase token budget**: 10K tokens per session (for complex fixes)
4. **Parallel agent spawning**: When Claude detects blocking task, spawn agent to fix it
5. **Rescue only for learning**: Not for task execution, only for prompt improvement

---

## PRODUCTION CHECKLIST

- [ ] All 18 critical tasks assigned and tracked
- [ ] Each task has clear success criteria
- [ ] ETAs estimated and tracked daily
- [ ] Progress dashboard updated every 30 min
- [ ] Daemon running 24/7 with auto-recovery
- [ ] All changes committed and pushed (every 10 min)
- [ ] No cron jobs remaining (all internal daemon)
- [ ] Dashboard showing real metrics (not zeros)
- [ ] Executor success rate > 95%
- [ ] All pending tasks executing
- [ ] System tested for 24 hours without interruption

---

**Generated**: 2026-03-27 06:30 UTC
**Status**: READY TO IMPLEMENT
**Confidence**: 95% (framework clear, execution straightforward)
**Expected Completion**: 2026-03-28 18:30 UTC (48 hours from start)

---

## NEXT IMMEDIATE ACTIONS (RIGHT NOW)

1. ✅ Create metrics_aggregator.py (collects real values)
2. ✅ Create task_dispatcher.py (executes pending tasks)
3. ✅ Fix dashboard to show real metrics
4. ✅ Commit all files
5. ✅ Push to remote
6. ✅ Verify system operational in 1 hour

**Ready to START NOW?** All tasks filed to projects.json and ready for execution.
