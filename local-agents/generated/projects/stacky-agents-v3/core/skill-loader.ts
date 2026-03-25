import { readFileSync, existsSync, readdirSync } from 'fs';
import { join, basename } from 'path';
import { execSync } from 'child_process';
import { getDB } from './db';

// ============ TYPES ============

export interface Skill {
  id: string;
  name: string;
  description: string;
  category: string;
  agents: string[];
  triggers: string[];
  tokenCost: number;
  dependencies?: string[];
  shellInjections?: Record<string, string>;
  content: string;
}

export interface SkillMatch {
  skill: Skill;
  confidence: number;
  matchedTrigger: string;
}

// ============ SKILL REGISTRY ============

class SkillLoader {
  private skills: Map<string, Skill> = new Map();
  private skillsByAgent: Map<string, Skill[]> = new Map();
  private skillsByCategory: Map<string, Skill[]> = new Map();
  private loaded = false;

  constructor(private skillsPath: string = './skills') {}

  // Load all skills from filesystem
  loadSkills(): void {
    if (this.loaded) return;

    const categories = readdirSync(this.skillsPath, { withFileTypes: true })
      .filter(d => d.isDirectory())
      .map(d => d.name);

    for (const category of categories) {
      const categoryPath = join(this.skillsPath, category);
      const files = readdirSync(categoryPath)
        .filter(f => f.endsWith('.md') || f.endsWith('.skill'));

      for (const file of files) {
        const skill = this.parseSkillFile(join(categoryPath, file), category);
        if (skill) {
          this.registerSkill(skill);
        }
      }
    }

    this.loaded = true;
    console.log(`Loaded ${this.skills.size} skills from ${categories.length} categories`);
  }

