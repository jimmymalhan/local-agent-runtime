# STACKY V3 - QUICK START

## 🚀 Start in 60 Seconds

### 1. Copy ONE_BIG_PROMPT.md to Claude

Open Claude Code or any Claude interface and paste the contents of `ONE_BIG_PROMPT.md`.

Then say:
```
Initialize Stacky for this project and show me what you find.
```

### 2. Add Your First Task

```
Build a landing page with 3D hero section and email signup form.
```

The system will:
1. Parse your request
2. Create task in `intel/task-queue.json`
3. Assign to appropriate agent (Frontend)
4. Execute with relevant skills loaded
5. Update memory and status

---

## 📁 File Structure

```
stacky-v3/
├── ONE_BIG_PROMPT.md          ← THE PROMPT (copy this to Claude)
├── AGENT_SYSTEM_V3.md         ← Full architecture docs
├── AGENTS.md                   ← Shared rules for all agents
├── HEARTBEAT.md                ← Self-healing configuration
│
├── agents/                     ← Agent identities
│   ├── lead/SOUL.md
│   ├── frontend/SOUL.md        (Monica - perfectionist)
│   ├── backend/SOUL.md         (Chandler - handles pressure)
│   ├── aiml/SOUL.md            (Ross - analytical)
│   ├── design/SOUL.md          (Phoebe - creative)
│   ├── devops/SOUL.md          (Joey - reliable)
│   └── qa/SOUL.md              (Rachel - catches issues)
│
├── core/                       ← System code
│   ├── db.ts                   ← SQLite database
│   ├── skill-loader.ts         ← Progressive skill loading
│   └── daemon.ts               ← 24/7 operation
│
├── skills/                     ← Agent capabilities
│   ├── frontend/
│   │   ├── react-component.md
│   │   └── three-scene.md
│   ├── backend/
│   │   └── api-route.md
│   └── aiml/
│       └── llm-integration.md
│
├── templates/                  ← Project scaffolding
│   ├── frontend/               ← Next.js + 3D + GSAP
│   ├── backend/                ← Hono + Drizzle
│   └── aiml/                   ← Claude/GPT integration
│
├── db/
│   └── schema.sql              ← Database schema
│
├── intel/                      ← Shared work products
│   ├── task-queue.json
│   ├── DAILY-STATUS.md
│   └── handoffs/
│
└── memory/                     ← Persistent state
    ├── stacky.db
    └── YYYY-MM-DD.md (daily logs)
```

---

## ⚡ Key Commands

```bash
# Initialize in any project
cd your-project
# (paste ONE_BIG_PROMPT.md into Claude, say "initialize")

# Add a task
"Add task: Build user authentication with OAuth"

# Check status
"Show me the current task queue and agent status"

# Force heartbeat
"Run a heartbeat check now"

# View agent memory
"Show me Frontend agent's memory from the last 7 days"
```

---

## 🔧 Database

**YES, you need the database for session persistence.**

The SQLite database (`memory/stacky.db`) stores:
- Tasks and their status
- Agent sessions
- Skill execution logs
- Errors and resolutions
- Cron jobs
- Memory entries

Initialize it by running the schema:
```bash
sqlite3 memory/stacky.db < db/schema.sql
```

Or the daemon auto-creates it on first run.

---

## 🧠 Memory System (3 Layers)

1. **SQLite** (structured) - Tasks, metrics, errors
2. **JSON** (state) - Current workflow, task queue
3. **Markdown** (context) - Daily logs, MEMORY.md

Agents read their MEMORY.md at session start.
They write to daily logs during work.
Heartbeat distills daily logs into permanent memory.

---

## 🤖 How Agents Work

1. **Lead Orchestrator** receives your request
2. Creates task, assigns to specialist agent
3. Specialist loads relevant skills (not all 120)
4. Executes task, logging progress
5. Updates task status
6. Creates handoff if another agent needed
7. Writes to daily memory

---

## 🔄 Self-Healing

Every 15 minutes:
- Check for stale cron jobs (>26 hours)
- Check agent health
- Auto-fix known error patterns
- Clean up memory
- Update DAILY-STATUS.md

Known auto-fixes:
- `ENOENT` → Create missing directory
- `Module not found` → npm install
- `EADDRINUSE` → Kill conflicting process
- `SQLITE_BUSY` → Retry with backoff
- `rate limit` → Wait and retry

---

## 📋 Task Types

| Type | Description | Typical Agent |
|------|-------------|---------------|
| feature | New functionality | frontend, backend, aiml |
| bug | Fix issue | qa, frontend, backend |
| refactor | Improve code | frontend, backend |
| test | Write tests | qa |
| docs | Documentation | design, lead |
| research | Investigation | aiml, lead |
| review | Code review | qa, lead |

---

## 🎯 Best Practices

1. **Be specific** - "Add OAuth login" better than "improve auth"
2. **Set priorities** - 1-10, higher = more urgent
3. **Check status** - Ask for queue/status regularly
4. **Review memory** - Check what agents learned
5. **Clear tasks** - Remove completed tasks periodically

---

## 🚨 When Things Go Wrong

If stuck:
```
"Run a heartbeat check and show me any errors"
"Show me the last 5 errors from the error log"
"Restart the Frontend agent"
```

If really stuck:
```
"Clear all pending tasks and start fresh"
"Reset the task queue"
```

---

## 🏃 24/7 Operation

For true autonomous operation:

1. Use dedicated hardware (Mac Mini M4 recommended)
2. Run daemon as system service
3. Set up notifications (Slack/email)
4. Monitor token costs

```bash
# Start daemon
node core/daemon.ts start

# Or with pm2
pm2 start core/daemon.ts --name stacky
```

---

## ✨ That's It!

1. Copy `ONE_BIG_PROMPT.md` to Claude
2. Say "Initialize Stacky"
3. Start giving it tasks
4. Watch it work

The system gets smarter every day as memory compounds.

Questions? Ask the Lead Orchestrator.
