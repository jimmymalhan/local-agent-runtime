#!/usr/bin/env bash
# scripts/auto_commit_pr.sh — Auto-commit + push + PR every 30 minutes
# Runs on: feature/* branches only. Skips if nothing changed.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
if [[ -z "$BRANCH" || "$BRANCH" == "main" ]]; then
  echo "[auto-commit] Skipping — not on a feature branch (branch=$BRANCH)"
  exit 0
fi

# Stage tracked modified files in key dirs (never root stray files)
git add local-agents/ scripts/ state/ docs/ .gitignore 2>/dev/null || true

# Check if anything is staged
if git diff --cached --quiet; then
  echo "[auto-commit] Nothing to commit on $BRANCH"
  exit 0
fi

TS=$(date '+%Y-%m-%d %H:%M PST')
MSG="chore: auto-sync $(date '+%H:%M') — dashboard + orchestrator updates

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>"

git commit -m "$MSG"
git push origin "$BRANCH" 2>&1

# Create PR if none exists; otherwise it's already open
PR_URL=$(gh pr view "$BRANCH" --json url -q '.url' 2>/dev/null || echo "")
if [[ -z "$PR_URL" ]]; then
  gh pr create \
    --title "feat: supervisor, auto-heal, auto-fix, checkpoint system" \
    --body "$(cat <<'EOF'
## Summary
- Supervisor agent runs first on every version start
- Auto-heal: restarts crashed components in <10s, 3-failure rebuild
- Auto-fix: 5-step pipeline — pattern match → Debugger → prompt upgrade
- Checkpoint manager: 30s snapshots + version rollback on regression
- Error pattern library: 10 seed patterns + auto-discovery
- Dashboard: Done board 24h cleanup, live-updating Tasks board, CEO metrics

## Auto-generated
This PR is managed by the auto-commit cron (every 30 min).

🤖 Generated with [Claude Code](https://claude.com/claude-code)
EOF
)" \
    --base main \
    --head "$BRANCH" 2>&1 || echo "[auto-commit] PR already exists or creation skipped"
else
  echo "[auto-commit] PR already open: $PR_URL"
fi

echo "[auto-commit] Done — $BRANCH pushed at $TS"
