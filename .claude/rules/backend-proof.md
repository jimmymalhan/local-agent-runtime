# Backend Proof Standards

**Purpose:** Specify the evidence required for backend modifications, ensuring reliability, error handling, and observability are demonstrably working.

## Requirements
- Every API or server change must include:
  - Unit tests exercising new validation, retries, and error cases.
  - Integration tests hitting the endpoints with both valid and invalid inputs.
  - Logs or simulated runs showing retry behavior and error messages.
  - Documentation updates to API.md or similar contract documents.
- Proof may also include load test results or database migration verification when applicable.

## Verification
- `qa-engineer` validates that tests cover all critical flows.
- `senior-backend-reviewer` and `staff-engineer-reviewer` look for missing edge cases or undiscovered failure modes.
- Observability metrics or simulated logs should be provided when possible.

## Failure Learning
- Any backend regression triggers an update to this rule with the missing proof type.
- Record the incident and corrective action in `.claude/PROJECT_STATUS.md`.
