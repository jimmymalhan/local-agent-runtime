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
(type claude 2>/dev/null || echo "  (not found)")
echo ""
echo "Current 'codex' resolves to:"
(type codex 2>/dev/null || echo "  (not found)")
echo ""
echo "Checking $RC_FILE and ~/.local/bin for overrides..."
echo ""

if [ -f "$RC_FILE" ]; then
  grep -n "codex()\|claude()" "$RC_FILE" 2>/dev/null | head -20
fi
for cmd in claude codex; do
  p="$HOME/.local/bin/$cmd"
  if [ -f "$p" ]; then
    echo "  $p contents:"
    head -3 "$p" | sed 's/^/    /'
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
if [ -f "$RC_FILE" ]; then
  if grep -q "start_codex_compatible" "$RC_FILE" 2>/dev/null; then
    cp -a "$RC_FILE" "${RC_FILE}.bak.$(date +%Y%m%d_%H%M%S)"
    python3 - "$RC_FILE" <<'PY'
import re, sys
path = sys.argv[1]
with open(path) as f:
    s = f.read()
for name in ("codex", "claude"):
    # Match: name() { newline bash ...local-agent-runtime... }
    pat = r"^(" + re.escape(name) + r"\(\) \{[^}]*(local-agent-runtime)[^}]*\})"
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

# 2. Backup ~/.local/bin wrappers that point to local agent
for cmd in claude codex; do
  p="$HOME/.local/bin/$cmd"
  if [ -f "$p" ] && grep -Eq "local-agent-runtime" "$p" 2>/dev/null; then
    mv "$p" "${p}.local-agent.bak"
    echo "  Backed up $p -> ${p}.local-agent.bak"
    APPLIED=1
  fi
done

if [ "$APPLIED" -eq 1 ]; then
  echo ""
  echo "Done. Run one of:"
  echo "  1. Open a NEW terminal (recommended - clears old function definitions)"
  echo "  2. Run: unset -f codex claude 2>/dev/null; source $RC_FILE"
  echo "Then: claude -> real Claude, codex -> real Codex"
  echo "Use local-claude or local-codex when you want the local agent."
else
  echo "  No local-agent overrides found."
fi
