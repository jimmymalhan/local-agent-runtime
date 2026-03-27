#!/bin/bash
# resume_if_needed.sh — Auto-resume if health issues detected

BASE_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$BASE_DIR"

# Run health check
bash scripts/health_check.sh

case $? in
    0)
        echo "[RESUME] System healthy, no action needed"
        exit 0
        ;;
    2)
        echo "[RESUME] Warnings detected, attempting repair..."
        # Repair state.json schema
        python3 << 'PYTHON'
from orchestrator.schema_validator import read_state_safe, write_state_safe
state = read_state_safe()
write_state_safe(state)
print("[RESUME] State schema repaired")
PYTHON
        # Restart critical processes if needed
        ;;
    1)
        echo "[RESUME] Critical failure, restarting system..."
        bash scripts/bootstrap.sh
        ;;
esac
