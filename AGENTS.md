# Local Agent Repo Rules

## User Session Choice (takes priority)

- When the user asks to open **Codex, Claude, or Cursor** (their own sessions)—help them do that. Do NOT route to local runtime.
- Codex, Claude, Cursor run independently. Local agent (Local, local-codex) is opt-in only when the user explicitly asks for it.

## MANDATORY: Respect The Chosen Session

- If the user is already working in **Codex, Claude, or Cursor** and asks for coding work there, execute the work in that session end to end.
- Do not stop at a generated command or ask the user to run the local runtime manually when the current session can perform the work.
- The local runtime remains opt-in and should be used when the user explicitly asks for `Local`, `local-codex`, `local agent`, or `Ollama`.
- Review still runs at the end of local pipeline runs when the local runtime is used.

## Core Rules

- Use feature branches for all work. Never commit directly to `main`.
- Always check whether the requested work already exists before creating new files, workflows, or scripts.
- If the work already exists, update it in place or skip it.
- Keep execution local-only by default unless a user explicitly approves another path.
- Start sessions by confirming the local runtime is available; if the local runtime is unavailable, stop instead of silently falling back to an external model path.
- Keep private local tool inventories out of tracked git content.
- End each work item with local review, local validation, and a pull request when git hosting is in use.

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
- Save progress state to disk so interrupted runs can be resumed or inspected.
- Finish interactive task runs with an automatic local review pass.

## Recovery Rule

- Create checkpoints before destructive or long-running operations when practical.
- If checkpointing fails, stop instead of continuing on a non-recoverable tree.
- If something needs to be removed, deprecate it to an older-version path or state first instead of deleting it immediately.
- Before any deprecation or removal, make sure the replacement version and the most current backup are active and recoverable.
- Only delete deprecated content after the newer version is running and recovery has been verified.
