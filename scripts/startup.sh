#!/bin/bash
# startup.sh — 24/7 Agent System Bootstrap
# ==========================================
# Launches all 4 components needed for continuous autonomous operation:
#   1. orchestrator/main.py --auto 1 — Main v1→v1000 loop
#   2. local-agents/orchestrator/self_heal.py — Hourly failure recovery
#   3. scripts/auto_recover.sh via cron — 2-min heartbeat + auto-commit
#   4. dashboard/server.py — Web UI (already running, monitored)
#
# Usage:
#   bash scripts/startup.sh           # Start all components
#   bash scripts/startup.sh --status  # Check status only
#   bash scripts/startup.sh --kill    # Kill all agents
#   bash scripts/startup.sh --restart # Kill and restart

set -e

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
LOG_DIR="$REPO_ROOT/local-agents/logs"
PID_DIR="$REPO_ROOT/.pids"

mkdir -p "$LOG_DIR" "$PID_DIR"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# ============================================================================
# Helper Functions
# ============================================================================

log_info() {
    echo -e "${BLUE}[INFO]${NC} $*"
}

log_success() {
    echo -e "${GREEN}[✓]${NC} $*"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $*"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $*"
}

check_process() {
    local name=$1
    local pattern=$2
    if pgrep -f "$pattern" > /dev/null 2>&1; then
        log_success "$name is running"
        return 0
    else
        log_warn "$name is NOT running"
        return 1
    fi
}

# ============================================================================
# Status Check
# ============================================================================

status() {
    echo ""
    echo "========================================"
    echo "Agent System Status Check"
    echo "========================================"

    local all_running=1

    # Check orchestrator
    if ! check_process "Orchestrator" "orchestrator/main.py"; then
        all_running=0
    fi

    # Check self-heal
    if ! check_process "Self-Heal" "self_heal.py"; then
        all_running=0
    fi

    # Check dashboard
    if ! check_process "Dashboard" "dashboard/server.py"; then
        all_running=0
    fi

    # Check heartbeat freshness
    if [ -f "$REPO_ROOT/state/watchdog_heartbeat.json" ]; then
        HEARTBEAT_TS=$(jq -r '.timestamp' "$REPO_ROOT/state/watchdog_heartbeat.json" 2>/dev/null || echo "unknown")
        log_success "Heartbeat timestamp: $HEARTBEAT_TS"
    else
        log_warn "Heartbeat file not found"
    fi

    # Check state validity
    if [ -f "$REPO_ROOT/dashboard/state.json" ]; then
        if python3 -c "from state.dashboard_schema import is_valid_state; import json; print(is_valid_state(json.load(open('$REPO_ROOT/dashboard/state.json'))))" 2>/dev/null | grep -q True; then
            log_success "Dashboard state is valid"
        else
            log_warn "Dashboard state is invalid or not yet initialized"
        fi
    fi

    echo "========================================"

    if [ $all_running -eq 0 ]; then
        log_error "Some components are not running"
        return 1
    else
        log_success "All components are running"
        return 0
    fi
}

# ============================================================================
# Kill All Agents
# ============================================================================

kill_all() {
    echo ""
    log_info "Killing all agent processes..."

    pkill -f "orchestrator/main.py" || true
    pkill -f "self_heal.py" || true
    pkill -f "dashboard/server.py" || true

    sleep 1

    if pgrep -f "orchestrator/main.py" > /dev/null 2>&1; then
        log_warn "Orchestrator still running, force killing..."
        pkill -9 -f "orchestrator/main.py" || true
    fi

    log_success "All agent processes killed"
}

# ============================================================================
# Start Components
# ============================================================================

start_orchestrator() {
    log_info "Starting orchestrator (v1→v1000 auto-loop)..."

    cd "$REPO_ROOT"
    python3 orchestrator/main.py --auto 1 \
        > "$LOG_DIR/orchestrator.log" 2>&1 &

    local PID=$!
    echo $PID > "$PID_DIR/orchestrator.pid"

    sleep 2

    if ps -p $PID > /dev/null 2>&1; then
        log_success "Orchestrator started (PID: $PID)"
        return 0
    else
        log_error "Orchestrator failed to start"
        cat "$LOG_DIR/orchestrator.log"
        return 1
    fi
}

