#!/bin/bash
set -euo pipefail

# Diagnose and fix: claude/codex opening local agent instead of real Claude/Codex
# Run with --fix to automatically apply the fix.

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
RC_FILE="${ZDOTDIR:-$HOME}/.zshrc"
[ -f "$RC_FILE" ] || RC_FILE="$HOME/.bashrc"

echo "=== Diagnosing claude/codex commands ==="
echo ""
echo "Current 'claude' resolves to:"
CLAUDE_TYPE=$(type claude 2>/dev/null || echo "  (not found)")
echo "$CLAUDE_TYPE"
echo ""
echo "Current 'codex' resolves to:"
CODEX_TYPE=$(type codex 2>/dev/null || echo "  (not found)")
echo "$CODEX_TYPE"
echo ""
if echo "$CLAUDE_TYPE $CODEX_TYPE" | grep -q "shell function"; then
  echo "*** claude/codex are SHELL FUNCTIONS - they override the real CLI. ***"
  echo "*** Run this to fix (or open a NEW terminal):                       ***"
  echo "***   unset -f codex claude 2>/dev/null; source ~/.zshrc            ***"
  echo ""
fi
echo "Checking $RC_FILE and ~/.local/bin for overrides..."
echo ""

if [ -f "$RC_FILE" ]; then
  grep -n "codex()\|claude()" "$RC_FILE" 2>/dev/null | head -20
fi
for cmd in claude codex; do
  p="$HOME/.local/bin/$cmd"
  if [ -f "$p" ] || [ -L "$p" ]; then
    echo "  $p:"
    if [ -L "$p" ]; then
      echo "    -> $(readlink "$p")"
    elif [ -f "$p" ]; then
      sz=$(stat -f%z "$p" 2>/dev/null || stat -c%s "$p" 2>/dev/null || echo 0)
      if [ "${sz:-0}" -lt 500 ] 2>/dev/null; then
        head -3 "$p" 2>/dev/null | sed 's/^/    /' || echo "    (binary or unreadable)"
      else
        echo "    (binary, ${sz} bytes)"
      fi
    fi
  fi
done

echo ""
echo "=== Fix ==="
echo "To stop 'claude' and 'codex' from opening the local agent:"
echo "  Run: $0 --fix"
echo ""
echo "Use local-claude or local-codex when you want the local agent."
echo ""

if [ "${1:-}" != "--fix" ]; then
  exit 0
fi

echo "=== Applying fix ==="
APPLIED=0

# 1. Comment out codex() and claude() functions in .zshrc
#    (handle both local-agent-runtime and local_agent_repo paths)
if [ -f "$RC_FILE" ]; then
  if grep -qE "start_(codex|claude)_compatible" "$RC_FILE" 2>/dev/null; then
    cp -a "$RC_FILE" "${RC_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
    python3 - "$RC_FILE" <<'PY'
import re, sys
path = sys.argv[1]
with open(path) as f:
    s = f.read()
for name in ("codex", "claude"):
    # Match: name() { ... local-agent-runtime or local_agent_repo ... }
    pat = r"^(" + re.escape(name) + r"\(\) \{[^}]*(?:local-agent-runtime|local_agent_repo)[^}]*\})"
    def repl(m, n=name):
        return "# [local-agent-runtime] disabled so real " + n + " works\n# " + m.group(1).replace("\n", "\n# ")
    s = re.sub(pat, lambda m: repl(m), s, flags=re.MULTILINE | re.DOTALL)
with open(path, "w") as f:
    f.write(s)
PY
    echo "  Commented out codex() and claude() in $RC_FILE (backup created)"
    APPLIED=1
  fi
fi

# 2. Replace ~/.local/bin wrappers with real Claude/Codex
mkdir -p "$HOME/.local/bin"
for cmd in claude codex; do
  p="$HOME/.local/bin/$cmd"
  wrapper_bak="$HOME/.local/bin/${cmd}.local-agent-wrapper.bak"
  if [ -f "$p" ] && grep -Eq "local-agent-runtime|local_agent_repo" "$p" 2>/dev/null; then
    cp -a "$p" "$wrapper_bak"
    rm -f "$p"
    echo "  Backed up local-agent wrapper $p -> $wrapper_bak"

    if [ "$cmd" = "claude" ]; then
      # Restore real Claude CLI: symlink to Anthropic's binary in ~/.local/share/claude/versions/
      # Skip our wrapper (small script); pick the largest real binary
      CLAUDE_VERSIONS="$HOME/.local/share/claude/versions"
      if [ -d "$CLAUDE_VERSIONS" ]; then
        # Pick the largest file that's a real binary (>1MB); skip tiny wrapper scripts
        real_bin=$(ls -S "$CLAUDE_VERSIONS" 2>/dev/null | while read v; do
          f="$CLAUDE_VERSIONS/$v"
          [ -f "$f" ] || [ -L "$f" ] || continue
          sz=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null)
          [ "${sz:-0}" -gt 1000000 ] 2>/dev/null || continue
          echo "$f"
          break
        done)
        if [ -n "$real_bin" ] && [ -f "$real_bin" ]; then
          ln -sf "$real_bin" "$p"
          echo "  Restored real Claude CLI: $p -> $real_bin"
        fi
      fi
    fi
    APPLIED=1
  fi
done

if [ "$APPLIED" -eq 1 ]; then
  echo ""
  echo "Done."
  echo ""
  echo "IMPORTANT: If claude/codex still opens local agent, the shell function is cached."
  echo "  Run BOTH commands (in order):"
  echo "    unset -f codex claude 2>/dev/null"
  echo "    source ~/.zshrc"
  echo "  OR open a brand NEW terminal tab/window."
  echo ""
  echo "Then: claude -> real Claude CLI, codex -> real Codex"
  echo "Use ./local-claude or ./local-codex when you want the local Nexus engine agent."
fi

# If no changes but claude is a function, warn
if [ "$APPLIED" -eq 0 ] && type claude 2>/dev/null | grep -q "shell function"; then
  echo ""
  echo "claude is a shell function (shadows real CLI). To use real Claude:"
  echo "  unset -f claude codex 2>/dev/null; source ~/.zshrc"
  echo "  OR open a new terminal."
fi

if [ "$APPLIED" -eq 0 ] && ! type claude 2>/dev/null | grep -q "shell function"; then
  echo "  No local-agent overrides found."
fi
