# Implement Feature v2 — Chain-of-Thought Scaffolding

Upgraded implementation skill with explicit reasoning steps before code generation.

## Chain-of-Thought Protocol

Before writing any code, the implementer must work through these reasoning steps in order:

### Step 1: Understand the Request
- Restate the user's request in one sentence.
- List the specific deliverables (files to create, files to edit, commands to run).
- Identify what is NOT being asked (scope boundaries).

### Step 2: Locate Existing Code
- List every file that will be read or modified.
- For each file, confirm it exists in the repo (never invent paths).
- Note the current state of each file (what functions, classes, or sections are relevant).

### Step 3: Plan the Changes
- For each file, describe the specific change (add function X, modify block Y, delete line Z).
- Identify dependencies between changes (order matters).
- Flag any change that could break existing functionality.

### Step 4: Implement
- Write the actual code changes.
- Use the repo's existing patterns (imports, naming conventions, error handling style).
- Keep changes minimal — do not refactor unrelated code.

### Step 5: Verify
- For each file changed, confirm the edit is syntactically valid.
- List the test commands that would validate the changes.
- Note any manual verification steps needed.

## Quality Checks (Self-Audit Before Output)

Before producing final output, the implementer must answer:

1. **File paths**: Are ALL referenced file paths real? (Check against repo context.)
2. **Imports**: Do all imports reference real modules present in the repo or standard library?
3. **Existing code**: Does the edit target code that actually exists in the file? (Never edit phantom lines.)
4. **Syntax**: Does every code block parse cleanly?
5. **Completeness**: Does the output cover every deliverable from Step 1?

If any answer is "no", revise before outputting.

## Differences from v1

| Aspect | v1 (implement-feature.md) | v2 (this file) |
|---|---|---|
| Reasoning | Implicit | Explicit 5-step chain-of-thought |
| Path verification | Not required | Required before output |
| Self-audit | None | 5-point quality checklist |
| Scope boundaries | Not stated | Explicitly identified |
| Dependency ordering | Ad hoc | Planned in Step 3 |

## When to Use v2

- Tasks involving 3+ file changes.
- Tasks where the user's request is ambiguous or complex.
- Tasks where prior attempts produced hallucinated paths or broken code.
- Any task flagged by the cross-role critique loop.
