import Database from 'better-sqlite3';
import { readFileSync, existsSync, mkdirSync } from 'fs';
import { join, dirname } from 'path';

// ============ DATABASE CONFIGURATION ============

interface DBConfig {
  path: string;
  verbose?: boolean;
  readonly?: boolean;
}

// ============ DATABASE CLASS ============

export class StackyDB {
  private db: Database.Database;
  private readonly path: string;

  constructor(config: DBConfig) {
    this.path = config.path;
    
    // Ensure directory exists
    const dir = dirname(this.path);
    if (!existsSync(dir)) {
      mkdirSync(dir, { recursive: true });
    }

    // Initialize database
    this.db = new Database(this.path, {
      verbose: config.verbose ? console.log : undefined,
      readonly: config.readonly,
    });

    // Enable WAL mode for better concurrency
    this.db.pragma('journal_mode = WAL');
    this.db.pragma('synchronous = NORMAL');
    this.db.pragma('foreign_keys = ON');

    // Initialize schema
    this.initSchema();
  }

  private initSchema(): void {
    const schemaPath = join(__dirname, '../../db/schema.sql');
    if (existsSync(schemaPath)) {
      const schema = readFileSync(schemaPath, 'utf-8');
      this.db.exec(schema);
    }
  }

  // ============ PROJECTS ============

  createProject(data: {
    name: string;
    path: string;
    description?: string;
    detected_stack?: string[];
    config?: Record<string, unknown>;
  }) {
    const stmt = this.db.prepare(`
      INSERT INTO projects (name, path, description, detected_stack, config)
      VALUES (@name, @path, @description, @detected_stack, @config)
      RETURNING *
    `);
    return stmt.get({
      ...data,
      detected_stack: JSON.stringify(data.detected_stack || []),
      config: JSON.stringify(data.config || {}),
    });
  }

  getProject(id: string) {
    return this.db.prepare('SELECT * FROM projects WHERE id = ?').get(id);
  }

  getProjectByPath(path: string) {
    return this.db.prepare('SELECT * FROM projects WHERE path = ?').get(path);
  }

  listProjects(status?: string) {
    if (status) {
      return this.db.prepare('SELECT * FROM projects WHERE status = ? ORDER BY last_activity_at DESC').all(status);
    }
    return this.db.prepare('SELECT * FROM projects ORDER BY last_activity_at DESC').all();
  }

  // ============ TASKS ============

  createTask(data: {
    project_id: string;
    title: string;
    description?: string;
    type: string;
    priority?: number;
    input?: Record<string, unknown>;
    parent_task_id?: string;
  }) {
    const stmt = this.db.prepare(`
      INSERT INTO tasks (project_id, title, description, type, priority, input, parent_task_id)
      VALUES (@project_id, @title, @description, @type, @priority, @input, @parent_task_id)
      RETURNING *
    `);
    return stmt.get({
      ...data,
      priority: data.priority || 5,
      input: JSON.stringify(data.input || {}),
    });
  }

  getTask(id: string) {
    return this.db.prepare('SELECT * FROM tasks WHERE id = ?').get(id);
  }

  getNextTask(agentId?: string) {
    if (agentId) {
      return this.db.prepare(`
        SELECT * FROM tasks 
        WHERE status = 'pending' 
        AND (assigned_agent IS NULL OR assigned_agent = ?)
        ORDER BY priority DESC, created_at ASC 
        LIMIT 1
      `).get(agentId);
    }
    return this.db.prepare(`
      SELECT * FROM tasks 
      WHERE status = 'pending'
      ORDER BY priority DESC, created_at ASC 
      LIMIT 1
    `).get();
  }

  assignTask(taskId: string, agentId: string) {
    return this.db.prepare(`
      UPDATE tasks 
      SET assigned_agent = ?, status = 'assigned', started_at = CURRENT_TIMESTAMP
      WHERE id = ?
      RETURNING *
    `).get(agentId, taskId);
  }

  updateTaskStatus(taskId: string, status: string, output?: unknown, error?: string) {
    const completedAt = ['completed', 'failed', 'cancelled'].includes(status) 
      ? new Date().toISOString() 
      : null;
    
    return this.db.prepare(`
      UPDATE tasks 
      SET status = ?, output = ?, error = ?, completed_at = ?
      WHERE id = ?
      RETURNING *
    `).get(status, output ? JSON.stringify(output) : null, error, completedAt, taskId);
  }

