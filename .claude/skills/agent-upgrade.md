# Skill: Agent Upgrade (Ultraadvanced)

**Trigger:** When a local agent fails 3+ times on the same task category and Claude rescue is eligible.

**Goal:** Write the SMALLEST surgical fix to the agent's system prompt or logic that permanently patches the failure pattern. Never fix the task. Fix the agent.

## Protocol

### Step 1: Diagnose the Pattern
From the failure log, identify:
- What the agent consistently outputs wrong (placeholder paths? no assertions? truncated code? wrong command?)
- Which dimension is lowest (plan_accuracy / code_correctness / hallucination / actionability)?
- Is this a prompt issue (wrong instructions) or logic issue (wrong parsing)?

### Step 2: Select Fix Type
| Pattern | Fix Type |
|---------|----------|
| Uses `/path/to/file.py` placeholder | Prompt injection: force real paths |
| Uses `python` not `python3` | Logic: exec_run normalization |
| Truncates output | Prompt injection: "NEVER truncate" |
| No assertions | Prompt injection: require `__main__` + 3 asserts |
| Syntax errors | Prompt injection: require py_compile check |
| Wrong imports | Prompt injection: list stdlib modules |
| Empty output | Logic: increase num_ctx, lower temperature |

### Step 3: Write the Fix
Output format:
```
FIX: <one sentence to append to agent SYSTEM_PROMPT or inject before run(task)>
PATTERN: <snake_case name of the failure pattern>
DIMENSION: <plan_accuracy|code_correctness|hallucination|actionability>
CONFIDENCE: <0-100>
```

Hard limits:
- ONE fix per rescue call
- FIX line must be < 200 chars
- Never rewrite the whole agent
- Never fix the task directly

### Step 4: Validate the Fix
After applying:
- Rerun the failed task on the upgraded agent
- Check composite score improved by >= 10 points
- Log to `reports/claude_rescue_upgrades.jsonl` with `task_rerun_passed: true/false`

## Quality Rubric for Fixes (from benchmark-against-quality-v2.md)

A good fix scores:
| Criterion | Good | Bad |
|-----------|------|-----|
| Specificity | Names the exact failure mode | Vague ("improve output") |
| Scope | One sentence, one pattern | Rewrites system prompt |
| Verifiability | Can be tested on failed task | Untestable |
| Permanence | Fixes ALL future occurrences | Only fixes this task |
| Token cost | < 50 tokens | > 200 tokens |

## Example Fixes

**Pattern: placeholder_path**
```
FIX: NEVER write /path/to/file.py — always use real absolute paths starting with {BOS}/ where BOS is your working directory.
PATTERN: placeholder_path
DIMENSION: plan_accuracy
CONFIDENCE: 95
```

**Pattern: missing_assertions**
```
FIX: Every implementation MUST include a __main__ block with at least 3 assert statements that prove the function works on normal input, empty input, and edge cases.
PATTERN: missing_assertions
DIMENSION: actionability
CONFIDENCE: 90
```

**Pattern: truncated_code**
```
FIX: NEVER truncate code with comments like "# rest of implementation" or "...". Write every line of every function completely.
PATTERN: truncated_code
DIMENSION: hallucination
CONFIDENCE: 98
```
