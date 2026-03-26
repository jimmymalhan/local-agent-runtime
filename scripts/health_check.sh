#!/bin/bash
# health_check.sh — Real-time Agent System Health Monitor
# ===========================================================
# Verifies that all 4 components are healthy:
#   1. Orchestrator running and making progress
#   2. Self-heal running (or scheduled)
#   3. Auto-recover heartbeat fresh (<2 min)
#   4. Dashboard state valid
#
# Usage:
#   bash scripts/health_check.sh           # Full check
#   bash scripts/health_check.sh --brief   # Quick summary
#   bash scripts/health_check.sh --json    # JSON output

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$REPO_ROOT/local-agents/logs"
STATE_DIR="$REPO_ROOT/state"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

BRIEF_MODE="${1:-}"
JSON_MODE=0
[ "$BRIEF_MODE" = "--brief" ] && BRIEF_MODE=1 || BRIEF_MODE=0
[ "$1" = "--json" ] && JSON_MODE=1 || true

# ============================================================================
# Helper Functions
# ============================================================================

log_check() {
    local name=$1
    local status=$2
    local detail=$3

    if [ $JSON_MODE -eq 1 ]; then
        echo "$status|$name|$detail"
    elif [ "$status" = "✓" ]; then
        echo -e "${GREEN}[✓]${NC} $name${detail:+: }$detail"
    elif [ "$status" = "✗" ]; then
        echo -e "${RED}[✗]${NC} $name${detail:+: }$detail"
    elif [ "$status" = "⚠" ]; then
        echo -e "${YELLOW}[⚠]${NC} $name${detail:+: }$detail"
    else
        echo -e "${BLUE}[$status]${NC} $name${detail:+: }$detail"
    fi
}

process_running() {
    pgrep -f "$1" > /dev/null 2>&1
}

# ============================================================================
# Checks
# ============================================================================

check_orchestrator() {
    if process_running "orchestrator/main.py"; then
        log_check "Orchestrator" "✓" "Running"
        return 0
    else
        log_check "Orchestrator" "✗" "NOT RUNNING"
        return 1
    fi
}

check_self_heal() {
    if process_running "self_heal.py"; then
        log_check "Self-Heal Loop" "✓" "Running"
        return 0
    else
        # Self-heal might be running as cron job, which is OK
        if grep -q "self_heal.py" <(crontab -l 2>/dev/null || echo ""); then
            log_check "Self-Heal Loop" "⚠" "Scheduled via cron (not running now)"
            return 1
        else
            log_check "Self-Heal Loop" "✗" "NOT scheduled or running"
            return 2
        fi
    fi
}

check_dashboard() {
    if process_running "dashboard/server.py"; then
        log_check "Dashboard Server" "✓" "Running on :3001"
        return 0
    else
        log_check "Dashboard Server" "⚠" "NOT RUNNING (optional, restart with startup.sh)"
        return 1
    fi
}

check_heartbeat() {
    if [ ! -f "$STATE_DIR/watchdog_heartbeat.json" ]; then
        log_check "Heartbeat" "✗" "File not found"
        return 1
    fi

    local ts=$(jq -r '.timestamp' "$STATE_DIR/watchdog_heartbeat.json" 2>/dev/null || echo "")
    if [ -z "$ts" ]; then
        log_check "Heartbeat" "✗" "Timestamp is empty"
        return 1
    fi

    # Check if timestamp is recent (within 2 minutes = 120 seconds)
    local ts_epoch=$(date -d "$ts" +%s 2>/dev/null || date -jf "%Y-%m-%dT%H:%M:%SZ" "$ts" +%s 2>/dev/null || echo 0)
    local now_epoch=$(date +%s)
    local diff=$((now_epoch - ts_epoch))

    if [ $diff -lt 120 ]; then
        log_check "Heartbeat" "✓" "Fresh ($diff seconds old)"
        return 0
    elif [ $diff -lt 300 ]; then
        log_check "Heartbeat" "⚠" "Stale ($diff seconds old, should be <120)"
        return 1
    else
        log_check "Heartbeat" "✗" "Very stale ($diff seconds old)"
        return 2
    fi
}

check_state_validity() {
    if [ ! -f "$REPO_ROOT/dashboard/state.json" ]; then
        log_check "Dashboard State" "⚠" "state.json not initialized yet"
        return 1
    fi

    if python3 -c "
from state.dashboard_schema import is_valid_state
import json
import sys
try:
    state = json.load(open('$REPO_ROOT/dashboard/state.json'))
    if is_valid_state(state):
        print('valid')
    else:
        print('invalid')
except Exception as e:
    print('error:' + str(e))
" 2>/dev/null | grep -q "^valid$"; then
        log_check "Dashboard State" "✓" "Valid and ready"
        return 0
    else
        log_check "Dashboard State" "⚠" "Invalid or error loading"
        return 1
    fi
}

