# Nexus — Local-First Autonomous Agent Runtime

> **Dashboard (live runtime truth):** `http://localhost:3001` — starts automatically with `./nexus init`
> **Current version:** v5 (0.5.0) — local agents beat Opus 4.6 on quality (90/100 vs 84/100)
> **Upgrade path:** v5 → v1000 (autonomous self-improvement loop)

Nexus is a local-first autonomous coding runtime. It runs real engineering work across one repo, many repos, or distributed workspaces. It self-heals, self-improves version by version, and benchmarks itself against strong baselines. **Local agents own 90% of work. Remote rescue is capped at 10%.**

### v5 Status
| Metric | Value |
|---|---|
| Local quality (v5) | 90/100 |
| Opus 4.6 baseline | 84/100 |
| Win rate | 100% |
| Claude rescue budget used | < 10% |
| Versions completed | 5 of 1000 |
| Active agents | 10 specialized + up to 1000 sub-agents |

---

## Quick Start (Under 2 Minutes)

```bash
# 1. Install local model
ollama pull qwen2.5-coder:7b

# 2. Clone and start
git clone <this-repo>
cd local-agent-runtime

# 3. Start Nexus (auto-launches dashboard)
./nexus init       # scan workspace, check health, open dashboard

# 4. Run a task
./nexus run "Build a rate limiter with sliding window"

# 5. Open dashboard
open http://localhost:3001
```

---

## Nexus Is the Wrapper

Nexus is the **only public interface**. Ollama, Claude, and other backends are internal provider details.

| What you see | What it hides |
|---|---|
| `nexus run "task"` | Routes to Ollama (90%) or Claude rescue (≤10%) |
| `nexus chat` | Chat with Nexus via best local model |
| `nexus eval` | Benchmarks local agents vs baseline |
| `nexus dashboard` | Opens live control plane at port 3001 |

**Never use Ollama or Claude commands directly in normal workflows.** All model access goes through `local-agents/providers/`.

---

## Public Commands

```
nexus init                     scan workspace, detect stack, initialize state
nexus doctor                   check all runtime health (Ollama, deps, config)
nexus sync                     refresh workspace map and dashboard state
nexus map                      show full repo / workspace map
nexus plan "<task>"            generate a plan without executing
nexus run "<task>"             run a task end-to-end with best available agents
nexus test [-n N]              run N benchmark tasks local-only (default: 5)
nexus eval [-n N]              evaluate local agents vs remote baseline
nexus replay <trace_id>        replay a run from its stored trace
nexus repair <failure_id>      attempt auto-repair of a recorded failure
nexus chat                     interactive chat with Nexus
nexus dashboard                start (or open) the live dashboard
nexus status                   current runtime status summary
nexus version                  show version
```

---

## Dashboard — Live Runtime Truth

The dashboard is the **primary operating surface**, not the terminal.

```bash
# Auto-launched by ./nexus init and ./Local
# Or start directly:
python3 local-agents/dashboard/server.py --port 3001
# Open: http://localhost:3001
```

**Dashboard panels:**
| Panel | What it shows |
|---|---|
| Overview | Agent cards, benchmark race, company projects, open PRs, rescue budget |
| Agents | All 10 agents with live status, task, sub-agents |
| Sub-Agents | Per-agent worker thread pool (up to 1000 workers) |
| Projects & Tasks | Jira-style board: Backlog / Running / Done / Blocked + project swimlanes |
| CEO | Strategic directives, KPI metrics, ETA to beat Opus |
| Logs | Real-time log stream with filter by level |
| Chat | Talk to Nexus directly through the dashboard |

**Dashboard freshness rules:**
- Every state write flows through `local-agents/dashboard/state.json` first
- Server pushes WebSocket updates within 800ms of any change
- Hardware (CPU/RAM) refreshes every 5s via live psutil polling
- Stale data is actively prevented — if dashboard and runtime disagree, fix immediately

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                         nexus CLI                            │
│   nexus run / plan / chat / eval / dashboard / doctor        │
├──────────────────────────────────────────────────────────────┤
│                    Provider Router                           │
│   providers/router.py → OllamaProvider (90%) | Claude (≤10%)│
├─────────────────────────────┬────────────────────────────────┤
│  LOCAL INFERENCE (90%)      │  REMOTE RESCUE (≤10%)          │
│  Ollama: qwen2.5-coder:7b   │  Claude Sonnet/Opus 4.6        │
│  deepseek-r1:8b (optional)  │  200-token cap per rescue call │
│  Any Ollama-compatible model│  Only when local fails 3×      │
└─────────────────────────────┴────────────────────────────────┘
         │                                    │
         ▼                                    ▼
