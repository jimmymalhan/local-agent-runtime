#!/bin/bash
# Uninstall and reinstall Claude CLI for a clean independent session.
# Uses official Anthropic method: https://docs.anthropic.com/en/docs/claude-code/setup

set -euo pipefail

echo "=== Claude CLI: Uninstall + Reinstall ==="
echo ""

# 1. Remove local-agent-runtime overrides so they don't shadow the fresh install
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
RC_FILE="${ZDOTDIR:-$HOME}/.zshrc"
if [ -f "$RC_FILE" ] && grep -qE "start_(codex|claude)_compatible" "$RC_FILE" 2>/dev/null; then
  echo "Disabling local-agent overrides in .zshrc..."
  bash "$REPO_ROOT/scripts/fix_shell_claude_codex.sh" --fix
fi

# 2. Uninstall: remove Claude Code binary and versions (per Anthropic docs)
echo "Removing Claude Code installation..."
rm -f ~/.local/bin/claude
rm -f ~/.local/bin/claude.local-agent-wrapper.bak
rm -f ~/.local/bin/claude.local-agent.bak
rm -rf ~/.local/share/claude

echo "Uninstall complete."
echo ""

# 3. Reinstall via official installer
echo "Reinstalling Claude CLI (official method)..."
curl -fsSL https://claude.ai/install.sh | bash

echo ""
echo "=== Done ==="
echo "Run: source ~/.zshrc  # or open a new terminal"
echo "Then: claude          # starts independent Claude CLI session"
echo ""
echo "To restore local-agent overrides (claude -> local Ollama):"
echo "  bash scripts/restore_local_agent_claude_codex.sh"