check_task_progress() {
    if [ ! -f "$REPO_ROOT/projects.json" ]; then
        log_check "Task Progress" "⚠" "projects.json not found"
        return 1
    fi

    local total=$(jq '.projects | length' "$REPO_ROOT/projects.json" 2>/dev/null || echo 0)
    local completed=$(jq '[.projects[] | select(.status=="completed")] | length' "$REPO_ROOT/projects.json" 2>/dev/null || echo 0)

    if [ "$total" -gt 0 ]; then
        local pct=$((completed * 100 / total))
        log_check "Task Progress" "✓" "$completed/$total complete ($pct%)"
        return 0
    else
        log_check "Task Progress" "⚠" "No projects loaded"
        return 1
    fi
}

check_resource_usage() {
    local cpu=$(ps aux | awk '{sum += $3} END {print int(sum)}')
    local mem=$(ps aux | awk '{sum += $4} END {print int(sum)}')

    if [ "$mem" -gt 80 ]; then
        log_check "Resource Usage" "✗" "Memory ${mem}% (too high)"
        return 2
    elif [ "$mem" -gt 60 ]; then
        log_check "Resource Usage" "⚠" "Memory ${mem}%, CPU ${cpu}%"
        return 1
    else
        log_check "Resource Usage" "✓" "CPU ${cpu}%, Memory ${mem}%"
        return 0
    fi
}

check_cron_jobs() {
    if crontab -l 2>/dev/null | grep -q "auto_recover.sh"; then
        log_check "Cron: Auto-Recover" "✓" "Scheduled (*/2 * * * *)"
        return 0
    else
        log_check "Cron: Auto-Recover" "✗" "NOT scheduled"
        return 1
    fi
}

check_agent_success_rates() {
    if [ ! -f "$STATE_DIR/agent_success_stats.json" ]; then
        log_check "Agent Success Rates" "⚠" "Stats not available yet"
        return 1
    fi

    # Show brief summary
    local researcher=$(jq '.researcher.success_rate' "$STATE_DIR/agent_success_stats.json" 2>/dev/null | awk '{printf "%.0f%%\n", $1*100}' || echo "?")
    local planner=$(jq '.planner.success_rate' "$STATE_DIR/agent_success_stats.json" 2>/dev/null | awk '{printf "%.0f%%\n", $1*100}' || echo "?")
    local executor=$(jq '.executor.success_rate' "$STATE_DIR/agent_success_stats.json" 2>/dev/null | awk '{printf "%.0f%%\n", $1*100}' || echo "?")

    log_check "Agent Success Rates" "✓" "Executor: $executor, Researcher: $researcher, Planner: $planner"
    return 0
}

# ============================================================================
# Summary Report
# ============================================================================

health_report() {
    echo ""
    echo "========================================"
    echo "Agent System Health Report"
    echo "========================================"
    echo ""

    local failed=0
    local warned=0
    local passed=0

    check_orchestrator || ((failed++))
    check_self_heal || ((warned++))
    check_dashboard || ((warned++))
    check_heartbeat || ((failed++))
    check_state_validity || ((warned++))
    check_task_progress || ((warned++))
    check_resource_usage || ((warned++))
    check_cron_jobs || ((failed++))
    check_agent_success_rates || ((warned++))

    echo ""
    echo "========================================"
    echo "Summary: $passed passed, $warned warned, $failed failed"
    echo "========================================"
    echo ""

    if [ $failed -eq 0 ] && [ $warned -eq 0 ]; then
        echo -e "${GREEN}✓ System is healthy${NC}"
        echo ""
        return 0
    elif [ $failed -eq 0 ]; then
        echo -e "${YELLOW}⚠ System is operational but has warnings${NC}"
        echo ""
        return 1
    else
        echo -e "${RED}✗ System has critical issues${NC}"
        echo ""
        echo "Recommended actions:"
        echo "  1. Check logs: tail -f $LOG_DIR/*.log"
        echo "  2. Restart system: bash scripts/startup.sh --restart"
        echo "  3. Run auto-recover: bash scripts/auto_recover.sh"
        echo ""
        return 2
    fi
}

# ============================================================================
# Main
# ============================================================================

if [ $BRIEF_MODE -eq 1 ]; then
    # Brief mode: just check critical components
    echo "Checking system..."
    check_orchestrator && check_heartbeat && check_cron_jobs && echo "✓ All critical checks passed" || echo "✗ Some critical checks failed"
else
    health_report
fi
