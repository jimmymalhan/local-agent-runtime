---
name: Advanced Hono API Application
description: Production-ready Hono API with Drizzle ORM, auth, jobs, webhooks, rate limiting, and real-time
category: backend
agents: [backend]
triggers: [hono, api, server, backend, database, auth, drizzle, postgres, crud]
tokenCost: 8000
---

# Advanced Hono API Application Skill

## Complete API Structure

```
src/
├── index.ts                 # Server entry point
├── app.ts                   # Hono app configuration
├── env.ts                   # Environment validation
├── routes/
│   ├── index.ts             # Route aggregation
│   ├── auth.ts              # Authentication
│   ├── users.ts             # User management
│   ├── projects.ts          # Projects CRUD
│   ├── tasks.ts             # Tasks CRUD
│   └── webhooks.ts          # Webhook handlers
├── services/
│   ├── auth-service.ts      # Auth business logic
│   ├── user-service.ts      # User business logic
│   └── email-service.ts     # Email sending
├── middleware/
│   ├── auth.ts              # JWT authentication
│   ├── rate-limit.ts        # Rate limiting
│   ├── error-handler.ts     # Error handling
│   ├── request-id.ts        # Request tracing
│   └── cors.ts              # CORS configuration
├── db/
│   ├── index.ts             # Database connection
│   ├── schema.ts            # Drizzle schema
│   └── migrations/          # Migration files
├── jobs/
│   ├── index.ts             # Job queue setup
│   ├── email-job.ts         # Email sending job
│   └── cleanup-job.ts       # Database cleanup
├── lib/
│   ├── utils.ts             # Utility functions
│   ├── logger.ts            # Structured logging
│   └── crypto.ts            # Encryption utilities
└── types/
    └── index.ts             # TypeScript types
```

## Server Entry Point

```typescript
// src/index.ts
import { serve } from '@hono/node-server';
import { app } from './app';
import { env } from './env';
import { log } from './lib/logger';
import { runMigrations } from './db';
import { startJobRunner } from './jobs';

async function main() {
  log.info('Starting server...');

  // Run database migrations
  await runMigrations();
  log.info('Database migrations complete');

  // Start background job runner
  startJobRunner();
  log.info('Job runner started');

  // Start HTTP server
  serve({
    fetch: app.fetch,
    port: env.PORT,
  }, (info) => {
    log.info(`Server running at http://localhost:${info.port}`);
    log.info(`API docs at http://localhost:${info.port}/api/docs`);
    log.info(`Health check at http://localhost:${info.port}/health`);
  });

  // Graceful shutdown
  const shutdown = async (signal: string) => {
    log.info(`Received ${signal}, shutting down gracefully`);
    process.exit(0);
  };

  process.on('SIGTERM', () => shutdown('SIGTERM'));
  process.on('SIGINT', () => shutdown('SIGINT'));
}

main().catch((error) => {
  log.error('Failed to start server', { error });
  process.exit(1);
});
```

## App Configuration

```typescript
// src/app.ts
import { OpenAPIHono } from '@hono/zod-openapi';
import { cors } from 'hono/cors';
import { logger } from 'hono/logger';
import { secureHeaders } from 'hono/secure-headers';
import { timing } from 'hono/timing';
import { compress } from 'hono/compress';
import { etag } from 'hono/etag';
import { prettyJSON } from 'hono/pretty-json';
import { swaggerUI } from '@hono/swagger-ui';

import { env } from './env';
import { requestIdMiddleware } from './middleware/request-id';
import { rateLimitMiddleware } from './middleware/rate-limit';
import { errorHandler } from './middleware/error-handler';

import { authRoutes } from './routes/auth';
import { userRoutes } from './routes/users';
import { projectRoutes } from './routes/projects';
import { taskRoutes } from './routes/tasks';
import { webhookRoutes } from './routes/webhooks';

import type { AuthContext } from './types';

const app = new OpenAPIHono<{ Variables: AuthContext }>();

// Global middleware
app.use('*', requestIdMiddleware);
app.use('*', logger());
app.use('*', timing());
app.use('*', secureHeaders());
app.use('*', cors({
  origin: env.CORS_ORIGINS,
  allowMethods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
  allowHeaders: ['Content-Type', 'Authorization', 'X-Request-ID'],
  credentials: true,
  maxAge: 86400,
}));
app.use('*', compress());
app.use('*', etag());

