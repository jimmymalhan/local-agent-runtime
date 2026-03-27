# Agent Integration Guide — Token Efficiency APIs

**Quick reference for agents to use new token-efficient APIs.**

---

## 1. Output Contract (MANDATORY)

Every agent response must be **valid JSON** matching the contract:

```json
{
  "status": "done|blocked|needs_review|partial",
  "summary": "Result in ≤100 chars",
  "confidence": 0-100,
  "evidence": ["actual output", "verification"],
  "files_changed": ["relative/path.js"],
  "next_steps": ["blocker 1", "blocker 2"],
  "errors": [{"type": "validation|timeout", "message": "..."}],
  "rollback_safe": true
}
```

**Why:** Eliminates re-parsing overhead (saves 40% tokens per call).

**Example:**
```json
{
  "status": "done",
  "summary": "Added validation to POST /diagnose, 5 tests pass",
  "confidence": 87,
  "evidence": ["npm test output: 319 pass", "GitHub Actions #451 green"],
  "files_changed": ["src/api/routes.js", "tests/api.test.js"],
  "next_steps": [],
  "errors": [],
  "rollback_safe": true
}
```

---

## 2. Task Registry API

**Don't** read `projects.json` or `AGENT_TODO.md` repeatedly.
**Do** use the registry:

```python
from local_agents.registry.task_registry import get_registry

registry = get_registry()

# Get pending tasks for you
pending = registry.get_pending(agent_name="frontend_agent")
# → ["t-abc123", "t-def456"]

# Get task details (minimal: id, title, status)
task = registry.get_task("t-abc123")
# → {"id": "t-abc123", "title": "Add form validation", "status": "pending"}

# Claim task
registry.claim("t-abc123", "frontend_agent")

# Mark done
registry.done("t-abc123", "Form validation added + 10 tests pass", confidence=92)

# Mark blocked
registry.block("t-abc123", "Requires auth API endpoint from backend")
```

**Why:** Saves ~1,500 tokens per lookup (no repeated file I/O).

---

## 3. Event Bus API

**Don't** poll files repeatedly.
**Do** subscribe to events:

```python
from local_agents.registry.event_bus import get_bus

bus = get_bus()

# Publish your work
bus.publish(
    event_type="task_completed",
    agent_name="frontend_agent",
    task_id="t-abc123",
    payload={"result": "Form validation added"}
)

# Subscribe to changes (get only new events)
last_id = 0
while True:
    new_events = bus.get_delta(since_id=last_id)
    for event in new_events:
        print(f"Agent {event['agent_name']}: {event['event_type']}")
        last_id = event["id"]
    time.sleep(5)
```

**Why:** Saves ~2,000 tokens per cycle (delta reads instead of full reads).

---

## 4. State Compression

**Don't** load 100KB+ state.json.
**Do** use hot state only:

```python
from local_agents.registry.state_compressor import StateCompressor

compressor = StateCompressor()

# Get only recent tasks (≤5KB)
hot_state = compressor.get_hot_state()
recent_tasks = hot_state["tasks"]

# Archive old tasks (automatic)
result = compressor.compress()
# → {"archived_tasks": 50, "remaining_hot_tasks": 50}

# Retrieve archived task if needed
old_task = compressor.get_task_from_archive("task-id-from-2026-01-01")
```

**Why:** Saves ~500 tokens per read (small files load faster).

---

## 5. Core Rules (from CLAUDE_CORE.md)

Before responding:
1. ✅ Read the code/requirements
2. ✅ Implement and test locally
3. ✅ Run `npm test` — never claim without proof
4. ✅ Output JSON contract
5. ✅ Mark confidence only with evidence

---

## 6. Confidence Scoring (Quick Version)

- **95-100**: Tests pass locally + in GitHub Actions, 90%+ coverage, rollback verified
- **80-94**: Code matches plan, tests pass, minor unknowns documented
- **60-79**: Implemented, some flows untested, assumptions present
- **<60**: Do not release — incomplete or unverified

**Merge gate (HARD)**: Confidence ≥ 95% with evidence, or PR stalls.

---

## 7. Example Agent Task Flow

```python
#!/usr/bin/env python3
"""Example agent task execution."""

import json
from local_agents.registry.task_registry import get_registry
from local_agents.registry.event_bus import get_bus

def run_task():
    registry = get_registry()
    bus = get_bus()

    # 1. Get pending tasks
    pending = registry.get_pending(agent_name="my_agent")
    if not pending:
        return {"status": "done", "summary": "No pending tasks"}

    task_id = pending[0]
    task = registry.get_task(task_id)

    # 2. Claim task
    registry.claim(task_id, "my_agent")
    bus.publish("task_claimed", "my_agent", task_id)

    try:
        # 3. Do the work (implement + test locally)
        result = do_work(task)

        # 4. Mark done with JSON contract
        registry.done(task_id, result["summary"], confidence=result["confidence"])
        bus.publish("task_completed", "my_agent", task_id, result)

        return result  # ← Must be valid JSON contract
    except Exception as e:
        registry.block(task_id, str(e))
        bus.publish("error_occurred", "my_agent", task_id, {"error": str(e)})
        return {
            "status": "blocked",
            "summary": f"Error: {str(e)[:80]}",
            "confidence": 0,
            "next_steps": [f"Debug: {str(e)}"],
        }

def do_work(task):
    """Implement task, test locally, return JSON contract."""
    # ... implementation ...
    return {
        "status": "done",
        "summary": "Task completed with verification",
        "confidence": 89,
        "evidence": ["npm test: 15 new tests pass"],
        "files_changed": ["src/file.js"],
        "errors": [],
        "rollback_safe": True,
    }

if __name__ == "__main__":
    result = run_task()
    print(json.dumps(result, indent=2))  # ← Valid JSON response
```

---

## 8. Token Savings Checklist

Before submitting work:
- [ ] Output is valid JSON (not prose)
- [ ] Using registry API (not reading files)
- [ ] Using event bus (not polling)
- [ ] Tests run locally (`npm test` pass)
- [ ] Confidence score backed by evidence
- [ ] No invented files/APIs/results

---

## 9. When Tests Fail

```python
# ❌ Wrong:
return {"status": "done", "summary": "Should work"}

# ✅ Right:
return {
    "status": "blocked",
    "summary": "Test failure: validation_error",
    "confidence": 0,
    "next_steps": ["npm test output: 3 tests failing", "See errors in evidence"],
    "evidence": ["npm test output here..."],
}
```

---

## 10. Questions?

Refer to:
- `.claude/CLAUDE_CORE.md` — Non-negotiable rules
- `.claude/contracts/` — JSON schemas and prompt templates
- `local-agents/registry/` — API documentation in docstrings
