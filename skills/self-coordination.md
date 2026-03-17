# Skill: Self-Coordination

**Trigger:** When multiple agents run concurrently, or any agent starts a task that touches shared state or files.

## Coordination Protocol

### 1. Check State Before Starting
Before any work, read `state/agent-coordination.json`:
```json
{
  "claims": [
    {
      "agent": "researcher",
      "task": "analyze-codebase",
      "files": ["src/pipeline.js", "src/api.js"],
      "locked_at": "2026-03-17T04:10:00",
      "expires_at": "2026-03-17T04:15:00",
      "status": "active"
    }
  ],
  "collisions": [],
  "updated_at": "2026-03-17T04:10:00"
}
```
- If another agent has claimed files you need, wait or pick different files.
- If a claim is expired (`expires_at` in the past), treat it as released.
- Never assume a file is free without checking.

### 2. Lock Your Task
Before starting work, write your claim to `state/agent-coordination.json`:
```json
{
  "agent": "your-role-name",
  "task": "short-task-description",
  "files": ["list", "of", "files", "you-will-touch"],
  "locked_at": "<current ISO timestamp>",
  "expires_at": "<current time + 5 minutes>",
  "status": "active"
}
```
- Lock duration: 5 minutes max (matches fast-iteration time-box).
- List every file you plan to read-write (read-only files do not need locks).
- Set status to `active`.

### 3. Update Progress
While working, update your claim's status:
- `active` — currently working
- `partial` — made progress but not done, releasing lock temporarily
- `blocked` — cannot proceed, see blocker field
- `complete` — finished, lock will be released

Add a `progress` field:
```json
{
  "agent": "implementer",
  "task": "add-retry-logic",
  "files": ["src/api-client.js"],
  "status": "active",
  "progress": "70% - retry logic written, testing next",
  "locked_at": "2026-03-17T04:10:00",
  "expires_at": "2026-03-17T04:15:00"
}
```

### 4. Never Overlap Files
Hard rule: two agents must never write to the same file simultaneously.

If you discover a collision:
1. Stop writing immediately.
2. Add an entry to the `collisions` array:
```json
{
  "agents": ["implementer", "reviewer"],
  "file": "src/api-client.js",
  "detected_at": "2026-03-17T04:12:00",
  "resolution": "implementer yields, reviewer completes first"
}
```
3. The agent with the older lock keeps priority.
4. The yielding agent switches to a different task (see `fast-iteration` skill).

### 5. Release Locks When Done
When your task completes or you switch away:
1. Set your claim status to `complete` or remove it from `claims`.
2. Update `updated_at` timestamp.
3. If you produced artifacts, note them so the next agent can pick up:
```json
{
  "agent": "implementer",
  "task": "add-retry-logic",
  "status": "complete",
  "artifacts": ["src/api-client.js", "tests/api-client.test.js"],
  "completed_at": "2026-03-17T04:14:30"
}
```

### 6. Report Blockers
When blocked, write to `state/auto-remediation.json`:
```json
{
  "blocker_type": "resource|model|file_lock|test_failure|dependency",
  "status": "needs_remediation",
  "message": "Ollama model qwen2.5:3b not responding after 30s timeout",
  "agent": "retriever",
  "task": "extract-context",
  "tried": ["restart ollama", "switch to codellama", "check port 11434"],
  "fallback": "Use cloud model sonnet for this stage",
  "reported_at": "2026-03-17T04:11:00"
}
```
- Always list what you already tried.
- Always suggest a fallback if you have one.
- The orchestrator or lead agent reads this file to resolve blockers.

## Coordination Checklist (Every Task)
1. [ ] Read `state/agent-coordination.json`
2. [ ] Check for file conflicts with active claims
3. [ ] Write your claim with file list and expiry
4. [ ] Do the work (max 5 minutes)
5. [ ] Update progress at least once during work
6. [ ] Release lock when done or switching
7. [ ] Report any blockers to `state/auto-remediation.json`
8. [ ] Leave artifacts list for downstream agents

## Anti-Patterns
- Starting work without checking coordination state.
- Holding locks longer than 5 minutes.
- Locking files you only read (not write).
- Ignoring expired locks (treat them as stale, clean them up).
- Silently failing without reporting the blocker.

## Integration
- Reads/Writes: `state/agent-coordination.json`
- Writes: `state/auto-remediation.json`
- Related skills: `fast-iteration`, `lead-coordination`, `team-orchestration`
