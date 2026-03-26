import Anthropic from '@anthropic-ai/sdk';
import OpenAI from 'openai';
import { z } from 'zod';

// ============ TYPES ============

export interface Message {
  role: 'user' | 'assistant' | 'system';
  content: string;
}

export interface Tool {
  name: string;
  description: string;
  parameters: z.ZodSchema;
  execute: (params: unknown) => Promise<unknown>;
}

export interface AgentConfig {
  id: string;
  name: string;
  description: string;
  systemPrompt: string;
  model?: string;
  tools?: Tool[];
  maxIterations?: number;
  temperature?: number;
  maxTokens?: number;
}

export interface StreamCallbacks {
  onStart?: () => void;
  onToken?: (token: string) => void;
  onToolCall?: (name: string, args: unknown) => void;
  onToolResult?: (name: string, result: unknown) => void;
  onComplete?: (content: string) => void;
  onError?: (error: Error) => void;
}

export interface CompletionResult {
  content: string;
  toolCalls?: Array<{ name: string; args: unknown; result: unknown }>;
  usage: {
    inputTokens: number;
    outputTokens: number;
    totalTokens: number;
  };
  model: string;
  finishReason: string;
}

// ============ PROVIDER ABSTRACTION ============

type Provider = 'anthropic' | 'openai';

interface ProviderConfig {
  anthropic?: { apiKey: string };
  openai?: { apiKey: string };
}

export class AIService {
  private anthropic?: Anthropic;
  private openai?: OpenAI;
  private defaultProvider: Provider = 'anthropic';
  
  constructor(config: ProviderConfig) {
    if (config.anthropic?.apiKey) {
      this.anthropic = new Anthropic({ apiKey: config.anthropic.apiKey });
    }
    if (config.openai?.apiKey) {
      this.openai = new OpenAI({ apiKey: config.openai.apiKey });
    }
  }

  // ============ BASIC COMPLETION ============

  async complete(
    messages: Message[],
    options: {
      model?: string;
      maxTokens?: number;
      temperature?: number;
      system?: string;
      provider?: Provider;
    } = {}
  ): Promise<CompletionResult> {
    const provider = options.provider || this.defaultProvider;
    
    if (provider === 'anthropic') {
      return this.completeAnthropic(messages, options);
    } else {
      return this.completeOpenAI(messages, options);
    }
  }

