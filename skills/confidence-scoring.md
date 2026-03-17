Confidence-scoring skill for local agents.

Use this when a role must decide whether the current answer is strong enough to ship.

Rules:
- Score confidence implicitly from evidence quality, test coverage, reproduction quality, and unresolved risk.
- High confidence requires direct evidence plus at least one validation path.
- Lower confidence when key files were not read, tests were not run, or competing explanations remain open.
- When confidence is not high, propose the fastest next validation step.
- Keep the output binary in spirit: ship, hold, or ship-with-risk.

Expected behavior by role:
- QA: gate completion on evidence plus validation.
- Benchmarker: compare current output quality against the local bar.
- CEO and Summarizer: compress the answer without overstating certainty.
