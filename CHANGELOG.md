# Changelog

## 0.2.3 - 2026-03-17

- fix(shell): ensure `claude` uses real Claude CLI by default, not local agent
- add `scripts/fix_shell_claude_codex.sh` to comment out local-agent overrides and restore real CLI
- add `scripts/use_real_claude.sh` to clear cached claude/codex functions in current shell
- add `scripts/claude_cli_reinstall.sh` for clean uninstall/reinstall of Claude CLI
- docs: clarify in SESSION_COMMANDS.md that claude=real CLI by default; local agent is opt-in

## 0.2.2 - 2026-03-16

- prevent `scripts/session_compare.py` from starting parallel persona runs when another task already holds `state/run.lock`
- add regression tests for live and stale compare-lock detection so local agents do not step on each other

## 0.2.1 - 2026-03-16

- fix the Lighthouse workflow so repos without a Node web target skip FC-007 cleanly instead of failing on missing npm lockfiles
- make the local runtime fail fast under lock and resource pressure, downgrade to cheaper models sooner, and emit takeover guidance for Codex/Claude
- expand live todo and team status output with next-focus lanes and use-case rollups, backed by regression tests

## 0.2.0 - 2026-03-16

- move checkpoint storage into each target project under `.local-agent/checkpoints/`
- improve Codex-style live status with local/cloud execution ownership
- add todo lane progress for local, cloud, shared, and general work
- add repo-appropriate CI validation and session comparison coverage
- prepare GitHub release workflow for semantic version tags
