# Skill: Fast Iteration

**Trigger:** Every task, every agent, every session. This is the default operating mode.

## Core Rules

### 1. Small Incremental Changes, Push Immediately
- Make the smallest useful change that moves the task forward.
- Commit and push after each logical unit (one function, one fix, one config change).
- Never batch multiple unrelated changes into a single commit.
- If a change takes more than 5 minutes, break it into smaller steps.

### 2. Never Wait for Resources
- If the preferred model is unavailable or slow, downgrade immediately:
  - `opus` unavailable -> use `sonnet`
  - `sonnet` unavailable -> use `haiku`
  - Cloud unavailable -> use local Ollama (`qwen2.5:3b`, `codellama`)
  - Ollama unavailable -> write pseudocode and move to next task
- Never block on a resource for more than 30 seconds.
- Log the downgrade in `state/runtime-lessons.json` so the system learns.

### 3. Maintain 2-3 Backup Options for Every Blocker
- **Model blocker:** Have 3 models ranked by preference. Fall through automatically.
- **API blocker:** Cache last successful response. Use stale data rather than stalling.
- **File lock blocker:** Work on a different file. Come back when lock clears.
- **Test blocker:** Skip the failing test (mark `[SKIP]`), continue, fix later.
- **Network blocker:** Switch to offline-capable tasks (refactoring, docs, local tests).

### 4. Time-Box Every Task to 5 Minutes Max
- Set a mental timer at task start.
- At 3 minutes: assess progress. If less than 50% done, simplify scope.
- At 5 minutes: stop, commit what you have, document remaining work.
- Move partial results to `state/progress.json` with status `partial`.
- Never let a single task consume the entire session.

### 5. If Stuck, Switch and Return
- Stuck means: no progress for 60 seconds, or same error twice.
- When stuck:
  1. Write down exactly where you stopped and what blocked you.
  2. Add the blocker to `state/auto-remediation.json`.
  3. Switch to the next task in the queue.
  4. Return to the blocked task after completing one other task.
- Cycling between tasks often unblocks issues naturally (resources free up, locks release).

## Anti-Patterns (Never Do These)
- Waiting 10+ minutes for a model to respond.
- Rewriting a large file in one pass instead of incremental edits.
- Blocking on a PR review before starting the next task.
- Perfecting code before committing (commit rough, refine later).
- Debugging the same error for more than 3 minutes without trying a different approach.

## Metrics
- **Commit frequency:** Target 1 commit per 3-5 minutes of active work.
- **Blocked time:** Should be < 10% of total session time.
- **Task switches:** 0-2 per session is healthy. More than 5 indicates systemic blockers.

## Integration
- Reads: `state/progress.json`, `state/agent-coordination.json`
- Writes: `state/runtime-lessons.json`, `state/auto-remediation.json`
- Related skills: `lead-coordination`, `team-orchestration`, `self-coordination`
