# HANDOFF.md — Nexus Control Plane
**Last updated**: 2026-03-26 (Claude Sonnet 4.6 control-plane audit)
**Branch**: feature/handoff-agents-exit

---

## Mission
Turn Nexus into a sellable local-first code assistant:
- Custom local agents as code assistance
- Developer-friendly CLI on the SDK
- Benchmarked local model performance that continuously improves vs Opus 4.6 baseline
- Hardened real-time dashboard (source of truth)
- SLC product outcome + GTM readiness

---

## Current Runtime Status

| Component | Status | Notes |
|-----------|--------|-------|
| live_state_updater.py | ✅ Running | Confirmed via watchdog |
| dashboard/server.py | ✅ Running | Confirmed via watchdog |
| continuous_loop.py | ❌ DOWN | Not running — needs start |
| Cron (watchdog, rescue) | ⚠️ BROKEN | "Operation not permitted" — macOS FDA issue |
| Dashboard data | ❌ STALE | quality=None, model=None, 0 tasks showing |
| Task queue (task_intake) | ✅ Active | 36 pending tasks loaded |

**Critical blocker**: `cron` gets "Operation not permitted" when executing shell scripts.
macOS requires Full Disk Access for `cron`. Until fixed, watchdog auto-restart is non-functional.
Workaround: run `bash scripts/watchdog.sh` manually or fix macOS Terminal FDA permissions.

---

## Active Epics

| Epic ID | Name | Project | Priority |
|---------|------|---------|---------|
| e-pr-hygiene | Fix 21 conflicting PRs + merge 4 MERGEABLE | p-infra | P0 |
| e-dashboard-stale | Dashboard blank data (quality, model, tasks, changelog) | p-dashboard | P0 |
| e-never-down | Orchestrator + loop never-down guarantee | p-nexus | P0 |
| e-cron-broken | macOS cron "Operation not permitted" blocker | p-infra | P0 |
| e-loop-v100 | v1→v100 Continuous Task Loop | p-nexus | P1 |
| e-agent-quality | Agent Quality & Capabilities | p-nexus | P1 |
| e-dashboard-ui | Dashboard UI Features | p-dashboard | P1 |
| e-jobs | jobs.hil-tad.com Core Components | p-jobs | P1 |
| e-memory | Memory System (episodic/semantic/procedural) | p-infra | P2 |
| e-benchmark | Local model benchmarking vs Opus 4.6 | p-nexus | P2 |

---

## Active Projects

| Project | Tasks Queued | Assigned Agent | Status |
|---------|-------------|---------------|--------|
| p-nexus (Nexus Runtime Core) | 8 | executor | active |
| p-dashboard (Nexus Dashboard) | 15 | frontend_agent | active |
| p-jobs (jobs.hil-tad.com) | 6 | frontend_agent | active |
| p-infra (Agent Infrastructure) | 7 | executor/architect | active |
| **TOTAL** | **36** | — | — |

---

## Backlog (High Priority, Not Yet Filed)

- [ ] macOS Full Disk Access fix for cron (ops task — user must grant FDA to Terminal/cron)
- [ ] Benchmark suite: bug fix quality, repo nav, CLI UX, FE regression, task pickup latency
- [ ] GTM readiness: Reddit launch material, ideal customer profile
- [ ] SDK CLI developer-friendly interface (nexus CLI)
- [ ] PR automation: auto-merge passing PRs every 30 min (scripts/auto_pr.sh)
- [ ] Model routing: choose cheapest local model that clears quality threshold
- [ ] Leaderboard: local models vs Opus 4.6 baseline

---

## Blocked Items

| Item | Blocker | Resolution |
|------|---------|-----------|
| Cron auto-restart | macOS FDA not granted to cron | User grants Full Disk Access to Terminal in System Settings → Privacy & Security |
| 19 conflicting PRs | Branches diverged from main | Rebase with --strategy-option=theirs after adding state.json to .gitignore |
| Dashboard blank data | Agents not calling state_writer methods | Tasks t-ce5ff84a, t-644865cf, t-ab37fb1d, t-811f198d, t-7a48cbf1, t-545cf9fe |
| continuous_loop.py | Never started this session | Must start: `python3 local-agents/orchestrator/continuous_loop.py` |

---

## PR Queue

### MERGEABLE (4 PRs — blocked by CI check only)
| PR | Branch | Action |
|----|--------|--------|
| #46 | feature/doc-agent | Merge after CI passes |
| #45 | feature/continuous-loop | Merge after CI passes |
| #44 | feature/multi-editor | Merge after CI passes |
| #27 | feature/deduplicate-skills-roles | Merge after CI passes |

