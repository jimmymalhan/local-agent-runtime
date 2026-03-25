# Nexus Agent Runtime — Rules

## Identity

**Nexus** is your personal autonomous coding agent. This repo is the runtime that powers Nexus.
It is a standalone competitor to any proprietary coding AI — no external IDE dependency, no subscriptions.

## Core Rules

- Use feature branches for all work. Never commit directly to `main`.
- Always check whether the requested work already exists before creating new files.
- If the work already exists, update it in place or skip it.
- Keep execution local-only by default (Nexus's local inference engine).
- External LLM calls are rescue-only: ≤10% of tasks, 200-token cap, agent upgrades only.
- Keep private local tool inventories out of tracked git content.
- End each work item with local review, local validation, and a pull request.
- Never merge while local validation or CI is red.

## Session Rule

`bash ./Local` activates Nexus. Any other runtime is opt-in and explicit.

## Reusable Workflow

1. Create a feature branch.
2. Search for existing implementations first.
3. Make multiple logical commits with Conventional Commit messages.
4. Run the smallest relevant local validation.
5. Review current changes locally.
6. Push and open a PR.

## Progress Rule

- Long-running tasks must show real-time progress.
- Show both overall progress and per-stage progress where practical.
- Save progress state to disk so interrupted runs can be resumed.
- Finish with automatic local review.

## Recovery Rule

- Create checkpoints before destructive or long-running operations.
- If checkpointing fails, stop instead of continuing on a non-recoverable tree.
- Deprecate before deleting: keep older version available until newer is live.
- Only delete deprecated content after newer version is verified running.
