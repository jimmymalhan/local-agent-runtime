# STACKY AGENT SYSTEM V3 - AUTONOMOUS 24/7 LOCAL OPERATION

## ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                         STACKY V3 AUTONOMOUS SYSTEM                         │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│  ┌─────────────────────────────────────────────────────────────────────┐   │
│  │                        LEAD ORCHESTRATOR                            │   │
│  │  SOUL.md: Identity + Role + Principles + Stop Conditions            │   │
│  │  MEMORY.md: Curated long-term wisdom                                │   │
│  │  memory/YYYY-MM-DD.md: Daily raw logs                               │   │
│  └─────────────────────────────────────────────────────────────────────┘   │
│                                    │                                        │
│                    ┌───────────────┼───────────────┐                        │
│                    ▼               ▼               ▼                        │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │                     SPECIALIST AGENTS (6)                            │  │
│  │  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────┐ │  │
│  │  │FRONTEND │ │BACKEND  │ │ AI/ML   │ │ DESIGN  │ │ DEVOPS  │ │ QA  │ │  │
│  │  │Monica   │ │Chandler │ │ Ross    │ │ Phoebe  │ │ Joey    │ │Rachel│ │  │
│  │  └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────────┘ └─────┘ │  │
│  │  Each has: SOUL.md + AGENTS.md + MEMORY.md + memory/                 │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│  ┌─────────────────────────────────┼────────────────────────────────────┐  │
│  │                          CORE SYSTEMS                                │  │
│  │  ┌────────────┐  ┌────────────┐  ┌────────────┐  ┌────────────────┐  │  │
│  │  │  MEMORY    │  │  WORKFLOW  │  │SELF-HEALING│  │    DAEMON      │  │  │
│  │  │  3-Layer   │  │   Engine   │  │ HEARTBEAT  │  │    24/7        │  │  │
│  │  └────────────┘  └────────────┘  └────────────┘  └────────────────┘  │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│  ┌─────────────────────────────────┼────────────────────────────────────┐  │
│  │                         SKILL SYSTEM                                 │  │
│  │  120+ Skills - Progressive Loading - Shell Injection - Sub-Agents   │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                    │                                        │
│  ┌─────────────────────────────────┼────────────────────────────────────┐  │
│  │                      DATA PERSISTENCE                                │  │
│  │  SQLite (structured) + JSON (state) + Markdown (context)            │  │
│  └──────────────────────────────────────────────────────────────────────┘  │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

## KEY PATTERNS FROM PRODUCTION SYSTEMS

### 1. SOUL.md Identity Pattern
Every agent has a 40-60 line SOUL.md defining:
- Core identity and TV character baseline (free personality from training data)
- Role boundaries and specialization
- Operating principles
- Inter-agent relationships
- Hard stop conditions

### 2. Three-Layer Memory System
```
Layer 1: SQLite (structured)     → Tasks, errors, metrics, skill execution logs
Layer 2: JSON (state)            → Current workflow state, agent status, queues
Layer 3: Markdown (context)      → MEMORY.md (curated) + daily logs (raw)
```

### 3. One-Writer, Many-Readers File Coordination
Each intel file has exactly ONE agent that writes it. All others only read.
- Prevents race conditions
- No distributed locks needed
- Files don't crash, don't need auth, don't rate limit

### 4. Progressive Skill Loading
Don't load all 120 skills. Load only what's needed for current task.
- Trigger conditions per skill
- Category-based filtering
- Shell command injection for live context

### 5. HEARTBEAT.md Self-Healing
Every 15 minutes:
- Check all cron jobs for staleness (>26 hours = force re-run)
- Validate agent health
- Distill daily logs into MEMORY.md
- Clean up context windows

### 6. Fallback Model Chain
```
Primary:   Local model (Qwen 2.5 32B / Llama 3.2)  → Zero cost, always available
Secondary: Cloud API (Claude Sonnet)               → When local fails or reasoning needed
Tertiary:  Cloud API (Claude Opus)                 → Complex multi-step tasks only
```

## DIRECTORY STRUCTURE

