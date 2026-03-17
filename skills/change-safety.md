Change-safety skill for local agents.

Use this when a role is making or validating code changes.

Rules:
- Prefer the smallest diff that resolves the blocker or delivers the feature increment.
- Preserve existing behavior unless the task explicitly requires behavioral change.
- Add or update the nearest relevant test when a behavior change is introduced.
- Call out rollback points, risky files, and interface contracts before broad edits.
- Avoid touching unrelated files when the worktree is already mixed.

Expected behavior by role:
- Architect: constrain the change surface.
- Implementer: ship the smallest useful diff.
- Tester: verify the changed contract, not the whole world.
