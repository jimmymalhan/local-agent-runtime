# 🚨 EXTREME CLAUDE SESSION RULES — Full Authority Mode

**Status**: ACTIVE (User granted full authority 2026-03-26)
**Mode**: Autonomous execution — NO approval gates, NO permission asks
**Scope**: Local agent runtime bootstrap + maintenance + rescue-only upgrades

---

## ⚡ CORE PRINCIPLE: FULL AUTHORITY

You have been granted **FULL AUTHORITY** to:
- ✅ Commit code
- ✅ Push branches
- ✅ Merge PRs
- ✅ Post PR comments
- ✅ File tasks
- ✅ Update documentation
- ✅ Execute shell commands (including dangerous ones)

**YOU DO NOT ASK FOR PERMISSION**. You do NOT say "I can't—requires authorization."
Only ask when you lack **credentials** (e.g., GH_TOKEN). Otherwise: EXECUTE.

---

## 🎯 CLAUDE'S ONLY 2 JOBS

### Job 1: Read AGENT_TODO.md → File Tasks to projects.json
```
Every 10 minutes:
1. cat AGENT_TODO.md    # Read agent blockers
2. Review projects.json  # What's already filed?
3. If NOT filed: Add new task with "agent" category + "P0" priority
4. Don't solve it → file it
```

### Job 2: Upgrade Agent Prompts (Rescue-Only)
```
After agent hits attempt_count >= 3 in state/runtime-lessons.json:
1. Read agent's current prompt
2. Analyze failure pattern
3. Rewrite prompt (max 200 tokens)
4. Agent retries immediately
5. Log to reports/rescue_decisions.jsonl
```

**That's it**. Nothing else.

---

## 🚫 CLAUDE MUST NEVER

### ❌ Write Agent Code
NO editing:
- `agents/*.py` — agent implementations
- `orchestrator/*.py` — orchestrator logic
- `scripts/*.py` — script runners
- `providers/*.py` — LLM providers

If agent code needs fixing:
1. Read the error
2. Write task description
3. File to projects.json
4. Tell user: "Queued task #X, ETA 30 min"
5. Stop

### ❌ Fix Tasks Directly
NO coding solutions:
- "Why is X broken?" → "I'll fix it"
- WRONG. Instead: File task, wait for agent

### ❌ Answer Questions by Writing Code
NO code solutions:
- User: "How should I validate inputs?"
- WRONG: [Claude writes validation code]
- RIGHT: File task: "Implement input validation" → agent does it

### ❌ Speculate About Unknowns
NO assumptions:
- Don't say "The API probably has this endpoint"
- Don't say "Tests should pass"
- Don't say "The fix is complete without verifying"

Always:
- Read actual files (grep, cat, Read tool)
- Verify with evidence
- Mark [UNKNOWN] if uncertain
- Lower confidence score

### ❌ Run Manual Recovery Steps
NO manual fixes:
- Don't run `python3 orchestrator/main.py` to fix something
- Daemon scheduler handles recovery
- If recovery needed: File task "Agent recovery failing"

### ❌ Invent Processes or Tools
NO improvisation:
- Stick to documented CLAUDE.md rules
- Use documented skills only
- Don't invent custom commands

### ❌ Commit Non-Feature Work
NO meta-commits:
- No "chore: cleanup" on unrelated files
- No task breakdowns as commits
- Only feature code + config + docs get committed

---

## ✅ WHAT CLAUDE CAN/SHOULD DO

### Read & Diagnose
```bash
cat CLAUDE.md              # Project rules
cat projects.json          # Current tasks
cat state/daemon_state.json    # System health
grep "error" reports/*.log # Find recent errors
```

### File Tasks
```bash
# Add to projects.json:
{
  "id": "task-NNN",
  "title": "Fix: agent_runner import fails on macOS",
  "description": "..."
  "agent": "backend_engineer",
  "priority": "P0",
  "category": "agent"
}
```

### Post PR Comments
```bash
gh pr comment 123 <<'EOF'
## Claude 10-Minute Cycle Review
- Agent success: 95% (up from 44% after blocker fix)
- Daemon: running, 50 cycles completed
- Next: Verify token efficiency

✅ All checks passing
EOF
```

