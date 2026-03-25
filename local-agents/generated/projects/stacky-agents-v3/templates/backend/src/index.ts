import { serve } from '@hono/node-server';
import { Hono } from 'hono';
import { cors } from 'hono/cors';
import { logger } from 'hono/logger';
import { secureHeaders } from 'hono/secure-headers';
import { timing } from 'hono/timing';
import { compress } from 'hono/compress';
import { etag } from 'hono/etag';
import { prettyJSON } from 'hono/pretty-json';
import { HTTPException } from 'hono/http-exception';
import { zValidator } from '@hono/zod-validator';
import { swaggerUI } from '@hono/swagger-ui';
import { OpenAPIHono, createRoute, z } from '@hono/zod-openapi';

import { db } from './db';
import { env } from './env';
import { authMiddleware, type AuthContext } from './middleware/auth';
import { rateLimitMiddleware } from './middleware/rate-limit';
import { requestIdMiddleware } from './middleware/request-id';
import { errorHandler, AppError } from './middleware/error-handler';
import { createLogger } from './lib/logger';

import { authRoutes } from './routes/auth';
import { userRoutes } from './routes/users';
import { projectRoutes } from './routes/projects';
import { taskRoutes } from './routes/tasks';
import { agentRoutes } from './routes/agents';
import { aiRoutes } from './routes/ai';
import { webhookRoutes } from './routes/webhooks';

// Create logger
const log = createLogger('server');

// Create app with typed context
const app = new OpenAPIHono<{ Variables: AuthContext }>();

// ============ GLOBAL MIDDLEWARE ============

// Request ID for tracing
app.use('*', requestIdMiddleware);

// Logging
app.use('*', logger((message, ...rest) => {
  log.info(message, ...rest);
}));

// Timing headers
app.use('*', timing());

// Security headers
app.use('*', secureHeaders());

// CORS
app.use('*', cors({
  origin: env.CORS_ORIGINS,
  allowMethods: ['GET', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'],
  allowHeaders: ['Content-Type', 'Authorization', 'X-Request-ID'],
  exposeHeaders: ['X-Request-ID', 'X-Response-Time'],
  credentials: true,
  maxAge: 86400,
}));

// Compression
app.use('*', compress());

// ETag for caching
app.use('*', etag());

// Pretty JSON in development
if (env.NODE_ENV === 'development') {
  app.use('*', prettyJSON());
}

// Rate limiting (skip in development)
if (env.NODE_ENV === 'production') {
  app.use('/api/*', rateLimitMiddleware);
}

// ============ HEALTH CHECK ============

const healthRoute = createRoute({
  method: 'get',
  path: '/health',
  tags: ['System'],
  summary: 'Health check',
  responses: {
    200: {
      content: {
        'application/json': {
          schema: z.object({
            status: z.literal('ok'),
            timestamp: z.string(),
            version: z.string(),
            uptime: z.number(),
          }),
        },
      },
      description: 'Service is healthy',
    },
  },
});

app.openapi(healthRoute, (c) => {
  return c.json({
    status: 'ok' as const,
    timestamp: new Date().toISOString(),
    version: env.APP_VERSION,
    uptime: process.uptime(),
  });
});

// Detailed health check (internal only)
app.get('/health/detailed', async (c) => {
  const checks = {
    database: false,
    redis: false,
  };

  try {
    // Check database
    await db.execute(sql`SELECT 1`);
    checks.database = true;
  } catch (error) {
    log.error('Database health check failed', { error });
  }

  // Add more checks as needed

  const allHealthy = Object.values(checks).every(Boolean);

  return c.json({
    status: allHealthy ? 'healthy' : 'degraded',
    checks,
    timestamp: new Date().toISOString(),
  }, allHealthy ? 200 : 503);
});

// ============ API ROUTES ============

// Mount routes
app.route('/api/auth', authRoutes);
app.route('/api/users', userRoutes);
app.route('/api/projects', projectRoutes);
app.route('/api/tasks', taskRoutes);
app.route('/api/agents', agentRoutes);
app.route('/api/ai', aiRoutes);
app.route('/api/webhooks', webhookRoutes);

// ============ DOCUMENTATION ============

// OpenAPI spec
app.doc('/api/openapi.json', {
  openapi: '3.1.0',
  info: {
    title: 'Stacky API',
    version: env.APP_VERSION,
    description: 'AI Dev Platform API',
  },
  servers: [
    { url: env.API_URL, description: env.NODE_ENV },
  ],
  tags: [
    { name: 'Auth', description: 'Authentication endpoints' },
    { name: 'Users', description: 'User management' },
    { name: 'Projects', description: 'Project management' },
    { name: 'Tasks', description: 'Task management' },
    { name: 'Agents', description: 'AI agent management' },
    { name: 'AI', description: 'AI operations' },
    { name: 'System', description: 'System endpoints' },
  ],
});

// Swagger UI
app.get('/api/docs', swaggerUI({ url: '/api/openapi.json' }));

// ============ ERROR HANDLING ============

// 404 handler
app.notFound((c) => {
  return c.json({
    success: false,
    error: {
      code: 'NOT_FOUND',
      message: `Route ${c.req.method} ${c.req.path} not found`,
    },
  }, 404);
});

// Global error handler
app.onError(errorHandler);

// ============ START SERVER ============

const port = env.PORT;

log.info(`Starting server on port ${port}`);

serve({
  fetch: app.fetch,
  port,
}, (info) => {
  log.info(`Server running at http://localhost:${info.port}`);
  log.info(`API docs at http://localhost:${info.port}/api/docs`);
});

// Graceful shutdown
const shutdown = async (signal: string) => {
  log.info(`Received ${signal}, shutting down gracefully`);
  
  // Close database connections
  // await db.end();
  
  process.exit(0);
};

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

export default app;
export type AppType = typeof app;

// SQL template tag for raw queries
import { sql } from 'drizzle-orm';
