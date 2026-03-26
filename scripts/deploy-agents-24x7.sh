#!/bin/bash
# deploy-agents-24x7.sh — Deploy agents for permanent 24/7 autonomous operation
# Run this once to set up permanent agent automation

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
LAUNCH_AGENT="$HOME/Library/LaunchAgents/com.nexus.agents.plist"
LOG_DIR="/tmp/nexus-logs"
mkdir -p "$LOG_DIR"

echo "=== NEXUS 24/7 AGENT DEPLOYMENT ==="
echo ""

# Step 1: Merge PR #53 to main (force-enable auto-merge)
echo "Step 1: Enable auto-merge for PR #53..."
gh pr merge 53 --auto --squash --delete-branch 2>&1 || echo "  (PR may already be queued for merge)"
echo ""

# Step 2: Load launchd service
echo "Step 2: Install permanent agent service..."
if [ -f "$LAUNCH_AGENT" ]; then
    launchctl unload "$LAUNCH_AGENT" 2>/dev/null || true
    sleep 1
fi
launchctl load "$LAUNCH_AGENT"
echo "  ✓ Agents service loaded (will persist across reboots)"
echo ""

# Step 3: Wait for service to start
echo "Step 3: Starting agents..."
sleep 3
if launchctl list | grep -q "com.nexus.agents"; then
    echo "  ✓ Service is running"
else
    echo "  ✗ Service failed to start (check: launchctl list | grep nexus)"
    exit 1
fi
echo ""

# Step 4: Verify agents are executing tasks
echo "Step 4: Verifying agent execution..."
sleep 5
if tail -20 "$LOG_DIR"/* 2>/dev/null | grep -q "task_done\|tasks_completed"; then
    echo "  ✓ Agents are executing tasks"
else
    echo "  ! Agents started but no task completion yet (may take 30s)"
fi
echo ""

# Step 5: Show dashboard status
echo "Step 5: Agent status..."
ps aux | grep -E "continuous_loop|live_state|dashboard" | grep -v grep || true
echo ""

echo "=== DEPLOYMENT COMPLETE ==="
echo ""
echo "Agents are now running 24/7. Status:"
echo "  Service: com.nexus.agents"
echo "  Logs: /tmp/nexus-logs/* and /tmp/nexus-agents.log"
echo "  Control:"
echo "    Start:   launchctl start com.nexus.agents"
echo "    Stop:    launchctl stop com.nexus.agents"
echo "    Unload:  launchctl unload $LAUNCH_AGENT"
echo "    Status:  launchctl list | grep nexus"
echo ""
echo "Dashboard: http://localhost:3001"
echo "Task queue: local-agents/projects/projects.json"
echo ""
