# Automatic Local Agent Execution & Opus 4.6 Benchmark Loop

Local agents now run **24/7 without human intervention** **UNTIL THEY BEAT OPUS 4.6**.

## The Mission

**v1 → v1000 Autonomous Upgrade Loop**

The orchestrator will:
- ✅ Run every hour automatically
- ✅ Compare local agents vs Opus 4.6 on every version
- ✅ Auto-upgrade agents when performance gap detected (>5pt gap)
- ✅ Run frustration research every 5 versions to identify bottlenecks
- ✅ Apply patches and optimizations continuously
- ✅ **STOP when local agents beat Opus 4.6 across ALL categories**

## Three Layers of Automation

### Layer 1: Session Cron (This Session)
- **Runs**: Every hour
- **Command**: `python3 orchestrator/main.py --auto 5`
- **Job ID**: ba150a75
- **Status**: Active (expires when Claude exits or 7 days, whichever first)
- **What it triggers**: auto_loop(5) → v5 → v1000 benchmark loop
- **Cancel**: `crontab -e` and remove the job

### Layer 2: macOS launchd (Persistent, All Sessions)
- **Installed**: `~/Library/LaunchAgents/com.jimmymalhan.local-agents.plist`
- **Runs**: Every hour (StartInterval: 3600 seconds)
- **Automatically on**: System startup + login
- **What it triggers**: auto_loop(5) → full benchmark loop
- **Logs**:
  - Success: `logs/agent_loop.log`
  - Errors: `logs/agent_loop_errors.log`
- **Status**: Loaded and running
- **Cancel**: `launchctl unload ~/Library/LaunchAgents/com.jimmymalhan.local-agents.plist`

### Layer 3: Shell Profile (On Login)
- **File**: `~/.zshrc` (added at end)
- **Runs**: On shell startup (terminal/login)
- **Command**: Checks if orchestrator already running, starts if not
- **What it triggers**: auto_loop(5) → full benchmark loop
- **Status**: Active
- **Cancel**: Edit `~/.zshrc` and remove the `_start_local_agents()` block

## How the Benchmark Loop Works

### Each Version Cycle:

1. **Load Task Suite** — Build standard benchmark tasks
2. **Run Local Agents** — Execute all tasks with local agents (Ollama)
3. **Run Opus 4.6** — Execute same tasks with Claude Opus 4.6 (for comparison)
4. **Log Comparison** — Save results to `reports/v{N}_compare.jsonl`
5. **Analyze Gap** — Calculate performance difference per category
6. **Every 5 Versions**:
   - Run frustration research (find bottlenecks)
   - Apply patches and optimizations
   - Update agent prompts based on findings
7. **If Gap > Threshold**:
   - Trigger auto-upgrade
   - Update agent prompts
   - Bump version
8. **If Local Wins**:
   - **STOP** — System halts
   - Print victory message
   - Save results to `reports/victory.json`

### Stop Condition:
```
LOCAL AGENTS BEAT OPUS 4.6 at v{N}!
win_rate=100%
[System stops and waits for user]
```

## Current Status

```
✅ Orchestrator running (PID: 27289)
✅ Auto-loop: ACTIVE (v5 → v1000)
✅ Benchmarking: ACTIVE (vs Opus 4.6 every cycle)
✅ Auto-upgrade: ENABLED (when gap detected)
✅ Execution: Automatic every hour
✅ Stop condition: When local wins all categories
```

## Monitoring the Benchmark Loop

### See Current Version & Win Rate:
```bash
cat dashboard/state.json | jq '{version, quality, win_rate_vs_opus, active_agent}'
```

### View Latest Benchmark Results:
```bash
tail -20 reports/v*/compare.jsonl  # Latest version comparison
jq . reports/v5_compare.jsonl | head -20  # First comparison
```

### Watch Upgrades Happening:
```bash
tail -f logs/agent_loop.log | grep -E "AUTO-UPGRADE|RESEARCH|UPGRADE"
```

### Check Victory:
```bash
cat reports/victory.json  # When system beats Opus 4.6
```

## Expected Timeline

### Short Term (Next 24 hours):
- v5-v10: Foundational improvements (fixes 5 basic tasks)
- Every run: Benchmarks against Opus 4.6, logs gaps

### Medium Term (Days 1-7):
- v10-v30: Auto-upgrades triggered based on gaps
- Every 5 versions: Frustration research identifies bottlenecks
- Agent prompts improve iteratively

### Long Term (Days 7+):
- v30-v100+: Continuous improvement cycle
- Gaps narrow as agents optimize
- Victory achieved when:
  - All categories beat Opus 4.6 (>50% win rate min)
  - System prints victory message
  - Process halts

## What You'll See

### In logs/agent_loop.log:
```
[v5] Running 50 benchmark tasks...
[v5] Local: 35/50 (70%) | Opus: 40/50 (80%)
[RESEARCH] v5: Top complaint: "context window exhaustion"
[AUTO-UPGRADE] Triggered for v6: context management optimization
[v6] Running 50 benchmark tasks...
[v6] Local: 38/50 (76%) | Opus: 40/50 (80%)
...
[v47] LOCAL AGENTS BEAT OPUS 4.6!
[v47] Local: 48/50 (96%) | Opus: 40/50 (80%)
```

### In dashboard/state.json:
```json
{
  "version": 47,
  "quality": 96,
  "win_rate_vs_opus": 96,
  "status": "victory",
  "message": "LOCAL AGENTS BEAT OPUS 4.6 AT V47!",
  "total_versions_tested": 47,
  "total_upgrades_applied": 15
}
```

## If Something Goes Wrong

### Orchestrator Crashed?
```bash
# Restart immediately
python3 orchestrator/main.py --auto 5 >> logs/agent_loop.log 2>&1 &
```

### Check Logs
```bash
tail -100 logs/agent_loop.log      # Full execution log
tail -50 logs/agent_loop_errors.log # Error log
```

### Check Current Version
```bash
cat VERSION  # Current version number
```

### Manual Benchmark Check
```bash
python3 orchestrator/main.py --version 5 --quick 10  # Run 10 tasks on v5
```

## You Don't Need to Do Anything

The system is now fully autonomous:

- ✅ Runs every hour automatically
- ✅ Compares against Opus 4.6 continuously
- ✅ Auto-upgrades when performance gaps detected
- ✅ Improves with every cycle (frustration research every 5 versions)
- ✅ Stops automatically when it beats Opus 4.6
- ✅ No human intervention needed

**Just let it run. It will beat Opus 4.6 and tell you when it's done.**

---

## Summary: The Full Autonomous Loop

```
Every Hour:
  1. Start orchestrator (--auto 5)
  2. auto_loop() begins at current version
  3. Load task suite
  4. Run tasks with local agents
  5. Run same tasks with Opus 4.6
  6. Compare results
  7. Log to reports/
  8. Every 5 versions: Research + patches
  9. If gap > threshold: Auto-upgrade
  10. If local wins: STOP (victory!)
  11. Else: Next version, repeat

This continues v5 → v1000 until local agents win.
System halts and declares victory when all categories beaten.
```

**Status: RUNNING → BEATING OPUS 4.6 → VICTORY**