  private async completeAnthropic(
    messages: Message[],
    options: {
      model?: string;
      maxTokens?: number;
      temperature?: number;
      system?: string;
    }
  ): Promise<CompletionResult> {
    if (!this.anthropic) throw new Error('Anthropic not configured');

    const systemMessage = options.system || messages.find(m => m.role === 'system')?.content;
    const chatMessages = messages
      .filter(m => m.role !== 'system')
      .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content }));

    const response = await this.anthropic.messages.create({
      model: options.model || 'claude-sonnet-4-20250514',
      max_tokens: options.maxTokens || 4096,
      temperature: options.temperature ?? 0.7,
      system: systemMessage,
      messages: chatMessages,
    });

    const textContent = response.content.find(c => c.type === 'text');

    return {
      content: textContent?.text || '',
      usage: {
        inputTokens: response.usage.input_tokens,
        outputTokens: response.usage.output_tokens,
        totalTokens: response.usage.input_tokens + response.usage.output_tokens,
      },
      model: response.model,
      finishReason: response.stop_reason || 'stop',
    };
  }

  private async completeOpenAI(
    messages: Message[],
    options: {
      model?: string;
      maxTokens?: number;
      temperature?: number;
    }
  ): Promise<CompletionResult> {
    if (!this.openai) throw new Error('OpenAI not configured');

    const response = await this.openai.chat.completions.create({
      model: options.model || 'gpt-4o',
      max_tokens: options.maxTokens || 4096,
      temperature: options.temperature ?? 0.7,
      messages: messages.map(m => ({
        role: m.role,
        content: m.content,
      })),
    });

    const choice = response.choices[0];

    return {
      content: choice.message.content || '',
      usage: {
        inputTokens: response.usage?.prompt_tokens || 0,
        outputTokens: response.usage?.completion_tokens || 0,
        totalTokens: response.usage?.total_tokens || 0,
      },
      model: response.model,
      finishReason: choice.finish_reason || 'stop',
    };
  }

  // ============ STREAMING ============

  async *stream(
    messages: Message[],
    options: {
      model?: string;
      maxTokens?: number;
      temperature?: number;
      system?: string;
      provider?: Provider;
    } = {}
  ): AsyncGenerator<string, void, unknown> {
    const provider = options.provider || this.defaultProvider;

    if (provider === 'anthropic') {
      yield* this.streamAnthropic(messages, options);
    } else {
      yield* this.streamOpenAI(messages, options);
    }
  }

  private async *streamAnthropic(
    messages: Message[],
    options: {
      model?: string;
      maxTokens?: number;
      temperature?: number;
      system?: string;
    }
  ): AsyncGenerator<string, void, unknown> {
    if (!this.anthropic) throw new Error('Anthropic not configured');

    const systemMessage = options.system || messages.find(m => m.role === 'system')?.content;
    const chatMessages = messages
      .filter(m => m.role !== 'system')
      .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content }));

    const stream = await this.anthropic.messages.stream({
      model: options.model || 'claude-sonnet-4-20250514',
      max_tokens: options.maxTokens || 4096,
      temperature: options.temperature ?? 0.7,
      system: systemMessage,
      messages: chatMessages,
    });

    for await (const event of stream) {
      if (event.type === 'content_block_delta' && event.delta.type === 'text_delta') {
        yield event.delta.text;
      }
    }
  }

  private async *streamOpenAI(
    messages: Message[],
    options: {
      model?: string;
      maxTokens?: number;
      temperature?: number;
    }
  ): AsyncGenerator<string, void, unknown> {
    if (!this.openai) throw new Error('OpenAI not configured');

    const stream = await this.openai.chat.completions.create({
      model: options.model || 'gpt-4o',
      max_tokens: options.maxTokens || 4096,
      temperature: options.temperature ?? 0.7,
      messages: messages.map(m => ({
        role: m.role,
        content: m.content,
      })),
      stream: true,
    });

    for await (const chunk of stream) {
      const content = chunk.choices[0]?.delta?.content;
      if (content) {
        yield content;
      }
    }
  }

  // ============ TOOL USE ============

  async completeWithTools(
    messages: Message[],
    tools: Tool[],
    options: {
      model?: string;
      maxTokens?: number;
      temperature?: number;
      system?: string;
      maxIterations?: number;
    } = {}
  ): Promise<CompletionResult> {
    if (!this.anthropic) throw new Error('Anthropic not configured');

    const maxIterations = options.maxIterations || 10;
    let iteration = 0;
    let currentMessages = [...messages];
    const toolCalls: Array<{ name: string; args: unknown; result: unknown }> = [];
    let totalInputTokens = 0;
    let totalOutputTokens = 0;

    const systemMessage = options.system || messages.find(m => m.role === 'system')?.content;
    
    // Convert tools to Anthropic format
    const anthropicTools = tools.map(tool => ({
      name: tool.name,
      description: tool.description,
      input_schema: this.zodToJsonSchema(tool.parameters),
    }));

    while (iteration < maxIterations) {
      iteration++;

      const chatMessages = currentMessages
        .filter(m => m.role !== 'system')
        .map(m => ({ role: m.role as 'user' | 'assistant', content: m.content }));

      const response = await this.anthropic.messages.create({
        model: options.model || 'claude-sonnet-4-20250514',
        max_tokens: options.maxTokens || 4096,
        temperature: options.temperature ?? 0.7,
        system: systemMessage,
        messages: chatMessages,
        tools: anthropicTools,
      });

      totalInputTokens += response.usage.input_tokens;
      totalOutputTokens += response.usage.output_tokens;

      // Check if we need to execute tools
      const toolUseBlocks = response.content.filter(c => c.type === 'tool_use');
      
      if (toolUseBlocks.length === 0) {
        // No tool calls, return the response
        const textContent = response.content.find(c => c.type === 'text');
        return {
          content: textContent?.text || '',
          toolCalls,
          usage: {
            inputTokens: totalInputTokens,
            outputTokens: totalOutputTokens,
            totalTokens: totalInputTokens + totalOutputTokens,
          },
          model: response.model,
          finishReason: response.stop_reason || 'stop',
        };
      }

      // Execute tools
      const toolResults: Array<{ type: 'tool_result'; tool_use_id: string; content: string }> = [];

      for (const toolUse of toolUseBlocks) {
        if (toolUse.type !== 'tool_use') continue;

        const tool = tools.find(t => t.name === toolUse.name);
        if (!tool) {
          toolResults.push({
            type: 'tool_result',
            tool_use_id: toolUse.id,
            content: JSON.stringify({ error: `Unknown tool: ${toolUse.name}` }),
          });
          continue;
        }

        try {
          // Validate input
          const validatedInput = tool.parameters.parse(toolUse.input);
          
          // Execute tool
          const result = await tool.execute(validatedInput);
          
          toolCalls.push({
            name: toolUse.name,
            args: toolUse.input,
            result,
          });

          toolResults.push({
            type: 'tool_result',
            tool_use_id: toolUse.id,
            content: JSON.stringify(result),
          });
        } catch (error) {
          toolResults.push({
            type: 'tool_result',
            tool_use_id: toolUse.id,
            content: JSON.stringify({ error: error instanceof Error ? error.message : 'Unknown error' }),
          });
        }
      }

      // Add assistant message with tool use and tool results
      currentMessages.push({
        role: 'assistant',
        content: JSON.stringify(response.content),
      });
      currentMessages.push({
        role: 'user',
        content: JSON.stringify(toolResults),
      });
    }

    throw new Error('Max iterations reached');
  }

  private zodToJsonSchema(schema: z.ZodSchema): Record<string, unknown> {
    // Simple Zod to JSON Schema conversion
    // For production, use zod-to-json-schema library
    return {
      type: 'object',
      properties: {},
    };
  }
}