  getTasksByProject(projectId: string, status?: string) {
    if (status) {
      return this.db.prepare(`
        SELECT * FROM tasks WHERE project_id = ? AND status = ?
        ORDER BY priority DESC, created_at ASC
      `).all(projectId, status);
    }
    return this.db.prepare(`
      SELECT * FROM tasks WHERE project_id = ?
      ORDER BY priority DESC, created_at ASC
    `).all(projectId);
  }

  // ============ AGENT SESSIONS ============

  startSession(agentId: string, projectId?: string) {
    return this.db.prepare(`
      INSERT INTO agent_sessions (agent_id, project_id)
      VALUES (?, ?)
      RETURNING *
    `).get(agentId, projectId);
  }

  updateSession(sessionId: string, updates: Record<string, unknown>) {
    const fields = Object.keys(updates)
      .map(key => `${key} = @${key}`)
      .join(', ');
    
    return this.db.prepare(`
      UPDATE agent_sessions SET ${fields}, last_heartbeat_at = CURRENT_TIMESTAMP
      WHERE id = @id
      RETURNING *
    `).get({ id: sessionId, ...updates });
  }

  endSession(sessionId: string) {
    return this.db.prepare(`
      UPDATE agent_sessions 
      SET status = 'terminated', ended_at = CURRENT_TIMESTAMP
      WHERE id = ?
      RETURNING *
    `).get(sessionId);
  }

  getActiveSession(agentId: string) {
    return this.db.prepare(`
      SELECT * FROM agent_sessions 
      WHERE agent_id = ? AND status = 'active'
      ORDER BY started_at DESC LIMIT 1
    `).get(agentId);
  }

  // ============ SKILL EXECUTIONS ============

  logExecution(data: {
    task_id?: string;
    agent_id: string;
    skill_id: string;
    input?: unknown;
    output?: unknown;
    success: boolean;
    error?: string;
    duration_ms?: number;
    tokens_input?: number;
    tokens_output?: number;
    model_used?: string;
  }) {
    return this.db.prepare(`
      INSERT INTO skill_executions 
      (task_id, agent_id, skill_id, input, output, success, error, duration_ms, tokens_input, tokens_output, model_used)
      VALUES (@task_id, @agent_id, @skill_id, @input, @output, @success, @error, @duration_ms, @tokens_input, @tokens_output, @model_used)
      RETURNING *
    `).get({
      ...data,
      input: data.input ? JSON.stringify(data.input) : null,
      output: data.output ? JSON.stringify(data.output) : null,
    });
  }

  // ============ HANDOFFS ============

  createHandoff(data: {
    task_id?: string;
    from_agent: string;
    to_agent: string;
    context: Record<string, unknown>;
    priority?: number;
  }) {
    return this.db.prepare(`
      INSERT INTO handoffs (task_id, from_agent, to_agent, context, priority)
      VALUES (@task_id, @from_agent, @to_agent, @context, @priority)
      RETURNING *
    `).get({
      ...data,
      context: JSON.stringify(data.context),
      priority: data.priority || 5,
    });
  }

  getPendingHandoffs(agentId: string) {
    return this.db.prepare(`
      SELECT * FROM handoffs 
      WHERE to_agent = ? AND status = 'pending'
      ORDER BY priority DESC, created_at ASC
    `).all(agentId);
  }

  acknowledgeHandoff(handoffId: string) {
    return this.db.prepare(`
      UPDATE handoffs 
      SET status = 'acknowledged', acknowledged_at = CURRENT_TIMESTAMP
      WHERE id = ?
      RETURNING *
    `).get(handoffId);
  }

  // ============ ERRORS ============

  logError(data: {
    task_id?: string;
    agent_id?: string;
    skill_id?: string;
    error_type: string;
    error_code?: string;
    error_message: string;
    stack_trace?: string;
    context?: Record<string, unknown>;
  }) {
    return this.db.prepare(`
      INSERT INTO errors 
      (task_id, agent_id, skill_id, error_type, error_code, error_message, stack_trace, context)
      VALUES (@task_id, @agent_id, @skill_id, @error_type, @error_code, @error_message, @stack_trace, @context)
      RETURNING *
    `).get({
      ...data,
      context: data.context ? JSON.stringify(data.context) : null,
    });
  }

  resolveError(errorId: string, resolution: string, autoFixed = false, fixPattern?: string) {
    return this.db.prepare(`
      UPDATE errors 
      SET resolved = TRUE, resolution = ?, auto_fixed = ?, fix_pattern = ?, resolved_at = CURRENT_TIMESTAMP
      WHERE id = ?
      RETURNING *
    `).get(resolution, autoFixed, fixPattern, errorId);
  }