if (env.NODE_ENV === 'development') {
  app.use('*', prettyJSON());
}

if (env.NODE_ENV === 'production') {
  app.use('/api/*', rateLimitMiddleware);
}

// Health check
app.get('/health', (c) => c.json({
  status: 'ok',
  timestamp: new Date().toISOString(),
  version: env.APP_VERSION,
  uptime: process.uptime(),
}));

// API routes
app.route('/api/auth', authRoutes);
app.route('/api/users', userRoutes);
app.route('/api/projects', projectRoutes);
app.route('/api/tasks', taskRoutes);
app.route('/api/webhooks', webhookRoutes);

// OpenAPI documentation
app.doc('/api/openapi.json', {
  openapi: '3.1.0',
  info: { title: 'API', version: env.APP_VERSION, description: 'API Documentation' },
  servers: [{ url: env.API_URL, description: env.NODE_ENV }],
  tags: [
    { name: 'Auth', description: 'Authentication endpoints' },
    { name: 'Users', description: 'User management' },
    { name: 'Projects', description: 'Project management' },
    { name: 'Tasks', description: 'Task management' },
  ],
});

app.get('/api/docs', swaggerUI({ url: '/api/openapi.json' }));

// 404 handler
app.notFound((c) => c.json({
  success: false,
  error: { code: 'NOT_FOUND', message: `Route ${c.req.method} ${c.req.path} not found` },
}, 404));

// Error handler
app.onError(errorHandler);

export { app };
```

## Environment Validation

```typescript
// src/env.ts
import { createEnv } from '@t3-oss/env-core';
import { z } from 'zod';

export const env = createEnv({
  server: {
    NODE_ENV: z.enum(['development', 'production', 'test']).default('development'),
    PORT: z.coerce.number().default(3000),
    APP_VERSION: z.string().default('1.0.0'),
    API_URL: z.string().url().default('http://localhost:3000'),
    CORS_ORIGINS: z.string().transform((s) => s.split(',')).default('http://localhost:3000'),
    
    DATABASE_URL: z.string().url(),
    
    JWT_SECRET: z.string().min(32),
    JWT_EXPIRES_IN: z.string().default('7d'),
    
    REDIS_URL: z.string().url().optional(),
    
    ANTHROPIC_API_KEY: z.string().optional(),
    OPENAI_API_KEY: z.string().optional(),
    
    SMTP_HOST: z.string().optional(),
    SMTP_PORT: z.coerce.number().optional(),
    SMTP_USER: z.string().optional(),
    SMTP_PASS: z.string().optional(),
    EMAIL_FROM: z.string().email().optional(),
    
    WEBHOOK_SECRET: z.string().optional(),
  },
  runtimeEnv: process.env,
  skipValidation: process.env.SKIP_ENV_VALIDATION === 'true',
});
```

## Database Schema (Drizzle)

```typescript
// src/db/schema.ts
import { pgTable, text, timestamp, boolean, integer, json, pgEnum } from 'drizzle-orm/pg-core';
import { relations } from 'drizzle-orm';
import { createId } from '@paralleldrive/cuid2';

// Enums
export const userRoleEnum = pgEnum('user_role', ['user', 'admin']);
export const projectStatusEnum = pgEnum('project_status', ['active', 'paused', 'completed', 'archived']);
export const taskStatusEnum = pgEnum('task_status', ['pending', 'in_progress', 'review', 'completed', 'failed']);
export const taskPriorityEnum = pgEnum('task_priority', ['low', 'medium', 'high', 'urgent']);

// Users
export const users = pgTable('users', {
  id: text('id').primaryKey().$defaultFn(() => createId()),
  email: text('email').notNull().unique(),
  name: text('name').notNull(),
  passwordHash: text('password_hash'),
  avatar: text('avatar'),
  role: userRoleEnum('role').default('user').notNull(),
  emailVerified: boolean('email_verified').default(false),
  preferences: json('preferences').$type<{ theme: string; notifications: boolean }>(),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull().$onUpdate(() => new Date()),
  deletedAt: timestamp('deleted_at'),
});

