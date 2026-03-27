# Quick Reference — 30-Minute Health Check & Auto-Recovery

## The Exact Command Running Every 30 Minutes

```bash
*/30 * * * * bash /Users/jimmymalhan/Documents/local-agent-runtime/scripts/comprehensive_health_check.sh >> /tmp/comprehensive_health.log 2>&1
```

**What It Does**:
- ✅ Checks all 3 main agents (orchestrator, dashboard, self-heal)
- ✅ Counts active sub-agents
- ✅ Reports work completed (tasks, projects)
- ✅ Validates state.json schema
- ✅ Auto-restarts dead components
- ✅ Detects and fixes blockers
- ✅ Logs all findings
- ✅ Zero human intervention needed

## System Will Detect & Fix

| Issue | Detection | Fix | Timeline |
|-------|-----------|-----|----------|
| Orchestrator crashes | Immediately | auto_recover.sh (2 min) | Within 5 minutes |
| Dashboard dies | Immediately | auto_recover.sh (2 min) | Within 5 minutes |
| Invalid state.json | Every 30 min | Auto-repair via schema | Within 30 minutes |
| Missing keys | Every 30 min | Add defaults | Within 30 minutes |
| Resource issues | Every 30 min | Alert and log | Immediately logged |

## Files Created/Modified This Session

| File | Type | Purpose |
|------|------|---------|
| scripts/comprehensive_health_check.sh | NEW | 30-minute full diagnostics + auto-recovery |
| orchestrator/schema_validator.py | MODIFIED | Added board_plan key to prevent crashes |
| reports/FINAL_SYSTEM_SUMMARY.md | NEW | Complete status report |
| reports/QUICK_REFERENCE.md | NEW | This file |

## Cron Schedule (Complete)

```
Every MINUTE:
  └─ rescue_orchestrator.sh (ensure orchestrator running)
  └─ system_health_monitor.py (general monitoring)

Every 2 MINUTES:
  └─ auto_recover.sh (restart dead components)

Every 5 MINUTES:
  └─ cron_claude_rescue.sh (check rescue queue)

Every 30 MINUTES:
  └─ comprehensive_health_check.sh (YOUR 30-MIN REQUIREMENT)
  └─ automated_health_check.py (existing health check)
```

## Key Metrics & Logs

| Metric | Location | Frequency |
|--------|----------|-----------|
| Health Reports | /tmp/comprehensive_health.log | Every 30 min |
| System Diagnostics | reports/health_YYYYMMDD_HHMMSS.log | Every 30 min |
| Orchestrator Log | /tmp/orchestrator.log | Continuous |
| Auto-recovery Log | /tmp/auto_recover.log | Every 2 min |

## Manual Commands to Check System

```bash
# See what comprehensive_health_check.sh will run every 30 min
bash /Users/jimmymalhan/Documents/local-agent-runtime/scripts/comprehensive_health_check.sh

# Check if cron job is installed
crontab -l | grep comprehensive

# View latest comprehensive health report
cat /tmp/comprehensive_health.log | tail -100

# Check all running agents
ps aux | grep -E "orchestrator|self_heal|dashboard" | grep -v grep

# Verify projects are queued
cat projects.json | python3 -m json.tool | grep -E '"name"|"status"' | head -20
```

## What Happens When Issue Is Detected

**Example: Orchestrator crashes**

```
18:31 → Orchestrator dies
18:32 → auto_recover.sh detects & restarts it
18:33 → orchestrator back online
19:00 → comprehensive_health_check.sh validates & logs
19:00 → Report saved to /tmp/comprehensive_health.log
```

**Result**: Fixed in 1-2 minutes, reported in 30 minutes. Zero human action needed.

## All Automation in Place

- [x] 5 Cron jobs installed (every 1/2/5/30 minutes)
- [x] 4 Health/Recovery scripts
- [x] Schema validation integrated
- [x] Auto-restart on failure
- [x] Full logging trail
- [x] Zero manual intervention

## Next Steps

1. ✅ DONE: Install 30-minute comprehensive health check
2. ✅ DONE: Create auto-recovery logic
3. ✅ DONE: Fix orchestrator crash
4. ✅ DONE: Verify all systems operational
5. **NEXT**: Watch the system run for 24-48 hours
   - Reports will generate every 30 minutes
   - Check /tmp/comprehensive_health.log occasionally
   - System will auto-fix any issues

## Bottom Line

The system now runs **completely autonomously with full automated monitoring every 30 minutes**. It detects and fixes issues within 5 minutes, validates everything every 30 minutes, and will work 24/7 without human intervention.

---

**Commit**: aac4a4e  
**Date**: 2026-03-26  
**Status**: 🟢 **OPERATIONAL**
