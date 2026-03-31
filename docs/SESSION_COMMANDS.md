# Session Commands: Codex, Claude, Cursor vs Local Agent

## Default: `claude` = Real Claude CLI

**By default, `claude` should start the real Claude CLI (Anthropic's app), not the local agent.**

- `claude` → real Claude Code CLI (Anthropic)
- `codex` → real Codex CLI
- `cursor` → Cursor IDE

Use `./local-claude`, `./local-codex`, or `./Local` **only when you explicitly want** the local Nexus engine runtime.

## Opening Codex, Claude, or Cursor

Codex, Claude, and Cursor run independently of the local agent. When you type `claude`, `codex`, or `cursor` in chat, the AI should help you open that app, not the local agent.

- **Claude:** `open -a Claude` (macOS) or open claude.ai
- **Codex:** Run your Codex app or CLI
- **Cursor:** Already open if you're in Cursor; or `cursor .` for a new window

## If `claude` or `codex` in Terminal Opens Local Agent

Run the fix script from this repo:

```bash
cd /Users/jimmymalhan/Doc/local-agent-runtime
bash scripts/fix_shell_claude_codex.sh --fix
```

Then either **open a new terminal** or in the same shell run:

```bash
# Option A: One-liner (clears cached functions, then reloads .zshrc)
unset -f codex claude 2>/dev/null; source ~/.zshrc

# Option B: Helper script (must be sourced, not just run)
source scripts/use_real_claude.sh
```

`source ~/.zshrc` alone does *not* remove already-defined functions—they persist until you `unset -f` them or start a fresh shell. After that, `claude` and `codex` resolve to the real apps (or "command not found" if not installed).

## If the Local Agent Still Opens (Cursor Chat)

1. **Rules updated:** `.cursor/rules/local-only.mdc` now says: when you ask for Codex/Claude/Cursor, do NOT route to local. Start a **new chat** so the AI picks up the updated rules.

2. **Disable local-runtime MCP:** Cursor Settings → Features → MCP → disable or remove the `local-runtime` server. That removes `run_local_pipeline` so the AI cannot call it.

3. **Terminal fix (claude/codex open local agent):** If typing `claude` or `codex` in the terminal opens the local agent instead of the real app, run:
   ```bash
   bash /Users/jimmymalhan/Doc/local-agent-runtime/scripts/fix_shell_claude_codex.sh --fix
   ```
   This comments out the overrides in your `~/.zshrc` and backs up the wrappers in `~/.local/bin`. Then open a **new terminal** or run `unset -f codex claude 2>/dev/null; source ~/.zshrc` (plain `source` won't clear existing functions).

4. **Use explicit commands:** To open the real apps from a terminal:
   ```bash
   open -a Claude      # macOS Claude app
   codex              # if Codex is in PATH (real Codex, not local)
   cursor .           # new Cursor window
   ```

## Local Agent (Opt-In Only)

Use `Local`, `local-codex`, or `local-claude` **only when you explicitly want** the local Nexus engine runtime:

```bash
bash ./Local
./local-codex
./local-claude
```

## Quick Response (Fast Mode)

To make the local agent respond faster, use **fast** mode:

| Method | How |
|--------|-----|
| Default | `config/runtime.json` uses `default_profile: "fast"` |
| In-session | Type `/mode fast` once the session is running |
| Env var | `LOCAL_AGENT_MODE=fast ./local-codex` or `LOCAL_AGENT_MODE=fast ./local-claude` |

`fast` uses fewer, lighter steps than `exhaustive`.

## Session Self-Heal

The local runtime now inspects interactive `codex` and `claude` CLI sessions by terminal (`TTY`).

- `/doctor` shows active sessions and flags duplicate active sessions on the same terminal.
- `/heal` auto-suspends stale duplicate active sessions on the same terminal and writes `logs/session-health-report.md`.
