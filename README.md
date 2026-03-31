# Nexus — Autonomous Local Agent Runtime

> **Live Dashboard:** `http://localhost:3001`
> **Chat with Nexus:** Dashboard → Chat tab or `nexus chat`

Nexus is a fully autonomous, local-first AI agent runtime. It runs real engineering work 24/7, self-heals, self-improves version by version, and executes tasks without any external API dependencies. **You talk to Nexus. Nexus handles everything else.**

---

## Quick Start

```bash
# 1. Clone
git clone <this-repo>
cd local-agent-runtime

# 2. Start Nexus (launches dashboard + daemon)
./nexus init

# 3. Open dashboard
open http://localhost:3001

# 4. Chat with Nexus
nexus chat
# or open the Chat tab in the dashboard
```

---

## What Nexus Does

| Capability | Description |
|---|---|
| **Talk** | Chat with Nexus in the dashboard — ask questions, get code, debug issues |
| **Execute** | Say "do X" or `/do create a rate limiter` — Nexus dispatches to agent queue |
| **Run 24/7** | Autonomous daemon processes tasks continuously, commits results, merges branches |
| **Self-heal** | Detects stuck/failed agents, auto-restarts, retries with different strategies |
| **Self-improve** | Learns from failures, upgrades agent prompts, tracks quality version over version |

---

## Nexus Chat — Talk & Execute

Nexus chat works like a terminal assistant — you can both **ask questions** and **dispatch tasks**.

```
# In dashboard Chat tab or terminal:
nexus chat

# Ask anything:
> /status
> /agents
> /epics
> /health
> why is the executor agent blocked?
> explain the persistence layer

# Execute tasks:
> /do build a Redis cache wrapper with TTL support
> /do add rate limiting to the API
> create a metrics aggregator for the dashboard
```

**Slash commands:**
```
/status   — live agent status, task counts, health
/agents   — all 15 agents with current task
/epics    — all epics with completion %
/tasks    — next pending tasks in queue
/health   — daemon, watchdog, disk, memory
/do <x>  — dispatch task to agent queue (auto-executes in 10min)
/help     — all commands
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Nexus Interface                           │
│         CLI (nexus chat/run) · Dashboard UI (port 3001)     │
├─────────────────────────────────────────────────────────────┤
│                   Nexus Inference Engine                     │
│         agents/nexus_inference.py — model routing internal  │
├────────────────────────────┬────────────────────────────────┤
│   15 Specialized Agents    │   Orchestrator / Daemon        │
│   executor · architect     │   unified_daemon.py (24/7)     │
│   researcher · planner     │   quick_dispatcher.py          │
│   debugger · reviewer      │   auto_recover.sh (cron 2min)  │
│   doc_writer · benchmarker │   projects.json (task queue)   │
│   + resilience agents      │   30-min branch/merge cycle    │
├────────────────────────────┴────────────────────────────────┤
│                   Dashboard (Live State)                     │
│   FastAPI · WebSocket · state.json · port 3001              │
└─────────────────────────────────────────────────────────────┘
```

---

## 24/7 Operation

Nexus runs continuously without human intervention:

| Cycle | What happens |
|---|---|
| Every 5s | Dashboard state refreshed |
| Every 2min | Auto-recovery: restart stuck agents |
| Every 10min | Execute pending tasks, commit, push |
| Every 30min | Create feature branch → execute batch → merge back |
| Every 60min | Health check, resource monitoring |

**Start the daemon:**
```bash
python3 orchestrator/unified_daemon.py &
# or via ./nexus init which starts everything
```

**Watchdog (cron):**
```bash
crontab -l  # shows: */2 * * * * bash scripts/auto_recover.sh
```

---

## 15 Specialized Agents

| Agent | Role |
|---|---|
| Executor | Code generation, bug fixes, feature implementation |
| Architect | System design, scaffolding, blueprints |
| Researcher | Code search, web research, analysis |
| Planner | Task decomposition, roadmaps |
| Debugger | Error diagnosis, root cause analysis |
| Reviewer | Quality scoring, code review |
| Refactor | Code transformation, optimization |
| TestEngineer | Test generation, coverage |
| DocWriter | Documentation, README updates |
| Benchmarker | Quality measurement, gap analysis |
| SubagentPool | Parallel worker threads (scales with RAM) |
| GeoReplication | Active-active replication |
| AutoFailover | Automatic failover (<5s) |
| ReadReplicas | Read replica management |
| BackupRestore | Backup and restore (<1h RTO) |

---

## Business Features Built

**99% of 434 tasks complete** across 86 epics:

| Epic | Status |
|---|---|
| System Reliability & Health | ✅ Complete |
| Dashboard Quality & State Management | ✅ Complete |
| Policy Enforcement & Budget Control | ✅ Complete |
| Multi-Loop Execution & Self-Improvement | ✅ Complete |
| Local Agent Autonomy (15 agents) | ✅ Complete |
| Advanced Token Compression | ✅ Complete |
| Advanced Resilience (geo-replication, failover) | ✅ Complete |
| Nexus Chat (wide knowledge + task execution) | ✅ Complete |
| 24/7 Daemon + Auto-Recovery | ✅ Complete |
| Dashboard Log Monitoring | ⏳ In Progress |

---

## Project Structure

```
nexus                      ← CLI entry point
agent_runner.py            ← core agent execution loop
agent_implementations/     ← task routing and execution
agents/                    ← 15 specialized agents
  nexus_inference.py       ← inference engine (internal, model-agnostic)
  ollama_guard.py          ← backward-compat shim
orchestrator/
  main.py                  ← orchestration loop
  unified_daemon.py        ← 24/7 daemon with internal scheduler
  quick_dispatcher.py      ← fast task dispatcher
  projects_loader.py       ← task queue from projects.json
providers/                 ← inference adapters (internal, never exposed)
dashboard/
  server.py                ← FastAPI + chat API
  index.html               ← live dashboard UI
projects.json              ← single source of truth for all tasks
state/                     ← runtime state (gitignored)
reports/                   ← agent output logs (gitignored)
```

---

## Branch Policy

- `main` protected — PR-only merges
- Feature branches: `feature/<name>`
- Auto branches: `auto/nexus-<timestamp>` (created every 30min by daemon)
- All auto branches merge back after task execution

---

## ETA

- **428/434 tasks complete (99%)**
- 6 remaining tasks executing autonomously
- Full completion: ~30 minutes at current rate

---

*Last updated: 2026-03-30 — Dashboard is live runtime truth. README is documentation truth.*