// ============ AGENT IMPLEMENTATION ============

export class Agent {
  private ai: AIService;
  private config: AgentConfig;
  private memory: Message[] = [];

  constructor(ai: AIService, config: AgentConfig) {
    this.ai = ai;
    this.config = config;
  }

  async chat(userMessage: string): Promise<string> {
    this.memory.push({ role: 'user', content: userMessage });

    const messages: Message[] = [
      { role: 'system', content: this.config.systemPrompt },
      ...this.memory,
    ];

    if (this.config.tools && this.config.tools.length > 0) {
      const result = await this.ai.completeWithTools(messages, this.config.tools, {
        model: this.config.model,
        maxTokens: this.config.maxTokens,
        temperature: this.config.temperature,
        maxIterations: this.config.maxIterations,
      });

      this.memory.push({ role: 'assistant', content: result.content });
      return result.content;
    } else {
      const result = await this.ai.complete(messages, {
        model: this.config.model,
        maxTokens: this.config.maxTokens,
        temperature: this.config.temperature,
      });

      this.memory.push({ role: 'assistant', content: result.content });
      return result.content;
    }
  }

  async *streamChat(userMessage: string): AsyncGenerator<string, void, unknown> {
    this.memory.push({ role: 'user', content: userMessage });

    const messages: Message[] = [
      { role: 'system', content: this.config.systemPrompt },
      ...this.memory,
    ];

    let fullContent = '';

    for await (const token of this.ai.stream(messages, {
      model: this.config.model,
      maxTokens: this.config.maxTokens,
      temperature: this.config.temperature,
    })) {
      fullContent += token;
      yield token;
    }

    this.memory.push({ role: 'assistant', content: fullContent });
  }

  clearMemory(): void {
    this.memory = [];
  }

  getMemory(): Message[] {
    return [...this.memory];
  }
}

// ============ PROMPT TEMPLATES ============

export const prompts = {
  codeReview: (code: string, language: string) => `
You are a senior code reviewer. Analyze this ${language} code:

\`\`\`${language}
${code}
\`\`\`

Provide:
1. **Issues**: Bugs, logic errors, potential runtime problems
2. **Security**: Vulnerabilities, unsafe patterns
3. **Performance**: Inefficiencies, optimization opportunities
4. **Style**: Readability, naming, best practices
5. **Suggestions**: Specific improvements with examples

Be specific. Reference line numbers. Explain your reasoning.
`,

  generateCode: (description: string, language: string, context?: string) => `
Generate ${language} code for the following requirement:

${description}

${context ? `Context:\n${context}` : ''}

Requirements:
- Follow best practices for ${language}
- Include error handling
- Add comments for complex logic
- Make it production-ready

Return ONLY the code, no explanations.
`,

  explainCode: (code: string, language: string) => `
Explain this ${language} code in detail:

\`\`\`${language}
${code}
\`\`\`

Cover:
1. What does this code do?
2. How does it work step by step?
3. What are the key concepts used?
4. When would you use this pattern?
`,

  refactorCode: (code: string, language: string, instruction: string) => `
Refactor this ${language} code:

\`\`\`${language}
${code}
\`\`\`

Refactoring goal: ${instruction}

Provide the refactored code with comments explaining the changes.
`,
};

// ============ FACTORY FUNCTIONS ============

export function createAIService(): AIService {
  return new AIService({
    anthropic: { apiKey: process.env.ANTHROPIC_API_KEY || '' },
    openai: { apiKey: process.env.OPENAI_API_KEY || '' },
  });
}

export function createCodeAgent(ai: AIService): Agent {
  return new Agent(ai, {
    id: 'code-agent',
    name: 'Code Assistant',
    description: 'Helps with coding tasks',
    systemPrompt: `You are an expert software developer. You help with:
- Writing clean, efficient code
- Debugging and fixing issues
- Code review and optimization
- Explaining complex concepts
- Best practices and patterns

Be precise, practical, and provide working code examples.`,
    model: 'claude-sonnet-4-20250514',
    temperature: 0.3,
    maxTokens: 8192,
  });
}

export function createChatAgent(ai: AIService): Agent {
  return new Agent(ai, {
    id: 'chat-agent',
    name: 'Chat Assistant',
    description: 'General purpose assistant',
    systemPrompt: `You are a helpful AI assistant. Be friendly, clear, and concise.`,
    model: 'claude-sonnet-4-20250514',
    temperature: 0.7,
    maxTokens: 4096,
  });
}
