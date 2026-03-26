---
name: API Route Builder
description: Build production-ready REST APIs with Hono, Zod validation, and OpenAPI docs
category: backend
agents: [backend]
triggers: [api, endpoint, route, rest, crud, hono]
tokenCost: 3000
dependencies: []
shellInjections:
  git_branch: git branch --show-current 2>/dev/null || echo 'main'
---

# API Route Builder Skill

## Architecture

```
src/
├── routes/
│   ├── index.ts           # Route aggregation
│   ├── auth.ts            # Auth routes
│   ├── users.ts           # User routes
│   └── projects.ts        # Project routes
├── services/
│   ├── user-service.ts    # Business logic
│   └── project-service.ts
├── middleware/
│   ├── auth.ts            # Auth middleware
│   ├── rate-limit.ts
│   └── error-handler.ts
├── db/
│   ├── schema.ts          # Drizzle schema
│   └── index.ts           # DB connection
└── lib/
    ├── validators.ts       # Zod schemas
    └── utils.ts
```

## Route File Template

```typescript
import { Hono } from 'hono';
import { zValidator } from '@hono/zod-validator';
import { z } from 'zod';
import { authMiddleware } from '../middleware/auth';
import { userService } from '../services/user-service';
import type { AuthContext } from '../types';

// Initialize router with typed context
const app = new Hono<{ Variables: AuthContext }>();

// ============ SCHEMAS ============

const createUserSchema = z.object({
  email: z.string().email(),
  name: z.string().min(2).max(100),
  role: z.enum(['user', 'admin']).default('user'),
});

const updateUserSchema = z.object({
  name: z.string().min(2).max(100).optional(),
  role: z.enum(['user', 'admin']).optional(),
});

const querySchema = z.object({
  page: z.coerce.number().min(1).default(1),
  limit: z.coerce.number().min(1).max(100).default(20),
  search: z.string().optional(),
  role: z.enum(['user', 'admin']).optional(),
});

// ============ ROUTES ============

// GET /users - List users (paginated)
app.get(
  '/',
  authMiddleware,
  zValidator('query', querySchema),
  async (c) => {
    const query = c.req.valid('query');
    const user = c.get('user');

    // Only admins can list all users
    if (user.role !== 'admin') {
      return c.json({ success: false, error: 'Forbidden' }, 403);
    }

    const { users, total } = await userService.list(query);

    return c.json({
      success: true,
      data: users,
      meta: {
        page: query.page,
        limit: query.limit,
        total,
        totalPages: Math.ceil(total / query.limit),
      },
    });
  }
);

// GET /users/:id - Get single user
app.get(
  '/:id',
  authMiddleware,
  async (c) => {
    const id = c.req.param('id');
    const currentUser = c.get('user');

    // Users can only view their own profile (unless admin)
    if (currentUser.role !== 'admin' && currentUser.id !== id) {
      return c.json({ success: false, error: 'Forbidden' }, 403);
    }

    const user = await userService.getById(id);

    if (!user) {
      return c.json({ success: false, error: 'User not found' }, 404);
    }

    return c.json({ success: true, data: user });
  }
);

// POST /users - Create user
app.post(
  '/',
  authMiddleware,
  zValidator('json', createUserSchema),
  async (c) => {
    const data = c.req.valid('json');
    const currentUser = c.get('user');

    // Only admins can create users
    if (currentUser.role !== 'admin') {
      return c.json({ success: false, error: 'Forbidden' }, 403);
    }

    try {
      const user = await userService.create(data);
      return c.json({ success: true, data: user }, 201);
    } catch (error) {
      if (error instanceof Error && error.message.includes('unique')) {
        return c.json({ success: false, error: 'Email already exists' }, 409);
      }
      throw error;
    }
  }
);

// PATCH /users/:id - Update user
app.patch(
  '/:id',
  authMiddleware,
  zValidator('json', updateUserSchema),
  async (c) => {
    const id = c.req.param('id');
    const data = c.req.valid('json');
    const currentUser = c.get('user');

    // Users can only update their own profile (unless admin)
    if (currentUser.role !== 'admin' && currentUser.id !== id) {
      return c.json({ success: false, error: 'Forbidden' }, 403);
    }

    // Non-admins can't change their own role
    if (currentUser.role !== 'admin' && data.role) {
      return c.json({ success: false, error: 'Cannot change own role' }, 403);
    }

    const user = await userService.update(id, data);

    if (!user) {
      return c.json({ success: false, error: 'User not found' }, 404);
    }

    return c.json({ success: true, data: user });
  }
);

// DELETE /users/:id - Delete user
app.delete(
  '/:id',
  authMiddleware,
  async (c) => {
    const id = c.req.param('id');
    const currentUser = c.get('user');

    // Only admins can delete users
    if (currentUser.role !== 'admin') {
      return c.json({ success: false, error: 'Forbidden' }, 403);
    }

    // Can't delete yourself
    if (currentUser.id === id) {
      return c.json({ success: false, error: 'Cannot delete yourself' }, 400);
    }

    const deleted = await userService.delete(id);

    if (!deleted) {
      return c.json({ success: false, error: 'User not found' }, 404);
    }

    return c.json({ success: true, message: 'User deleted' });
  }
);

export { app as userRoutes };
```

## Service Layer Template

