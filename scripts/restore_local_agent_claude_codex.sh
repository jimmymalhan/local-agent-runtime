#!/bin/bash
# Restore claude/codex to run local agents (undo fix_shell_claude_codex.sh --fix)

set -euo pipefail
RC_FILE="${ZDOTDIR:-$HOME}/.zshrc"
[ -f "$RC_FILE" ] || RC_FILE="$HOME/.bashrc"
REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)

echo "=== Restoring claude/codex -> local agents ==="

# 1. Uncomment codex() and claude() in .zshrc (handle both local-agent-runtime and local_agent_repo)
if grep -Eq "# \[local-agent-runtime\] disabled|# \[local_agent_repo\] disabled" "$RC_FILE" 2>/dev/null; then
  sed -i.bak 's/^# \[local-agent-runtime\] disabled so real \(claude\|codex\) works$//' "$RC_FILE"
  sed -i.bak 's/^# \[local_agent_repo\] disabled so real \(claude\|codex\) works$//' "$RC_FILE"
  sed -i.bak 's/^# codex() {$/codex() {/' "$RC_FILE"
  sed -i.bak 's/^#   bash /  bash /' "$RC_FILE"
  sed -i.bak 's/^# claude() {$/claude() {/' "$RC_FILE"
  sed -i.bak 's/^# }$/}/' "$RC_FILE"
  # Fix paths: replace only the repo dir (e.g. .../local_agent_repo) with current REPO_ROOT,
  # preserving /scripts/... (do not match trailing path)
  sed -i.bak "s|[^ ]*local_agent_repo|$REPO_ROOT|g" "$RC_FILE" 2>/dev/null || true
  sed -i.bak "s|[^ ]*local-agent-runtime|$REPO_ROOT|g" "$RC_FILE" 2>/dev/null || true
  echo "  Uncommented functions in $RC_FILE"
fi

# 1b. Fix claude/codex functions: ensure correct script paths
python3 - "$RC_FILE" "$REPO_ROOT" <<'PY' 2>/dev/null || true
import sys
path, repo = sys.argv[1], sys.argv[2]
s = open(path).read()
lines = s.split("\n")
out = []
i = 0
while i < len(lines):
    line = lines[i]
    # Fix claude block: use start_claude_compatible
    if line.strip().startswith("claude()"):
        out.append(line)
        i += 1
        while i < len(lines) and not line.rstrip().endswith("}"):
            line = lines[i]
            if "bash " in line and "scripts/" not in line and repo in line:
                line = line.replace(repo, repo + "/scripts/start_claude_compatible.sh")
            elif "start_codex_compatible" in line:
                line = line.replace("start_codex_compatible", "start_claude_compatible")
            out.append(line)
            i += 1
        continue
    # Fix codex block: ensure has scripts path
    if line.strip().startswith("codex()"):
        out.append(line)
        i += 1
        while i < len(lines) and not line.rstrip().endswith("}"):
            line = lines[i]
            if "bash " in line and "scripts/" not in line and repo in line:
                line = line.replace(repo, repo + "/scripts/start_codex_compatible.sh")
            out.append(line)
            i += 1
        continue
    out.append(line)
    i += 1
open(path, "w").write("\n".join(out))
PY

# 2. Ensure ~/.local/bin/claude and codex run local agents
#    Only restore from .local-agent.bak if it's our wrapper (not real Claude/Codex app)
mkdir -p "$HOME/.local/bin"
for cmd in claude codex; do
  bak="$HOME/.local/bin/${cmd}.local-agent.bak"
  dest="$HOME/.local/bin/$cmd"
  start_script="start_codex_compatible.sh"
  [ "$cmd" = "claude" ] && start_script="start_claude_compatible.sh"
  wrapper_content="exec bash $REPO_ROOT/scripts/$start_script \"\$@\""
  # Always (re)create wrappers with current REPO_ROOT so path is correct
  if [ -f "$bak" ] && [ -f "$dest" ] && [ ! -L "$dest" ] && grep -q "start_.*_compatible" "$dest" 2>/dev/null && grep -q "$REPO_ROOT" "$dest" 2>/dev/null; then
    echo "  $dest already points to this repo, skipping"
  else
    printf '%s\n' '#!/bin/bash' "$wrapper_content" > "$dest"
    chmod +x "$dest"
    echo "  Installed $dest -> Claude (local) / Codex (local) session"
  fi
done

echo ""
echo "Done. Run: source $RC_FILE"
echo "Then: claude -> Claude (local) session, codex -> Codex (local) session"
echo "Each session spins up first, then uses local agents for actions."