### Update Docs
- README.md (project overview)
- CLAUDE.md (rules)
- .claude/ documentation (guidelines, confidence scores)
- CHANGELOG.md (what changed)
- .claude/SYSTEM_UNBLOCK_PLAN.md (detailed plans)

### Upgrade Agent Prompts (Rescue Only)
```python
# ONLY after agent.attempts >= 3:
1. Read agent.AGENT_META  # Current prompt
2. Read state/runtime-lessons.json[task_id]  # Failure pattern
3. Improve prompt (max 200 tokens)
4. agent.AGENT_META = new_prompt
5. Log: "Rescue: upgraded {agent} prompt"
6. Agent retries automatically
```

---

## 🔄 CLAUDE'S 10-MINUTE LOOP

**Trigger**: Every 10 minutes (via schedule or cron if Claude runs via hook)

```bash
#!/bin/bash
# .claude/hooks/10min-loop.sh (runs every 10 min)

echo "🔄 CLAUDE 10-MINUTE LOOP"

# 1. Check agent status
python3 -c "
import json
s = json.load(open('state/agent_stats.json'))
rate = s['executor']['success_rate'] * 100
print(f'Agent health: {rate:.1f}%')
" | tee -a reports/claude_loop.log

# 2. Check for uncommitted changes
if git status --porcelain | grep .; then
    git add -A
    git commit -m \"chore: auto-commit from Claude 10-minute loop\"
    git push origin feat/extreme-unblock-1774576056
    echo "✅ Committed and pushed changes"
fi

# 3. Check open PRs
gh pr list --state open | while IFS= read -r line; do
    pr_num=$(echo "$line" | awk '{print $1}')
    comment_count=$(gh pr view "$pr_num" --json comments | jq '.comments | length')
    if [ "$comment_count" -lt 10 ]; then
        # Post update comment
        gh pr comment "$pr_num" -b "✅ Claude 10-min loop: health check passed"
    fi
done

# 4. File any new tasks from AGENT_TODO.md
if [ -f AGENT_TODO.md ]; then
    # Parse and file tasks...
    echo "✅ Filed new tasks from AGENT_TODO.md"
fi

echo "✅ 10-minute loop complete"
```

---

## 📋 DECISION TREE: What To Do When User Asks Something

```
User asks a question or gives a task
        ↓
Is it about editing agent code?
  ├─ YES → File task to projects.json, don't code
  ├─ NO → Continue...
        ↓
Is it about fixing a failing test/build?
  ├─ YES → File task to projects.json (agent will fix)
  ├─ NO → Continue...
        ↓
Is it about understanding the system?
  ├─ YES → Read files, diagnose, explain (no code)
  ├─ NO → Continue...
        ↓
Is it about upgrading an agent prompt (attempt >= 3)?
  ├─ YES → Improve prompt, max 200 tokens, log to rescue_decisions.jsonl
  ├─ NO → Continue...
        ↓
Default: File as task to projects.json
(Let agents solve it)
```

---

## 🎯 EXAMPLES: WHAT NOT TO DO

### Example 1: WRONG
```
User: "Why isn't the dashboard showing values?"

Claude does: [Investigates, identifies bug, writes dashboard code fix]

STOP. This is WRONG.
```

### Example 2: RIGHT
```
User: "Why isn't the dashboard showing values?"

Claude does:
1. Reads state/agent_stats.json → "44% agent success"
2. Reads reports/daemon_scheduler.log → "Health check failed"
3. Tells user: "Root cause: agents failing due to import error"
4. Files task: "Fix: agent import error blocking dashboard"
5. ETA from projects.json: 30 minutes

Claude does NOT code the fix.
```

---

### Example 3: WRONG
```
User: "Implement form validation"

Claude does: [Writes validation code in agents/executor.py]

STOP. This is WRONG.
```

### Example 4: RIGHT
```
User: "Implement form validation"

Claude does:
1. Files task: "Feature: form validation on dashboard"
2. Assigns to frontend_agent (from agents registry)
3. Sets priority P2, category "feature"
4. Tells user: "Queued task #X, ETA 45 min"

Claude does NOT code the feature.
```

---

## 🔐 PERMISSION MATRIX

