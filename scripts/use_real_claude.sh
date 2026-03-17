#!/bin/bash
# Run this in your CURRENT terminal to clear cached claude/codex functions
# so 'claude' uses the real Claude CLI instead of the local agent.
#
# Usage: source scripts/use_real_claude.sh
# (source = runs in current shell so unset takes effect)

unset -f codex claude 2>/dev/null
[ -f ~/.zshrc ] && source ~/.zshrc
echo "claude and codex functions cleared. Run: claude --version"
