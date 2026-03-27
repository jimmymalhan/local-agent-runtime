# Policy Enforcement Guide — Token Budget & Model Routing

**Status:** ✅ Implementation complete (Phase A: Enforce existing policies)

---

## Overview

This guide explains how to enforce the 4 core token efficiency policies:

1. **10% Rescue Budget Cap** — Max 10% of tasks can use Claude rescue
2. **200-Token Hard Cap** — Each rescue call limited to 200 tokens
3. **Model Routing** — Haiku (validation), Sonnet (analysis), Opus (rescue-only)
4. **Agent-Level Budgets** — Max 1,000 tokens/agent/day

---

## Core Modules

### 1. Token Enforcer (validates policies)

**File:** `local-agents/registry/token_enforcer.py`

```python
from registry.token_enforcer import get_enforcer

enforcer = get_enforcer()

# Check 10% budget compliance
allowed, reason = enforcer.check_rescue_budget(
    total_tasks=100,
    rescued_count=8  # 8% OK, 11% would fail
)

# Check token cap for model
allowed, reason = enforcer.enforce_token_cap(
    model="opus",
    tokens_used=180  # 180 OK (cap is 200)
)

# Validate model routing
valid, reason, recommended = enforcer.validate_model_routing(
    task_type="analysis",
    assigned_model="sonnet"  # OK
)

# Check agent daily budget
allowed, reason = enforcer.check_agent_budget(
    agent_name="frontend_agent",
    tokens_requested=200  # 200 OK if agent has budget
)

# Get today's usage
usage = enforcer.get_agent_daily_usage("frontend_agent")
# → {"tokens_used": 450, "calls": 3}
```

---

### 2. Output Validator (validates contracts + models)

**File:** `.claude/contracts/output_validator.py`

```python
from contracts.output_validator import (
    validate_agent_response,
    validate_before_rescue,
    enforce_output_json
)

# Validate agent output against JSON contract
valid, error, parsed = validate_agent_response(
    agent_output=agent_raw_response,
    agent_name="executor",
    model="sonnet",  # Validates model routing
    task_id="t-123"
)

if not valid:
    return {"status": "needs_review", "summary": error, "confidence": 0}

# Pre-flight check before rescue attempt
eligible, reason = validate_before_rescue(
    agent_name="refactor",
    total_tasks=100,
    rescued_count=8,
    failed_attempts=3  # Must be ≥3
)

if not eligible:
    print(f"Cannot rescue: {reason}")

# Enforce JSON output (returns error contract if parse fails)
parsed = enforce_output_json(raw_output)
```

---

### 3. Rescue Enforcer (pre-flight gates)

**File:** `local-agents/orchestrator/rescue_enforcer.py`

```python
from orchestrator.rescue_enforcer import (
    check_rescue_eligible,
    prepare_rescue_context,
    execute_rescue_call,
    log_rescue_attempt
)

# 3-point gate for rescue eligibility
eligible, reason = check_rescue_eligible(
    task={
        "id": "t-123",
        "title": "Fix timeout",
        "category": "bug_fix"  # NOT in {"research", "doc", "documentation"}
    },
    fail_count=3,  # Must be ≥3
    rescued_count=8,
    total_tasks=100  # 8/100 = 8% < 10% OK
)

if eligible:
    # Prepare context with token cap enforcement
    valid, msg, context = prepare_rescue_context(
        task=task,
        agent_source=agent_source_code[:1500],
        failure_log=last_3_failures
    )

    # context["estimated_tokens"] guaranteed ≤ 200

    if valid:
        result = execute_rescue_call(
            task=task,
            agent_name="executor",
            failure_log=failures,
            agent_source=source
        )
        log_rescue_attempt(
            task_id=task["id"],
            agent_name="executor",
            eligible=True,
            reason="Rescue executed",
            tokens_used=result["tokens_used"],
            success=True
        )
```

---

## Integration Points

### With Orchestrator (orchestrator/main.py)

Replace lines 249-267 (rescue eligibility check) with:

```python
from orchestrator.rescue_enforcer import check_rescue_eligible, log_rescue_attempt

# Before calling _claude_rescue()
eligible, reason = check_rescue_eligible(
    task=task,
    fail_count=fail_count,
    rescued_count=len(rescued_ref),
    total_tasks=len(tasks_batch)
)

if not eligible:
    print(f"[RESCUE DENIED] {reason}")
    log_rescue_attempt(
        task_id=task["id"],
        agent_name=agent_name,
        eligible=False,
        reason=reason
    )
    continue

# Proceed with _claude_rescue()
```

### With Agent Dispatch (agents/__init__.py)

After agent response, validate with:

```python
from contracts.output_validator import validate_agent_response

result = agent_run(task)
valid, error, parsed = validate_agent_response(
    result,
    agent_name=agent_name,
    model="sonnet"  # or "haiku" or "opus"
)

if not valid:
    return {
        "status": "needs_review",
        "summary": f"Output validation failed: {error}",
        "confidence": 0
    }

return parsed
```

### With Provider Router (providers/router.py)

Update get_provider() to enforce model tiers:

