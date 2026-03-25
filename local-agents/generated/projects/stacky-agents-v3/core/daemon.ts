import { getDB } from './db';
import { getSkillLoader } from './skill-loader';
import { readFileSync, writeFileSync, existsSync, mkdirSync } from 'fs';
import { join } from 'path';
import { execSync, spawn, type ChildProcess } from 'child_process';

// ============ TYPES ============

interface DaemonConfig {
  heartbeatIntervalMs: number;
  staleThresholdMs: number;
  maxConcurrentAgents: number;
  workingDir: string;
  logLevel: 'debug' | 'info' | 'warn' | 'error';
}

interface AgentProcess {
  id: string;
  process: ChildProcess | null;
  status: 'idle' | 'running' | 'error';
  lastActivity: Date;
  currentTask: string | null;
}

interface HeartbeatResult {
  timestamp: Date;
  status: 'healthy' | 'degraded' | 'unhealthy';
  checks: {
    database: boolean;
    agents: boolean;
    cronJobs: boolean;
    memory: boolean;
    disk: boolean;
  };
  actions: string[];
  errors: string[];
}

// ============ DAEMON CLASS ============

export class StackyDaemon {
  private config: DaemonConfig;
  private db = getDB();
  private skillLoader = getSkillLoader();
  private agents: Map<string, AgentProcess> = new Map();
  private heartbeatInterval: NodeJS.Timeout | null = null;
  private running = false;

  constructor(config?: Partial<DaemonConfig>) {
    this.config = {
      heartbeatIntervalMs: 15 * 60 * 1000, // 15 minutes
      staleThresholdMs: 26 * 60 * 60 * 1000, // 26 hours
      maxConcurrentAgents: 2,
      workingDir: process.cwd(),
      logLevel: 'info',
      ...config,
    };

    // Initialize agent slots
    const agentIds = ['lead', 'frontend', 'backend', 'aiml', 'design', 'devops', 'qa'];
    for (const id of agentIds) {
      this.agents.set(id, {
        id,
        process: null,
        status: 'idle',
        lastActivity: new Date(),
        currentTask: null,
      });
    }
  }

  // ============ LIFECYCLE ============

  async start(): Promise<void> {
    if (this.running) {
      this.log('warn', 'Daemon already running');
      return;
    }

    this.log('info', '=== STACKY DAEMON STARTING ===');
    this.running = true;

    // Run initial heartbeat
    await this.heartbeat();

    // Start heartbeat interval
    this.heartbeatInterval = setInterval(
      () => this.heartbeat(),
      this.config.heartbeatIntervalMs
    );

    // Start task loop
    this.taskLoop();

    this.log('info', 'Daemon started successfully');
    this.log('info', `Heartbeat interval: ${this.config.heartbeatIntervalMs / 1000}s`);
  }

  async stop(): Promise<void> {
    this.log('info', '=== STACKY DAEMON STOPPING ===');
    this.running = false;

    if (this.heartbeatInterval) {
      clearInterval(this.heartbeatInterval);
      this.heartbeatInterval = null;
    }

    // Stop all agent processes
    for (const [id, agent] of this.agents) {
      if (agent.process) {
        this.log('info', `Stopping agent: ${id}`);
        agent.process.kill('SIGTERM');
        agent.process = null;
        agent.status = 'idle';
      }
    }

    this.log('info', 'Daemon stopped');
  }

  // ============ HEARTBEAT ============

  async heartbeat(): Promise<HeartbeatResult> {
    const startTime = Date.now();
    this.log('info', '--- HEARTBEAT ---');

    const result: HeartbeatResult = {
      timestamp: new Date(),
      status: 'healthy',
      checks: {
        database: false,
        agents: false,
        cronJobs: false,
        memory: false,
        disk: false,
      },
      actions: [],
      errors: [],
    };

    // Check database
    try {
      this.db.raw('SELECT 1');
      result.checks.database = true;
    } catch (error) {
      result.errors.push(`Database check failed: ${error}`);
      result.status = 'unhealthy';
    }

    // Check agents
    try {
      let healthyAgents = 0;
      for (const [id, agent] of this.agents) {
        const timeSinceActivity = Date.now() - agent.lastActivity.getTime();
        
        if (agent.status === 'running' && timeSinceActivity > 30 * 60 * 1000) {
          // Agent stuck for more than 30 minutes
          this.log('warn', `Agent ${id} appears stuck, restarting`);
          await this.restartAgent(id);
          result.actions.push(`Restarted stuck agent: ${id}`);
        } else {
          healthyAgents++;
        }
      }
      result.checks.agents = healthyAgents >= 6;
    } catch (error) {
      result.errors.push(`Agent check failed: ${error}`);
      result.status = 'degraded';
    }

    // Check cron jobs
    try {
      const staleCrons = this.checkStaleCronJobs();
      for (const cron of staleCrons) {
        this.log('warn', `Cron job ${cron.id} is stale, forcing run`);
        await this.forceCronRun(cron.id);
        result.actions.push(`Forced stale cron: ${cron.id}`);
      }
      result.checks.cronJobs = staleCrons.length === 0;
    } catch (error) {
      result.errors.push(`Cron check failed: ${error}`);
    }

    // Check memory
    try {
      const memUsage = process.memoryUsage();
      const memPercent = memUsage.heapUsed / memUsage.heapTotal;
      result.checks.memory = memPercent < 0.85;
      
      if (memPercent > 0.85) {
        this.log('warn', `Memory usage high: ${(memPercent * 100).toFixed(1)}%`);
        global.gc?.(); // Force GC if available
        result.actions.push('Triggered garbage collection');
      }
    } catch (error) {
      result.errors.push(`Memory check failed: ${error}`);
    }

    // Check disk
    try {
      const diskUsage = this.checkDiskUsage();
      result.checks.disk = diskUsage < 90;
      
      if (diskUsage > 90) {
        this.log('warn', `Disk usage high: ${diskUsage}%`);
        result.status = 'degraded';
      }
    } catch (error) {
      result.errors.push(`Disk check failed: ${error}`);
    }

    // Determine overall status
    const allChecks = Object.values(result.checks);
    if (allChecks.every(Boolean)) {
      result.status = 'healthy';
    } else if (allChecks.some(Boolean)) {
      result.status = 'degraded';
    } else {
      result.status = 'unhealthy';
    }

    // Record heartbeat
    const durationMs = Date.now() - startTime;
    this.db.recordHeartbeat({
      status: result.status,
      checks: result.checks,
      actions_taken: result.actions,
      duration_ms: durationMs,
    });

    // Update daily status
    this.updateDailyStatus(result);

    this.log('info', `Heartbeat complete: ${result.status} (${durationMs}ms)`);
    return result;
  }

