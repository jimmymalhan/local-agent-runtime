# Jimmy — Personal Agent Runtime

## What This Is

Jimmy is your personal autonomous coding agent. This repo runs Jimmy locally on your machine.

- **Local inference**: primary model runs via local inference engine (no external API by default)
- **Self-improving**: Jimmy upgrades its own prompts every version based on benchmark results
- **Private**: all data stays on your machine unless you explicitly enable the external LLM rescue path

## Session Policy

**Jimmy is always on** — `bash ./Local` activates the full runtime.

External LLM access is rescue-only: enabled only when Jimmy fails a task 3× with different approaches, and only to upgrade Jimmy's agents (never to fix tasks directly). Hard cap: 10% of tasks, 200 tokens per rescue.

## Capabilities

- CLI session commands: /compact, /undo, /copy, /mention, /init, /personality, /debug-config
- Reusable skills, roles, and workflows
- Real-time progress tracking
- Hardware-aware resource guardrails
- Private tool registry support
- Branch and PR hygiene rules

## Rules

- Keep default execution local-only (Jimmy's inference engine).
- Always check for existing work first. Update or skip duplicates.
- Use feature branches and pull requests. Never commit to `main` directly.
- Prefer multiple logical commits over one large dump commit.
- Keep private local tool inventories out of tracked git files.
- Show real-time progress for long-running work.
- Use checkpoints and recovery state where practical.
- Deprecate before deleting.

## Main Branch Protection

- `main` is protected. No direct pushes. PR-only merges.
- Do not force-push or delete `main`.

## Session Policy

When given a coding task, execute the work in that session instead of replying with a command for the user to run.
Local runtime is opt-in — Claude Code activates it only when the user explicitly invokes `nexus` or `bash ./Local`.

## Validation

- Run smallest relevant local validation before handoff.
- Review current changes locally before handoff.
