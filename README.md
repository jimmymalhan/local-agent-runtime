# Nexus — Autonomous Local AI Agent Runtime

> **Dashboard:** `http://localhost:3001` · **Chat:** Dashboard → Chat tab

---

## Quickstart (3 commands)

```bash
git clone https://github.com/jimmymalhan/local-agent-runtime
cd local-agent-runtime
python3 dashboard/server.py --port 3001
```

Open `http://localhost:3001`. That's it.

**For 24/7 autonomous operation:**
```bash
python3 orchestrator/unified_daemon.py &
```

---

## What It Does

Nexus runs 15 specialized AI agents locally. You talk to it. It handles everything else — executes tasks, commits code, merges PRs, self-heals, and upgrades itself continuously.

```
You: /do build a Redis cache wrapper with TTL support
Nexus: On it — dispatching to executor agent. Task ID: chat-a3f9b2c1
       Estimated completion: next 10-min cycle
```

---

## Architecture

```
┌─────────────────────────────────────────┐
│         Dashboard  :3001                │
│   FastAPI + WebSocket + Chat API        │
├──────────────────┬──────────────────────┤
│  15 Agents       │  Unified Daemon      │
│  executor        │  task execution      │
│  architect       │  branch/merge cycle  │
│  researcher      │  auto-recovery       │
│  planner         │  health checks       │
│  debugger        │  PR cleanup          │
│  reviewer        │                      │
│  doc_writer      │  Every 10min:        │
│  benchmarker     │  → run 3 tasks       │
│  + 7 more        │  → commit + push     │
├──────────────────┴──────────────────────┤
│  projects.json  ←  single source of     │
│  (94 projects, 500+ tasks)              │
├─────────────────────────────────────────┤
│  Nexus Inference  (agents/nexus_inference.py)  │
│  Local LLM — no external API required   │
└─────────────────────────────────────────┘
```

---

## Chat Commands

```
/status   — live agent status, task counts, health
/agents   — all 15 agents with current task
/epics    — all epics, completion %, ETA
/tasks    — next 10 pending tasks
/health   — daemon, watchdog, disk, memory
/do <x>   — dispatch task to agent queue
/help     — all commands
```

**Execute anything:**
```
/do add rate limiting to the API
/do create a metrics dashboard for agent performance
/do fix the stale task detection bug
```

---

## API Reference

| Method | Endpoint | Description |
|--------|----------|-------------|
| `GET` | `/` | Dashboard UI |
| `POST` | `/api/chat` | Nexus chat — `{message, history}` |
| `GET` | `/api/state` | Full runtime state JSON |
| `GET` | `/api/projects` | All projects + task status |
| `GET` | `/api/health` | System health check |
| `GET` | `/api/status` | Live agent status |
| `WS` | `/ws` | WebSocket stream (2s updates) |

```bash
# Chat
curl -X POST http://localhost:3001/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "/status"}'

# Dispatch a task
curl -X POST http://localhost:3001/api/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "do build a JWT auth middleware"}'
```

---

## 15 Agents

| Agent | Role |
|-------|------|
| `executor` | Code generation, bug fixes, features |
| `architect` | System design, scaffolding |
| `researcher` | Search, analysis, research |
| `planner` | Task decomposition, roadmaps |
| `debugger` | Error diagnosis, self-healing |
| `reviewer` | Code review, quality scoring |
| `refactor` | Code transformation |
| `test_engineer` | Test generation |
| `doc_writer` | Docs, READMEs, API refs |
| `benchmarker` | Quality measurement |
| `subagent_pool` | Parallel workers |
| `geo_replication` | Active-active replication |
| `auto_failover` | Failover (<5s) |
| `read_replicas` | Read replica management |
| `backup_restore` | Backup and restore |

---

## 24/7 Schedule

| Interval | Action |
|----------|--------|
| 5s | Dashboard state refresh |
| 2min | Auto-recovery: reset stuck tasks |
| 10min | Execute tasks → commit → push |
| 30min | Branch → batch → merge → cleanup |
| 30min | Auto-merge PRs, close stale PRs |
| 60min | System health check |

---

## Project Structure

```
agent_runner.py              core execution loop
agents/
  nexus_inference.py         LLM entry point (model-agnostic)
  executor.py / ...          15 specialized agents
orchestrator/
  unified_daemon.py          24/7 scheduler
  quick_dispatcher.py        fast task runner
dashboard/
  server.py                  FastAPI + WebSocket + chat
  index.html                 dashboard UI
projects.json                task queue (source of truth)
scripts/
  auto_recover.sh            watchdog (cron every 2min)
```

---

## Add Your Own Tasks

```python
import json
with open('projects.json') as f:
    data = json.load(f)
data['projects'][0]['tasks'].append({
    "id": "my-1",
    "title": "Build X",
    "description": "Details...",
    "status": "pending",
    "agent": "executor"
})
with open('projects.json', 'w') as f:
    json.dump(data, f, indent=2)
# Daemon picks it up within 10 minutes automatically
```

---

## Requirements

```bash
pip install fastapi uvicorn psutil
ollama serve &           # local LLM (optional)
ollama pull llama3.1:8b  # or any model
```

Python 3.9+. No external API keys required.

---

*Last updated: 2026-03-31*
