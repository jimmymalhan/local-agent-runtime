# Local Agent Repo

## Session Policy

**When the user asks to open Codex, Claude, or Cursor**—help them open those sessions. Do not route session-open requests to local runtime. Codex, Claude, and Cursor run independently.

**For implementation/coding tasks inside a user-chosen Codex, Claude, or Cursor session:** execute the work in that session instead of replying with a command for the user to run.

**Local runtime is opt-in**—use `bash ./Local`, `/pipeline <task>`, or `scripts/run_pipeline.sh "<task>"` only when the user explicitly asks for Local, local-codex, local agent, or Ollama. Review still runs at the end of local pipeline runs.

## What This Repo Is

Reusable local-agent scaffolding for multiple projects. It provides:

- local CLI session commands (Codex-like: /compact, /undo, /copy, /mention, /init, /personality, /debug-config)
- reusable scripts and skills
- progress tracking
- resource guardrails
- private local tool registry support
- branch and PR hygiene rules

## Rules

- Keep default execution local-only.
- Always check for existing work first.
- Update or skip duplicates instead of recreating them.
- Use feature branches and pull requests.
- Prefer multiple logical commits over one large dump commit.
- Keep private local tool inventories out of tracked git files.
- Show real-time progress for long-running work.
- Use checkpoints and recovery state where practical.
- Deprecate before deleting: keep an older version available, make sure the newest backup is valid, and verify the replacement is live before removal.

## Main Branch Protection

- `main` should be protected with a GitHub ruleset.
- Do not delete or force-push `main`.
- Use PR-only merges for `main`.

## Validation

- Run the smallest relevant local validation before handoff.
- Review current changes locally before handoff.
