# Agentic AI Standards

**Purpose:** Establish best practices for designing, orchestrating, and reviewing multi‑agent workflows.

## Requirements
- Clearly define each agent's responsibility and input/output expectations.
- Use shared memory patterns judiciously; document what is stored and why.
- Include retry logic and failure handling for inter‑agent coordination.
- Avoid unnecessary agent proliferation; prefer simple delegation over complex pipelines.
- Provide a plan for human override or stop conditions to prevent runaway loops.

## Verification
- `agentic-ai-engineer` checks workflows for safe coordination and tool usage.
- `code-reviewer` and `evidence-reviewer` ensure tasks are well-bounded and not hallucinated.
- `staff-engineer-reviewer` assesses system fit and potential maintenance burden.

## Failure Learning
- If agent confusion or infinite loops occur, add concrete checks in this rule and log the issue in `.claude/PROJECT_STATUS.md`.
