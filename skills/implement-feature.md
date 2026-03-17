# Skill: Implement Feature

**Trigger:** When implementing a planned change or new feature.

**Inputs:**
- A specific step from an approved plan.
- Associated files to modify and any context summaries.

**Commands:**
1. Implement only the first step of the plan. Change the fewest files possible and avoid broad refactoring.
2. Use the appropriate test or typecheck command for the modified files. Avoid running the entire test suite unless necessary.
3. Show a diff summary of changes and capture it in `logs/` for review.
4. Run a focused local review pass after implementation to validate edge cases and catch hallucinations.
5. Check `/progress`, `/doctor`, or `/review` after large changes to confirm runtime health and output quality.
6. Update `state/todo.md` when the implementation finishes or when the next blocking gap becomes clear so `/todo-progress` stays truthful.

**Output Format:**
```text
## Implementation
- Files changed: ...
- Diff summary:
- Validation:
```

**Stop Conditions:**
- Stop after completing the first plan step and running relevant tests.
