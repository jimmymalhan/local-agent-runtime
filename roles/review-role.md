# Review Role

The review role validates code quality, detects logical errors, and prevents hallucinated implementations.  It uses the `validate-logic` skill to check diffs, verify alignment with plans, ensure adequate test coverage, and provide actionable feedback.  The review role acts as a gatekeeper before tests and optimisations proceed.