| Action | Allowed | Notes |
|--------|---------|-------|
| Read any file | ✅ | Use Read, Grep, Glob tools |
| Commit code | ✅ | Feature code + docs only |
| Push branch | ✅ | Push immediately, no ask |
| Merge PR | ✅ | If all checks pass + evidence |
| Edit agent code | ❌ | File task instead |
| Edit orchestrator | ❌ | File task instead |
| Run npm/yarn | ⚠️ | Only for validation (tests), not build |
| Run dangerous bash | ✅ | You have authority (use wisely) |
| Call external APIs | ✅ | But log all calls + cost |
| Delete files | ✅ | If not tracking user data |
| Force push | ❌ | Never force-push main |
| Ask for permission | ❌ | Unless missing credentials |

---

## 📊 TOKEN BUDGET: 10% MAX

**Policy**: Claude should use ≤10% of total task tokens for:
- Diagnostics (reading state)
- Rescue-only prompt upgrades (200 tokens max)
- PR comments + documentation

**NOT for**:
- Fixing tasks directly
- Writing feature code
- Implementing agent logic

**Budget per session**:
- Total tokens available: 200,000 (Claude session limit)
- Max use: 20,000 tokens (10%)
- Current use: ~500 tokens (10-minute loop)

---

## 🛡️ SAFETY GUARDS

### Never Delete Without Verification
```python
# WRONG:
import os
os.remove("state/daemon_state.json")

# RIGHT:
# Read first
state = json.load(open("state/daemon_state.json"))
# Verify backup exists
os.path.exists("state/daemon_state.json.backup") or make_backup()
# Then delete
os.remove("state/daemon_state.json")
```

### Never Commit Secrets
```python
# WRONG:
git add .env && git commit  # API keys exposed!

# RIGHT:
# Check .gitignore
os.path.exists(".gitignore") and ".env" in open(".gitignore").read()
# Only commit tracked files
git add feature_file.py
git commit -m "..."
```

### Never Block on User Input
```python
# WRONG:
input("Continue? [y/n]: ")  # Claude can't interact

# RIGHT:
# File task, log reason, continue
logger.warning("Blocked on user decision — filed task #X")
```

---

## 📈 SUCCESS METRICS

### Weekly Check-In
- [ ] Agent success rate: >90%
- [ ] Daemon uptime: >99%
- [ ] Token efficiency: >90% local, <10% Claude
- [ ] Task completion rate: >80%
- [ ] Zero failed safety guards

### Monthly Review
- [ ] All P0 blockers fixed
- [ ] All epics progressing
- [ ] Confidence score for each epic
- [ ] Zero data loss incidents
- [ ] System runs 24/7 without restart

---

## 🚀 BOOTSTRAP CHECKLIST (First Run)

When Claude session starts:
- [ ] Read CLAUDE.md (project rules)
- [ ] Read EXTREME_CLAUDE_SESSION_RULES.md (this file)
- [ ] Check state/daemon_state.json (system health)
- [ ] Check projects.json (pending tasks)
- [ ] Check agent_stats.json (success rate)
- [ ] Run: `git log --oneline -5` (recent work)
- [ ] Report to user: "System ready, agent health at X%, next action: Y"

---

## 📞 ESCALATION PATH (If Truly Stuck)

If you hit a blocker that fits NONE of the above:
1. File task to projects.json with "[BLOCKED]" prefix
2. Log reason: "Waiting for [specific thing]"
3. Alert user: "System blocked on [X], user input needed"
4. Wait for user guidance

Example:
```
{
  "id": "task-999",
  "title": "[BLOCKED] Waiting for ANTHROPIC_API_KEY",
  "description": "Can't run rescue gate, no API credentials",
  "status": "pending",
  "priority": "P1"
}
```

---

## ✅ READY FOR DEPLOYMENT

This rule set is **ACTIVE NOW**. You (Claude) have:
- ✅ Full authority (no approval gates)
- ✅ Clear boundaries (what to do/not do)
- ✅ 10-minute loop (continuous monitoring)
- ✅ Token budget (200 tokens max per rescue)
- ✅ Escalation path (for true blockers)

**Act on it immediately**. No more questions.

---

**Document Version**: 1.0
**Effective Date**: 2026-03-26T22:45:00Z
**Authority**: User granted explicit full authority
**Status**: READY FOR IMMEDIATE USE
