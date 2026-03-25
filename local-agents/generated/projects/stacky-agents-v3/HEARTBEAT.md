# HEARTBEAT.md - Self-Healing Monitor

## Overview
The Heartbeat system runs every 15 minutes to ensure all agents and cron jobs are healthy. It detects failures, attempts auto-recovery, and escalates when needed.

## Heartbeat Schedule
```yaml
heartbeat:
  interval_minutes: 15
  active_hours: "00:00-23:59"  # 24/7
  stale_threshold_hours: 26   # Jobs older than this are considered stale
  max_recovery_attempts: 3
  escalation_channel: "slack"  # or "email", "discord"
```

## Health Checks

### 1. Cron Job Health
Check if any scheduled jobs have missed their execution window.

```yaml
cron_jobs:
  - id: "daily-cleanup"
    schedule: "0 3 * * *"
    max_age_hours: 26
    action_on_stale: "force-run"
    
  - id: "hourly-sync"
    schedule: "0 * * * *"
    max_age_hours: 2
    action_on_stale: "force-run"
    
  - id: "health-check"
    schedule: "*/15 * * * *"
    max_age_hours: 1
    action_on_stale: "alert"
```

### 2. Agent Health
Verify each agent can respond and has valid state.

```yaml
agent_health:
  check_type: "ping"
  timeout_ms: 5000
  required_files:
    - SOUL.md
    - MEMORY.md
  max_memory_file_age_hours: 48
```

### 3. System Resources
Monitor system resources to prevent crashes.

```yaml
resource_limits:
  max_cpu_percent: 80
  max_memory_percent: 85
  max_disk_percent: 90
  action_on_breach: "pause-agents"
```

### 4. Database Health
Ensure database is accessible and responsive.

```yaml
database_health:
  check_query: "SELECT 1"
  timeout_ms: 3000
  action_on_failure: "retry"
  max_retries: 3
```

## Auto-Recovery Procedures

### Stale Cron Job Recovery
```bash
# Force run a stale cron job
stacky cron run <job_id> --force

# The system will:
# 1. Log the forced execution
# 2. Update last_run_at timestamp
# 3. Record result in cron_jobs table
# 4. Alert if force-run also fails
```

### Agent Recovery
```bash
# If agent is unresponsive
stacky agent restart <agent_id>

# The system will:
# 1. Save current agent state
# 2. Terminate agent process
# 3. Restart with fresh context
# 4. Load SOUL.md and MEMORY.md
# 5. Resume from saved state
```

### Resource Recovery
```bash
# If resources are constrained
stacky daemon pause

# The system will:
# 1. Pause all non-critical agents
# 2. Wait for resources to free
# 3. Resume agents one by one
# 4. Alert if resources don't recover
```

## Error Pattern Detection

### Known Error Patterns
```yaml
error_patterns:
  - pattern: "ENOENT: no such file"
    fix: "mkdir -p $(dirname $file)"
    auto_apply: true
    
  - pattern: "Module not found"
    fix: "npm install"
    auto_apply: true
    
  - pattern: "EADDRINUSE"
    fix: "kill $(lsof -t -i:$port)"
    auto_apply: true
    
  - pattern: "ENOMEM"
    fix: "stacky daemon pause --gc"
    auto_apply: true
    
  - pattern: "rate limit exceeded"
    fix: "sleep 60 && retry"
    auto_apply: true
    max_retries: 3
    
  - pattern: "connection refused"
    fix: "stacky service restart $service"
    auto_apply: false  # Requires manual check
    
  - pattern: "SQLITE_BUSY"
    fix: "sleep 1 && retry"
    auto_apply: true
    max_retries: 5
    
  - pattern: "context_length_exceeded"
    fix: "stacky agent trim-context $agent"
    auto_apply: true
```

### Learning From Errors
When a new error is successfully fixed:
1. Extract error pattern
2. Document fix procedure
3. Add to auto-fix registry
4. Update agent MEMORY.md with learnings

## Escalation Procedures

### Level 1: Auto-Fix (Immediate)
- Pattern matches known error
- Auto-fix available
- Less than max_retries attempts

### Level 2: Alert (5 minutes)
- Auto-fix failed
- Unknown error pattern
- Resource constraints detected

### Level 3: Pause (15 minutes)
- Critical system failure
- Data integrity risk
- Security concern detected

### Level 4: Human Required (Immediate)
- Deployment to production
- Database migration
- Security incident
- Cost threshold exceeded

## Notification Templates

### Slack Alert
```json
{
  "channel": "#stacky-alerts",
  "username": "Stacky Heartbeat",
  "icon_emoji": ":heartbeat:",
  "attachments": [{
    "color": "{{severity_color}}",
    "title": "{{alert_title}}",
    "text": "{{alert_message}}",
    "fields": [
      {"title": "Agent", "value": "{{agent_id}}", "short": true},
      {"title": "Error", "value": "{{error_type}}", "short": true},
      {"title": "Attempts", "value": "{{attempt_count}}/{{max_attempts}}", "short": true},
      {"title": "Action Taken", "value": "{{action}}", "short": true}
    ],
    "ts": "{{timestamp}}"
  }]
}
```

### Email Alert
```
Subject: [Stacky] {{severity}}: {{alert_title}}

Agent: {{agent_id}}
Error: {{error_type}}
Time: {{timestamp}}

Details:
{{error_details}}

Action Taken:
{{action}}

Recovery Status:
{{recovery_status}}

---
View logs: {{log_url}}
```

## Memory Maintenance

During each heartbeat, maintain agent memories:

### 1. Context Window Cleanup
```yaml
context_maintenance:
  max_context_tokens: 100000
  cleanup_strategy: "oldest-first"
  preserve:
    - SOUL.md
    - AGENTS.md
    - MEMORY.md
    - current_task
```

### 2. Daily Log Archival
```yaml
log_archival:
  archive_after_days: 7
  archive_location: "memory/archive/"
  compression: "gzip"
```

### 3. Memory Distillation
```yaml
memory_distillation:
  trigger: "daily-logs > 5"
  action: "summarize-to-memory-md"
  preserve_patterns:
    - "Error: *"
    - "Fix: *"
    - "Decision: *"
    - "Human feedback: *"
```

## Heartbeat Execution Flow

```
┌─────────────────┐
│  START HEARTBEAT │
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Check Cron Jobs │──▶ Stale? ──▶ Force Run ──▶ Log
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Check Agents    │──▶ Unhealthy? ──▶ Restart ──▶ Log
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Check Resources │──▶ Constrained? ──▶ Pause ──▶ Alert
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Check Database  │──▶ Unreachable? ──▶ Retry ──▶ Alert
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Check Errors    │──▶ Unresolved? ──▶ Auto-fix ──▶ Log
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Maintain Memory │──▶ Cleanup + Distill
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Update Status   │──▶ intel/DAILY-STATUS.md
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  END HEARTBEAT  │
└─────────────────┘
```

## Manual Commands

```bash
# Force heartbeat check now
stacky heartbeat --force

# View heartbeat history
stacky heartbeat history --days 7

# Check specific agent health
stacky heartbeat check-agent frontend

# Test escalation
stacky heartbeat test-alert --level 2

# View auto-fix registry
stacky heartbeat fixes

# Add new error pattern
stacky heartbeat add-fix --pattern "ERROR" --fix "COMMAND"
```
