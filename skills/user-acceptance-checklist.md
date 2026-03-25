# Skill: User Acceptance Checklist

**Trigger:** When the workflow needs a final non-technical expectation check.

**Checklist:**
1. Would a non-technical user understand what to run first?
2. Are the benefits and limitations obvious?
3. Are the commands short and realistic?
4. Does the result feel like what the user asked for, not just what the engineer built?
5. If `logs/uat-suite-report.md`, `logs/qa-suite-report.md`, or `logs/latest-response.md` exist, use them to judge whether the final experience is actually ready.
6. Fail the review if the answer hides the first-run command, the progress command, or the recovery path.

**Output Format:**
```
## Acceptance Review
- ...

## Confusing Parts
- ...

## Expectation Match
- yes|no
```