### CONFLICTING (19 PRs — needs rebase)
feature/fix-orchestrator-never-down, feature/agent-watchdog-cron, feature/velocity-tracker,
feature/dag-prioritization, feature/agent-batch-2, feature/memory-system,
feature/context-and-graph, feature/project-management-system, feature/git-agent,
feature/readme-custom-ai-model-docs, feature/observability, feature/validation-health,
feature/worktree-isolation, feature/self-improvement, feature/web-researcher,
feature/dashboard-projects, feature/test-generator, feature/project-templates,
feature/handoff-agents-exit

**Fix sequence**:
```bash
echo "local-agents/dashboard/state.json" >> .gitignore
git add .gitignore && git commit -m "chore: ignore live-written state.json to unblock PR rebases"
git fetch --all --prune
# For each branch: git checkout <branch> && git rebase origin/main --strategy-option=theirs && git push origin <branch> --force-with-lease
```

---

## Assigned Agents

| Agent | Tasks | Category |
|-------|-------|---------|
| frontend_agent | t-dash-01..t-dash-05, t-jobs-01..t-jobs-06, t-6e7d77e3, t-09946532, t-ce5ff84a, t-644865cf, t-ab37fb1d, t-811f198d, t-7a48cbf1, t-545cf9fe, t-ac528ed7, t-0f873f3a | dashboard, react, PR rebase |
| executor | t-loop-01..t-loop-04, t-agents-01..t-agents-03, t-a9251c18, t-infra-01, t-infra-03..t-infra-05 | deploy, code_gen, perf |
| architect | t-infra-02, t-e49c297f, t-aba394d0 | arch, infra |

---

## Dashboard QA Tasks (P0)

All registered in task queue under epic `e-dashboard-stale`:
- quality chips blank → t-ce5ff84a
- model chips blank → t-644865cf
- tasks tab empty → t-ab37fb1d
- changelog empty → t-811f198d
- logs/research empty → t-7a48cbf1
- projects tab empty → t-545cf9fe

**Fix pattern** (every agent must call after each task):
```python
from dashboard.state_writer import update_agent, update_task_queue
update_agent(agent_name, task_result, quality_score)
update_task_queue(pending_tasks)
```

---

## Benchmark Queue

Tasks: t-loop-01, t-loop-04 (velocity tracking per version)
Baseline: Opus 4.6 (run separately, not in production)
Metrics to track: correctness, latency, completion rate, rescue rate, token cost

---

## Rescue Rules

1. Cron `*/5 * * * *` runs `scripts/cron_claude_rescue.sh` → audit only, file tasks, never fix
2. Remote trigger `trig_011sLANs2MtSJRissMX4T5r4` runs hourly diagnostics
3. If cron broken: run `bash scripts/watchdog.sh` manually until macOS FDA is fixed
4. Max rescue: 10% of tasks, 200 tokens/rescue

---

## Hook-Driven Workflow

| Hook Event | Script | Status |
|-----------|--------|--------|
| watchdog (1 min) | scripts/watchdog.sh | ⚠️ Cron broken (FDA) |
| rescue audit (5 min) | scripts/cron_claude_rescue.sh | ⚠️ Cron broken (FDA) |
| auto-merge (30 min) | scripts/auto_merge_pr.sh | ⚠️ Cron broken (FDA) |
| rescue orchestrator (1 min) | scripts/rescue_orchestrator.sh | ⚠️ Cron broken (FDA) |

**Fix**: User must grant Full Disk Access to Terminal app in macOS System Settings → Privacy & Security → Full Disk Access

---

## Next Actions by Local Agent

### IMMEDIATE (before anything else)
1. **architect**: Add `local-agents/dashboard/state.json` to `.gitignore` (task t-e49c297f)
2. **executor**: Start `continuous_loop.py` (task t-loop-01)
3. **frontend_agent**: Fix dashboard blank data — call state_writer after each task (tasks t-ce5ff84a, t-644865cf)

### P0 (today)
4. **executor/cicd_agent**: Rebase 19 conflicting PRs onto origin/main (task t-09946532)
5. **frontend_agent**: Fix projects tab empty (task t-545cf9fe)
6. **architect**: Verify watchdog cron + document FDA fix (task t-aba394d0)

### P1 (this week)
7. **frontend_agent**: Company projects panel polling /api/projects every 2s (t-dash-04)
8. **executor**: Deploy context_optimizer.py (t-agents-01)
9. **executor**: Wire continuous_loop.py to pull from projects.json (t-infra-01)
10. **frontend_agent**: jobs.hil-tad.com JobCard + JobList components (t-jobs-01, t-jobs-02)

---

## Session Policy Reminder

```
Claude main = DIAGNOSE + TASK_INTAKE + HANDOFF only. NEVER fix code.
Local agents = ALL code fixes, features, PR work, dashboard updates.
File a task: python3 -m orchestrator.task_intake "description" --category <cat>
```
