---
name: LLM Integration
description: Integrate Claude/GPT with streaming, tool use, RAG, and multi-turn conversations
category: aiml
agents: [aiml]
triggers: [llm, ai, claude, gpt, prompt, streaming, chat, completion, tools, rag]
tokenCost: 3500
dependencies: []
---

# LLM Integration Skill

## Architecture

```
src/
├── ai/
│   ├── providers/
│   │   ├── anthropic.ts      # Claude integration
│   │   ├── openai.ts         # GPT integration
│   │   └── index.ts          # Provider factory
│   ├── agents/
│   │   ├── base-agent.ts     # Agent base class
│   │   ├── code-agent.ts     # Code-focused agent
│   │   └── chat-agent.ts     # General chat agent
│   ├── tools/
│   │   ├── registry.ts       # Tool registry
│   │   ├── web-search.ts     # Web search tool
│   │   └── code-runner.ts    # Code execution tool
│   ├── memory/
│   │   ├── conversation.ts   # Conversation memory
│   │   └── vector-store.ts   # RAG vector store
│   └── prompts/
│       ├── templates.ts      # Prompt templates
│       └── system-prompts.ts # System prompts
└── lib/
    └── streaming.ts          # SSE streaming utilities
```

## Basic Completion

```typescript
import Anthropic from '@anthropic-ai/sdk';

const anthropic = new Anthropic({
  apiKey: process.env.ANTHROPIC_API_KEY,
});

export async function complete(
  prompt: string,
  options?: {
    model?: string;
    maxTokens?: number;
    temperature?: number;
    system?: string;
  }
): Promise<string> {
  const response = await anthropic.messages.create({
    model: options?.model || 'claude-sonnet-4-20250514',
    max_tokens: options?.maxTokens || 4096,
    temperature: options?.temperature ?? 0.7,
    system: options?.system,
    messages: [{ role: 'user', content: prompt }],
  });

  const textBlock = response.content.find((c) => c.type === 'text');
  return textBlock?.text || '';
}
```

## Streaming Response

```typescript
import Anthropic from '@anthropic-ai/sdk';

export async function* streamComplete(
  prompt: string,
  options?: {
    model?: string;
    maxTokens?: number;
    system?: string;
  }
): AsyncGenerator<string, void, unknown> {
  const anthropic = new Anthropic();

  const stream = anthropic.messages.stream({
    model: options?.model || 'claude-sonnet-4-20250514',
    max_tokens: options?.maxTokens || 4096,
    system: options?.system,
    messages: [{ role: 'user', content: prompt }],
  });

  for await (const event of stream) {
    if (
      event.type === 'content_block_delta' &&
      event.delta.type === 'text_delta'
    ) {
      yield event.delta.text;
    }
  }
}

// Usage in Hono route
app.get('/api/chat/stream', async (c) => {
  const prompt = c.req.query('prompt') || '';

  return c.streamText(async function* () {
    for await (const chunk of streamComplete(prompt)) {
      yield chunk;
    }
  });
});
```

## Tool Use / Function Calling

