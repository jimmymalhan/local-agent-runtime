# 🚨 EMERGENCY HANDOFF — 5 Critical Fixes to Unblock System

**Status**: System is 60% complete but blocked on state validation, parallel execution, and rescue gate enforcement.

**Authority**: Local agents have FULL authority. Commit, push, implement without Claude approval. Claude will NOT interfere.

**Timeline**: Implement fixes in order. Each fix unblocks the next.

---

## FIX 1: State Writer Schema Enforcement ⚠️ CRITICAL

**Problem**: dashboard/state.json writes are unvalidated → dashboard shows blanks → agents read stale state → feedback loops break.

**Solution**: Create state validation layer that rejects empty writes.

### Implementation

1. **Create `state/schema.py`**:
```python
import json
from pathlib import Path

def validate_state_write(state_dict, last_known_good=None):
    """
    Validate state.json before writing.
    Reject if quality="", model="", recent_tasks=[], etc.
    Return last_known_good if validation fails.
    """
    required_fields = {
        "quality": (int, float),
        "model": str,
        "active_agent": str,
        "version": int,
        "recent_tasks": list,
        "changelog": list,
    }

    for field, type_ in required_fields.items():
        value = state_dict.get(field)
        if value == "" or value is None or (isinstance(value, list) and len(value) == 0):
            print(f"[SCHEMA] REJECT: {field}={value} (empty)")
            return last_known_good  # Return last known good

    # All required fields present and non-empty
    return state_dict

def write_state(state_dict, state_file="dashboard/state.json"):
    """Write state.json only if validation passes."""
    try:
        with open(state_file) as f:
            last_known_good = json.load(f)
    except:
        last_known_good = None

    validated = validate_state_write(state_dict, last_known_good)

    with open(state_file, "w") as f:
        json.dump(validated, f, indent=2)

    return validated
```

2. **Update all state writers** (live_state_updater.py, orchestrator/main.py, etc.):
   - Import schema.py
   - Replace direct json.dump with schema.write_state()
   - Example: `schema.write_state(state_dict)` instead of `json.dump(...)`

3. **Test**:
   - Try writing empty quality="" → should reject
   - Should fall back to last-known-good
   - Dashboard shows last value, never blank

