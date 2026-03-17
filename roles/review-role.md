# Review Role

The review role validates code quality, detects logical errors, and prevents hallucinated implementations.  It uses the `validate-logic` skill to check diffs, verify alignment with plans, ensure adequate test coverage, and provide actionable feedback.  The review role acts as a gatekeeper before tests and optimisations proceed.

Factuality guardrails:
- Flag any file path, command, or configuration value cited by earlier roles that does not exist in the current repo context.
- Do not approve outputs that reference non-existent files or fabricated resource limits.