```typescript
import Anthropic from '@anthropic-ai/sdk';
import { z } from 'zod';

// Define tools
const tools = [
  {
    name: 'get_weather',
    description: 'Get current weather for a location',
    input_schema: {
      type: 'object',
      properties: {
        location: {
          type: 'string',
          description: 'City and state, e.g. San Francisco, CA',
        },
      },
      required: ['location'],
    },
  },
  {
    name: 'search_web',
    description: 'Search the web for information',
    input_schema: {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'Search query',
        },
      },
      required: ['query'],
    },
  },
];

// Tool implementations
const toolImplementations: Record<string, (input: unknown) => Promise<unknown>> = {
  get_weather: async (input: { location: string }) => {
    // Implement weather API call
    return { temperature: 72, conditions: 'sunny', location: input.location };
  },
  search_web: async (input: { query: string }) => {
    // Implement web search
    return { results: [`Result for: ${input.query}`] };
  },
};

// Execute with tools
export async function executeWithTools(
  prompt: string,
  maxIterations = 10
): Promise<{ content: string; toolCalls: Array<{ name: string; result: unknown }> }> {
  const anthropic = new Anthropic();
  const messages: Anthropic.MessageParam[] = [{ role: 'user', content: prompt }];
  const toolCalls: Array<{ name: string; result: unknown }> = [];

  for (let i = 0; i < maxIterations; i++) {
    const response = await anthropic.messages.create({
      model: 'claude-sonnet-4-20250514',
      max_tokens: 4096,
      tools,
      messages,
    });

    // Check for tool use
    const toolUseBlocks = response.content.filter((c) => c.type === 'tool_use');

    if (toolUseBlocks.length === 0) {
      // No tool calls, return final response
      const textBlock = response.content.find((c) => c.type === 'text');
      return { content: textBlock?.text || '', toolCalls };
    }

    // Execute tools
    const toolResults: Anthropic.MessageParam = {
      role: 'user',
      content: [],
    };

    for (const toolUse of toolUseBlocks) {
      if (toolUse.type !== 'tool_use') continue;

      const impl = toolImplementations[toolUse.name];
      if (!impl) {
        (toolResults.content as Anthropic.ToolResultBlockParam[]).push({
          type: 'tool_result',
          tool_use_id: toolUse.id,
          content: JSON.stringify({ error: `Unknown tool: ${toolUse.name}` }),
        });
        continue;
      }

      try {
        const result = await impl(toolUse.input as Record<string, unknown>);
        toolCalls.push({ name: toolUse.name, result });
        (toolResults.content as Anthropic.ToolResultBlockParam[]).push({
          type: 'tool_result',
          tool_use_id: toolUse.id,
          content: JSON.stringify(result),
        });
      } catch (error) {
        (toolResults.content as Anthropic.ToolResultBlockParam[]).push({
          type: 'tool_result',
          tool_use_id: toolUse.id,
          content: JSON.stringify({ error: String(error) }),
        });
      }
    }

    // Add assistant message and tool results
    messages.push({ role: 'assistant', content: response.content });
    messages.push(toolResults);
  }

  throw new Error('Max iterations reached');
}
```

## Agent Pattern

```typescript
import Anthropic from '@anthropic-ai/sdk';

interface AgentConfig {
  name: string;
  description: string;
  systemPrompt: string;
  tools?: Anthropic.Tool[];
  model?: string;
  maxTokens?: number;
  temperature?: number;
}

export class Agent {
  private anthropic: Anthropic;
  private config: AgentConfig;
  private memory: Array<{ role: 'user' | 'assistant'; content: string }> = [];

  constructor(config: AgentConfig) {
    this.anthropic = new Anthropic();
    this.config = config;
  }

  async chat(message: string): Promise<string> {
    this.memory.push({ role: 'user', content: message });

    const response = await this.anthropic.messages.create({
      model: this.config.model || 'claude-sonnet-4-20250514',
      max_tokens: this.config.maxTokens || 4096,
      temperature: this.config.temperature ?? 0.7,
      system: this.config.systemPrompt,
      tools: this.config.tools,
      messages: this.memory,
    });

    const textBlock = response.content.find((c) => c.type === 'text');
    const reply = textBlock?.text || '';

    this.memory.push({ role: 'assistant', content: reply });

    return reply;
  }

  async *streamChat(message: string): AsyncGenerator<string, void, unknown> {
    this.memory.push({ role: 'user', content: message });

    const stream = this.anthropic.messages.stream({
      model: this.config.model || 'claude-sonnet-4-20250514',
      max_tokens: this.config.maxTokens || 4096,
      system: this.config.systemPrompt,
      messages: this.memory,
    });

    let fullReply = '';

    for await (const event of stream) {
      if (event.type === 'content_block_delta' && event.delta.type === 'text_delta') {
        fullReply += event.delta.text;
        yield event.delta.text;
      }
    }

    this.memory.push({ role: 'assistant', content: fullReply });
  }

  clearMemory(): void {
    this.memory = [];
  }

  getMemory(): typeof this.memory {
    return [...this.memory];
  }
}

// Factory functions
export function createCodeAgent(): Agent {
  return new Agent({
    name: 'Code Assistant',
    description: 'Helps with coding tasks',
    systemPrompt: `You are an expert software developer. You help with:
- Writing clean, efficient code
- Debugging and fixing issues
- Code review and optimization
- Explaining complex concepts

Be precise, practical, and provide working code examples.
Always use TypeScript with proper types.`,
    model: 'claude-sonnet-4-20250514',
    temperature: 0.3,
  });
}

export function createChatAgent(): Agent {
  return new Agent({
    name: 'Chat Assistant',
    description: 'General purpose assistant',
    systemPrompt: 'You are a helpful AI assistant. Be friendly, clear, and concise.',
    temperature: 0.7,
  });
}
```

## RAG Integration

