# AI/ML Standards

**Purpose:** Provide guidelines for machine learning model components, ensuring quality, safety, and measurable outcomes.

## Requirements
- Define clear input/output contracts for models.
- Include evaluation loops with metrics (accuracy, precision, recall, etc.) and baseline comparisons.
- Document prompt engineering decisions and provide examples of typical inputs and outputs.
- Establish safety boundaries (rate limits, content filters, guardrails against sensitive data).
- Add unit or integration tests where feasible (e.g., validating preprocessing logic or scoring functions).

## Verification
- `ai-ml-engineer` ensures evaluation artifacts exist and metrics are tracked.
- `evidence-reviewer` demands actual metric results, not statements of adequacy.
- `principal-engineer-reviewer` examines long‑term maintenance plans for models.

## Failure Learning
- When an ML failure occurs (drift, bias, outage), update this rule with the missing control and record learning in `.claude/PROJECT_STATUS.md`.