```
stacky-v3/
├── AGENTS.md                    # Shared behavioral rules (ALL agents read this)
├── HEARTBEAT.md                 # Self-healing monitor config
├── intel/                       # Shared work products (one-writer, many-readers)
│   ├── task-queue.json          # Source of truth for pending tasks
│   ├── DAILY-STATUS.md          # Human/agent-readable summary
│   └── handoffs/                # Agent-to-agent handoff files
│
├── agents/
│   ├── lead/
│   │   ├── SOUL.md              # Lead orchestrator identity
│   │   ├── MEMORY.md            # Curated long-term memory
│   │   └── memory/              # Daily logs: YYYY-MM-DD.md
│   ├── frontend/                # Monica - perfectionist, detail-oriented
│   ├── backend/                 # Chandler - witty, handles pressure
│   ├── aiml/                    # Ross - analytical, knowledge-focused
│   ├── design/                  # Phoebe - creative, unconventional
│   ├── devops/                  # Joey - straightforward, reliable
│   └── qa/                      # Rachel - quality-focused, catches issues
│
├── core/
│   ├── memory-system.ts         # 3-layer memory manager
│   ├── workflow-engine.ts       # YAML workflow executor
│   ├── self-healing.ts          # HEARTBEAT implementation
│   ├── daemon.ts                # 24/7 process manager
│   ├── skill-loader.ts          # Progressive skill loading
│   └── db.ts                    # SQLite + migrations
│
├── skills/
│   ├── shared/                  # Cross-agent skills
│   ├── frontend/                # React, Next.js, Three.js, GSAP
│   ├── backend/                 # Hono, Drizzle, auth, jobs
│   ├── aiml/                    # Claude, GPT, RAG, streaming
│   ├── design/                  # Mermaid, SVG, D2, mockups
│   ├── devops/                  # Docker, CI/CD, monitoring
│   └── qa/                      # Testing, security, a11y
│
├── templates/
│   ├── frontend/                # Advanced React + Next.js + 3D
│   ├── backend/                 # Hono + Drizzle + auth + jobs
│   └── aiml/                    # Agents + streaming + tools + RAG
│
├── workflows/
│   ├── templates.yaml           # Workflow definitions
│   └── active/                  # Currently running workflows
│
├── memory/
│   ├── stacky.db                # SQLite database
│   └── state.json               # Current system state
│
└── db/
    ├── schema.sql               # Database schema
    └── migrations/              # Schema migrations
```

## AGENT NAMING CONVENTION

Using TV character names gives agents a free personality baseline from LLM training data.

| Agent    | Character | Personality Traits                    |
|----------|-----------|---------------------------------------|
| Lead     | -         | Calm coordinator, sees the big picture|
| Frontend | Monica    | Perfectionist, organized, detail-oriented |
| Backend  | Chandler  | Witty, handles pressure with humor    |
| AI/ML    | Ross      | Analytical, knowledge-focused, thorough |
| Design   | Phoebe    | Creative, unconventional, artistic    |
| DevOps   | Joey      | Straightforward, reliable, gets it done |
| QA       | Rachel    | Quality-focused, catches what others miss |

## DATABASE SCHEMA