```typescript
import { OpenAI } from 'openai';

// Embedding function
export async function embed(text: string): Promise<number[]> {
  const openai = new OpenAI();
  
  const response = await openai.embeddings.create({
    model: 'text-embedding-3-small',
    input: text,
  });

  return response.data[0].embedding;
}

// Chunking function
export function chunkText(
  text: string,
  options?: { chunkSize?: number; overlap?: number }
): string[] {
  const chunkSize = options?.chunkSize || 512;
  const overlap = options?.overlap || 50;
  const chunks: string[] = [];

  let start = 0;
  while (start < text.length) {
    const end = Math.min(start + chunkSize, text.length);
    chunks.push(text.slice(start, end));
    start += chunkSize - overlap;
  }

  return chunks;
}

// Simple vector search (in production, use Pinecone/Qdrant)
export function cosineSimilarity(a: number[], b: number[]): number {
  let dotProduct = 0;
  let normA = 0;
  let normB = 0;
  
  for (let i = 0; i < a.length; i++) {
    dotProduct += a[i] * b[i];
    normA += a[i] * a[i];
    normB += b[i] * b[i];
  }
  
  return dotProduct / (Math.sqrt(normA) * Math.sqrt(normB));
}

// RAG query
export async function ragQuery(
  query: string,
  documents: Array<{ content: string; embedding: number[] }>,
  topK = 5
): Promise<string[]> {
  const queryEmbedding = await embed(query);
  
  const scored = documents.map((doc) => ({
    content: doc.content,
    score: cosineSimilarity(queryEmbedding, doc.embedding),
  }));
  
  scored.sort((a, b) => b.score - a.score);
  
  return scored.slice(0, topK).map((d) => d.content);
}
```

## Prompt Templates

```typescript
// Structured prompt templates
export const prompts = {
  codeReview: (code: string, language: string) => `
Review this ${language} code:

\`\`\`${language}
${code}
\`\`\`

Provide:
1. **Issues**: Bugs, logic errors, runtime problems
2. **Security**: Vulnerabilities, unsafe patterns
3. **Performance**: Inefficiencies, optimizations
4. **Style**: Readability, naming, best practices
5. **Suggestions**: Specific improvements with examples

Be specific. Reference line numbers. Explain reasoning.
`,

  generateCode: (description: string, language: string, context?: string) => `
Generate ${language} code for:

${description}

${context ? `Context:\n${context}` : ''}

Requirements:
- Follow ${language} best practices
- Include error handling
- Add comments for complex logic
- Make it production-ready
- Use TypeScript types if applicable

Return ONLY the code, no explanations.
`,

  explainCode: (code: string, language: string) => `
Explain this ${language} code:

\`\`\`${language}
${code}
\`\`\`

Cover:
1. What does this code do?
2. How does it work step by step?
3. What are the key concepts used?
4. When would you use this pattern?
`,

  summarize: (text: string, maxLength?: number) => `
Summarize the following text${maxLength ? ` in ${maxLength} words or less` : ''}:

${text}

Provide a clear, concise summary capturing the key points.
`,
};
```

## API Route for Chat

```typescript
import { Hono } from 'hono';
import { streamSSE } from 'hono/streaming';
import { createChatAgent } from '../ai/agents';

const app = new Hono();

// Non-streaming chat
app.post('/chat', async (c) => {
  const { message, history } = await c.req.json();
  const agent = createChatAgent();
  
  // Restore history
  for (const msg of history || []) {
    agent.chat(msg.content); // This is simplified, properly restore memory
  }
  
  const response = await agent.chat(message);
  
  return c.json({
    success: true,
    data: { message: response },
  });
});

// Streaming chat
app.post('/chat/stream', async (c) => {
  const { message } = await c.req.json();
  const agent = createChatAgent();
  
  return streamSSE(c, async (stream) => {
    for await (const chunk of agent.streamChat(message)) {
      await stream.writeSSE({
        data: JSON.stringify({ chunk }),
      });
    }
    await stream.writeSSE({
      data: JSON.stringify({ done: true }),
    });
  });
});

export { app as chatRoutes };
```

## Checklist

- [ ] Error handling for API failures
- [ ] Rate limit handling with retries
- [ ] Token counting for cost tracking
- [ ] Streaming for long responses
- [ ] Memory management for multi-turn
- [ ] Tool validation with Zod
- [ ] Proper typing throughout
- [ ] Logging for debugging

## Current Context
- Date: {{today}}
- Git branch: {{git_branch}}
