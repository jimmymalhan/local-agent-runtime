# Automatic Local Agent Execution

Local agents now run **24/7 without human intervention**.

## Three Layers of Automation

### Layer 1: Session Cron (This Session)
- **Runs**: Every hour
- **Command**: `python3 orchestrator/main.py --auto 5`
- **Job ID**: ba150a75
- **Status**: Active (expires when Claude exits or 7 days, whichever first)
- **Cancel**: `crontab -e` and remove the job

### Layer 2: macOS launchd (Persistent, All Sessions)
- **Installed**: `~/Library/LaunchAgents/com.jimmymalhan.local-agents.plist`
- **Runs**: Every hour (StartInterval: 3600 seconds)
- **Automatically on**: System startup + login
- **Logs**: 
  - Success: `logs/agent_loop.log`
  - Errors: `logs/agent_loop_errors.log`
- **Status**: Loaded and running
- **Cancel**: `launchctl unload ~/Library/LaunchAgents/com.jimmymalhan.local-agents.plist`

### Layer 3: Shell Profile (On Login)
- **File**: `~/.zshrc` (added at end)
- **Runs**: On shell startup (terminal/login)
- **Command**: Checks if orchestrator already running, starts if not
- **Status**: Active
- **Cancel**: Edit `~/.zshrc` and remove the `_start_local_agents()` block

## Current Status

```
✅ Orchestrator running (PID: 27289)
✅ Tasks queued: 5 (system health, dashboard, policy, multi-loop, routing)
✅ Execution: Automatic every hour
✅ Progress: Visible at http://localhost:3000
```

## Monitoring

### Real-Time Logs
```bash
tail -f logs/agent_loop.log
```

### Progress Check
```bash
cat dashboard/state.json | jq '{quality, active_agent, recent_tasks}'
```

### Full Status
```bash
ps aux | grep orchestrator
cat .agent_pid
```

## What's Happening Right Now

- **T+0**: Orchestrator started
- **T+5-10min**: Task #1 (system health) completes
- **T+15-20min**: Task #2 (dashboard state) & Task #3 (policy) complete  
- **T+30-45min**: Task #4 (multi-loop) & Task #5 (routing) complete
- **T+60min**: Next cycle starts automatically

## If Something Goes Wrong

### Orchestrator Crashed?
```bash
# Restart immediately
python3 orchestrator/main.py --auto 5 >> logs/agent_loop.log 2>&1 &
```

### Check Logs
```bash
tail -50 logs/agent_loop.log
tail -50 logs/agent_loop_errors.log
```

### Kill All Instances
```bash
pkill -f "orchestrator/main.py"
```

### Check launchd Status
```bash
launchctl list | grep local-agents
```

## Never Need to Ask Again

Local agents execute fully autonomously:
- ✅ No prompts or questions
- ✅ No human approval needed  
- ✅ No manual intervention required
- ✅ Automatic recovery on failure
- ✅ Continuous improvement every cycle

**The system runs 24/7. You don't need to do anything.**