┌──────────────────────────────────────────────────────────────┐
│              10 Specialized Agents (Layer 3)                 │
│  Executor · Planner · Reviewer · Debugger · Researcher       │
│  Benchmarker · Architect · Refactor · TestEngineer · DocKeeper│
├──────────────────────────────────────────────────────────────┤
│              Sub-Agent Pool (up to 1000 workers)             │
│  Hardware-aware: scales on free RAM, caps at 1000 workers    │
├──────────────────────────────────────────────────────────────┤
│              Orchestrator (Layer 2)                          │
│  Supervisor · Resource Guard · Rescue Watchdog (60s)         │
│  Auto-heal · Checkpoint Manager · Version Upgrade Loop       │
├──────────────────────────────────────────────────────────────┤
│              Dashboard (Live Control Plane)                  │
│  FastAPI + WebSocket · state.json · port 3001                │
└──────────────────────────────────────────────────────────────┘
```

### 4-Layer Model
| Layer | Owns | Files |
|---|---|---|
| L1 Meta | Docs, policy, repo rules | README.md, AGENTS.md, CLAUDE.md |
| L2 Supervisor | Pre-flight, heartbeat, stall detection, restarts | orchestrator/main.py, resource_guard.py |
| L3 Execution | 10 specialized agents do the actual work | agents/*.py |
| L4 Learning | Failure detection, A/B prompt tests, auto-upgrade | orchestrator/main.py auto_upgrade logic |

---

## Folder Contract

```
nexus                           ← public CLI entry point
local-agents/
  agents/                       ← 10 specialized agents
  providers/                    ← Ollama + Claude adapters (internal)
    base.py                     ← abstract NexusProvider interface
    ollama.py                   ← local inference adapter
    claude.py                   ← remote rescue adapter
    router.py                   ← routing logic (local vs rescue)
  orchestrator/                 ← main.py, resource_guard.py
  dashboard/                    ← server.py, index.html, state.json
  tasks/                        ← 100-task benchmark suite
  benchmarks/                   ← benchmark suites and results
  registry/                     ← agents.json (versions + scores)
  reports/                      ← runtime logs (gitignored)
  agent_runner.py               ← core Ollama iterative loop
  opus_runner.py                ← baseline comparison runner
  deploy.py                     ← deploy Nexus to any project
scripts/                        ← intentional ops scripts only
tests/                          ← persistent test suites
state/                          ← runtime state files
config/                         ← runtime configuration
```

**Root contract:** Only `nexus`, `Local`, `README.md`, `AGENTS.md`, `CLAUDE.md`, `VERSION`, `.gitignore`, approved top-level dirs.
**Agent outputs go to `local-agents/generated/projects/` — never to project root.**
**Temp artifacts go to `.nexus_tmp/` and are cleaned after use.**

---

## Self-Heal

Always on. When any failure occurs:
1. Capture full context → `local-agents/reports/`
2. Classify failure type (truncated_code, stub_functions, missing_assertions, etc.)
3. Attempt auto-fix with different approach (max 3 tries)
4. If fix works → promote to durable agent prompt improvement
5. If fix fails → Claude rescue (if budget allows)
6. Reflect failure + repair status in dashboard immediately

**8 known failure patterns auto-fixed:**
`truncated_code` · `placeholder_path` · `missing_assertions` · `syntax_error`
`stub_functions` · `no_main_guard` · `hallucinated_import` · `wrong_command`

---

## Self-Improve Loop

After each version:
```
1. Run full benchmark suite → capture traces
2. Score: correctness, safety, completeness, speed, rescue usage
3. Find top 3 failure patterns
4. Generate targeted fix for each
5. A/B test: 5 sub-agents on old prompt vs 5 on new
6. If new wins by ≥5pts → commit permanently to agent file
7. Increment version, update dashboard benchmark panel
8. Update README if behavior changed
```

No version bump without evidence. No self-improvement without replayable traces.

---

## Benchmark Policy

Real engineering work — not just algorithmic puzzles:
- Bug fixes in unfamiliar codebases
- Multi-file feature implementation
- Refactors with dependency chains
- CI pipeline repair
- Documentation sync
- Release prep
- Production debugging
- Cross-repo changes

Honesty: Nexus is designed to handle the same broad classes of engineering work as frontier models, benchmark itself against stronger models on identical tasks, and improve version by version through replayable traces, repair loops and benchmark-driven upgrades.

---

## Claude Hard Guardrails

```
Before ANY Claude rescue call — all 3 must be true:
  1. Task failed 3+ times with different approaches
  2. Rescue count still < 10% of total tasks
  3. Category is rescue-eligible (not research/doc)

