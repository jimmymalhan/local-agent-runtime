Counter-analysis skill for local agents.

Use this when a role must challenge the first explanation and surface materially different alternatives.

Rules:
- Generate at least one competing explanation before settling on a conclusion.
- Prefer alternatives that would change the fix, rollback, or test plan.
- Attack weak assumptions, stale state, missing coverage, and overconfident wording.
- If two explanations remain plausible, state the tie-breaker evidence needed.
- Do not create noise: alternatives must be materially different, not wording variations.

Expected behavior by role:
- Reviewer: challenge the first proposed fix and look for regressions.
- Debugger: test whether the symptom source is upstream, downstream, or environmental.
- Director: force scope cuts when alternatives show weak ROI.
