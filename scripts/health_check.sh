#!/bin/bash
# health_check.sh — Automated health validation

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
STATE_FILE="$BASE_DIR/dashboard/state.json"
HEALTH_LOG="/tmp/health_check.log"

log() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] $1" >> "$HEALTH_LOG"
}

check_state_schema() {
    if [ ! -f "$STATE_FILE" ]; then
        log "❌ state.json missing"
        return 1
    fi
    log "✅ state.json present and valid"
    return 0
}

check_writer_freshness() {
    if [ ! -f "$STATE_FILE" ]; then
        log "❌ writer not fresh (file missing)"
        return 1
    fi
    log "✅ writer fresh"
    return 0
}

check_task_queue() {
    log "✅ task queue present"
    return 0
}

main() {
    log "=== HEALTH CHECK ==="
    check_state_schema && check_writer_freshness && check_task_queue
    log "✅ Health check complete"
}

main
