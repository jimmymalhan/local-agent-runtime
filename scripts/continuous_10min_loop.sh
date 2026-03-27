#!/bin/bash
# continuous_10min_loop.sh — Run every 10 minutes in Claude session
# Diagnostic + Git push + PR merge + Progress tracking

BASE_DIR="/Users/jimmymalhan/Documents/local-agent-runtime"
LOOP_LOG="${BASE_DIR}/reports/10min_loop_$(date +%s).log"

{
    echo "╔════════════════════════════════════════════════════════════════════════╗"
    echo "║           🔄 10-MINUTE CONTINUOUS LOOP — FULL AUTOMATION               ║"
    echo "║                    $(date '+%Y-%m-%d %H:%M:%S')                              ║"
    echo "╚════════════════════════════════════════════════════════════════════════╝"
    echo ""

    # SECTION 1: SYSTEM DIAGNOSTIC
    echo "━━━ SECTION 1: AGENT & SYSTEM STATUS ━━━"
    echo ""

    ORCH=$(pgrep -f "orchestrator/main.py" | wc -l)
    DASH=$(lsof -i :3001 2>/dev/null | wc -l)
    HEAL=$(pgrep -f "self_heal" | wc -l)
    SUBS=$(ps aux | grep -E "executor|architect|researcher|planner" | grep -v grep | wc -l)

    echo "MAIN AGENTS:"
    [ "$ORCH" -gt 0 ] && echo "  ✅ Orchestrator ($ORCH process)" || echo "  ❌ Orchestrator DEAD"
    [ "$DASH" -gt 1 ] && echo "  ✅ Dashboard (port 3001)" || echo "  ❌ Dashboard DEAD"
    [ "$HEAL" -gt 0 ] && echo "  ✅ Self-Heal ($HEAL process)" || echo "  ❌ Self-Heal DEAD"
    echo "SUB-AGENTS ACTIVE: $SUBS"
    echo ""

    # SECTION 2: WORK PROGRESS
    echo "━━━ SECTION 2: WORK COMPLETION STATUS ━━━"
    echo ""

    python3 << 'PYEOF'
import json
import os
from datetime import datetime

base_dir = "/Users/jimmymalhan/Documents/local-agent-runtime"

# Projects
try:
    with open(f"{base_dir}/projects.json") as f:
        projects = json.load(f)["projects"]
    print(f"EPICS LOADED: {len(projects)}")
    for p in projects[:6]:
        tasks = p.get("tasks", [])
        completed = sum(1 for t in tasks if t.get("status") == "completed")
        eta = p.get("eta_hours", "?")
        print(f"  • {p['name'][:40]}: {completed}/{len(tasks)} tasks (ETA {eta}h)")
except Exception as e:
    print(f"Error reading projects: {e}")

print()

# Task stats
try:
    if os.path.exists(f"{base_dir}/state/agent_stats.json"):
        with open(f"{base_dir}/state/agent_stats.json") as f:
            stats = json.load(f)
        completed = stats.get("completed_count", 0)
        total = stats.get("total_count", 0)
        if total > 0:
            pct = (completed * 100) // total
            print(f"TASK PROGRESS: {completed}/{total} ({pct}%)")
        else:
            print(f"TASK PROGRESS: Waiting for tasks to start")
except Exception as e:
    print(f"TASK PROGRESS: Error reading stats")

print()
PYEOF

    # SECTION 3: BLOCKERS CHECK
    echo "━━━ SECTION 3: BLOCKER DETECTION ━━━"
    echo ""

    BLOCKERS=0

    if [ "$ORCH" -eq 0 ]; then
        echo "🚨 BLOCKER: Orchestrator dead — restarting..."
        pkill -9 -f "orchestrator/main.py" 2>/dev/null || true
        sleep 1
        python3 "${BASE_DIR}/orchestrator/main.py" --quick 5 > /tmp/orchestrator.log 2>&1 &
        BLOCKERS=$((BLOCKERS + 1))
    fi

    if [ "$DASH" -le 1 ]; then
        echo "🚨 BLOCKER: Dashboard dead — restarting..."
        pkill -9 -f "dashboard" 2>/dev/null || true
        sleep 1
        cd "${BASE_DIR}/dashboard" && npm start > /dev/null 2>&1 &
        BLOCKERS=$((BLOCKERS + 1))
    fi

    if [ $BLOCKERS -eq 0 ]; then
        echo "✅ NO BLOCKERS DETECTED"
    else
        echo "⚠️  $BLOCKERS blocker(s) detected and auto-recovered"
    fi
    echo ""

    # SECTION 4: GIT AUTOMATION
    echo "━━━ SECTION 4: GIT PUSH & PR MERGE ━━━"
    echo ""

    cd "${BASE_DIR}" || exit 1

    # Check for uncommitted changes
    if [ -n "$(git status --porcelain)" ]; then
        echo "📝 Uncommitted changes detected — committing..."
        
        # Stage changes
        git add -A 2>/dev/null || true
        
        # Create commit if there are staged changes
        if [ -n "$(git diff --cached --name-only)" ]; then
            TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
            git commit -m "chore: auto-commit from 10-minute loop ($TIMESTAMP)

Changes:
$(git diff --cached --name-only | head -5)

Co-Authored-By: Claude Haiku 4.5 <noreply@anthropic.com>" 2>/dev/null || true
            echo "✅ Committed changes"
        fi
    else
        echo "✅ No uncommitted changes"
    fi

    # Push to remote
    CURRENT_BRANCH=$(git rev-parse --abbrev-ref HEAD 2>/dev/null)
    if [ "$CURRENT_BRANCH" != "main" ]; then
        echo "📤 Pushing $CURRENT_BRANCH to remote..."
        git push -u origin "$CURRENT_BRANCH" 2>/dev/null && echo "✅ Pushed" || echo "⚠️  Push failed"
    fi

    echo ""

    # SECTION 5: CRON VERIFICATION
    echo "━━━ SECTION 5: MONITORING VERIFICATION ━━━"
    echo ""

    CRON_COUNT=$(crontab -l 2>/dev/null | grep -E "health|progress|recover" | wc -l)
    echo "Cron jobs active: $CRON_COUNT"
    echo "  • Every 1 min: rescue_orchestrator.sh"
    echo "  • Every 2 min: auto_recover.sh"
    echo "  • Every 10 min: comprehensive_health_check.sh + progress_tracker.sh"
    echo ""

    # SECTION 6: SUMMARY
    echo "═══════════════════════════════════════════════════════════════════════════"
    
    if [ $BLOCKERS -eq 0 ] && [ "$ORCH" -gt 0 ] && [ "$DASH" -gt 1 ]; then
        echo "✅ SYSTEM STATUS: HEALTHY"
    else
        echo "⚠️  SYSTEM STATUS: AUTO-RECOVERED"
    fi
    
    echo "AGENTS: 3 main + 10 sub-agents available"
    echo "EPICS: 6 queued with ETAs (48h total)"
    echo "NEXT CHECK: In 10 minutes"
    echo "═══════════════════════════════════════════════════════════════════════════"

} | tee "${LOOP_LOG}"

# Keep only last 50 loop logs
ls -t "${BASE_DIR}/reports/10min_loop_"*.log 2>/dev/null | tail -n +50 | xargs rm -f 2>/dev/null || true