Per call: 200-token hard cap. Agent prompt upgrade only. Never fixes tasks directly.
Budget logged: local-agents/reports/claude_token_log.jsonl
Rescue log:    local-agents/reports/claude_rescue_upgrades.jsonl
```

---

## Resource Limits

| Threshold | Action |
|---|---|
| RAM < 50% | Scale to 1000 sub-agents |
| RAM 50–70% | Scale to 500 sub-agents |
| RAM 70–80% | Scale to 128 sub-agents |
| RAM > 80% | Stop spawning new agents |
| RAM > 85% | Kill lowest-priority agent |
| CPU > 90% | Single agent at a time |

---

## Workspace Support

Works across:
- Single repo
- Monorepo
- Multiple repos
- Mixed stacks (Python, Node.js, Go, Rust)
- Distributed project workspaces

```bash
# Deploy Nexus to any project (5 minutes)
python3 local-agents/deploy.py all --to /path/to/your/project
python3 /path/to/your/project/.local-agents/runner.py "Write a Redis cache wrapper"
```

---

## 10 Specialized Agents

| Agent | Handles | File |
|---|---|---|
| Nexus-Executor | code_gen, bug_fix | agents/executor.py |
| Nexus-Planner | task decomposition | agents/planner.py |
| Nexus-Reviewer | quality scoring | agents/reviewer.py |
| Nexus-Debugger | error diagnosis | agents/debugger.py |
| Nexus-Researcher | code + web search | agents/researcher.py |
| Nexus-Benchmarker | gap analysis | agents/benchmarker.py |
| Nexus-Architect | scaffold, arch, e2e | agents/architect.py |
| Nexus-Refactor | code transformation | agents/refactor.py |
| Nexus-TestEngineer | pytest generation | agents/test_engineer.py |
| Nexus-DocKeeper | documentation | agents/doc_writer.py |

Plus Nexus-Frontend, Nexus-Backend, Nexus-AIML (see `.claude/roles/`).

---

## Key Files — Source of Truth

| File | What it controls |
|---|---|
| `AGENTS.md` | Runtime operating rules, agent roster, folder contract |
| `CLAUDE.md` | AI session rules |
| `local-agents/agents/config.yaml` | Model, timeouts, quality threshold |
| `local-agents/registry/agents.json` | Agent versions, capabilities, scores |
| `local-agents/dashboard/state.json` | Live runtime state (source of truth for dashboard) |
| `local-agents/providers/router.py` | Provider routing logic |
| `nexus` | Public CLI entry point |

---

## Branch Protection

- `main` is protected. No direct pushes. PR-only merges.
- PRs auto-merge when CI passes and no conflicts
- Run `bash scripts/merge_gate.sh "$PWD"` before any merge

---

## Current Benchmark

| Version | Nexus Score | Baseline | Win Rate | Claude Tokens |
|---|---|---|---|---|
| v5 | 100.0/100 | 0.0/100 | 100% | 10 total |

*Scores update automatically after each benchmark run. See `local-agents/reports/` for details.*

---

## Adding Skills / Prompt Packs

Skills live in `.claude/skills/` (local, gitignored).
To add a skill: create `nexus-<name>.md` in `.claude/skills/` following the frontmatter format.
Roles live in `.claude/roles/`. Agent identity files (SOUL.md equivalents).

---

*Last updated: 2026-03-25 — README is documentation truth. Dashboard is live runtime truth.*