// Sessions
export const sessions = pgTable('sessions', {
  id: text('id').primaryKey().$defaultFn(() => createId()),
  userId: text('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  token: text('token').notNull().unique(),
  expiresAt: timestamp('expires_at').notNull(),
  userAgent: text('user_agent'),
  ipAddress: text('ip_address'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

// Projects
export const projects = pgTable('projects', {
  id: text('id').primaryKey().$defaultFn(() => createId()),
  userId: text('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  name: text('name').notNull(),
  description: text('description'),
  status: projectStatusEnum('status').default('active').notNull(),
  settings: json('settings'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull().$onUpdate(() => new Date()),
});

// Tasks
export const tasks = pgTable('tasks', {
  id: text('id').primaryKey().$defaultFn(() => createId()),
  projectId: text('project_id').notNull().references(() => projects.id, { onDelete: 'cascade' }),
  parentId: text('parent_id'),
  title: text('title').notNull(),
  description: text('description'),
  status: taskStatusEnum('status').default('pending').notNull(),
  priority: taskPriorityEnum('priority').default('medium').notNull(),
  assigneeId: text('assignee_id').references(() => users.id),
  dueDate: timestamp('due_date'),
  completedAt: timestamp('completed_at'),
  metadata: json('metadata'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
  updatedAt: timestamp('updated_at').defaultNow().notNull().$onUpdate(() => new Date()),
});

// API Keys
export const apiKeys = pgTable('api_keys', {
  id: text('id').primaryKey().$defaultFn(() => createId()),
  userId: text('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  name: text('name').notNull(),
  keyHash: text('key_hash').notNull().unique(),
  lastUsedAt: timestamp('last_used_at'),
  expiresAt: timestamp('expires_at'),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

// Webhooks
export const webhooks = pgTable('webhooks', {
  id: text('id').primaryKey().$defaultFn(() => createId()),
  userId: text('user_id').notNull().references(() => users.id, { onDelete: 'cascade' }),
  url: text('url').notNull(),
  events: json('events').$type<string[]>().notNull(),
  secret: text('secret').notNull(),
  active: boolean('active').default(true),
  createdAt: timestamp('created_at').defaultNow().notNull(),
});

// Relations
export const usersRelations = relations(users, ({ many }) => ({
  sessions: many(sessions),
  projects: many(projects),
  apiKeys: many(apiKeys),
  webhooks: many(webhooks),
}));

export const projectsRelations = relations(projects, ({ one, many }) => ({
  user: one(users, { fields: [projects.userId], references: [users.id] }),
  tasks: many(tasks),
}));

export const tasksRelations = relations(tasks, ({ one, many }) => ({
  project: one(projects, { fields: [tasks.projectId], references: [projects.id] }),
  assignee: one(users, { fields: [tasks.assigneeId], references: [users.id] }),
  parent: one(tasks, { fields: [tasks.parentId], references: [tasks.id] }),
  subtasks: many(tasks),
}));
```

## Auth Routes (Complete)

```typescript
// src/routes/auth.ts
import { OpenAPIHono, createRoute, z } from '@hono/zod-openapi';
import { zValidator } from '@hono/zod-validator';
import { setCookie, deleteCookie } from 'hono/cookie';
import { authService } from '../services/auth-service';
import { authMiddleware } from '../middleware/auth';
import type { AuthContext } from '../types';

const app = new OpenAPIHono<{ Variables: AuthContext }>();

// Schemas
const registerSchema = z.object({
  email: z.string().email(),
  password: z.string().min(8).max(72),
  name: z.string().min(2).max(100),
});

const loginSchema = z.object({
  email: z.string().email(),
  password: z.string(),
});

const forgotPasswordSchema = z.object({
  email: z.string().email(),
});

const resetPasswordSchema = z.object({
  token: z.string(),
  password: z.string().min(8).max(72),
});

// POST /auth/register
app.post('/register', zValidator('json', registerSchema), async (c) => {
  const data = c.req.valid('json');
  
  try {
    const { user, token } = await authService.register(data);
    
    setCookie(c, 'token', token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 7, // 7 days
      path: '/',
    });
    
    return c.json({ success: true, data: { user } }, 201);
  } catch (error) {
    if (error instanceof Error && error.message === 'Email already exists') {
      return c.json({ success: false, error: { code: 'EMAIL_EXISTS', message: error.message } }, 409);
    }
    throw error;
  }
});

// POST /auth/login
app.post('/login', zValidator('json', loginSchema), async (c) => {
  const data = c.req.valid('json');
  const userAgent = c.req.header('User-Agent');
  const ipAddress = c.req.header('X-Forwarded-For') || c.req.header('X-Real-IP');
  
  try {
    const { user, token } = await authService.login(data, { userAgent, ipAddress });
    
    setCookie(c, 'token', token, {
      httpOnly: true,
      secure: process.env.NODE_ENV === 'production',
      sameSite: 'lax',
      maxAge: 60 * 60 * 24 * 7,
      path: '/',
    });
    
    return c.json({ success: true, data: { user } });
  } catch (error) {
    return c.json({ success: false, error: { code: 'INVALID_CREDENTIALS', message: 'Invalid email or password' } }, 401);
  }
});

// POST /auth/logout
app.post('/logout', authMiddleware, async (c) => {
  const user = c.get('user');
  await authService.logout(user.sessionId);
  
  deleteCookie(c, 'token', { path: '/' });
  
  return c.json({ success: true, message: 'Logged out successfully' });
});

// GET /auth/me
app.get('/me', authMiddleware, async (c) => {
  const user = c.get('user');
  return c.json({ success: true, data: { user } });
});

// POST /auth/forgot-password
app.post('/forgot-password', zValidator('json', forgotPasswordSchema), async (c) => {
  const { email } = c.req.valid('json');
  
  // Always return success to prevent email enumeration
  await authService.sendPasswordResetEmail(email).catch(() => {});
  
  return c.json({ success: true, message: 'If an account exists, a reset email has been sent' });
});

// POST /auth/reset-password
app.post('/reset-password', zValidator('json', resetPasswordSchema), async (c) => {
  const { token, password } = c.req.valid('json');
  
  try {
    await authService.resetPassword(token, password);
    return c.json({ success: true, message: 'Password reset successfully' });
  } catch (error) {
    return c.json({ success: false, error: { code: 'INVALID_TOKEN', message: 'Invalid or expired reset token' } }, 400);
  }
});

// POST /auth/refresh
app.post('/refresh', authMiddleware, async (c) => {
  const user = c.get('user');
  const { token } = await authService.refreshToken(user.sessionId);
  
  setCookie(c, 'token', token, {
    httpOnly: true,
    secure: process.env.NODE_ENV === 'production',
    sameSite: 'lax',
    maxAge: 60 * 60 * 24 * 7,
    path: '/',
  });
  
  return c.json({ success: true, message: 'Token refreshed' });
});

export { app as authRoutes };
```

## Auth Middleware

```typescript
// src/middleware/auth.ts
import { createMiddleware } from 'hono/factory';
import { getCookie } from 'hono/cookie';
import { HTTPException } from 'hono/http-exception';
import { verify } from 'jose';
import { env } from '../env';
import type { AuthContext } from '../types';

const JWT_SECRET = new TextEncoder().encode(env.JWT_SECRET);

export const authMiddleware = createMiddleware<{ Variables: AuthContext }>(async (c, next) => {
  // Try cookie first, then Authorization header
  let token = getCookie(c, 'token');
  
  if (!token) {
    const authHeader = c.req.header('Authorization');
    if (authHeader?.startsWith('Bearer ')) {
      token = authHeader.slice(7);
    }
  }
  
  if (!token) {
    throw new HTTPException(401, { message: 'Authentication required' });
  }
  
  try {
    const { payload } = await verify(token, JWT_SECRET);
    
    c.set('user', {
      id: payload.sub as string,
      email: payload.email as string,
      role: payload.role as 'user' | 'admin',
      sessionId: payload.sid as string,
    });
    
    await next();
  } catch (error) {
    throw new HTTPException(401, { message: 'Invalid or expired token' });
  }
});

export const adminMiddleware = createMiddleware<{ Variables: AuthContext }>(async (c, next) => {
  const user = c.get('user');
  
  if (user.role !== 'admin') {
    throw new HTTPException(403, { message: 'Admin access required' });
  }
  
  await next();
});
```

## Rate Limiting

```typescript
// src/middleware/rate-limit.ts
import { createMiddleware } from 'hono/factory';
import { Ratelimit } from '@upstash/ratelimit';
import { Redis } from '@upstash/redis';
import { HTTPException } from 'hono/http-exception';
import { env } from '../env';

const redis = env.REDIS_URL ? new Redis({ url: env.REDIS_URL }) : null;

const ratelimit = redis
  ? new Ratelimit({
      redis,
      limiter: Ratelimit.slidingWindow(100, '1 m'), // 100 requests per minute
      analytics: true,
    })
  : null;

export const rateLimitMiddleware = createMiddleware(async (c, next) => {
  if (!ratelimit) {
    return next();
  }
  
  const ip = c.req.header('X-Forwarded-For') || c.req.header('X-Real-IP') || 'unknown';
  const { success, limit, reset, remaining } = await ratelimit.limit(ip);
  
  c.header('X-RateLimit-Limit', limit.toString());
  c.header('X-RateLimit-Remaining', remaining.toString());
  c.header('X-RateLimit-Reset', reset.toString());
  
  if (!success) {
    throw new HTTPException(429, { message: 'Too many requests' });
  }
  
  return next();
});
```

## Error Handler

```typescript
// src/middleware/error-handler.ts
import { HTTPException } from 'hono/http-exception';
import type { ErrorHandler } from 'hono';
import { ZodError } from 'zod';
import { log } from '../lib/logger';
import { env } from '../env';

export class AppError extends Error {
  constructor(public statusCode: number, public code: string, message: string) {
    super(message);
    this.name = 'AppError';
  }
}

export const errorHandler: ErrorHandler = (err, c) => {
  const requestId = c.get('requestId') || 'unknown';
  
  log.error('Request error', {
    requestId,
    error: err.message,
    stack: err.stack,
    path: c.req.path,
    method: c.req.method,
  });
  
  // HTTP Exception (from hono)
  if (err instanceof HTTPException) {
    return c.json({
      success: false,
      error: { code: 'HTTP_ERROR', message: err.message },
      requestId,
    }, err.status);
  }
  
  // App Error (custom)
  if (err instanceof AppError) {
    return c.json({
      success: false,
      error: { code: err.code, message: err.message },
      requestId,
    }, err.statusCode);
  }
  
  // Zod validation error
  if (err instanceof ZodError) {
    return c.json({
      success: false,
      error: {
        code: 'VALIDATION_ERROR',
        message: 'Invalid request data',
        details: err.errors.map((e) => ({
          path: e.path.join('.'),
          message: e.message,
        })),
      },
      requestId,
    }, 400);
  }
  
  // Database errors
  if (err.message?.includes('unique constraint')) {
    return c.json({
      success: false,
      error: { code: 'DUPLICATE_ENTRY', message: 'Resource already exists' },
      requestId,
    }, 409);
  }
  
  // Unknown error
  return c.json({
    success: false,
    error: {
      code: 'INTERNAL_ERROR',
      message: env.NODE_ENV === 'production' ? 'An unexpected error occurred' : err.message,
    },
    requestId,
  }, 500);
};
```

## Background Jobs (Inngest)

```typescript
// src/jobs/index.ts
import { Inngest } from 'inngest';
import { serve } from 'inngest/hono';
import { sendWelcomeEmail } from './email-job';
import { cleanupSessions } from './cleanup-job';
import { processWebhook } from './webhook-job';

export const inngest = new Inngest({ id: 'my-app' });

// Define all functions
export const functions = [
  sendWelcomeEmail,
  cleanupSessions,
  processWebhook,
];

// Hono route handler
export const inngestHandler = serve({ client: inngest, functions });

// Start periodic jobs
export function startJobRunner() {
  // Cleanup expired sessions every hour
  inngest.send({ name: 'cleanup/sessions', data: {} });
}
```

```typescript
// src/jobs/email-job.ts
import { inngest } from './index';
import { emailService } from '../services/email-service';

export const sendWelcomeEmail = inngest.createFunction(
  { id: 'send-welcome-email', retries: 3 },
  { event: 'user/created' },
  async ({ event }) => {
    const { userId, email, name } = event.data;
    
    await emailService.sendWelcome({ to: email, name });
    
    return { sent: true, userId };
  }
);
```

## Logger

```typescript
// src/lib/logger.ts
import pino from 'pino';
import { env } from '../env';

export const log = pino({
  level: env.NODE_ENV === 'production' ? 'info' : 'debug',
  transport: env.NODE_ENV === 'development'
    ? { target: 'pino-pretty', options: { colorize: true } }
    : undefined,
  base: { pid: process.pid, env: env.NODE_ENV },
  timestamp: pino.stdTimeFunctions.isoTime,
});
```

This skill provides a complete production-ready Hono API with authentication, database, jobs, rate limiting, and proper error handling.
