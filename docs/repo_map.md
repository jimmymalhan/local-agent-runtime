# Repo Map — Local Agent Runtime

**Read this before touching any file.** This is the authoritative directory map.
Last auto-refreshed: see git log on this file.

---

## Quick Answer: Where Does Everything Live?

| What | Where |
|------|-------|
| Agent code | `local-agents/agents/` |
| Main loop | `local-agents/orchestrator/main.py` |
| Task list | `local-agents/tasks/task_suite.py` |
| Dashboard | `local-agents/dashboard/` → http://localhost:3001/api/state |
| Registry | `local-agents/registry/agents.json` |
| Reports | `local-agents/reports/` (gitignored — runtime only) |
| Agent outputs | `~/local-agents-work/` (BOS — never in project root) |
| Config | `local-agents/agents/config.yaml` |
| Docs | `docs/` |

---

## Full Directory Map

### `/` — Project root
| File/Dir | Type | Purpose |
|----------|------|---------|
| `README.md` | source-of-truth | Primary entry point for all humans and agents |
| `CLAUDE.md` | source-of-truth | Rules for Claude AI sessions |
| `AGENTS.md` | source-of-truth | Rules for Jimmy agent runtime |
| `Local` | executable | Interactive CLI — `bash ./Local` activates Jimmy |
| `.gitignore` | config | Excludes runtime artifacts, reports, agent outputs |
| `local-agents/` | runtime core | All agent code lives here |
| `docs/` | documentation | Architecture docs, guides, leaderboard |
| `scripts/` | utilities | Helper scripts (coordinator, tracker, health) |
| `tests/` | tests | Unit and integration tests |
| `state/` | runtime state | Session state, workflow state |
| `workflows/` | process docs | Workflow definitions |
| `.claude/` | AI config | Claude-specific rules, skills, commands |

### `/local-agents/` — Runtime Core (Layer 2 + 3 + 4)

**LAYER 3 — Execution agents:**
```
agents/
  __init__.py           Router: route(task) → agent_name, run_task(task) → result
  config.yaml           Global model config (model, timeouts, thresholds)
  executor.py           code_gen, bug_fix → Ollama best-of-3
  planner.py            Task decomposition
  reviewer.py           Quality scoring (static 50% + dynamic execution 50%)
  debugger.py           Error diagnosis + fix generation
  researcher.py         Code search + pattern analysis
  benchmarker.py        Gap analysis, wraps upgrade_agent.py
  architect.py          scaffold, arch, e2e tasks
  refactor.py           Code transformation
  test_engineer.py      pytest generation
  doc_writer.py         Documentation generation
  distributed_state.py  Lock-free concurrent R/W state store
  subagent_pool.py      1000-sub-agent ThreadPoolExecutor
```

**LAYER 2 — Supervisor + orchestration:**
```
orchestrator/
  main.py               Self-running v1→v100 loop (entry point)
  supervisor.py         Pre-flight, heartbeat, stall detection
  auto_upgrade.py       Failure pattern detection, A/B testing, prompt patches
  resource_guard.py     CPU/RAM monitor (pause 80%, kill 85%, throttle 90%)
```

**LAYER 4 — Learning:**
```
upgrade_agent.py        Calls Claude to generate prompt improvements (rescue-only)
benchmarks/
  frustration_research.py  Scrapes Reddit/HN/Blind every 5 versions
```

**Supporting infrastructure:**
```
agent_runner.py         Core Ollama iterative loop (all agents use this)
opus_runner.py          Opus 4.6 comparison via claude CLI
tasks/
  task_suite.py         100-task benchmark suite (7 categories)
dashboard/
  server.py             FastAPI + WebSocket server (port 3001)
  state.json            Live state file — written by all agents, read by dashboard
  state_writer.py       Thread-safe state update functions
  index.html            Dashboard frontend
registry/
  agents.json           Agent versions, capabilities, benchmark scores
reports/                Runtime logs (gitignored)
  v{N}_compare.jsonl    Per-version task results (local vs Opus)
  auto_upgrade_log.jsonl Self-improvement history
  claude_token_log.jsonl Claude rescue budget tracker
  auto_loop.log         Continuous loop stdout
```

### `/docs/` — Documentation
| File | Purpose |
|------|---------|
| `README.md` → (root) | Primary entry |
| `local_agents_setup.md` | Full setup guide (1998 lines, complete reference) |
| `leaderboard.md` | Auto-updated benchmark scores per version |
| `repo_map.md` | This file |
| `agent_playbook.md` | Step-by-step guide for any agent entering the repo |

### `/scripts/` — Utilities (Layer 1 meta tools)
```
agents/               8 shell agent wrappers
agent_coordinator.py  Multi-agent coordination
dashboard_server.py   Alternative dashboard server
progress_tracker.py   Task progress tracking
resource_status.py    Hardware status
session_health.py     Session diagnostics
local_team_run.py     Multi-role parallel runner
```

---

## Layer Ownership

| Layer | Owner | Files |
|-------|-------|-------|
| Meta (L1) | Claude Code session | `README.md`, `docs/`, `AGENTS.md` |
| Supervisor (L2) | `orchestrator/supervisor.py` | Pre-flight checks, heartbeat |
| Execution (L3) | `agents/*.py` | Task execution, quality scoring |
| Learning (L4) | `orchestrator/auto_upgrade.py` | Prompt improvement, A/B test |

---

## Read Order for New Agents

1. `README.md` — what and why
2. `docs/agent_playbook.md` — how to act safely
3. `local-agents/agents/config.yaml` — model and limits
4. `local-agents/registry/agents.json` — current agent versions
5. `local-agents/orchestrator/main.py` — how the loop works
6. `local-agents/agents/__init__.py` — routing table
7. `local-agents/dashboard/state.json` — current system state

---

## Write Rules

| Directory | Who writes | Rules |
|-----------|-----------|-------|
| `local-agents/agents/` | Developers / auto_upgrade | Never auto-delete; deprecate first |
| `local-agents/registry/` | Benchmarker, auto_upgrade | Append-only for benchmark_scores |
| `local-agents/reports/` | All agents | Gitignored. Purge after 30 days |
| `~/local-agents-work/` | Executor, all code agents | BOS — ALL agent file output goes here |
| `docs/` | Meta layer (Claude sessions) | Refresh after any structural change |
| Root `/` | Nothing | No agent output in project root |

---

## Generated vs Hand-Maintained

**Generated (do not hand-edit):**
- `local-agents/reports/*.jsonl` — runtime logs
- `local-agents/dashboard/state.json` — live state
- `docs/leaderboard.md` — auto-written by `_write_leaderboard()`
- `~/local-agents-work/*.py` — agent task outputs

**Hand-maintained (source of truth):**
- `README.md`
- `docs/repo_map.md` (this file)
- `docs/agent_playbook.md`
- `docs/local_agents_setup.md`
- `local-agents/agents/config.yaml`
- `local-agents/registry/agents.json`
- `AGENTS.md`, `CLAUDE.md`