  // Parse a skill file
  private parseSkillFile(path: string, category: string): Skill | null {
    if (!existsSync(path)) return null;

    const content = readFileSync(path, 'utf-8');
    const id = basename(path, '.md').replace('.skill', '');

    // Parse frontmatter
    const frontmatterMatch = content.match(/^---\n([\s\S]*?)\n---/);
    if (!frontmatterMatch) {
      // Simple skill file without frontmatter
      return {
        id: `${category}/${id}`,
        name: id,
        description: content.slice(0, 200),
        category,
        agents: [category],
        triggers: [id.toLowerCase()],
        tokenCost: Math.ceil(content.length / 4),
        content,
      };
    }

    // Parse YAML frontmatter
    const frontmatter = frontmatterMatch[1];
    const skillContent = content.slice(frontmatterMatch[0].length).trim();

    const metadata: Record<string, unknown> = {};
    for (const line of frontmatter.split('\n')) {
      const [key, ...valueParts] = line.split(':');
      if (key && valueParts.length) {
        const value = valueParts.join(':').trim();
        // Parse arrays
        if (value.startsWith('[')) {
          metadata[key.trim()] = value
            .slice(1, -1)
            .split(',')
            .map(s => s.trim().replace(/['"]/g, ''));
        } else {
          metadata[key.trim()] = value.replace(/['"]/g, '');
        }
      }
    }

    return {
      id: `${category}/${id}`,
      name: (metadata.name as string) || id,
      description: (metadata.description as string) || skillContent.slice(0, 200),
      category,
      agents: (metadata.agents as string[]) || [category],
      triggers: (metadata.triggers as string[]) || [id.toLowerCase()],
      tokenCost: (metadata.tokenCost as number) || Math.ceil(skillContent.length / 4),
      dependencies: metadata.dependencies as string[] | undefined,
      shellInjections: metadata.shellInjections as Record<string, string> | undefined,
      content: skillContent,
    };
  }

  // Register a skill
  private registerSkill(skill: Skill): void {
    this.skills.set(skill.id, skill);

    // Index by agent
    for (const agent of skill.agents) {
      const agentSkills = this.skillsByAgent.get(agent) || [];
      agentSkills.push(skill);
      this.skillsByAgent.set(agent, agentSkills);
    }

    // Index by category
    const categorySkills = this.skillsByCategory.get(skill.category) || [];
    categorySkills.push(skill);
    this.skillsByCategory.set(skill.category, categorySkills);
  }

  // Get skill by ID
  getSkill(id: string): Skill | undefined {
    return this.skills.get(id);
  }

  // Get all skills for an agent
  getSkillsForAgent(agentId: string): Skill[] {
    return this.skillsByAgent.get(agentId) || [];
  }

  // Get skills by category
  getSkillsByCategory(category: string): Skill[] {
    return this.skillsByCategory.get(category) || [];
  }

  // Find matching skills for a task
  findMatchingSkills(
    taskDescription: string,
    agentId?: string,
    maxSkills = 5
  ): SkillMatch[] {
    const matches: SkillMatch[] = [];
    const description = taskDescription.toLowerCase();

    const skillsToCheck = agentId 
      ? this.getSkillsForAgent(agentId)
      : Array.from(this.skills.values());

    for (const skill of skillsToCheck) {
      for (const trigger of skill.triggers) {
        if (description.includes(trigger.toLowerCase())) {
          // Calculate confidence based on trigger specificity
          const confidence = trigger.length / description.length;
          matches.push({
            skill,
            confidence: Math.min(confidence * 2, 1),
            matchedTrigger: trigger,
          });
          break;
        }
      }
    }

    // Sort by confidence and return top matches
    return matches
      .sort((a, b) => b.confidence - a.confidence)
      .slice(0, maxSkills);
  }

  // Load skill content with shell injections
  loadSkillContent(skillId: string, context?: Record<string, string>): string {
    const skill = this.skills.get(skillId);
    if (!skill) throw new Error(`Skill not found: ${skillId}`);

    let content = skill.content;

    // Process shell injections
    if (skill.shellInjections) {
      for (const [placeholder, command] of Object.entries(skill.shellInjections)) {
        try {
          const result = execSync(command, { encoding: 'utf-8', timeout: 5000 }).trim();
          content = content.replace(new RegExp(`\\{\\{${placeholder}\\}\\}`, 'g'), result);
        } catch (error) {
          console.warn(`Shell injection failed for ${placeholder}:`, error);
          content = content.replace(new RegExp(`\\{\\{${placeholder}\\}\\}`, 'g'), '[unavailable]');
        }
      }
    }

    // Process context variables
    if (context) {
      for (const [key, value] of Object.entries(context)) {
        content = content.replace(new RegExp(`\\{\\{${key}\\}\\}`, 'g'), value);
      }
    }

    // Standard variable replacements
    const standardVars: Record<string, () => string> = {
      today: () => new Date().toISOString().split('T')[0],
      timestamp: () => new Date().toISOString(),
      git_branch: () => {
        try {
          return execSync('git branch --show-current', { encoding: 'utf-8' }).trim();
        } catch { return 'unknown'; }
      },
      git_status: () => {
        try {
          return execSync('git status --short', { encoding: 'utf-8' }).trim();
        } catch { return 'unknown'; }
      },
      node_version: () => process.version,
      cwd: () => process.cwd(),
    };

    for (const [key, getValue] of Object.entries(standardVars)) {
      if (content.includes(`{{${key}}}`)) {
        content = content.replace(new RegExp(`\\{\\{${key}\\}\\}`, 'g'), getValue());
      }
    }

    return content;
  }

  // Build context prompt with loaded skills
  buildSkillContext(skillIds: string[], context?: Record<string, string>): string {
    const skillContents: string[] = [];
    let totalTokens = 0;

    for (const id of skillIds) {
      const skill = this.skills.get(id);
      if (!skill) continue;

      // Check token budget
      if (totalTokens + skill.tokenCost > 50000) {
        console.warn(`Token budget exceeded, skipping skill: ${id}`);
        continue;
      }

      const content = this.loadSkillContent(id, context);
      skillContents.push(`## Skill: ${skill.name}\n\n${content}`);
      totalTokens += skill.tokenCost;
    }

    return skillContents.join('\n\n---\n\n');
  }

  // Log skill execution
  logExecution(
    skillId: string,
    agentId: string,
    taskId: string | undefined,
    success: boolean,
    durationMs: number,
    tokensUsed: number
  ): void {
    const db = getDB();
    db.logExecution({
      task_id: taskId,
      agent_id: agentId,
      skill_id: skillId,
      success,
      duration_ms: durationMs,
      tokens_input: Math.floor(tokensUsed * 0.3),
      tokens_output: Math.floor(tokensUsed * 0.7),
    });
  }

  // Get skill statistics
  getSkillStats(skillId?: string): Record<string, unknown> {
    const db = getDB();
    
    if (skillId) {
      const stats = db.raw(`
        SELECT 
          skill_id,
          COUNT(*) as total_executions,
          SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
          AVG(duration_ms) as avg_duration,
          SUM(tokens_input + tokens_output) as total_tokens
        FROM skill_executions
        WHERE skill_id = ?
        GROUP BY skill_id
      `, [skillId]);
      return stats[0] || {};
    }

    return db.raw(`
      SELECT 
        skill_id,
        COUNT(*) as total_executions,
        SUM(CASE WHEN success THEN 1 ELSE 0 END) as successful,
        AVG(duration_ms) as avg_duration,
        SUM(tokens_input + tokens_output) as total_tokens
      FROM skill_executions
      GROUP BY skill_id
      ORDER BY total_executions DESC
    `);
  }
}

// ============ SINGLETON ============

let loader: SkillLoader | null = null;

export function getSkillLoader(skillsPath?: string): SkillLoader {
  if (!loader) {
    loader = new SkillLoader(skillsPath);
    loader.loadSkills();
  }
  return loader;
}

export default getSkillLoader;
