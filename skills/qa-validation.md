# Skill: QA Validation

**Trigger:** When the workflow needs a final technical quality gate before handoff.

**Checklist:**
1. Verify the main commands are internally consistent.
2. Verify checkpoint, restore, and rollback paths are present when relevant.
3. Verify progress, team-status, review, and verification flows line up with the actual scripts.
4. Check `logs/qa-suite-report.md` when available and treat failing smoke tests as release blockers.
5. Check `logs/runtime-heal-report.md` when available and treat stale-lock or broken-session issues as workflow bugs, not user error.
6. Call out missing tests, missing validation, or unclear operational assumptions.

**Output Format:**
```
## QA Findings
- ...

## Required Fixes
- ...

## Release Gate
- pass|fail
```
