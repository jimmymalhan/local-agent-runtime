# Nexus — Custom AI Model Runtime

> **Any use case. Any stack. Runs locally. Assigns to specialist agents automatically.**
> Dashboard: `http://localhost:3001` — live after `./nexus init`

Nexus is a custom AI model you deploy once and use for anything — coding, research, debugging, documentation, planning, testing, and more. It runs 100% on your machine, routes tasks to the right specialist agent automatically, self-heals on failure, and improves itself version by version.

**No API key required for daily use. No data leaves your machine.**

### Current Status
| Metric | Value |
|---|---|
| Local quality (v5) | 90/100 |
| Baseline comparison | 84/100 |
| Win rate | 100% |
| Active agents | 10 specialized + up to 1000 sub-agents |

---

## What Can Nexus Do?

Nexus handles any task you'd give an AI assistant — and assigns it to the best local agent automatically.

```bash
nexus run "Build a rate limiter with sliding window"
nexus run "Debug why my API returns 500 on POST /users"
nexus run "Write pytest coverage for auth module"
nexus run "Refactor this service to use dependency injection"
nexus run "Generate OpenAPI docs from this Express router"
nexus run "Fix all TypeScript errors in src/"
nexus run "Scaffold a new Go microservice with gRPC"
```

---

## Use Cases

| Domain | Example |
|---|---|
| Code generation | `nexus run "Build a JWT auth middleware"` |
| Bug fixing | `nexus run "Fix the race condition in worker.js"` |
| Testing | `nexus run "Write unit tests for the payment module"` |
| Refactoring | `nexus run "Convert callbacks to async/await in legacy API"` |
| Documentation | `nexus run "Generate README for the analytics package"` |
| Architecture | `nexus run "Design a caching layer for high-read endpoints"` |
| Research | `nexus run "Compare Redis vs Memcached for session storage"` |
| CI repair | `nexus run "Fix the failing GitHub Actions workflow"` |
| Planning | `nexus plan "Migrate monolith to microservices"` |
| Multi-repo | Works across single repo, monorepo, or multiple repos |

---

## Quick Start (Under 2 Minutes)

```bash
# 1. Install local model
ollama pull qwen2.5-coder:7b

# 2. Clone and start
git clone <this-repo>
cd local-agent-runtime

# 3. Start Nexus
./nexus init       # scans workspace, checks health, opens dashboard

# 4. Run any task
nexus run "Your task here"

# 5. Watch live
open http://localhost:3001
```

---

## How It Works

You give Nexus a task in plain English. Nexus routes it to the right specialist agent, runs the work locally, self-heals if anything fails, and streams results to your dashboard.

```
Your task
    │
    ▼
┌─────────────────────────────────────────────────────────────┐
│                        Nexus Router                         │
│   Reads task → picks best agent → assigns automatically     │
├──────────────────────────┬──────────────────────────────────┤
│  LOCAL (90% of work)     │  RESCUE (≤10%, only if needed)   │
│  qwen2.5-coder:7b        │  Claude Sonnet/Opus 4.6          │
│  deepseek-r1:8b          │  200-token cap · upgrade only    │
│  Any Ollama model        │  Triggered after 3 local fails   │
└──────────────────────────┴──────────────────────────────────┘
         │
         ▼
┌─────────────────────────────────────────────────────────────┐
│         10 Specialist Agents (auto-assigned to your task)   │
│  Executor · Planner · Reviewer · Debugger · Researcher      │
│  Benchmarker · Architect · Refactor · TestEngineer · Docs   │
├─────────────────────────────────────────────────────────────┤
│              Sub-Agent Pool (up to 1000 workers)            │
│  Scales automatically based on available RAM                │
├─────────────────────────────────────────────────────────────┤
│              Orchestrator + Self-Heal                       │
│  Supervisor · Checkpoint Manager · Auto-repair loop         │
├─────────────────────────────────────────────────────────────┤
│              Live Dashboard (port 3001)                     │
│  Real-time task board · agent status · benchmark metrics    │
└─────────────────────────────────────────────────────────────┘
```

---

## Specialist Agents (Auto-Assigned)

Nexus picks the right agent for your task — you never need to specify which one.

| Agent | Best for |
|---|---|
| Nexus-Executor | Code generation, bug fixes, feature implementation |
| Nexus-Planner | Breaking down complex tasks, roadmaps, sequencing |
| Nexus-Reviewer | Code quality scoring, PR review, standards checks |
| Nexus-Debugger | Error diagnosis, stack trace analysis, root cause |
| Nexus-Researcher | Codebase exploration, comparison, deep analysis |
| Nexus-Architect | Scaffolding, system design, end-to-end structure |
| Nexus-Refactor | Code transformation, modernization, cleanup |
| Nexus-TestEngineer | Pytest/Jest generation, coverage, edge cases |
| Nexus-DocKeeper | README, API docs, inline comments, changelogs |
| Nexus-Benchmarker | Performance gaps, scoring, baseline comparison |

