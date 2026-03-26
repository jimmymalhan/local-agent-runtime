-- STACKY V3 DATABASE SCHEMA
-- SQLite for local operation, easy to migrate to Postgres later
-- This preserves ALL session data, agent state, and project context

-- ============ CORE TABLES ============

-- Projects: Top-level container for all work
CREATE TABLE IF NOT EXISTS projects (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
  name TEXT NOT NULL,
  path TEXT NOT NULL UNIQUE,
  description TEXT,
  detected_stack JSON DEFAULT '[]',
  config JSON DEFAULT '{}',
  status TEXT DEFAULT 'active' CHECK (status IN ('active', 'paused', 'completed', 'archived')),
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  last_activity_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Tasks: Individual units of work
CREATE TABLE IF NOT EXISTS tasks (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
  project_id TEXT NOT NULL,
  parent_task_id TEXT,
  title TEXT NOT NULL,
  description TEXT,
  type TEXT NOT NULL CHECK (type IN ('feature', 'bug', 'refactor', 'test', 'docs', 'research', 'review')),
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'queued', 'assigned', 'in_progress', 'blocked', 'review', 'completed', 'failed', 'cancelled')),
  priority INTEGER DEFAULT 5 CHECK (priority BETWEEN 1 AND 10),
  assigned_agent TEXT,
  input JSON DEFAULT '{}',
  output JSON,
  error TEXT,
  retry_count INTEGER DEFAULT 0,
  max_retries INTEGER DEFAULT 3,
  timeout_ms INTEGER DEFAULT 300000,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME,
  completed_at DATETIME,
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (parent_task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

-- Agent Sessions: Track each agent's work sessions
CREATE TABLE IF NOT EXISTS agent_sessions (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
  agent_id TEXT NOT NULL CHECK (agent_id IN ('lead', 'frontend', 'backend', 'aiml', 'design', 'devops', 'qa')),
  project_id TEXT,
  status TEXT DEFAULT 'active' CHECK (status IN ('active', 'idle', 'paused', 'error', 'terminated')),
  started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  ended_at DATETIME,
  tasks_completed INTEGER DEFAULT 0,
  tasks_failed INTEGER DEFAULT 0,
  tokens_input INTEGER DEFAULT 0,
  tokens_output INTEGER DEFAULT 0,
  context_snapshot JSON,
  memory_snapshot JSON,
  last_heartbeat_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE SET NULL
);

-- Skill Executions: Track every skill invocation
CREATE TABLE IF NOT EXISTS skill_executions (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
  task_id TEXT,
  agent_id TEXT NOT NULL,
  skill_id TEXT NOT NULL,
  input JSON,
  output JSON,
  success BOOLEAN DEFAULT FALSE,
  error TEXT,
  duration_ms INTEGER,
  tokens_input INTEGER DEFAULT 0,
  tokens_output INTEGER DEFAULT 0,
  model_used TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

-- Handoffs: Agent-to-agent task transfers
CREATE TABLE IF NOT EXISTS handoffs (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
  task_id TEXT,
  from_agent TEXT NOT NULL,
  to_agent TEXT NOT NULL,
  context JSON NOT NULL,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'acknowledged', 'completed', 'rejected')),
  priority INTEGER DEFAULT 5,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  acknowledged_at DATETIME,
  completed_at DATETIME,
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

-- Errors: Centralized error tracking
CREATE TABLE IF NOT EXISTS errors (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
  task_id TEXT,
  agent_id TEXT,
  skill_id TEXT,
  error_type TEXT NOT NULL,
  error_code TEXT,
  error_message TEXT NOT NULL,
  stack_trace TEXT,
  context JSON,
  resolved BOOLEAN DEFAULT FALSE,
  resolution TEXT,
  auto_fixed BOOLEAN DEFAULT FALSE,
  fix_pattern TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  resolved_at DATETIME,
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

-- Cron Jobs: Scheduled tasks
CREATE TABLE IF NOT EXISTS cron_jobs (
  id TEXT PRIMARY KEY,
  name TEXT NOT NULL,
  description TEXT,
  schedule TEXT NOT NULL,
  agent_id TEXT,
  workflow_id TEXT,
  task_template JSON,
  enabled BOOLEAN DEFAULT TRUE,
  last_run_at DATETIME,
  next_run_at DATETIME,
  last_result JSON,
  run_count INTEGER DEFAULT 0,
  fail_count INTEGER DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

-- Memory Entries: Structured memory storage
CREATE TABLE IF NOT EXISTS memory_entries (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
  agent_id TEXT NOT NULL,
  project_id TEXT,
  type TEXT NOT NULL CHECK (type IN ('fact', 'decision', 'error', 'fix', 'feedback', 'pattern', 'preference')),
  content TEXT NOT NULL,
  metadata JSON DEFAULT '{}',
  importance INTEGER DEFAULT 5 CHECK (importance BETWEEN 1 AND 10),
  expires_at DATETIME,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  accessed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  access_count INTEGER DEFAULT 0,
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- Conversations: Chat history for each agent
CREATE TABLE IF NOT EXISTS conversations (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
  agent_id TEXT NOT NULL,
  task_id TEXT,
  project_id TEXT,
  messages JSON NOT NULL DEFAULT '[]',
  summary TEXT,
  tokens_total INTEGER DEFAULT 0,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  updated_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL,
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);

-- Files: Track generated/modified files
CREATE TABLE IF NOT EXISTS files (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
  project_id TEXT NOT NULL,
  task_id TEXT,
  agent_id TEXT,
  path TEXT NOT NULL,
  type TEXT,
  hash TEXT,
  size_bytes INTEGER,
  action TEXT CHECK (action IN ('created', 'modified', 'deleted')),
  diff TEXT,
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE,
  FOREIGN KEY (task_id) REFERENCES tasks(id) ON DELETE SET NULL
);

-- Workflows: Workflow definitions and instances
CREATE TABLE IF NOT EXISTS workflows (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
  name TEXT NOT NULL,
  description TEXT,
  definition JSON NOT NULL,
  status TEXT DEFAULT 'pending' CHECK (status IN ('pending', 'running', 'paused', 'completed', 'failed')),
  current_step INTEGER DEFAULT 0,
  context JSON DEFAULT '{}',
  created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
  started_at DATETIME,
  completed_at DATETIME
);

-- Heartbeats: System health tracking
CREATE TABLE IF NOT EXISTS heartbeats (
  id TEXT PRIMARY KEY DEFAULT (lower(hex(randomblob(8)))),
  timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
  status TEXT NOT NULL CHECK (status IN ('healthy', 'degraded', 'unhealthy')),
  checks JSON NOT NULL,
  actions_taken JSON DEFAULT '[]',
  duration_ms INTEGER
);

-- ============ INDEXES ============

CREATE INDEX IF NOT EXISTS idx_tasks_project ON tasks(project_id);
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_agent ON tasks(assigned_agent);
CREATE INDEX IF NOT EXISTS idx_tasks_priority ON tasks(priority DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);

CREATE INDEX IF NOT EXISTS idx_sessions_agent ON agent_sessions(agent_id);
CREATE INDEX IF NOT EXISTS idx_sessions_status ON agent_sessions(status);
CREATE INDEX IF NOT EXISTS idx_sessions_heartbeat ON agent_sessions(last_heartbeat_at);

CREATE INDEX IF NOT EXISTS idx_executions_task ON skill_executions(task_id);
CREATE INDEX IF NOT EXISTS idx_executions_agent ON skill_executions(agent_id);
CREATE INDEX IF NOT EXISTS idx_executions_skill ON skill_executions(skill_id);

CREATE INDEX IF NOT EXISTS idx_handoffs_to ON handoffs(to_agent, status);
CREATE INDEX IF NOT EXISTS idx_handoffs_from ON handoffs(from_agent);

CREATE INDEX IF NOT EXISTS idx_errors_resolved ON errors(resolved);
CREATE INDEX IF NOT EXISTS idx_errors_type ON errors(error_type);
CREATE INDEX IF NOT EXISTS idx_errors_agent ON errors(agent_id);

CREATE INDEX IF NOT EXISTS idx_memory_agent ON memory_entries(agent_id);
CREATE INDEX IF NOT EXISTS idx_memory_type ON memory_entries(type);
CREATE INDEX IF NOT EXISTS idx_memory_project ON memory_entries(project_id);

CREATE INDEX IF NOT EXISTS idx_files_project ON files(project_id);
CREATE INDEX IF NOT EXISTS idx_files_path ON files(path);

CREATE INDEX IF NOT EXISTS idx_cron_next_run ON cron_jobs(next_run_at) WHERE enabled = TRUE;

-- ============ TRIGGERS ============

-- Auto-update updated_at
CREATE TRIGGER IF NOT EXISTS update_projects_timestamp 
AFTER UPDATE ON projects
BEGIN
  UPDATE projects SET updated_at = CURRENT_TIMESTAMP WHERE id = NEW.id;
END;

-- Track last activity
CREATE TRIGGER IF NOT EXISTS update_project_activity
AFTER INSERT ON tasks
BEGIN
  UPDATE projects SET last_activity_at = CURRENT_TIMESTAMP WHERE id = NEW.project_id;
END;

-- Auto-increment access count for memory
CREATE TRIGGER IF NOT EXISTS update_memory_access
AFTER UPDATE OF accessed_at ON memory_entries
BEGIN
  UPDATE memory_entries SET access_count = access_count + 1 WHERE id = NEW.id;
END;

-- ============ VIEWS ============

-- Active tasks view
CREATE VIEW IF NOT EXISTS v_active_tasks AS
SELECT 
  t.*,
  p.name as project_name,
  p.path as project_path
FROM tasks t
JOIN projects p ON t.project_id = p.id
WHERE t.status IN ('pending', 'queued', 'assigned', 'in_progress')
ORDER BY t.priority DESC, t.created_at ASC;

-- Agent workload view
CREATE VIEW IF NOT EXISTS v_agent_workload AS
SELECT 
  assigned_agent,
  COUNT(*) as total_tasks,
  SUM(CASE WHEN status = 'in_progress' THEN 1 ELSE 0 END) as active_tasks,
  SUM(CASE WHEN status = 'completed' THEN 1 ELSE 0 END) as completed_tasks,
  SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) as failed_tasks
FROM tasks
WHERE assigned_agent IS NOT NULL
GROUP BY assigned_agent;

-- Recent errors view
CREATE VIEW IF NOT EXISTS v_recent_errors AS
SELECT 
  e.*,
  t.title as task_title
FROM errors e
LEFT JOIN tasks t ON e.task_id = t.id
WHERE e.resolved = FALSE
ORDER BY e.created_at DESC
LIMIT 100;

-- Token usage by agent
CREATE VIEW IF NOT EXISTS v_token_usage AS
SELECT 
  agent_id,
  DATE(created_at) as date,
  SUM(tokens_input) as total_input,
  SUM(tokens_output) as total_output,
  SUM(tokens_input + tokens_output) as total_tokens,
  COUNT(*) as execution_count
FROM skill_executions
GROUP BY agent_id, DATE(created_at)
ORDER BY date DESC;