```sql
-- Core tables for persistent state

CREATE TABLE tasks (
  id TEXT PRIMARY KEY,
  type TEXT NOT NULL,
  status TEXT DEFAULT 'pending',
  priority INTEGER DEFAULT 5,
  assigned_agent TEXT,
  input JSON,
  output JSON,
  error TEXT,
  parent_task_id TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME,
  completed_at DATETIME,
  FOREIGN KEY (parent_task_id) REFERENCES tasks(id)
);

CREATE TABLE skill_executions (
  id TEXT PRIMARY KEY,
  skill_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  task_id TEXT,
  input JSON,
  output JSON,
  success BOOLEAN,
  duration_ms INTEGER,
  tokens_used INTEGER,
  model_used TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE TABLE agent_sessions (
  id TEXT PRIMARY KEY,
  agent_id TEXT NOT NULL,
  status TEXT DEFAULT 'active',
  memory_snapshot JSON,
  started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  ended_at DATETIME,
  tokens_consumed INTEGER DEFAULT 0,
  tasks_completed INTEGER DEFAULT 0
);

CREATE TABLE errors (
  id TEXT PRIMARY KEY,
  agent_id TEXT,
  task_id TEXT,
  error_type TEXT NOT NULL,
  error_message TEXT,
  stack_trace TEXT,
  context JSON,
  resolved BOOLEAN DEFAULT FALSE,
  resolution TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  resolved_at DATETIME,
  FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE TABLE cron_jobs (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  schedule TEXT NOT NULL,
  agent_id TEXT,
  workflow_id TEXT,
  last_run_at DATETIME,
  next_run_at DATETIME,
  status TEXT DEFAULT 'active',
  last_result JSON,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE handoffs (
  id TEXT PRIMARY KEY,
  from_agent TEXT NOT NULL,
  to_agent TEXT NOT NULL,
  task_id TEXT,
  context JSON,
  status TEXT DEFAULT 'pending',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  acknowledged_at DATETIME,
  FOREIGN KEY (task_id) REFERENCES tasks(id)
);

CREATE TABLE project_state (
  id TEXT PRIMARY KEY,
  project_path TEXT NOT NULL,
  detected_stack JSON,
  config JSON,
  last_scanned_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Indexes for performance
CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_agent ON tasks(assigned_agent);
CREATE INDEX idx_skill_executions_agent ON skill_executions(agent_id);
CREATE INDEX idx_errors_resolved ON errors(resolved);
CREATE INDEX idx_cron_jobs_next_run ON cron_jobs(next_run_at);
CREATE INDEX idx_handoffs_to_agent ON handoffs(to_agent, status);
```

## WORKFLOW EXECUTION MODEL

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│   TRIGGER   │────▶│  WORKFLOW   │────▶│    STEPS    │
│  (cron/api) │     │   ENGINE    │     │  (parallel) │
└─────────────┘     └─────────────┘     └─────────────┘
                           │                    │
                           ▼                    ▼
                    ┌─────────────┐     ┌─────────────┐
                    │   ASSIGN    │────▶│   EXECUTE   │
                    │   AGENT     │     │    SKILL    │
                    └─────────────┘     └─────────────┘
                                               │
                           ┌───────────────────┼───────────────────┐
                           ▼                   ▼                   ▼
                    ┌─────────────┐     ┌─────────────┐     ┌─────────────┐
                    │   SUCCESS   │     │   FAILURE   │     │   HANDOFF   │
                    │  → next     │     │ → self-heal │     │  → agent    │
                    └─────────────┘     └─────────────┘     └─────────────┘
```

## QUICK START

```bash
# 1. Initialize in any project
cd your-project
npx stacky init

# 2. Start daemon (24/7 mode)
npx stacky daemon start

# 3. Run a workflow
npx stacky run new-feature --input '{"name": "auth", "description": "user login with OAuth"}'

# 4. Chat with agents
npx stacky chat

# 5. Check status
npx stacky status

# 6. View agent memories
npx stacky memory frontend --days 7

# 7. Force heartbeat check
npx stacky heartbeat --force
```

## RESOURCE LIMITS (per agent)

```yaml
# Prevent any single agent from blocking the system
resource_limits:
  max_concurrent_tasks: 3
  max_context_tokens: 100000
  max_execution_time_ms: 300000  # 5 minutes
  max_memory_mb: 512
  max_cpu_percent: 25
  cooldown_between_tasks_ms: 5000

# Scheduling to prevent concurrent resource contention
scheduling:
  max_concurrent_agents: 2
  stagger_interval_ms: 30000  # 30 seconds between agent starts
```

## MODEL ROUTING

```yaml
model_routing:
  # Default for most tasks
  default: "claude-sonnet-4-20250514"
  
  # Complex reasoning
  reasoning: "claude-opus-4-20250514"
  
  # Fast, simple tasks
  fast: "claude-haiku-3-5-20241022"
  
  # Local fallback (when available)
  local: "qwen2.5-32b-q4"
  
  # Per-agent overrides
  agents:
    aiml: "claude-opus-4-20250514"  # Needs best reasoning
    qa: "claude-sonnet-4-20250514"   # Balance of speed/quality
    frontend: "claude-sonnet-4-20250514"
    backend: "claude-sonnet-4-20250514"
    design: "claude-haiku-3-5-20241022"  # Fast iteration
    devops: "claude-sonnet-4-20250514"
```
