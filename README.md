# Nexus — Autonomous Local AI Agent Runtime

> Run 15 specialized AI agents on your machine. Tell Nexus what to build. It handles everything — executes tasks, commits code, opens PRs, self-heals, and ships continuously.

[![CI](https://github.com/jimmymalhan/local-agent-runtime/actions/workflows/ci.yml/badge.svg)](https://github.com/jimmymalhan/local-agent-runtime/actions/workflows/ci.yml)
[![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

---

## What It Does

```
You:   /do build a Redis cache wrapper with TTL support
Nexus: Dispatching to executor agent — task queued
       → executor writes code → reviewer checks quality
       → commits to feature branch → opens PR automatically
```

No cloud. No API keys required. Everything runs on your machine.

---

## Quickstart

**Requirements:** Python 3.9+, [Ollama](https://ollama.ai) (optional, for local LLM)

```bash
# 1. Clone
git clone https://github.com/jimmymalhan/local-agent-runtime
cd local-agent-runtime

# 2. Install dependencies
pip install -r requirements.txt

# 3. Start the dashboard
python3 dashboard/server.py --port 3001
```

Open **http://localhost:3001** — the dashboard is live.

**Optional: connect a local LLM**
```bash
ollama serve &
ollama pull llama3.1:8b
```

**Optional: run the full autonomous daemon (24/7)**
```bash
python3 orchestrator/unified_daemon.py &
```

---

## Dashboard

The dashboard gives you a real-time view of every agent, task, and quality score.

| Tab | What you see |
|-----|-------------|
| **Overview** | Agent health, task queue, success rate |
| **Tasks** | Live task feed with status and quality scores |
| **Projects** | All 94 projects with completion % |
| **Chat** | Talk to Nexus via `/do`, `/status`, `/agents` |
| **Logs** | Execution logs and agent research feed |

---

## Chat Commands

Type any command in the dashboard Chat tab or `python3 nexus`:

| Command | What it does |
|---------|-------------|
| `/do <task>` | Dispatch a task to the agent queue |
| `/status` | Live agent status and task counts |
| `/agents` | All 15 agents with current assignment |
| `/epics` | All projects with completion % and ETA |
| `/tasks` | Next 10 pending tasks |
| `/health` | Daemon, disk, memory, Ollama status |
| `/help` | All commands |

**Examples:**
```
/do add rate limiting to the API
/do write tests for agents/executor.py
/do fix the stale task detection in orchestrator/supervisor.py
/do create a metrics endpoint for agent performance
```

---

## 15 Agents

| Agent | What It Does |
|-------|-------------|
| `executor` | Code generation, bug fixes, new features |
| `architect` | System design, project scaffolding |
| `researcher` | Search, analysis, technical research |
| `planner` | Task decomposition, roadmaps |
| `debugger` | Error diagnosis, self-healing |
| `reviewer` | Code review, quality scoring (0–100) |
| `refactor` | Code transformation, cleanup |
| `test_engineer` | Test generation and coverage analysis |
| `doc_writer` | Documentation, READMEs, API references |
| `benchmarker` | Performance measurement and comparison |
| `subagent_pool` | Parallel worker pool for large tasks |
| `geo_replication` | Active-active data replication |
| `auto_failover` | Automatic failover (< 5s detection) |
| `read_replicas` | Read replica management |
| `backup_restore` | Snapshot and restore |

---

## Architecture

```
┌──────────────────────────────────────────────────┐
│              Dashboard  :3001                    │
│        FastAPI + WebSocket + React UI            │
│        Chat API · REST API · Live State          │
├────────────────────────┬─────────────────────────┤
│   15 Agents            │   Unified Daemon         │
│   executor             │   ┌─ every 10s           │
│   architect            │   │  poll projects.json  │
│   researcher           │   ├─ every 10min         │
│   planner              │   │  execute 3 tasks     │
│   debugger             │   │  commit + push       │
│   reviewer             │   ├─ every 30min         │
│   + 9 more             │   │  branch/merge/PR     │
│                        │   └─ every 60min         │
│                        │      health check        │
├────────────────────────┴─────────────────────────┤
│              projects.json                       │
│    94 projects · 500+ tasks · source of truth    │
├──────────────────────────────────────────────────┤
│         agents/nexus_inference.py                │
│      Local LLM router — no API key needed        │
└──────────────────────────────────────────────────┘
```

### How a Task Flows

```
User types /do <task>
    → queued in projects.json (status: pending)
    → daemon polls, picks up task within 10s
    → routes to correct agent via nexus_inference.py
    → agent executes, writes result + quality score
    → projects.json updated (status: completed)
    → git commit + push every 10min cycle
```

---

## Project Structure

```
local-agent-runtime/
├── agent_runner.py          # Main orchestration loop
├── nexus                    # CLI entry point
├── projects.json            # Task queue — source of truth
│
├── agents/
│   ├── nexus_inference.py   # LLM router (model-agnostic)
│   ├── executor.py          # Code generation agent
│   ├── architect.py         # System design agent
│   └── ...                  # 12 more agents
│
├── orchestrator/
│   ├── unified_daemon.py    # 24/7 task scheduler
│   ├── quick_dispatcher.py  # Single-task fast runner
│   ├── supervisor.py        # Health monitor + auto-recovery
│   └── resource_guard.py    # RAM/CPU guardrails
│
├── dashboard/
│   ├── server.py            # FastAPI + WebSocket server
│   ├── index.html           # React dashboard UI
│   └── state_writer.py      # Live state persistence
│
├── docs/                    # Full documentation
├── scripts/                 # Automation helpers
└── requirements.txt
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Dashboard UI |
| `GET` | `/api/health` | System health check |
| `GET` | `/api/state` | Full runtime state JSON |
| `GET` | `/api/projects` | All projects + task status |
| `GET` | `/api/status` | Live agent status |
| `POST` | `/api/chat` | Nexus chat `{"message": "..."}` |
| `WS` | `/ws` | WebSocket stream (2s updates) |

```bash
# Health check
curl http://localhost:3001/api/health

# Dispatch a task
curl -X POST http://localhost:3001/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "/do build a Redis cache wrapper"}'

# Get all projects
curl http://localhost:3001/api/projects | python3 -m json.tool
```

---

## Add a Task Programmatically

```python
import json

with open('projects.json') as f:
    data = json.load(f)

data['projects'][0]['tasks'].append({
    "id": "my-task-1",
    "title": "Build a rate limiter",
    "description": "Token bucket rate limiter with Redis backend, 100 req/min per user",
    "status": "pending",
    "agent": "executor"
})

with open('projects.json', 'w') as f:
    json.dump(data, f, indent=2)

# Daemon picks it up within 10 seconds automatically
```

---

## Autonomous Operation Schedule

| Interval | What happens |
|----------|-------------|
| **5s** | Dashboard state pushed via WebSocket |
| **10s** | Orchestrator polls for pending tasks |
| **2min** | Auto-recovery: detect and retry stuck tasks |
| **10min** | Execute tasks → commit → push to GitHub |
| **30min** | Create branch → batch tasks → merge PRs |
| **60min** | Full system health check |

---

## Configuration

All configuration lives in environment variables or defaults safely:

| Variable | Default | Description |
|----------|---------|-------------|
| `NEXUS_PORT` | `3001` | Dashboard port |
| `NEXUS_WORKERS` | `5` | Max parallel agents |
| `NEXUS_POLL_INTERVAL` | `10` | Task poll interval (seconds) |
| `OLLAMA_HOST` | `http://localhost:11434` | Ollama endpoint |

---

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). PRs welcome — especially new agents, dashboard improvements, and Ollama model support.

---

## License

MIT — see [LICENSE](LICENSE).
