# Personal Agent Runtime

Autonomous self-improving agent system: 10 specialized agents run a 100-task benchmark, self-upgrade every version until they match or exceed the best available LLM baseline. Local agents own 90% of all work. External LLM calls are rescue-only at ≤10% budget, capped at 200 tokens, used only to upgrade failing agents — never to fix tasks directly.

## What This Is

A personal, fully autonomous coding agent platform you run locally — no vendor lock-in, no Cursor, no IDE dependency, no external subscriptions.

- **`local-agents/`** — 10 specialized agents + v1→v100 self-upgrade loop + real-time dashboard
- **`docs/`** — Setup guides and architecture documentation
- **`.claude/`** — Agent skills, roles, and commands

## Quick Start

```bash
# Start the interactive CLI
bash ./Local

# Run 3-task benchmark (local-only, no external API)
python3 local-agents/orchestrator/main.py --version 1 --quick 3 --local-only

# Full autonomous v1→v100 loop
python3 local-agents/orchestrator/main.py --auto 1

# Start the real-time dashboard
bash local-agents/dashboard/launch.sh
# Open: http://localhost:3001
```

## Runtime Policy

- **Local first** — `bash ./Local` activates the local Ollama runtime
- **External LLM** — Used only when local fails 3× with different approaches (≤10% of tasks)
- Review runs automatically after every pipeline run

## Local Agent v1→v100 Upgrade System

### How It Works

```
For each version 1→100:
  1. Check hardware (pause if RAM >80%, kill agent at 85%, throttle at 90% CPU)
  2. Route each task to the right specialized agent (10 roles)
  3. Run Opus 4.6 on same task for baseline comparison
  4. Log results to reports/v{N}_compare.jsonl
  5. Every 5 versions: scrape Reddit/HN/Blind for frustrations, patch system prompts
  6. Gap analysis → trigger upgrade_agent.py if local lags by >5pts
  7. Stop when local beats Opus 4.6 across ALL categories
```

### Claude Guardrail (Hard Limit: 10%)

Claude is only called to **upgrade the agent**, never to fix the task:

1. Task must fail 3+ times locally
2. Rescue budget must be < 10% of total tasks
3. Category must be rescue-eligible (not research/doc — local handles those)
4. Hard cap: **200 tokens per rescue call**
5. Every Claude call logs to `local-agents/reports/claude_rescue_upgrades.jsonl`

### 10 Specialized Agent Roles

| Agent | Category | File |
|-------|----------|------|
| Executor | code_gen, bug_fix | `agents/executor.py` |
| Planner | task decomposition | `agents/planner.py` |
| Reviewer | quality scoring | `agents/reviewer.py` |
| Debugger | error diagnosis | `agents/debugger.py` |
| Researcher | code + grep search | `agents/researcher.py` |
| Benchmarker | gap analysis | `agents/benchmarker.py` |
| Architect | scaffold, arch, e2e | `agents/architect.py` |
| Refactor | code transformation | `agents/refactor.py` |
| Test Engineer | pytest generation | `agents/test_engineer.py` |
| Doc Writer | readme, docstrings | `agents/doc_writer.py` |

### 100-Task Benchmark Suite

`local-agents/tasks/task_suite.py` — 100 tasks across 7 categories:

| Category | Count | Examples |
|----------|-------|---------|
| code_gen | 25 | LRU Cache, trie, graph BFS |
| bug_fix | 20 | off-by-one, async race, memory leak |
| scaffold | 15 | FastAPI service, React dashboard |
| tdd | 20 | pytest from spec, coverage gates |
| arch | 5 | distributed queue, event sourcing |
| refactor | 10 | N+1 → batched, sync → async |
| e2e | 5 | full login flow, payment pipeline |

### Orchestrator CLI

```bash
# Run N tasks for quick testing (no Opus baseline)
python3 local-agents/orchestrator/main.py --version 1 --quick 3 --local-only

# Run full version with Opus comparison
python3 local-agents/orchestrator/main.py --version 1

# Full autonomous loop v1→v100
python3 local-agents/orchestrator/main.py --auto 1

# Check resource headroom
python3 local-agents/orchestrator/resource_guard.py --check
```

### Real-Time Dashboard

FastAPI + WebSocket dashboard with 8 live panels:

- Global progress (version, % complete)
- Agent health (10 agents, current task, status)
- Task queue (pending / in-progress / done / failed)
- Benchmark scores (local vs Opus per version)
- Token usage (Claude rescue budget %, hard limit alert)
- Hardware monitor (CPU%, RAM%, alert levels)
- Failure log (last 10 failures with agent + task)
- Research feed (frustration findings every 5 versions)

```bash
bash local-agents/dashboard/launch.sh   # auto-restart loop
# Dashboard URL written to: DASHBOARD.txt
```

## Local Models (Ollama)

Primary executor: `qwen2.5-coder:7b`

| Role | Model |
|------|-------|
| Code gen, bug fix, TDD, scaffold | `qwen2.5-coder:7b` |
| Planning, architecture, refactor | `qwen2.5-coder:7b` |
| Reasoning, review, debug | `deepseek-r1:8b` |
| Research, embeddings | `nomic-embed-text:latest` |

Never pull models >7b unless RAM headroom > 8GB. `qwen2.5-coder:7b` is the primary — fast, code-focused, fits in 6GB.

## Interactive CLI (`bash ./Local`)

Key commands:

```
/pipeline <task>    run full local pipeline
/plan <task>        planning only
/run <task>         execute plan
/progress           show task progress
/team               show role assignments
/checkpoint [label] save checkpoint
/restore <id>       restore checkpoint
/review             run local review
/qa                 technical QA suite
/uat                user acceptance suite
/release            full release gate
/heal               fix stale locks/state
/compact            compress context
/session-compare    compare local-codex vs local-claude on same task
/help               full command list
```

## Resource Limits

- CPU pause threshold: 80% → stop spawning new agents
- RAM kill threshold: 85% → kill lowest-priority agent
- CPU throttle: 90% → single agent at a time
- All modes default to ≤70% CPU and ≤70% RAM for interactive sessions

## Reports and Logs

```
local-agents/reports/
  v{N}_compare.jsonl          per-task local vs Opus scores
  claude_rescue_upgrades.jsonl Claude upgrade log (tokens, fix, before/after version)
  claude_token_log.jsonl      token budget tracker
  token_comparison.jsonl      local vs Opus token usage
  benchmark_*.md              human-readable benchmark summaries
```

## Key Files

```
local-agents/
  orchestrator/main.py        self-running v1→v100 loop
  orchestrator/resource_guard.py  hardware monitor
  agents/                     10 specialized agent modules
  tasks/task_suite.py         100-task benchmark
  benchmarks/frustration_research.py  Reddit/HN/Blind research
  registry/agents.json        agent versions + benchmark scores
  dashboard/                  FastAPI + WebSocket dashboard

scripts/
  merge_gate.sh               pre-merge validation
  create_checkpoint.sh        checkpoint creator
  local_team_run.py           multi-role runner

docs/
  LOCAL_AGENTS_SETUP.md       full setup guide
  AI_FRAMEWORKS.md            framework comparisons
  UPGRADE.md                  upgrade procedures
  RAG.md                      RAG pipeline docs

workflows/
  workflow-idea-to-feature.md
  workflow-debug-system.md
  workflow-refactor-module.md
```

## Main Branch Protection

- Never commit directly to `main` — all changes through feature branches + PRs
- Run `bash scripts/merge_gate.sh "$PWD"` before any merge
- PR must pass `Validate Runtime` CI check