start_self_heal() {
    log_info "Starting self-heal loop (1-hour recovery cycle)..."

    cd "$REPO_ROOT"
    python3 local-agents/orchestrator/self_heal.py \
        > "$LOG_DIR/self_heal.log" 2>&1 &

    local PID=$!
    echo $PID > "$PID_DIR/self_heal.pid"

    sleep 1

    if ps -p $PID > /dev/null 2>&1; then
        log_success "Self-heal loop started (PID: $PID)"
        return 0
    else
        log_error "Self-heal loop failed to start"
        cat "$LOG_DIR/self_heal.log"
        return 1
    fi
}

setup_auto_recover_cron() {
    log_info "Setting up auto-recover cron job (every 2 minutes)..."

    cd "$REPO_ROOT"

    # First run to initialize
    bash scripts/auto_recover.sh > "$LOG_DIR/auto_recover_init.log" 2>&1
    log_success "Auto-recover initialized"

    # Add to crontab if not already there
    local cron_entry="*/2 * * * * cd $REPO_ROOT && bash scripts/auto_recover.sh >> $LOG_DIR/auto_recover.log 2>&1"

    if crontab -l 2>/dev/null | grep -q "auto_recover.sh"; then
        log_warn "Auto-recover cron job already exists, skipping"
    else
        (crontab -l 2>/dev/null || echo ""; echo "$cron_entry") | crontab - 2>/dev/null || true
        log_success "Auto-recover cron job added"
    fi
}

start_dashboard() {
    log_info "Dashboard server should already be running..."

    if check_process "Dashboard" "dashboard/server.py"; then
        log_success "Dashboard is running"
        return 0
    else
        log_warn "Dashboard is not running, starting it..."
        cd "$REPO_ROOT"
        python3 dashboard/server.py --port 3001 \
            > "$LOG_DIR/dashboard.log" 2>&1 &

        local PID=$!
        echo $PID > "$PID_DIR/dashboard.pid"

        sleep 2

        if ps -p $PID > /dev/null 2>&1; then
            log_success "Dashboard started (PID: $PID, port 3001)"
            return 0
        else
            log_error "Dashboard failed to start"
            return 1
        fi
    fi
}

# ============================================================================
# Main Startup
# ============================================================================

main() {
    case "${1:-start}" in
        start)
            echo ""
            echo "========================================"
            echo "🚀 Starting Agent System (24/7 Mode)"
            echo "========================================"

            start_orchestrator || exit 1
            start_self_heal || exit 1
            setup_auto_recover_cron
            start_dashboard || log_warn "Dashboard startup had issues"

            echo ""
            log_success "All components started successfully!"
            echo ""
            echo "Logs available at:"
            echo "  • Orchestrator: $LOG_DIR/orchestrator.log"
            echo "  • Self-Heal:    $LOG_DIR/self_heal.log"
            echo "  • Auto-Recover: $LOG_DIR/auto_recover.log"
            echo "  • Dashboard:    $LOG_DIR/dashboard.log"
            echo ""
            echo "Dashboard UI: http://localhost:3001"
            echo ""
            ;;

        status)
            status
            ;;

        kill)
            kill_all
            ;;

        restart)
            log_info "Restarting agent system..."
            kill_all
            sleep 2
            "$0" start
            ;;

        --status)
            status
            ;;

        --kill)
            kill_all
            ;;

        --restart)
            kill_all
            sleep 2
            "$0" start
            ;;

        *)
            echo "Usage: $0 {start|status|kill|restart}"
            echo ""
            echo "Commands:"
            echo "  start   - Start all components (default)"
            echo "  status  - Check component status"
            echo "  kill    - Stop all components"
            echo "  restart - Kill and restart all components"
            echo ""
            exit 1
            ;;
    esac
}

main "$@"
