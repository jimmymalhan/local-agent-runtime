#!/usr/bin/env bash
# scripts/auto_commit_pr.sh — Auto-commit + push + PR for feature branches
# Commit messages describe WHAT changed, not when. No timestamps in subjects.
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null || echo "")
if [[ -z "$BRANCH" || "$BRANCH" == "main" ]]; then
  echo "[auto-commit] Skipping — not on a feature branch (branch=$BRANCH)"
  exit 0
fi

# Stage tracked modified files in key dirs only (never root stray files)
git add local-agents/ scripts/ state/ docs/ .gitignore 2>/dev/null || true

# Nothing staged → nothing to do
if git diff --cached --quiet; then
  echo "[auto-commit] Nothing to commit on $BRANCH"
  exit 0
fi

# ── Derive a meaningful commit subject from what actually changed ──────────
CHANGED=$(git diff --cached --name-only)

# Classify changed files into feature areas
AREAS=()
echo "$CHANGED" | grep -q "dashboard/"       && AREAS+=("dashboard")
echo "$CHANGED" | grep -q "orchestrator/"    && AREAS+=("orchestrator")
echo "$CHANGED" | grep -q "error_patterns/"  && AREAS+=("error-patterns")
echo "$CHANGED" | grep -q "agents/"          && AREAS+=("agents")
echo "$CHANGED" | grep -q "scripts/ceo"      && AREAS+=("ceo-check")
echo "$CHANGED" | grep -q "scripts/"         && [[ ! " ${AREAS[*]} " =~ "ceo-check" ]] && AREAS+=("scripts")
echo "$CHANGED" | grep -q "registry/"        && AREAS+=("registry")
echo "$CHANGED" | grep -q "benchmarks/"      && AREAS+=("benchmarks")
echo "$CHANGED" | grep -q "state/"           && AREAS+=("state")
echo "$CHANGED" | grep -q "docs/"            && AREAS+=("docs")

# Determine commit type: feat if new files exist, fix if only modifications
NEW_FILES=$(git diff --cached --name-only --diff-filter=A | wc -l | tr -d ' ')
MOD_FILES=$(git diff --cached --name-only --diff-filter=M | wc -l | tr -d ' ')

if [[ "$NEW_FILES" -gt 0 ]]; then
  TYPE="feat"
else
  TYPE="fix"
fi

# Build scope from areas (max 3 to keep subject short)
SCOPE=""
if [[ ${#AREAS[@]} -gt 0 ]]; then
  LIMITED=("${AREAS[@]:0:3}")
  SCOPE="($(IFS=,; echo "${LIMITED[*]}"))"
fi

# Build a short description from branch name (strip feature/ prefix + dashes → spaces)
BRANCH_DESC="${BRANCH#feature/}"
BRANCH_DESC="${BRANCH_DESC//-/ }"

SUBJECT="${TYPE}${SCOPE}: ${BRANCH_DESC}"

# Build body with only the files that changed, grouped by area
BODY="Changed files:\n"
while IFS= read -r f; do
  BODY+="  - $f\n"
done <<< "$CHANGED"

FULL_MSG="${SUBJECT}

$(echo -e "$BODY")"

git commit -m "$FULL_MSG"
git push origin "$BRANCH" 2>&1

# ── PR: create if none exists, title/body derived from branch not timestamps ─
PR_URL=$(gh pr view "$BRANCH" --json url -q '.url' 2>/dev/null || echo "")
if [[ -z "$PR_URL" ]]; then
  # PR title = branch name cleaned up (feature/foo-bar → "Foo bar")
  PR_TITLE=$(echo "$BRANCH_DESC" | sed 's/\b\(.\)/\u\1/g')

  # PR body: list what each area adds/changes
  PR_BODY="## What changed\n"
  [[ " ${AREAS[*]} " =~ "dashboard" ]]      && PR_BODY+="- **Dashboard**: board updates, tab fixes, live metrics\n"
  [[ " ${AREAS[*]} " =~ "orchestrator" ]]   && PR_BODY+="- **Orchestrator**: auto-heal, checkpoint, auto-fix wiring\n"
  [[ " ${AREAS[*]} " =~ "error-patterns" ]] && PR_BODY+="- **Error patterns**: pattern library, auto-discovery, fix log\n"
  [[ " ${AREAS[*]} " =~ "agents" ]]         && PR_BODY+="- **Agents**: specialized agent updates\n"
  [[ " ${AREAS[*]} " =~ "ceo-check" ]]      && PR_BODY+="- **CEO check**: orchestrator health, todo board, researcher tasks\n"
  [[ " ${AREAS[*]} " =~ "registry" ]]       && PR_BODY+="- **Registry**: agent registry updates\n"
  [[ " ${AREAS[*]} " =~ "benchmarks" ]]     && PR_BODY+="- **Benchmarks**: benchmark suite, results, frustration research\n"
  [[ " ${AREAS[*]} " =~ "docs" ]]           && PR_BODY+="- **Docs**: documentation updates\n"
  [[ " ${AREAS[*]} " =~ "state" ]]          && PR_BODY+="- **State**: todo board, CEO report state updates\n"

  PR_BODY+="\n## Test plan\n- [ ] Python files compile: \`python3 -m py_compile\`\n"
  PR_BODY+="- [ ] Dashboard loads and board updates within 2s\n"
  PR_BODY+="- [ ] No regressions on existing functionality\n"
  PR_BODY+="\n🤖 Generated with [Claude Code](https://claude.com/claude-code)"

  gh pr create \
    --title "$PR_TITLE" \
    --body "$(echo -e "$PR_BODY")" \
    --base main \
    --head "$BRANCH" 2>&1 || echo "[auto-commit] PR already exists or creation skipped"
else
  echo "[auto-commit] PR already open: $PR_URL"
fi

echo "[auto-commit] Committed '${SUBJECT}' and pushed to $BRANCH"