  // ============ TASK LOOP ============

  private async taskLoop(): Promise<void> {
    while (this.running) {
      try {
        // Count running agents
        const runningCount = Array.from(this.agents.values())
          .filter(a => a.status === 'running').length;

        if (runningCount < this.config.maxConcurrentAgents) {
          // Get next pending task
          const task = this.db.getNextTask();
          
          if (task) {
            // Find best agent for task
            const agentId = this.selectAgentForTask(task);
            
            if (agentId) {
              await this.assignTaskToAgent(task.id, agentId);
            }
          }
        }
      } catch (error) {
        this.log('error', `Task loop error: ${error}`);
      }

      // Wait before next iteration
      await this.sleep(5000);
    }
  }

  private selectAgentForTask(task: { type: string; description?: string }): string | null {
    // Map task types to agents
    const typeMapping: Record<string, string[]> = {
      feature: ['frontend', 'backend', 'aiml'],
      bug: ['frontend', 'backend', 'qa'],
      refactor: ['frontend', 'backend'],
      test: ['qa'],
      docs: ['design', 'lead'],
      research: ['aiml', 'lead'],
      review: ['qa', 'lead'],
    };

    const candidates = typeMapping[task.type] || ['lead'];

    // Find first available agent
    for (const agentId of candidates) {
      const agent = this.agents.get(agentId);
      if (agent && agent.status === 'idle') {
        return agentId;
      }
    }

    return null;
  }

  private async assignTaskToAgent(taskId: string, agentId: string): Promise<void> {
    const agent = this.agents.get(agentId);
    if (!agent) return;

    this.log('info', `Assigning task ${taskId} to agent ${agentId}`);

    // Update task status
    this.db.assignTask(taskId, agentId);

    // Update agent status
    agent.status = 'running';
    agent.currentTask = taskId;
    agent.lastActivity = new Date();

    // Start agent session
    const session = this.db.startSession(agentId);

    // In a real implementation, this would spawn a subprocess
    // For now, we'll simulate the work
    this.executeAgentTask(agentId, taskId, session.id);
  }

  private async executeAgentTask(
    agentId: string,
    taskId: string,
    sessionId: string
  ): Promise<void> {
    const agent = this.agents.get(agentId);
    if (!agent) return;

    try {
      // Load task
      const task = this.db.getTask(taskId);
      if (!task) throw new Error('Task not found');

      // Load relevant skills
      const skills = this.skillLoader.findMatchingSkills(
        task.description || task.title,
        agentId
      );

      this.log('info', `Agent ${agentId} executing task with ${skills.length} skills`);

      // Simulate task execution
      // In production, this would call Claude or another LLM
      await this.sleep(Math.random() * 10000 + 5000);

      // Complete task
      this.db.updateTaskStatus(taskId, 'completed', { result: 'Task completed' });

      // Update session
      this.db.updateSession(sessionId, {
        tasks_completed: 1,
        status: 'completed',
      });

      this.log('info', `Agent ${agentId} completed task ${taskId}`);
    } catch (error) {
      this.log('error', `Agent ${agentId} failed task ${taskId}: ${error}`);
      
      // Log error
      this.db.logError({
        task_id: taskId,
        agent_id: agentId,
        error_type: 'TASK_EXECUTION',
        error_message: String(error),
      });

      // Update task status
      this.db.updateTaskStatus(taskId, 'failed', undefined, String(error));
    } finally {
      // Reset agent status
      agent.status = 'idle';
      agent.currentTask = null;
      agent.lastActivity = new Date();

      // End session
      this.db.endSession(sessionId);
    }
  }