```typescript
import { eq, like, and, desc, asc, sql } from 'drizzle-orm';
import { db } from '../db';
import { users } from '../db/schema';
import { createId } from '../lib/utils';

export const userService = {
  async list(options: {
    page: number;
    limit: number;
    search?: string;
    role?: 'user' | 'admin';
  }) {
    const offset = (options.page - 1) * options.limit;
    
    // Build where conditions
    const conditions = [];
    if (options.search) {
      conditions.push(
        like(users.email, `%${options.search}%`),
        like(users.name, `%${options.search}%`)
      );
    }
    if (options.role) {
      conditions.push(eq(users.role, options.role));
    }

    const where = conditions.length > 0 ? and(...conditions) : undefined;

    // Execute queries
    const [data, countResult] = await Promise.all([
      db
        .select()
        .from(users)
        .where(where)
        .orderBy(desc(users.createdAt))
        .limit(options.limit)
        .offset(offset),
      db
        .select({ count: sql<number>`count(*)` })
        .from(users)
        .where(where),
    ]);

    return {
      users: data,
      total: countResult[0]?.count ?? 0,
    };
  },

  async getById(id: string) {
    const result = await db
      .select()
      .from(users)
      .where(eq(users.id, id))
      .limit(1);
    
    return result[0] ?? null;
  },

  async create(data: { email: string; name: string; role?: 'user' | 'admin' }) {
    const id = createId();
    
    const [user] = await db
      .insert(users)
      .values({
        id,
        email: data.email,
        name: data.name,
        role: data.role ?? 'user',
      })
      .returning();
    
    return user;
  },

  async update(id: string, data: { name?: string; role?: 'user' | 'admin' }) {
    const [user] = await db
      .update(users)
      .set({
        ...data,
        updatedAt: new Date(),
      })
      .where(eq(users.id, id))
      .returning();
    
    return user ?? null;
  },

  async delete(id: string) {
    const result = await db
      .delete(users)
      .where(eq(users.id, id))
      .returning({ id: users.id });
    
    return result.length > 0;
  },
};
```

## Auth Middleware Template

```typescript
import { createMiddleware } from 'hono/factory';
import { verify } from 'jose';
import { HTTPException } from 'hono/http-exception';

export interface AuthContext {
  user: {
    id: string;
    email: string;
    role: 'user' | 'admin';
  };
}

const JWT_SECRET = new TextEncoder().encode(process.env.JWT_SECRET || 'secret');

export const authMiddleware = createMiddleware<{ Variables: AuthContext }>(
  async (c, next) => {
    const authHeader = c.req.header('Authorization');
    
    if (!authHeader?.startsWith('Bearer ')) {
      throw new HTTPException(401, { message: 'Missing authorization header' });
    }

    const token = authHeader.slice(7);

    try {
      const { payload } = await verify(token, JWT_SECRET);
      
      c.set('user', {
        id: payload.sub as string,
        email: payload.email as string,
        role: payload.role as 'user' | 'admin',
      });

      await next();
    } catch (error) {
      throw new HTTPException(401, { message: 'Invalid token' });
    }
  }
);
```

## Error Handler Template

```typescript
import { HTTPException } from 'hono/http-exception';
import type { ErrorHandler } from 'hono';

export class AppError extends Error {
  constructor(
    public statusCode: number,
    public code: string,
    message: string
  ) {
    super(message);
    this.name = 'AppError';
  }
}

export const errorHandler: ErrorHandler = (err, c) => {
  console.error('Error:', {
    message: err.message,
    stack: err.stack,
    path: c.req.path,
    method: c.req.method,
  });

  // Handle known error types
  if (err instanceof HTTPException) {
    return c.json(
      {
        success: false,
        error: {
          code: 'HTTP_ERROR',
          message: err.message,
        },
      },
      err.status
    );
  }

  if (err instanceof AppError) {
    return c.json(
      {
        success: false,
        error: {
          code: err.code,
          message: err.message,
        },
      },
      err.statusCode
    );
  }

  // Handle Zod validation errors
  if (err.name === 'ZodError') {
    return c.json(
      {
        success: false,
        error: {
          code: 'VALIDATION_ERROR',
          message: 'Invalid request data',
          details: (err as any).errors,
        },
      },
      400
    );
  }

  // Default error
  return c.json(
    {
      success: false,
      error: {
        code: 'INTERNAL_ERROR',
        message: process.env.NODE_ENV === 'production'
          ? 'An unexpected error occurred'
          : err.message,
      },
    },
    500
  );
};
```

## Response Format Standards

```typescript
// Success response
interface SuccessResponse<T> {
  success: true;
  data: T;
  meta?: {
    page?: number;
    limit?: number;
    total?: number;
    totalPages?: number;
  };
}

// Error response
interface ErrorResponse {
  success: false;
  error: {
    code: string;
    message: string;
    details?: unknown;
  };
}

// Always use this format:
return c.json({ success: true, data: result });
return c.json({ success: false, error: { code: 'NOT_FOUND', message: 'Resource not found' } }, 404);
```

## API Documentation

Add OpenAPI docs with `@hono/zod-openapi`:

```typescript
import { OpenAPIHono, createRoute, z } from '@hono/zod-openapi';

const getUserRoute = createRoute({
  method: 'get',
  path: '/users/{id}',
  tags: ['Users'],
  summary: 'Get user by ID',
  request: {
    params: z.object({
      id: z.string().openapi({ description: 'User ID' }),
    }),
  },
  responses: {
    200: {
      content: {
        'application/json': {
          schema: z.object({
            success: z.literal(true),
            data: userSchema,
          }),
        },
      },
      description: 'User found',
    },
    404: {
      content: {
        'application/json': {
          schema: errorSchema,
        },
      },
      description: 'User not found',
    },
  },
});
```

## Checklist

- [ ] Zod validation on all inputs
- [ ] Auth middleware on protected routes
- [ ] Proper HTTP status codes
- [ ] Consistent response format
- [ ] Error handling with specific codes
- [ ] OpenAPI documentation
- [ ] Rate limiting on sensitive endpoints
- [ ] Logging for debugging

## Current Context
- Git branch: {{git_branch}}
- Date: {{today}}
