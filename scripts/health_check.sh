#!/bin/bash
set -e

BASE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TIMESTAMP=$(date '+%Y-%m-%d %H:%M:%S')
HEALTH_LOG="${BASE_DIR}/reports/health_check.log"

# Color codes
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Initialize report
{
    echo "═════════════════════════════════════════════════════════════"
    echo "SYSTEM HEALTH CHECK: $TIMESTAMP"
    echo "═════════════════════════════════════════════════════════════"
    echo ""
} | tee "$HEALTH_LOG"

# Check 1: Watchdog daemon running
echo -n "1. Watchdog daemon... " | tee -a "$HEALTH_LOG"
if pgrep -f "watchdog.py" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ RUNNING${NC}" | tee -a "$HEALTH_LOG"
    WATCHDOG_PID=$(pgrep -f "watchdog.py")
    echo "   PID: $WATCHDOG_PID" | tee -a "$HEALTH_LOG"
    WATCHDOG_HEALTH=1
else
    echo -e "${RED}✗ DEAD${NC}" | tee -a "$HEALTH_LOG"
    echo "   Attempting restart..." | tee -a "$HEALTH_LOG"
    python3 "${BASE_DIR}/scripts/watchdog.py" > /dev/null 2>&1 &
    sleep 2
    if pgrep -f "watchdog.py" > /dev/null 2>&1; then
        echo -e "   ${GREEN}✓ Restarted successfully${NC}" | tee -a "$HEALTH_LOG"
        WATCHDOG_HEALTH=1
    else
        echo -e "   ${RED}✗ Restart failed${NC}" | tee -a "$HEALTH_LOG"
        WATCHDOG_HEALTH=0
    fi
fi

# Check 2: Dashboard server running
echo -n "2. Dashboard server (port 3001)... " | tee -a "$HEALTH_LOG"
if lsof -i :3001 > /dev/null 2>&1; then
    echo -e "${GREEN}✓ RUNNING${NC}" | tee -a "$HEALTH_LOG"
    DASHBOARD_HEALTH=1
else
    echo -e "${RED}✗ DOWN${NC}" | tee -a "$HEALTH_LOG"
    echo "   Attempting restart..." | tee -a "$HEALTH_LOG"
    cd "${BASE_DIR}/dashboard" && npm start > /dev/null 2>&1 &
    sleep 3
    if lsof -i :3001 > /dev/null 2>&1; then
        echo -e "   ${GREEN}✓ Restarted successfully${NC}" | tee -a "$HEALTH_LOG"
        DASHBOARD_HEALTH=1
    else
        echo -e "   ${RED}✗ Restart failed${NC}" | tee -a "$HEALTH_LOG"
        DASHBOARD_HEALTH=0
    fi
fi

# Check 3: Orchestrator loop running
echo -n "3. Orchestrator loop... " | tee -a "$HEALTH_LOG"
if pgrep -f "orchestrator/main.py" > /dev/null 2>&1; then
    echo -e "${GREEN}✓ RUNNING${NC}" | tee -a "$HEALTH_LOG"
    ORCH_PID=$(pgrep -f "orchestrator/main.py")
    echo "   PID: $ORCH_PID" | tee -a "$HEALTH_LOG"
    ORCH_HEALTH=1
else
    echo -e "${YELLOW}! NOT RUNNING${NC}" | tee -a "$HEALTH_LOG"
    echo "   (Check Local script for startup)" | tee -a "$HEALTH_LOG"
    ORCH_HEALTH=0
fi

# Check 4: State file validity
echo -n "4. State file (dashboard/state.json)... " | tee -a "$HEALTH_LOG"
if [ -f "${BASE_DIR}/dashboard/state.json" ]; then
    if python3 -m json.tool "${BASE_DIR}/dashboard/state.json" > /dev/null 2>&1; then
        # Check for required fields
        if python3 -c "import json; data=json.load(open('${BASE_DIR}/dashboard/state.json')); assert 'version' in data and 'agents' in data" 2>/dev/null; then
            echo -e "${GREEN}✓ VALID${NC}" | tee -a "$HEALTH_LOG"
            STATE_HEALTH=1
        else
            echo -e "${YELLOW}! INCOMPLETE${NC}" | tee -a "$HEALTH_LOG"
            echo "   Missing required fields" | tee -a "$HEALTH_LOG"
            STATE_HEALTH=0
        fi
    else
        echo -e "${RED}✗ INVALID JSON${NC}" | tee -a "$HEALTH_LOG"
        STATE_HEALTH=0
    fi
else
    echo -e "${RED}✗ NOT FOUND${NC}" | tee -a "$HEALTH_LOG"
    STATE_HEALTH=0
fi

