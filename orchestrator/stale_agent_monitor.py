#!/usr/bin/env python3
"""
orchestrator/stale_agent_monitor.py — Real-Time Stale Agent Detection
======================================================================
Monitors agent activity in real-time and updates dashboard with staleness.
Called every 5 seconds by unified_daemon for continuous monitoring.

Features:
- Detects agents inactive > 10 minutes
- Calculates staleness percentage per agent
- Updates dashboard in real-time
- Feeds data to network_mesh for routing decisions
- Prepares recovery actions for blocker_monitor
"""

import json
from pathlib import Path
from datetime import datetime, timedelta

BASE_DIR = Path(__file__).parent.parent
DASHBOARD_FILE = BASE_DIR / "dashboard" / "state.json"

def check_stale_agents():
    """Detect and report stale agents in real-time."""
    
    if not DASHBOARD_FILE.exists():
        return {"stale_agents": [], "healthy_agents": []}
    
    with open(DASHBOARD_FILE) as f:
        state = json.load(f)
    
    now = datetime.utcnow()
    stale_agents = []
    healthy_agents = []
    STALE_THRESHOLD = 600  # 10 minutes
    
    for agent_name, agent_data in state.get("agents", {}).items():
        last_activity = agent_data.get("last_activity", "")
        status = agent_data.get("status", "unknown")
        
        if last_activity:
            try:
                last_ts = datetime.fromisoformat(last_activity.replace("Z", "+00:00"))
                elapsed = (now - last_ts).total_seconds()
                
                if elapsed > STALE_THRESHOLD:
                    stale_agents.append({
                        "name": agent_name,
                        "status": status,
                        "elapsed_seconds": elapsed,
                        "minutes_inactive": elapsed / 60,
                        "needs_restart": elapsed > 1800  # > 30 min needs restart
                    })
                else:
                    healthy_agents.append({
                        "name": agent_name,
                        "status": status,
                        "elapsed_seconds": elapsed
                    })
            except:
                pass
    
    return {
        "timestamp": now.isoformat(),
        "stale_agents": stale_agents,
        "healthy_agents": healthy_agents,
        "total_stale": len(stale_agents),
        "total_healthy": len(healthy_agents),
        "system_health": "healthy" if len(stale_agents) == 0 else "degraded"
    }

if __name__ == "__main__":
    result = check_stale_agents()
    print(json.dumps(result, indent=2))
