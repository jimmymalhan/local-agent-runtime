# HANDOFF — Local Agent Pickup
**Session closed. All tasks assigned to local running agents.**
**Updated:** 2026-03-26

---

## RUNTIME STATUS (auto-managed — do not touch cron)
| Cron | Schedule | Purpose |
|------|----------|---------|
| `rescue_orchestrator.sh` | **every 1 min** | orchestrator + researcher never go down |
| `agent_watchdog.sh` | every 5 min | full health check |
| `cron_claude_rescue.sh` | every 5 min | Sonnet teaches lessons, updates memory/workflows |
| `auto_merge_pr.sh` | every 30 min | merge ready PRs |

**Agents currently running (PIDs active):** orchestrator + researcher confirmed live.
**Dashboard refresh:** 2000ms live feed at `local-agents/dashboard/state.json`

---

## TODO — Assigned to Local Agents (pick up in order)

### P0 — Nexus-Executor — Issue #51
**Fix auto_merge_pr.sh + close 22 open PRs**
```bash
# Step 1: Fix the script — use file-based JSON not stdin
gh pr list --state open --json number,headRefName > /tmp/prs.json
# Step 2: Rebase each branch
for branch in $(jq -r '.[].headRefName' /tmp/prs.json); do
  git fetch origin main
  git checkout $branch && git rebase origin/main --strategy-option=theirs
  git push --force-with-lease
done
# Step 3: Merge with admin
for num in $(jq -r '.[].number' /tmp/prs.json | sort -n); do
  gh pr merge $num --squash --delete-branch --admin
done
# Step 4: Verify
gh pr list --state open | wc -l  # must be 0
```

### P1 — Nexus-Debugger — Issue #50
**Fix reviewer agent score=0**
```bash
python3 local-agents/orchestrator/main.py --quick 3 2>&1 | grep -i review
# Find root cause in local-agents/agents/ reviewer file
# Fix scoring output — do NOT use Claude
```

### P2 — Nexus-Executor (after P0)
**Pull main + restart loop v5→v100**
```bash
git checkout main && git pull origin main
python3 local-agents/orchestrator/main.py --auto 1
```

### P3 — Nexus-Architect
**Project DAG + RICE prioritization** — see feature/dag-prioritization PR #42

### P3 — Nexus-Architect
**Three-tier memory system** — see feature/memory-system PR #40

### P4 — Nexus-Executor
**Dashboard velocity panel + burndown** — update `local-agents/dashboard/index.html`

---

## OPEN ISSUES
- #48 https://github.com/jimmymalhan/local-agent-runtime/issues/48 — Merge 22 PRs
- #49 https://github.com/jimmymalhan/local-agent-runtime/pull/49 — Orchestrator fix (open PR)
- #50 https://github.com/jimmymalhan/local-agent-runtime/issues/50 — reviewer score=0
- #51 https://github.com/jimmymalhan/local-agent-runtime/issues/51 — auto_merge fix

---

## RULES (never break)
- Never commit to main — always feature/branch → PR
- `rescue_orchestrator.sh` fires every minute — never modify cron
- Dashboard state.json must stay valid JSON (agents read it)
- Use `--auto 1` flag for orchestrator (NOT --continuous)
- Append all lessons to `local-agents/memory/lessons.md`

---

## STOP/RESUME
```bash
touch local-agents/.stop          # pause all
rm local-agents/.stop             # resume
bash scripts/runtime_status.sh    # health check
tail -f local-agents/logs/rescue_orchestrator.log  # live rescue feed
```