# Check 5: Projects file valid
echo -n "5. Projects file (projects.json)... " | tee -a "$HEALTH_LOG"
if [ -f "${BASE_DIR}/projects.json" ]; then
    if python3 -m json.tool "${BASE_DIR}/projects.json" > /dev/null 2>&1; then
        PROJ_COUNT=$(python3 -c "import json; data=json.load(open('${BASE_DIR}/projects.json')); print(len(data.get('projects', [])))" 2>/dev/null || echo "0")
        echo -e "${GREEN}✓ VALID${NC}" | tee -a "$HEALTH_LOG"
        echo "   Projects: $PROJ_COUNT" | tee -a "$HEALTH_LOG"
        PROJ_HEALTH=1
    else
        echo -e "${RED}✗ INVALID JSON${NC}" | tee -a "$HEALTH_LOG"
        PROJ_HEALTH=0
    fi
else
    echo -e "${RED}✗ NOT FOUND${NC}" | tee -a "$HEALTH_LOG"
    PROJ_HEALTH=0
fi

# Check 6: Task progress
echo -n "6. Task progress... " | tee -a "$HEALTH_LOG"
if [ -f "${BASE_DIR}/state/agent_stats.json" ]; then
    COMPLETED=$(python3 -c "import json; data=json.load(open('${BASE_DIR}/state/agent_stats.json')); print(data.get('completed_count', 0))" 2>/dev/null || echo "0")
    TOTAL=$(python3 -c "import json; data=json.load(open('${BASE_DIR}/state/agent_stats.json')); print(data.get('total_count', 0))" 2>/dev/null || echo "0")
    if [ "$TOTAL" -gt 0 ]; then
        PCT=$((COMPLETED * 100 / TOTAL))
        echo -e "${GREEN}$COMPLETED/$TOTAL ($PCT%)${NC}" | tee -a "$HEALTH_LOG"
        if [ "$PCT" -eq 0 ]; then
            echo -e "   ${YELLOW}! No progress detected${NC}" | tee -a "$HEALTH_LOG"
        fi
    else
        echo -e "${YELLOW}! No tasks tracked${NC}" | tee -a "$HEALTH_LOG"
    fi
else
    echo "   [stats file not found]" | tee -a "$HEALTH_LOG"
fi

# Check 7: Disk space
echo -n "7. Disk space... " | tee -a "$HEALTH_LOG"
AVAILABLE=$(df -h "${BASE_DIR}" | tail -1 | awk '{print $4}')
PERCENT=$(df -h "${BASE_DIR}" | tail -1 | awk '{print $5}' | sed 's/%//')
if [ "$PERCENT" -lt 80 ]; then
    echo -e "${GREEN}$AVAILABLE available ($PERCENT% used)${NC}" | tee -a "$HEALTH_LOG"
else
    echo -e "${YELLOW}$AVAILABLE available ($PERCENT% used)${NC}" | tee -a "$HEALTH_LOG"
fi

# Check 8: Memory usage
echo -n "8. Memory usage... " | tee -a "$HEALTH_LOG"
if [ -f "${BASE_DIR}/state/agent_budgets.json" ]; then
    MEMORY=$(python3 -c "import json; data=json.load(open('${BASE_DIR}/state/agent_budgets.json')); print(f\"{data.get('memory_used_mb', 0):.0f}MB\")" 2>/dev/null || echo "unknown")
    echo "$MEMORY" | tee -a "$HEALTH_LOG"
else
    echo "unknown" | tee -a "$HEALTH_LOG"
fi

echo "" | tee -a "$HEALTH_LOG"
echo "═════════════════════════════════════════════════════════════" | tee -a "$HEALTH_LOG"

# Summary
TOTAL_HEALTH=$((WATCHDOG_HEALTH + DASHBOARD_HEALTH + STATE_HEALTH + PROJ_HEALTH))
if [ "$TOTAL_HEALTH" -ge 3 ]; then
    echo -e "${GREEN}✓ SYSTEM HEALTHY${NC} ($TOTAL_HEALTH/4 checks passed)" | tee -a "$HEALTH_LOG"
elif [ "$TOTAL_HEALTH" -ge 2 ]; then
    echo -e "${YELLOW}! SYSTEM DEGRADED${NC} ($TOTAL_HEALTH/4 checks passed)" | tee -a "$HEALTH_LOG"
else
    echo -e "${RED}✗ SYSTEM CRITICAL${NC} ($TOTAL_HEALTH/4 checks passed)" | tee -a "$HEALTH_LOG"
fi

echo "" | tee -a "$HEALTH_LOG"
echo "Log saved to: $HEALTH_LOG" | tee -a "$HEALTH_LOG"
