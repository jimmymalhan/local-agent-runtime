#!/bin/bash
# 24x7_runtime_fixer.sh — Autonomous PR merge + runtime restart loop
# Runs every 30 minutes. Merges PRs that pass CI, rebases conflicting branches,
# keeps the runtime healthy.

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LOG_FILE="/tmp/24x7-fixer.log"
LOCK_FILE="/tmp/24x7-fixer.lock"

log() {
    echo "[$(date +'%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG_FILE"
}

# Prevent concurrent runs
if [ -f "$LOCK_FILE" ]; then
    age=$(($(date +%s) - $(stat -f%m "$LOCK_FILE" 2>/dev/null || echo 0)))
    if [ $age -lt 1800 ]; then  # 30 min lock
        exit 0
    fi
fi
touch "$LOCK_FILE"

on_exit() {
    rm -f "$LOCK_FILE"
}
trap on_exit EXIT

cd "$REPO_ROOT"

log "=== 24/7 Runtime Fixer ==="

# 1. Try to merge open PRs that pass CI
log "Checking for mergeable PRs..."
gh pr list --state open --json number,title,mergeable,statusCheckRollup \
    --jq '.[] | select(.mergeable=="MERGEABLE" and (.statusCheckRollup | length == 0 or any(.status == "SUCCESS"))) | .number' \
    | while read pr_num; do
    log "Auto-merging PR #$pr_num..."
    gh pr merge "$pr_num" --auto --squash 2>&1 | grep -E "(Merge|success|failed)" || true
done

# 2. Rebase conflicting PRs with --theirs strategy
log "Rebasing conflicting PRs..."
gh pr list --state open --json number,headRefName,mergeable \
    --jq '.[] | select(.mergeable=="CONFLICTING") | .headRefName' \
    | head -5 | while read branch; do
    log "Attempting rebase of $branch..."
    git fetch origin "$branch" 2>&1 | tail -1
    git rebase --strategy-option=theirs origin/main "$branch" 2>&1 \
        | grep -E "(CONFLICT|Successfully|error)" || true
    git push -f origin "$branch" 2>&1 | grep -E "(pushed|rejected|failed)" || true
done

# 3. Restart runtime if stale
log "Checking runtime health..."
if ! pgrep -f "continuous_loop" > /dev/null; then
    log "continuous_loop not running — restarting runtime..."
    bash "$REPO_ROOT/Local" 2>&1 | tail -5
fi

if ! pgrep -f "live_state_updater" > /dev/null; then
    log "live_state_updater not running — restart via watchdog..."
    python3 "$REPO_ROOT/scripts/watchdog_daemon.py" 2>&1 | tail -3 &
fi

log "=== Cycle complete ==="
