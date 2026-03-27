#!/bin/bash
# quick_status.sh — Get system status in 30 seconds
# ===================================================
# Usage: bash scripts/quick_status.sh

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_DIR"

echo "🏥 QUICK STATUS CHECK"
echo "===================="
echo ""

# 1. Agent count
echo "📊 AGENTS:"
AGENT_COUNT=$(jq '.agents | keys | length' registry/agents.json 2>/dev/null || echo "?")
echo "   Primary: $AGENT_COUNT/10"

# 2. Sub-agents
echo ""
echo "🤖 SUB-AGENTS:"
SUB_AGENT_TOTAL=$(jq '[.agents[].sub_agents[]? | 1] | length' dashboard/state.json 2>/dev/null || echo "0")
echo "   Spawned: $SUB_AGENT_TOTAL"

# 3. Orchestrator
echo ""
echo "⚙️  ORCHESTRATOR:"
ORCH_COUNT=$(pgrep -f "orchestrator" | wc -l)
if [ "$ORCH_COUNT" -gt 0 ]; then
    echo "   Status: ✅ RUNNING ($ORCH_COUNT process(es))"
    pgrep -f "orchestrator" -l | sed 's/^/   PID: /'
else
    echo "   Status: ❌ NOT RUNNING"
fi

# 4. Dashboard
echo ""
echo "📡 DASHBOARD STATE:"
if [ -f "dashboard/state.json" ]; then
    TS=$(jq -r '.ts' dashboard/state.json 2>/dev/null || echo "missing")
    AGE_EPOCH=$(date -j -f "%Y-%m-%dT%H:%M:%S" "${TS%.*}" +%s 2>/dev/null || echo "0")
    NOW_EPOCH=$(date +%s)
    AGE=$((NOW_EPOCH - AGE_EPOCH))

    if [ "$AGE" -lt 60 ]; then
        echo "   Status: ✅ VALID (updated ${AGE}s ago)"
    elif [ "$AGE" -lt 300 ]; then
        echo "   Status: ⚠️  STALE (${AGE}s ago)"
    else
        echo "   Status: ❌ OUTDATED (${AGE}s ago)"
    fi
else
    echo "   Status: ❌ MISSING"
fi

# 5. Version progress
echo ""
echo "📈 PROGRESS:"
VERSION=$(jq -r '.version.current' dashboard/state.json 2>/dev/null || echo "?")
PCT=$(jq -r '.version.pct_complete' dashboard/state.json 2>/dev/null || echo "?")
ETA_VER=$(jq -r '.eta.version' dashboard/state.json 2>/dev/null || echo "?")
ETA_HOURS=$(jq -r '.eta.hours' dashboard/state.json 2>/dev/null || echo "?")
echo "   Version: v$VERSION ($PCT%)"
echo "   Target: v$ETA_VER"
echo "   ETA: ~$ETA_HOURS hours remaining"

# 6. Blockers
echo ""
echo "🚫 BLOCKERS:"
if [ "$ORCH_COUNT" -eq 0 ]; then
    echo "   ❌ Orchestrator not running"
else
    echo "   ✅ None detected"
fi

echo ""
echo "===================="
echo "Last update: $(date)"
