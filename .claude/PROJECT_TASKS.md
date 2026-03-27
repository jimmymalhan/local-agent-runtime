# Project Task Breakdown
_Last updated: 2026-03-26_

## Status Legend
- [ ] TODO
- [~] IN PROGRESS
- [x] DONE
- [!] BLOCKED

---

## Project 1: README / Docs
- [~] Rewrite README to position Nexus as custom AI model runtime for any use case
- [ ] Create CHANGELOG.md — required by guardrails.md, currently missing
- [ ] Create .claude/CONFIDENCE_SCORE.md — referenced throughout rules, does not exist on disk
- [ ] Create .claude/PROJECT_STATUS.md — referenced by ai-ml.md, agentic-ai.md, rag.md, backend-proof.md rules, does not exist on disk
- [ ] Sync README agent table with actual agents/*.py files on disk
- [ ] Document nexus CLI commands with real examples from working code
- [ ] Add CONTRIBUTING.md with branch/PR/commit rules
- [ ] Update AGENTS.md to reflect current folder structure (BOS path changed)
- [ ] Document provider routing logic (router.py) for new contributors
- [ ] Add architecture diagram that matches actual layer structure

---

## Project 2: Agents
- [~] Deduplicate skills/roles from root into .claude/skills/ and .claude/roles/ (PR #27)
- [ ] Create missing self_improver.py — referenced in PRs, not on disk
- [ ] Create missing worktree_manager.py — referenced in PRs, not on disk
- [ ] Create missing incremental_validator.py — referenced in PRs, not on disk
- [ ] Verify all 10 agents (executor, planner, reviewer, debugger, researcher, benchmarker, architect, refactor, test_engineer, doc_writer) exist and are importable
- [ ] Register cicd_agent.py in registry/agents.json — file exists in PR #39 branch but not registered
- [ ] Register git_agent.py in registry/agents.json — file exists in PR #37 branch but not registered
- [ ] Register context_optimizer.py in registry/agents.json — file exists in PR #39 branch but not registered
- [ ] Fix agents/__init__.py router to correctly dispatch all 10 agent types
- [ ] Add --dry-run flag to each agent for health-check probing
- [ ] Add null/empty return guards to all agents (self-heal pattern)
- [ ] Add try/catch + retry wrapper to all agent entry points
- [ ] Verify Nexus-Frontend, Nexus-Backend, Nexus-AIML roles in .claude/roles/
- [ ] Add agent version tracking to registry/agents.json
- [ ] Populate benchmark_scores and win_rate fields in registry/agents.json — 9 of 10 agents show null/empty (only executor has data)
- [ ] Write agent health check script that probes all agents on startup
- [ ] Add timeout enforcement (60s default) to every agent call

---

## Project 3: Orchestrator / Self-Heal
- [~] Supervisor autoheal v2 (PR #34)
- [ ] Fix orchestrator/main.py — verify it starts without error (node/python check)
- [ ] Add checkpoint manager — save/restore task state on crash
- [ ] Implement rescue watchdog 60s timeout as described in README
- [ ] Verify auto_upgrade logic in main.py fires after each version benchmark
- [ ] Create scripts/improve_agents.sh — referenced in PRs, not on disk
- [ ] Create local-agents/templates/ directory — referenced in PRs, not on disk
- [ ] Add version increment logic tied to benchmark results
- [ ] Implement A/B prompt testing (5 sub-agents old vs 5 new) in self-improve loop
- [ ] Add replayable trace storage to local-agents/reports/
- [ ] Verify rescue budget enforced: <10% tasks, <200 tokens/call

---

## Project 4: Dashboard
- [~] Set all refresh intervals to 2 seconds for live data
- [ ] Verify WebSocket broadcast fires every 2s with full state payload
- [ ] Ensure state.json read is fresh on every broadcast (no stale cache)
- [ ] Add "Last updated Xs ago" ticker to all panels
- [ ] Verify Chat panel is wired to providers/router.py (currently unverified)
- [ ] Fix Projects panel — collapsed into Tasks tab per PR #34, verify correct
- [ ] Add Logs panel with real-time log stream + level filter
- [ ] Ensure all panels show live data: Overview, Agents, Sub-Agents, Tasks, CEO, Logs, Chat
- [ ] Add rescue budget meter to Overview panel
- [ ] Verify hardware (CPU/RAM) refreshes every 5s via psutil
- [ ] Test dashboard on fresh state.json (empty state shows loading, not crash)

---

## Project 5: CI / DevOps
- [ ] Fix Python 3.9 incompatibility — scripts/runtime_env.py uses `Path | None` syntax (requires 3.10+), causes 7 test collection failures
- [ ] Fix all 13 open PRs (#27–#39) — none merged, all IN PROGRESS
- [ ] Merge PR #27 — deduplicate skills/roles
- [ ] Merge PR #28 — review and unblock
- [ ] Merge PRs #29–#39 — review, fix CI, merge in order
- [!] BLOCKED: PR #29 (codebase analyzer) — active rebase conflict on feature/test-generator, must resolve before merge
- [ ] Add merge_gate.sh check to CI pipeline
- [ ] Ensure GitHub Actions workflow runs npm test + python tests on every PR
- [ ] Add coverage reporting to CI (upload artifacts)
- [ ] Set branch protection rules on main (no direct push enforced in GitHub settings)
- [ ] Add dependabot or equivalent for dependency updates
- [ ] Clean up stale feature branches after merge

---

## Project 6: Tests
- [!] BLOCKED: 7 test files fail to collect — Python 3.9 incompatibility in scripts/runtime_env.py (`Path | None` union syntax requires Python 3.10+)
- [ ] Fix runtime_env.py to use `Optional[Path]` instead of `Path | None` for 3.9 compat
- [ ] Verify all test files collect cleanly after fix: run `python -m pytest --collect-only`
- [ ] Add unit tests for agents/__init__.py router
- [ ] Add unit tests for providers/router.py (local vs rescue routing)
- [ ] Add integration tests for orchestrator startup
- [ ] Add tests for self-heal: simulate each of 8 failure patterns, assert auto-fix fires
- [ ] Add tests for rescue budget enforcement (<10% cap)
- [ ] Add tests for dashboard state.json write → WebSocket broadcast flow
- [ ] Add E2E test: nexus run "hello world" → agent completes → dashboard shows result
- [ ] Add retry logic tests (3 attempts, exponential backoff)
- [ ] Add permission/auth tests if applicable
- [ ] Achieve 60% global coverage minimum (current: unknown due to collection failures)
- [ ] Add test for A/B prompt upgrade logic
- [ ] Add benchmark regression test (score must not drop between versions)

---

## Project 7: Skills / Roles
- [x] Skills in .claude/skills/ (canonical location confirmed)
- [x] Roles in .claude/roles/ (canonical location confirmed)
- [ ] Remove root-level skills/ and roles/ duplicates (after PR #27 merges)
- [ ] Audit all skills for completeness — verify each has valid frontmatter
- [ ] Audit all roles for completeness — verify each has valid frontmatter
- [ ] Add nexus-frontend skill with FE-specific patterns
- [ ] Add nexus-backend skill with BE-specific patterns
- [ ] Add nexus-aiml skill with AI/ML-specific patterns
- [ ] Add nexus-cirepair skill for CI failure diagnosis patterns
- [ ] Document skill format in CONTRIBUTING.md
- [ ] Add skill loader test — verify all skills parse without error
- [ ] Add role loader test — verify all roles parse without error

---

## Project 8: Providers / Model Routing
- [ ] Verify providers/router.py exists and routes correctly (local 90% / rescue ≤10%)
- [ ] Verify providers/ollama.py connects to local Ollama instance
- [ ] Verify providers/claude.py enforces 200-token hard cap per call
- [ ] Add provider health check to nexus doctor command
- [ ] Test fallback: if Ollama is down, rescue path activates (not crash)
- [ ] Log all rescue calls to local-agents/reports/claude_token_log.jsonl
- [ ] Log all rescue upgrades to local-agents/reports/claude_rescue_upgrades.jsonl

---

## Project 9: Repo Hygiene / Contract Violations
- [!] BLOCKED: `regex_engine.py` at repo root — untracked file violates repo contract (all agent code must live in local-agents/agents/). Move or delete.
- [ ] Move regex_engine.py to local-agents/agents/ and register it, OR delete if experimental
- [ ] Audit repo root for any other stray .py files (should only contain nexus, Local, shell entrypoints)
- [ ] local-agents/agents/test_engineer_v2_funcs.py is untracked — register in agents.json or remove

---

## Summary

| Project | TODO | IN PROGRESS | DONE | BLOCKED |
|---|---|---|---|---|
| 1. README / Docs | 9 | 1 | 0 | 0 |
| 2. Agents | 15 | 2 | 0 | 0 |
| 3. Orchestrator / Self-Heal | 9 | 2 | 0 | 0 |
| 4. Dashboard | 9 | 2 | 0 | 0 |
| 5. CI / DevOps | 9 | 2 | 0 | 1 |
| 6. Tests | 13 | 0 | 0 | 2 |
| 7. Skills / Roles | 9 | 0 | 2 | 0 |
| 8. Providers / Model Routing | 7 | 0 | 0 | 0 |
| 9. Repo Hygiene | 2 | 0 | 0 | 2 |
| **Total** | **82** | **9** | **2** | **5** |

---

## Critical Blockers (Fix First)
1. **[!] Python 3.9 compat** — `scripts/runtime_env.py` uses `Path | None` syntax, breaks 7 test files. Fix: replace with `Optional[Path]`
2. **[!] 13 open PRs (#27–#39) unmerged** — all IN PROGRESS, none merged to main
3. **[!] PR #29 rebase conflict** — feature/test-generator has active rebase conflict; resolve before merge
4. **[!] regex_engine.py at repo root** — untracked, violates contract. Move to local-agents/agents/ or delete
5. **Missing files**: `self_improver.py`, `worktree_manager.py`, `incremental_validator.py`, `scripts/improve_agents.sh`, `local-agents/templates/`
6. **Missing docs**: `CHANGELOG.md`, `.claude/CONFIDENCE_SCORE.md`, `.claude/PROJECT_STATUS.md`
7. **Null benchmark data**: 9 of 10 agents in registry/agents.json have empty benchmark_scores and null win_rate