Plus `Nexus-Frontend`, `Nexus-Backend`, `Nexus-AIML` for domain-specific work (see `.claude/roles/`).

---

## All Commands

```
nexus init                     scan workspace, detect stack, initialize state
nexus run "<task>"             run any task end-to-end (auto-assigns agent)
nexus plan "<task>"            generate a plan without executing
nexus chat                     interactive chat with Nexus
nexus eval [-n N]              evaluate local agents vs remote baseline
nexus test [-n N]              run N benchmark tasks local-only
nexus replay <trace_id>        replay a run from its stored trace
nexus repair <failure_id>      attempt auto-repair of a recorded failure
nexus dashboard                open live dashboard at port 3001
nexus doctor                   check all runtime health (model, deps, config)
nexus sync                     refresh workspace map and dashboard state
nexus map                      show full repo / workspace map
nexus status                   current runtime status summary
nexus version                  show version
```

---

## Dashboard

```bash
open http://localhost:3001
# or start directly:
python3 local-agents/dashboard/server.py --port 3001
```

| Panel | What it shows |
|---|---|
| Overview | Agent cards, benchmark race, open PRs, rescue budget |
| Agents | All agents with live status and current task |
| Sub-Agents | Per-agent worker thread pool (up to 1000 workers) |
| Tasks | Jira-style board: Backlog / Running / Done / Blocked |
| CEO | Strategic directives, KPI metrics |
| Logs | Real-time log stream with level filter |
| Chat | Talk to Nexus directly through the dashboard |

Dashboard pushes WebSocket updates within 800ms of any state change. Hardware (CPU/RAM) refreshes every 5s.

---

## Self-Heal

Nexus automatically recovers from failures without manual intervention.

1. Captures full context on failure → `local-agents/reports/`
2. Classifies the failure type
3. Retries with a different approach (up to 3 attempts)
4. If fixed → promotes the repair to a permanent agent improvement
5. If not fixed → escalates to rescue (budget permitting)
6. All failures and recoveries reflected live in dashboard

**8 failure patterns auto-fixed:**
`truncated_code` · `placeholder_path` · `missing_assertions` · `syntax_error`
`stub_functions` · `no_main_guard` · `hallucinated_import` · `wrong_command`

---

## Self-Improve Loop

After every version, Nexus benchmarks itself and upgrades its own agents:

1. Run full benchmark suite → capture traces
2. Score: correctness, safety, completeness, speed, rescue usage
3. Find top 3 failure patterns
4. A/B test old prompt vs new prompt (5 sub-agents each)
5. If new wins by ≥5 points → commit permanently to agent file
6. Increment version, update dashboard

No version bump without evidence. No self-improvement without replayable traces.

---

## Deploy to Any Project

```bash
# Deploy Nexus to any existing project in 5 minutes
python3 local-agents/deploy.py all --to /path/to/your/project

# Then run tasks directly in that project
python3 /path/to/your/project/.local-agents/runner.py "Write a Redis cache wrapper"
```

Works with: single repo · monorepo · multiple repos · Python · Node.js · Go · Rust · mixed stacks.

---

## Resource Limits (Automatic)

| RAM Available | Sub-agents |
|---|---|
| > 50% free | Up to 1000 |
| 30–50% free | Up to 500 |
| 20–30% free | Up to 128 |
| < 20% free | Pause new spawns |
| < 15% free | Kill lowest-priority agent |
| CPU > 90% | Single agent at a time |

---

## Adding Custom Skills

```bash
# Add a skill (e.g., custom domain knowledge or workflow)
# Create: .claude/skills/nexus-<name>.md

# Add a role (agent identity / persona)
# Create: .claude/roles/<name>.md
```

---

## Key Files

| File | What it controls |
|---|---|
| `nexus` | Public CLI entry point |
| `local-agents/agents/config.yaml` | Model, timeouts, quality threshold |
| `local-agents/providers/router.py` | Local vs rescue routing logic |
| `local-agents/registry/agents.json` | Agent versions, capabilities, scores |
| `local-agents/dashboard/state.json` | Live runtime state |
| `AGENTS.md` | Runtime operating rules, agent roster |
| `CLAUDE.md` | AI session rules |

---

## Branch Protection

- `main` is protected. No direct pushes. PR-only merges.
- Run `bash scripts/merge_gate.sh "$PWD"` before any merge

---

## Current Benchmark

| Version | Nexus Score | Baseline | Win Rate | Claude Tokens Used |
|---|---|---|---|---|
| v5 | 100.0/100 | 0.0/100 | 100% | 10 total |

*Scores update automatically after each benchmark run. See `local-agents/reports/` for details.*

---

*Last updated: 2026-03-25 — README is documentation truth. Dashboard is live runtime truth.*