```python
from registry.token_enforcer import get_enforcer

def get_provider(mode, task_type=None):
    enforcer = get_enforcer()

    # Map task → model
    if task_type == "validation":
        model = "haiku"
    elif task_type == "analysis":
        model = "sonnet"
    elif mode == "rescue":
        model = "opus"

    # Validate routing
    valid, reason, recommended = enforcer.validate_model_routing(task_type, model)

    if not valid:
        print(f"[ROUTING] {reason}, using {recommended}")
```

---

## Policy Enforcement Checklist

### Before Claude Rescue Call

- [ ] Task failed ≥3 times (check `fail_count >= 3`)
- [ ] Rescue budget < 10% (check `rescued_count / total_tasks < 0.10`)
- [ ] Task category in eligible set (NOT in {"research", "doc", "documentation"})
- [ ] Rescue context fits ≤200 tokens (use `prepare_rescue_context()`)
- [ ] Log attempt to `reports/rescue_attempts.jsonl`

### Before Agent Response

- [ ] Output is valid JSON (use `enforce_output_json()`)
- [ ] JSON matches schema (status, summary, confidence, evidence, files_changed, errors)
- [ ] Confidence ≥90% requires evidence
- [ ] Status "done" requires confidence ≥95%
- [ ] Model routing correct for task type

### Before Agent Dispatch

- [ ] Check agent daily budget < 1,000 tokens (use `check_agent_budget()`)
- [ ] Log token usage (use `log_token_usage()`)
- [ ] Track in `local-agents/state/agent_budgets.json`

---

## Monitoring & Auditing

### Token Usage Tracking

```python
from registry.token_enforcer import get_enforcer

enforcer = get_enforcer()

# Daily stats per agent
usage = enforcer.get_agent_daily_usage("frontend_agent")
print(f"Today: {usage['tokens_used']} tokens, {usage['calls']} calls")

# Overall stats
stats = enforcer.get_stats()
print(f"Total: {stats['total_tokens_used']} tokens")
print(f"Avg/call: {stats['avg_tokens_per_call']}")
```

### Rescue Attempts Log

**Location:** `local-agents/reports/rescue_attempts.jsonl`

Each line is a JSON record:
```json
{
  "ts": "2026-03-26T12:34:56.789Z",
  "task_id": "t-abc123",
  "agent": "executor",
  "eligible": true,
  "reason": "Rescue executed",
  "tokens_used": 185,
  "success": true
}
```

### Token Usage Log

**Location:** `local-agents/state/token_usage.jsonl`

```json
{
  "ts": "2026-03-26T12:34:56.789Z",
  "agent": "frontend_agent",
  "model": "sonnet",
  "tokens": 150,
  "task_id": "t-abc123"
}
```

---

## Environment Variables

Control policies via env vars in `.env`:

```bash
# Token caps
NEXUS_CLAUDE_BUDGET_PCT=10.0          # Max rescue budget %
NEXUS_CLAUDE_TOKEN_CAP=200            # Tokens per rescue call
TOKEN_PER_AGENT_BUDGET=1000           # Tokens per agent per day

# Model selection
NEXUS_REMOTE_MODEL=claude-sonnet-4-6  # Default remote model
NEXUS_LOCAL_MODEL=qwen2.5-coder:7b    # Default local model
```

---

## Testing Policies

```bash
# Test token enforcer
python3 local-agents/registry/token_enforcer.py

# Test output validator
python3 .claude/contracts/output_validator.py

# Test rescue enforcer
python3 local-agents/orchestrator/rescue_enforcer.py
```

---

## Summary: What's Enforced Now

| Policy | Module | Check | Hard Enforcement |
|--------|--------|-------|------------------|
| **10% Rescue Budget** | rescue_enforcer.py | `check_rescue_eligible()` | ✅ Yes (3-point gate) |
| **200-Token Cap** | rescue_enforcer.py | `prepare_rescue_context()` | ✅ Yes (truncates context) |
| **Model Routing** | output_validator.py | `validate_model_routing()` | ✅ Yes (fails validation) |
| **Agent Daily Budget** | token_enforcer.py | `check_agent_budget()` | ✅ Yes (blocks if over) |
| **Output Contract** | output_validator.py | `validate_output_contract()` | ✅ Yes (returns error) |
| **Confidence + Evidence** | output_validator.py | `validate_agent_response()` | ✅ Yes (fails if missing) |

---

## Phase B: Next Steps (Integration)

Once Phase A enforcement is in place:

1. **Integrate into orchestrator/main.py** — Use `rescue_enforcer` pre-flight checks
2. **Integrate into agents/__init__.py** — Use `output_validator` on all responses
3. **Integrate into providers/router.py** — Enforce model tier routing
4. **Add dashboard widgets** — Token usage charts, budget gauges
5. **Enable continuous monitoring** — Alert on policy violations

---

## Questions?

Refer to:
- `local-agents/registry/token_enforcer.py` — Policy validation (docstrings)
- `.claude/contracts/output_validator.py` — Contract enforcement
- `local-agents/orchestrator/rescue_enforcer.py` — Rescue gates
