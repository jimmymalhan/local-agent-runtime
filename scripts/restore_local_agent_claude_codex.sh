#!/bin/bash
# Restore claude/codex to run local agents (undo fix_shell_claude_codex.sh --fix)

set -euo pipefail
RC_FILE="${ZDOTDIR:-$HOME}/.zshrc"
[ -f "$RC_FILE" ] || RC_FILE="$HOME/.bashrc"
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)

echo "=== Restoring claude/codex -> local agents ==="

# 1. Uncomment codex() and claude() in .zshrc
if grep -Eq "# \[local-agent-runtime\] disabled" "$RC_FILE" 2>/dev/null; then
  sed -i.bak 's/^# \[local-agent-runtime\] disabled so real \(claude\|codex\) works$//' "$RC_FILE"
  sed -i.bak 's/^# codex() {$/codex() {/' "$RC_FILE"
  sed -i.bak 's/^#   bash /  bash /' "$RC_FILE"
  sed -i.bak 's/^# claude() {$/claude() {/' "$RC_FILE"
  sed -i.bak 's/^# }$/}/' "$RC_FILE"
  echo "  Uncommented functions in $RC_FILE"
fi

# 1b. Ensure claude calls start_claude_compatible (for Claude persona)
python3 - "$RC_FILE" <<'PY' 2>/dev/null || true
import sys
path = sys.argv[1]
s = open(path).read()
if "claude()" in s and "start_codex_compatible" in s:
    # Replace only in claude block: claude() { ... start_codex... }
    in_claude = False
    lines = s.split("\n")
    out = []
    for i, line in enumerate(lines):
        if line.strip().startswith("claude()"):
            in_claude = True
        if in_claude and "start_codex_compatible" in line and "start_claude_compatible" not in line:
            line = line.replace("start_codex_compatible", "start_claude_compatible")
            in_claude = False
        out.append(line)
    open(path, "w").write("\n".join(out))
PY

# 2. Restore ~/.local/bin from backup (claude uses start_claude_compatible)
mkdir -p "$HOME/.local/bin"
for cmd in claude codex; do
  bak="$HOME/.local/bin/${cmd}.local-agent.bak"
  dest="$HOME/.local/bin/$cmd"
  if [ -f "$bak" ]; then
    cp -a "$bak" "$dest"
    [ "$cmd" = "claude" ] && sed -i.bak3 's|start_codex_compatible|start_claude_compatible|' "$dest" 2>/dev/null || true
    echo "  Restored $dest from backup"
  elif [ ! -f "$dest" ]; then
    start_script="start_codex_compatible.sh"
    [ "$cmd" = "claude" ] && start_script="start_claude_compatible.sh"
    printf '%s\n' '#!/bin/bash' "exec bash $REPO_ROOT/scripts/$start_script \"\$@\"" > "$dest"
    chmod +x "$dest"
    echo "  Created $dest"
  fi
done

echo ""
echo "Done. Run: source $RC_FILE"
echo "Then: claude -> Claude (local) session, codex -> Codex (local) session"
echo "Each session spins up first, then uses local agents for actions."
