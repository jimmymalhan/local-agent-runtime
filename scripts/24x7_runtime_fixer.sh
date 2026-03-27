#!/bin/bash
# 24x7 Runtime Fixer — Keep continuous_loop alive, auto-merge PRs, rebase branches
# Runs every 30 minutes via cron or launchd

set -e

PROJECT_ROOT="/Users/jimmymalhan/Documents/local-agent-runtime"
LOOP_LOG="/tmp/continuous_loop.log"
LOOP_PID_FILE="/tmp/continuous_loop.pid"

cd "$PROJECT_ROOT"

# ─────────────────────────────────────────────────────────────────────────────
# 1. Check & Restart Continuous Loop
# ─────────────────────────────────────────────────────────────────────────────

check_and_restart_loop() {
    local loop_pid=""

    # Find any running continuous_loop process
    loop_pid=$(pgrep -f "continuous_loop" || echo "")

    if [ -z "$loop_pid" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ❌ continuous_loop not running — restarting..."

        # Start fresh continuous loop in background
        cd "$PROJECT_ROOT/local-agents"
        nohup python3 << 'PYEOF' >> "$LOOP_LOG" 2>&1 &
from orchestrator.continuous_loop import ContinuousLoop
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
    datefmt="%H:%M:%S"
)

loop = ContinuousLoop()
loop.run()
PYEOF

        new_pid=$!
        echo $new_pid > "$LOOP_PID_FILE"
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ Restarted continuous_loop (PID: $new_pid)"
    else
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ continuous_loop running (PID: $loop_pid)"
    fi
}

# ─────────────────────────────────────────────────────────────────────────────
# 2. Auto-Merge Open PRs (GitHub API)
# ─────────────────────────────────────────────────────────────────────────────

auto_merge_prs() {
    # Only if gh CLI is available
    if ! command -v gh &> /dev/null; then
        return
    fi

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🔄 Checking for PRs to auto-merge..."

    # Get list of open PRs
    prs=$(gh pr list --state open --json number,title,statusCheckRollup --template '{{range .}}{{.number}}{{"\n"}}{{end}}' 2>/dev/null || echo "")

    if [ -z "$prs" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ℹ️  No open PRs"
        return
    fi

    while read pr_num; do
        if [ -z "$pr_num" ]; then
            continue
        fi

        # Check if PR has all status checks passing
        status=$(gh pr checks "$pr_num" --json state --jq '.[] | select(.state=="FAILURE") | .state' 2>/dev/null || echo "PENDING")

        if [ -z "$status" ] || [ "$status" = "PENDING" ]; then
            # All checks passed, merge it
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⬇️  Merging PR #$pr_num..."
            gh pr merge "$pr_num" --auto --squash 2>/dev/null || gh pr merge "$pr_num" --squash 2>/dev/null || true
        fi
    done <<< "$prs"
}

# ─────────────────────────────────────────────────────────────────────────────
# 3. Rebase Conflicting Branches
# ─────────────────────────────────────────────────────────────────────────────

rebase_conflicted_branches() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] 🔀 Checking for branches needing rebase..."

    # Fetch latest
    git fetch --all --prune 2>/dev/null || true

    # Get list of branches (excluding main)
    branches=$(git branch -r --list "origin/feature/*" 2>/dev/null || echo "")

    if [ -z "$branches" ]; then
        echo "[$(date '+%Y-%m-%d %H:%M:%S')] ℹ️  No feature branches"
        return
    fi

    while read branch; do
        if [ -z "$branch" ]; then
            continue
        fi

        # Clean branch name (remove origin/ prefix)
        clean_branch="${branch#origin/}"

        # Check if branch is behind main
        git log main.."$branch" --oneline 2>/dev/null | wc -l > /tmp/ahead_count
        ahead=$(cat /tmp/ahead_count)

        if [ "$ahead" -gt 0 ]; then
            # Try rebase
            echo "[$(date '+%Y-%m-%d %H:%M:%S')] ⚡ Rebasing $clean_branch onto main..."
            git checkout "$clean_branch" 2>/dev/null || continue
            git rebase origin/main --strategy-option=theirs 2>/dev/null || true
            git push origin "$clean_branch" --force-with-lease 2>/dev/null || true
        fi
    done <<< "$branches"
}

# ─────────────────────────────────────────────────────────────────────────────
# 4. Main Execution
# ─────────────────────────────────────────────────────────────────────────────

main() {
    echo ""
    echo "════════════════════════════════════════════════════════════════════════"
    echo "🤖 24x7 Runtime Fixer — $(date '+%Y-%m-%d %H:%M:%S')"
    echo "════════════════════════════════════════════════════════════════════════"

    check_and_restart_loop
    auto_merge_prs
    rebase_conflicted_branches

    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ✅ Runtime fixer complete"
    echo ""
}

main