  // ============ CRON JOBS ============

  private checkStaleCronJobs(): Array<{ id: string; name: string }> {
    const now = Date.now();
    const stale: Array<{ id: string; name: string }> = [];

    const cronJobs = this.db.getDueCronJobs();
    
    for (const job of cronJobs as Array<{ id: string; name: string; last_run_at: string | null }>) {
      if (job.last_run_at) {
        const lastRun = new Date(job.last_run_at).getTime();
        if (now - lastRun > this.config.staleThresholdMs) {
          stale.push({ id: job.id, name: job.name });
        }
      }
    }

    return stale;
  }

  private async forceCronRun(cronId: string): Promise<void> {
    this.log('info', `Forcing cron job: ${cronId}`);
    
    // Update last run time
    this.db.updateCronJob(cronId, {
      last_run_at: new Date().toISOString(),
      run_count: 1, // Increment in real implementation
    });

    // In production, this would execute the actual cron job
  }

  // ============ AGENT MANAGEMENT ============

  private async restartAgent(agentId: string): Promise<void> {
    const agent = this.agents.get(agentId);
    if (!agent) return;

    this.log('info', `Restarting agent: ${agentId}`);

    // Kill existing process
    if (agent.process) {
      agent.process.kill('SIGTERM');
      agent.process = null;
    }

    // Reset status
    agent.status = 'idle';
    agent.currentTask = null;
    agent.lastActivity = new Date();

    // Log error for the stuck task
    if (agent.currentTask) {
      this.db.logError({
        task_id: agent.currentTask,
        agent_id: agentId,
        error_type: 'AGENT_STUCK',
        error_message: 'Agent was stuck and had to be restarted',
      });

      this.db.updateTaskStatus(agent.currentTask, 'failed', undefined, 'Agent stuck');
    }
  }

  // ============ UTILITIES ============

  private checkDiskUsage(): number {
    try {
      const output = execSync('df -h . | tail -1', { encoding: 'utf-8' });
      const match = output.match(/(\d+)%/);
      return match ? parseInt(match[1], 10) : 0;
    } catch {
      return 0;
    }
  }

  private updateDailyStatus(result: HeartbeatResult): void {
    const statusPath = join(this.config.workingDir, 'intel', 'DAILY-STATUS.md');
    const date = new Date().toISOString().split('T')[0];

    const content = `# Daily Status - ${date}

## System Health
- Status: **${result.status.toUpperCase()}**
- Last heartbeat: ${result.timestamp.toISOString()}

## Checks
${Object.entries(result.checks)
  .map(([k, v]) => `- ${k}: ${v ? '✅' : '❌'}`)
  .join('\n')}

## Recent Actions
${result.actions.length > 0 ? result.actions.map(a => `- ${a}`).join('\n') : '- None'}

## Errors
${result.errors.length > 0 ? result.errors.map(e => `- ${e}`).join('\n') : '- None'}

## Agent Status
${Array.from(this.agents.values())
  .map(a => `- ${a.id}: ${a.status}${a.currentTask ? ` (task: ${a.currentTask})` : ''}`)
  .join('\n')}

---
*Auto-generated by Stacky Daemon*
`;

    try {
      const dir = join(this.config.workingDir, 'intel');
      if (!existsSync(dir)) {
        mkdirSync(dir, { recursive: true });
      }
      writeFileSync(statusPath, content);
    } catch (error) {
      this.log('error', `Failed to update daily status: ${error}`);
    }
  }

  private log(level: 'debug' | 'info' | 'warn' | 'error', message: string): void {
    const levels = { debug: 0, info: 1, warn: 2, error: 3 };
    if (levels[level] >= levels[this.config.logLevel]) {
      const timestamp = new Date().toISOString();
      const prefix = { debug: '🔍', info: 'ℹ️', warn: '⚠️', error: '❌' };
      console.log(`[${timestamp}] ${prefix[level]} ${message}`);
    }
  }

  private sleep(ms: number): Promise<void> {
    return new Promise(resolve => setTimeout(resolve, ms));
  }
}

// ============ CLI INTERFACE ============

async function main(): Promise<void> {
  const command = process.argv[2];

  switch (command) {
    case 'start': {
      const daemon = new StackyDaemon();
      
      // Handle shutdown signals
      process.on('SIGTERM', () => daemon.stop());
      process.on('SIGINT', () => daemon.stop());
      
      await daemon.start();
      break;
    }
    
    case 'heartbeat': {
      const daemon = new StackyDaemon();
      const result = await daemon.heartbeat();
      console.log(JSON.stringify(result, null, 2));
      break;
    }
    
    case 'status': {
      const db = getDB();
      const lastHeartbeat = db.getLastHeartbeat();
      console.log('Last heartbeat:', lastHeartbeat);
      break;
    }
    
    default:
      console.log('Usage: stacky-daemon <start|heartbeat|status>');
  }
}

// Run if called directly
if (import.meta.url === `file://${process.argv[1]}`) {
  main().catch(console.error);
}

export { StackyDaemon };
export default StackyDaemon;
