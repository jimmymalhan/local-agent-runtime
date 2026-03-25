# Skill: Validate Logic

**Trigger:** When reviewing code for correctness, security, and maintainability.

**Inputs:**
- The diff summary and list of changed files.
- Contextual summaries or relevant specification documents.

**Commands:**
1. Review the diff and check for logical errors, security flaws, and maintainability issues.  Use code compilation or linter tools where available to detect issues【390377402365791†L257-L266】.
2. Ensure the implementation aligns with the plan and does not introduce unrelated changes.
3. Verify that tests cover new code paths and edge cases; request additional tests if needed.
4. Provide a summary of findings and recommendations for improvement.

**Output Format:**
```
## Review Summary
- Issues found: ...
- Recommendations: ...

```

**Stop Conditions:**
- Stop after providing a thorough review summary.