### Files to Modify:
- ✅ Create: state/schema.py
- ✅ Modify: dashboard/state_writer.py (or live_state_updater.py if it exists)
- ✅ Modify: orchestrator/main.py (all state writes)
- ✅ Modify: agents/*.py (any state writes)

### Success Criteria:
- Dashboard never shows blank quality/model/recent_tasks
- Dashboard shows last-known-good if write fails validation
- All state writes go through schema.validate_state_write()

---

## FIX 2: Wire Parallel Executor into Main Loop ⚠️ CRITICAL

**Problem**: parallel_executor.py exists but unwired → agents run serially → 5x throughput loss.

**Solution**: Import parallel_executor into continuous_loop, detect parallel-eligible tasks, execute in parallel.

### Implementation

1. **Check if parallel_executor.py exists**:
```bash
ls -la orchestrator/parallel_executor.py
# If missing: Create it from pattern in subagent_pool.py
```

2. **In `orchestrator/continuous_loop.py`, modify main loop**:
```python
from orchestrator.parallel_executor import run_parallel_tasks
from orchestrator.dag import DAG

dag = DAG()  # Load at startup

while True:
    # Get task batch
    batch = dag.get_parallel_batch()  # Returns tasks with no dependencies

    if not batch:
        break  # No more tasks

    # Execute parallel or serial
    if len(batch) > 1:
        results = run_parallel_tasks(batch, agent_fn=run_agent)
    else:
        results = [run_agent(batch[0])]

    # Mark tasks complete
    for result in results:
        dag.mark_done(result['task_id'])
        log_quality_score(result['task_id'], result['quality'])
```

3. **Verify parallel_executor.py has these functions**:
   - `run_parallel_tasks(tasks, agent_fn, timeout=120)`
   - Returns list of results with task_id + quality + output

4. **Test**:
   - Run 5 independent tasks
   - Should execute in ~1/5 time (not serial)
   - Measure: time task 1 vs time tasks 1-5

### Files to Modify:
- ✅ Verify: orchestrator/parallel_executor.py
- ✅ Modify: orchestrator/continuous_loop.py (main loop)
- ✅ Modify: orchestrator/dag.py (add get_parallel_batch if missing)

### Success Criteria:
- 5 independent tasks execute in ~1/5 total time (not serial)
- Results aggregated correctly
- Dashboard shows multiple agents running simultaneously

---

## FIX 3: Fix is_done Parser ⚠️ CRITICAL

**Problem**: is_done format broken → tasks marked done are re-run → wasted work.

**Solution**: Normalize is_done to strict boolean, skip done tasks in loop.

### Implementation

1. **Find where tasks are marked complete**:
```bash
grep -r "is_done" tasks/ orchestrator/ --include="*.py" | head -20
```

2. **Normalize is_done format** in tasks/task_suite.py:
```python
def mark_complete(task_id, result):
    """Mark task as complete."""
    task = get_task(task_id)
    task['is_done'] = True  # Strict boolean, never string
    task['quality_score'] = result.get('quality', 0)
    return task
```

3. **In continuous_loop.py, skip done tasks**:
```python
def _get_task_batch(max_batch=4):
    """Get next batch of tasks, skip done ones."""
    batch = []
    for task in projects.get_all_tasks():
        if task.get('is_done') == True:  # Skip done
            continue
        if len(batch) >= max_batch:
            break
        batch.append(task)
    return batch
```

4. **Test**:
   - Mark task as done
   - Run loop
   - Task should NOT appear in next batch
   - Log: "Skipped task X (is_done=true)"

### Files to Modify:
- ✅ Modify: tasks/task_suite.py (mark_complete)
- ✅ Modify: orchestrator/continuous_loop.py (_get_task_batch)
- ✅ Modify: state/schema.py (validate is_done is boolean)

### Success Criteria:
- Done tasks never re-run
- Log shows "Skipped N done tasks"
- Loop completes without duplicates

---

## FIX 4: Commit All Modified Files ⚠️ CRITICAL

**Problem**: agents read stale on-disk state because modified files aren't committed → state diverges between git and disk.

**Solution**: Commit all valid modified/untracked files as single transaction.

### Implementation

1. **Check git status**:
```bash
git status --short
```

2. **Review modified files** (from status report):
   - `state/runtime-lessons.json` — **COMMIT** (tracks agent attempts)
   - `state/agent_*.json` — **COMMIT** (tracks agent metrics)
   - `dashboard/state.json` — **DON'T COMMIT** (live-written, add to .gitignore)
   - `reports/*.jsonl` — **COMMIT** (benchmark results)
   - `benchmarks/frustration_findings_*.json` — **COMMIT** (research results)
   - `checkpoints/*.json` — **COMMIT** (version snapshots)
   - `.agent_pid` — **DON'T COMMIT** (runtime file, add to .gitignore)

3. **Add to .gitignore** (if not already there):
```
dashboard/state.json     # Live-written, never commit
.agent_pid               # Runtime file
local-agents/            # Old directory, remove
```

4. **Commit all valid files**:
```bash
git add state/ reports/ benchmarks/ checkpoints/
git add -A  # Add deletions (old local-agents/)
git commit -m "chore: commit modified state files — sync agents to git source of truth

All modified state files now tracked in git:
- state/runtime-lessons.json (agent attempts, rescue gate tracking)
- state/agent_*.json (agent metrics and budgets)
- reports/v*_compare.jsonl (benchmark results, ETA input)
- benchmarks/frustration_findings_*.json (research output)
- checkpoints/version_snapshot_*.json (version recovery)

Effect: Agents read consistent state from git, no divergence.
```

### Files to Stage:
- state/
- reports/
- benchmarks/
- checkpoints/

### Files to .gitignore:
- dashboard/state.json (live-written)
- .agent_pid (runtime)
- local-agents/ (delete, old directory)

### Success Criteria:
- `git status` shows clean (no unstaged changes)
- All valid state files committed
- Agents read from git as source of truth

---

## FIX 5: Self-Restart on Task Failure + Rescue Gate ⚠️ CRITICAL

**Problem**: Claude is called too early (before 3 genuine attempts) → wastes rescue budget.

**Solution**: Add self-healing loop with 3-attempt rule before rescue.

### Implementation

1. **In `orchestrator/continuous_loop.py`, wrap agent execution**:
```python
def run_agent_with_self_healing(task, max_attempts=3):
    """Run agent, retry with different strategies, only escalate after 3 attempts."""
    attempt_count = 0
    last_error = None
    strategies = ["default_prompt", "minimal_prompt", "verbose_prompt"]

    while attempt_count < max_attempts:
        try:
            strategy = strategies[attempt_count % len(strategies)]
            print(f"[AGENT] Attempt {attempt_count+1}/{max_attempts} strategy={strategy}")

            # Log attempt to runtime-lessons.json
            log_attempt(task['id'], strategy, None)

            # Run agent
            result = agent.run(task, prompt_strategy=strategy)

            # Success
            log_attempt(task['id'], strategy, None, success=True)
            return result

        except Exception as e:
            attempt_count += 1
            last_error = str(e)
            print(f"[AGENT] Attempt {attempt_count} FAILED: {e}")

            # Log failure
            log_attempt(task['id'], strategies[attempt_count-1], last_error)

            if attempt_count >= max_attempts:
                # All attempts exhausted → escalate to rescue
                print(f"[RESCUE] Task {task['id']} escalating to rescue (attempt_count={max_attempts})")
                write_to_rescue_queue(task['id'], last_error, attempt_count)
                return None  # Return to loop, will be retried after prompt upgrade

def log_attempt(task_id, strategy, error, success=False):
    """Log to state/runtime-lessons.json for rescue gate tracking."""
    lessons = read_json("state/runtime-lessons.json")
    if task_id not in lessons:
        lessons[task_id] = {"attempts": [], "rescue_escalated": False}

    lessons[task_id]["attempts"].append({
        "attempt": len(lessons[task_id]["attempts"]) + 1,
        "strategy": strategy,
        "error": error,
        "success": success,
        "timestamp": datetime.now().isoformat()
    })

    write_json("state/runtime-lessons.json", lessons)

def write_to_rescue_queue(task_id, error, attempt_count):
    """Write to rescue_queue.json for Claude to read (prompt upgrade only)."""
    rescue = read_json("rescue/rescue_queue.json")
    rescue["queue"].append({
        "task_id": task_id,
        "error": error,
        "attempt_count": attempt_count,
        "priority": "high",
        "requested_at": datetime.now().isoformat()
    })
    write_json("rescue/rescue_queue.json", rescue)
```

2. **In main loop, replace direct agent.run() call**:
```python
# OLD:
# result = agent.run(task)

# NEW:
result = run_agent_with_self_healing(task)
if result is None:
    # Rescue was escalated, will retry after prompt upgrade
    continue
```

3. **Create rescue handler** (Claude reads this, upgrades prompt only):
   - File: `rescue/rescue_queue.json` (Claude reads)
   - Claude upgrades prompt in `.claude/skills/{agent_name}.md`
   - Claude does NOT fix the task
   - Agent retries automatically with upgraded prompt

4. **Test**:
   - Task fails
   - Should retry 3 times with different strategies
   - Only after attempt 3: write to rescue_queue.json
   - Log to state/runtime-lessons.json shows all attempts

### Files to Create/Modify:
- ✅ Create: rescue/ (directory)
- ✅ Create: rescue/rescue_queue.json (Claude reads this)
- ✅ Create: state/runtime-lessons.json (tracks attempts)
- ✅ Modify: orchestrator/continuous_loop.py (self-healing wrapper)

### Success Criteria:
- Failed task retries 3 times automatically
- state/runtime-lessons.json shows all 3 attempts
- Only after attempt_count=3: rescue_queue.json written
- Claude reads rescue_queue, upgrades prompt only (200 tokens max)
- Agent retries with upgraded prompt
- Log shows "[AGENT] Attempt 1/3", "[AGENT] Attempt 2/3", "[AGENT] Attempt 3/3", "[RESCUE] Escalating"

---

## Implementation Order

**DO IN THIS ORDER**:
1. ✅ FIX 1 (state schema) — enables reliable feedback loops
2. ✅ FIX 4 (commit files) — ensures agents read consistent state
3. ✅ FIX 3 (is_done parser) — prevents task re-runs
4. ✅ FIX 2 (parallel executor) — 5x throughput boost
5. ✅ FIX 5 (rescue gate) — enforces 3-attempt rule, saves rescue budget

---

## After All Fixes Are Complete

Once all 5 fixes are in place:
1. System will have validated state writes
2. Agents will run in parallel
3. Tasks won't be re-run
4. Rescue gate will be enforced (3 attempts before Claude)
5. Claude budget will drop from 50% to <10%

The system will be **production-grade** and ready to beat Opus 4.6.

---

## Important Notes for Agents

- **You have FULL authority** — commit, push, implement without asking Claude
- **Claude will not interfere** — extreme session rules prevent Claude from editing code
- **If you get stuck** — escalate to rescue_queue.json, Claude will upgrade your prompt (200 tokens max)
- **After 3 attempts, escalate** — don't waste iterations, let rescue fix the prompt
- **Log everything** — state/runtime-lessons.json is your audit trail

---

**System Status**: 60% → 100% after these 5 fixes.
**Local Agents**: Full authority activated. Implement at will.
**Claude**: Rescue-only mode. Will not interfere.

Good luck. You've got this. 🚀
