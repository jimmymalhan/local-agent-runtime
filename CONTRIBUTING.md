# Contributing

All changes must go through a feature branch. Do not commit directly to `main`.
Before starting new work, always check whether the work already exists. If it does, update it in place or skip it. Do not create duplicate workflows, scripts, or docs.
Do not commit the private local tool inventory. Keep it in ignored local config only.
Default automation and agent execution must stay local-only unless a user explicitly approves a different path.
At session start, confirm the local runtime is available. If it is not, stop instead of silently falling back to an external model path.
If you need to remove or replace something, deprecate it first, keep an older-version path available, and verify current backups plus the replacement are active before deleting anything.

## Workflow

1. **Create a feature branch**
   ```bash
   git checkout -b feature/your-change-name
   ```

2. **Check existing work first**
   ```bash
   rg -n "keyword-for-the-work" .
   ```

3. **Make your changes** with multiple logical commits
   ```bash
   git add path/to/file
   git commit -m "feat(scope): first logical change"

   git add path/to/another-file
   git commit -m "docs(scope): document the workflow change"
   ```

4. **Run relevant local validation**
   ```bash
   bash scripts/merge_gate.sh "$PWD"
   ```

5. **Review the current changes locally**
   Use the local CLI review flow or the project-specific reviewer.
   Interactive task flows should auto-run a local review at the end.

6. **Handle deprecation before deletion**
   - Move the outgoing version to an older-version or deprecated path when practical.
   - Confirm the replacement is running.
   - Confirm the newest backup or checkpoint can restore the prior state.
   - Only then remove the deprecated implementation if it is still necessary.

7. **Push and open a PR**
   ```bash
   git push -u origin feature/your-change-name
   ```

## Commit Naming

Use Conventional Commits:

- `feat(scope): ...`
- `fix(scope): ...`
- `docs(scope): ...`
- `refactor(scope): ...`
- `chore(scope): ...`

## PR Rule

- Every work item should end in a PR.
- Prefer multiple logical commits instead of one large commit.
- If the work already exists, update it or skip it instead of creating a duplicate implementation.
- Never merge on red. `bash scripts/merge_gate.sh "$PWD"` must pass locally, and the PR must have a green `Validate Runtime` check before merge.
- Never hard-delete active behavior first. Deprecate, back up, verify the replacement, then remove.