  getUnresolvedErrors(agentId?: string) {
    if (agentId) {
      return this.db.prepare(`
        SELECT * FROM errors WHERE resolved = FALSE AND agent_id = ?
        ORDER BY created_at DESC
      `).all(agentId);
    }
    return this.db.prepare(`
      SELECT * FROM errors WHERE resolved = FALSE
      ORDER BY created_at DESC
    `).all();
  }

  // ============ MEMORY ============

  addMemory(data: {
    agent_id: string;
    project_id?: string;
    type: string;
    content: string;
    metadata?: Record<string, unknown>;
    importance?: number;
    expires_at?: string;
  }) {
    return this.db.prepare(`
      INSERT INTO memory_entries 
      (agent_id, project_id, type, content, metadata, importance, expires_at)
      VALUES (@agent_id, @project_id, @type, @content, @metadata, @importance, @expires_at)
      RETURNING *
    `).get({
      ...data,
      metadata: JSON.stringify(data.metadata || {}),
      importance: data.importance || 5,
    });
  }

  getMemories(agentId: string, options?: {
    type?: string;
    project_id?: string;
    limit?: number;
    minImportance?: number;
  }) {
    let query = 'SELECT * FROM memory_entries WHERE agent_id = ?';
    const params: (string | number)[] = [agentId];

    if (options?.type) {
      query += ' AND type = ?';
      params.push(options.type);
    }
    if (options?.project_id) {
      query += ' AND project_id = ?';
      params.push(options.project_id);
    }
    if (options?.minImportance) {
      query += ' AND importance >= ?';
      params.push(options.minImportance);
    }

    query += ' ORDER BY importance DESC, accessed_at DESC';

    if (options?.limit) {
      query += ' LIMIT ?';
      params.push(options.limit);
    }

    return this.db.prepare(query).all(...params);
  }

  // ============ CRON JOBS ============

  createCronJob(data: {
    id: string;
    name: string;
    schedule: string;
    agent_id?: string;
    workflow_id?: string;
    task_template?: Record<string, unknown>;
  }) {
    return this.db.prepare(`
      INSERT OR REPLACE INTO cron_jobs 
      (id, name, schedule, agent_id, workflow_id, task_template)
      VALUES (@id, @name, @schedule, @agent_id, @workflow_id, @task_template)
      RETURNING *
    `).get({
      ...data,
      task_template: data.task_template ? JSON.stringify(data.task_template) : null,
    });
  }

  getDueCronJobs() {
    return this.db.prepare(`
      SELECT * FROM cron_jobs 
      WHERE enabled = TRUE AND (next_run_at IS NULL OR next_run_at <= CURRENT_TIMESTAMP)
      ORDER BY next_run_at ASC
    `).all();
  }

  updateCronJob(id: string, updates: Record<string, unknown>) {
    const fields = Object.keys(updates)
      .map(key => `${key} = @${key}`)
      .join(', ');
    
    return this.db.prepare(`
      UPDATE cron_jobs SET ${fields}
      WHERE id = @id
      RETURNING *
    `).get({ id, ...updates });
  }

  // ============ HEARTBEATS ============

  recordHeartbeat(data: {
    status: string;
    checks: Record<string, unknown>;
    actions_taken?: Array<unknown>;
    duration_ms?: number;
  }) {
    return this.db.prepare(`
      INSERT INTO heartbeats (status, checks, actions_taken, duration_ms)
      VALUES (@status, @checks, @actions_taken, @duration_ms)
      RETURNING *
    `).get({
      ...data,
      checks: JSON.stringify(data.checks),
      actions_taken: JSON.stringify(data.actions_taken || []),
    });
  }

  getLastHeartbeat() {
    return this.db.prepare(`
      SELECT * FROM heartbeats ORDER BY timestamp DESC LIMIT 1
    `).get();
  }

  // ============ UTILITIES ============

  transaction<T>(fn: () => T): T {
    return this.db.transaction(fn)();
  }

  close(): void {
    this.db.close();
  }

  // Raw query for custom operations
  raw(sql: string, params?: unknown[]) {
    if (params) {
      return this.db.prepare(sql).all(...params);
    }
    return this.db.prepare(sql).all();
  }

  exec(sql: string): void {
    this.db.exec(sql);
  }
}

// ============ SINGLETON INSTANCE ============

let db: StackyDB | null = null;

export function getDB(config?: DBConfig): StackyDB {
  if (!db) {
    db = new StackyDB(config || {
      path: process.env.STACKY_DB_PATH || './memory/stacky.db',
    });
  }
  return db;
}

export function closeDB(): void {
  if (db) {
    db.close();
    db = null;
  }
}

export default getDB;
