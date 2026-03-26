---
name: React Component Builder
description: Build production-ready React components with TypeScript, animations, and accessibility
category: frontend
agents: [nexus-frontend]
triggers: [component, react, button, form, card, modal, input, ui]
tokenCost: 2500
dependencies: []
shellInjections:
  git_branch: git branch --show-current 2>/dev/null || echo 'main'
  node_version: node -v 2>/dev/null || echo 'unknown'
---

# React Component Builder Skill

## Component Architecture Standards

### File Structure
```
src/components/
├── ui/                    # Primitive components (Button, Input, etc.)
│   ├── button.tsx
│   ├── input.tsx
│   └── index.ts          # Barrel export
├── features/             # Feature-specific components
│   └── auth/
│       ├── login-form.tsx
│       └── signup-form.tsx
└── layouts/              # Layout components
    ├── header.tsx
    └── footer.tsx
```

### Component Template

```tsx
'use client'; // Only if using hooks/interactivity

import { forwardRef, type ComponentPropsWithoutRef } from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

// 1. VARIANTS - Define all visual variations
const componentVariants = cva(
  // Base styles (always applied)
  'inline-flex items-center justify-center rounded-md font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:pointer-events-none disabled:opacity-50',
  {
    variants: {
      variant: {
        default: 'bg-primary text-primary-foreground hover:bg-primary/90',
        secondary: 'bg-secondary text-secondary-foreground hover:bg-secondary/80',
        outline: 'border border-input bg-background hover:bg-accent hover:text-accent-foreground',
        ghost: 'hover:bg-accent hover:text-accent-foreground',
        destructive: 'bg-destructive text-destructive-foreground hover:bg-destructive/90',
        link: 'text-primary underline-offset-4 hover:underline',
      },
      size: {
        sm: 'h-9 px-3 text-sm',
        md: 'h-10 px-4 text-sm',
        lg: 'h-11 px-6 text-base',
        icon: 'h-10 w-10',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'md',
    },
  }
);

// 2. TYPES - Extend native element props
interface ComponentProps
  extends ComponentPropsWithoutRef<'button'>,
    VariantProps<typeof componentVariants> {
  /** Optional loading state */
  isLoading?: boolean;
  /** Optional icon to display */
  leftIcon?: React.ReactNode;
  rightIcon?: React.ReactNode;
}

// 3. COMPONENT - Use forwardRef for ref forwarding
const Component = forwardRef<HTMLButtonElement, ComponentProps>(
  (
    {
      className,
      variant,
      size,
      isLoading,
      leftIcon,
      rightIcon,
      disabled,
      children,
      ...props
    },
    ref
  ) => {
    return (
      <button
        ref={ref}
        className={cn(componentVariants({ variant, size }), className)}
        disabled={disabled || isLoading}
        {...props}
      >
        {isLoading ? (
          <Spinner className="mr-2 h-4 w-4 animate-spin" />
        ) : leftIcon ? (
          <span className="mr-2">{leftIcon}</span>
        ) : null}
        {children}
        {rightIcon && <span className="ml-2">{rightIcon}</span>}
      </button>
    );
  }
);

Component.displayName = 'Component';

export { Component, componentVariants };
export type { ComponentProps };
```

### Form Component Pattern

```tsx
'use client';

import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { z } from 'zod';
import { useTransition } from 'react';

// 1. Schema
const formSchema = z.object({
  email: z.string().email('Invalid email address'),
  password: z.string().min(8, 'Password must be at least 8 characters'),
});

type FormData = z.infer<typeof formSchema>;

// 2. Component
export function LoginForm() {
  const [isPending, startTransition] = useTransition();
  
  const form = useForm<FormData>({
    resolver: zodResolver(formSchema),
    defaultValues: {
      email: '',
      password: '',
    },
  });

  const onSubmit = (data: FormData) => {
    startTransition(async () => {
      try {
        // Call server action or API
        const result = await loginAction(data);
        if (result.error) {
          form.setError('root', { message: result.error });
        }
      } catch (error) {
        form.setError('root', { message: 'Something went wrong' });
      }
    });
  };

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
      <div>
        <label htmlFor="email" className="block text-sm font-medium">
          Email
        </label>
        <input
          {...form.register('email')}
          type="email"
          id="email"
          className="mt-1 block w-full rounded-md border"
          aria-invalid={!!form.formState.errors.email}
          aria-describedby={form.formState.errors.email ? 'email-error' : undefined}
        />
        {form.formState.errors.email && (
          <p id="email-error" className="mt-1 text-sm text-red-500">
            {form.formState.errors.email.message}
          </p>
        )}
      </div>

      {form.formState.errors.root && (
        <div role="alert" className="rounded-md bg-red-50 p-4 text-red-700">
          {form.formState.errors.root.message}
        </div>
      )}

      <button
        type="submit"
        disabled={isPending}
        className="w-full rounded-md bg-primary px-4 py-2 text-white"
      >
        {isPending ? 'Signing in...' : 'Sign In'}
      </button>
    </form>
  );
}
```

### Animation Integration

```tsx
'use client';

import { useRef, useEffect } from 'react';
import gsap from 'gsap';

export function AnimatedCard({ children }: { children: React.ReactNode }) {
  const cardRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!cardRef.current) return;

    const ctx = gsap.context(() => {
      // Entrance animation
      gsap.from(cardRef.current, {
        opacity: 0,
        y: 20,
        duration: 0.6,
        ease: 'power3.out',
      });

      // Hover animation
      const card = cardRef.current;
      
      const handleMouseEnter = () => {
        gsap.to(card, {
          scale: 1.02,
          duration: 0.3,
          ease: 'power2.out',
        });
      };

      const handleMouseLeave = () => {
        gsap.to(card, {
          scale: 1,
          duration: 0.3,
          ease: 'power2.out',
        });
      };

      card?.addEventListener('mouseenter', handleMouseEnter);
      card?.addEventListener('mouseleave', handleMouseLeave);

      return () => {
        card?.removeEventListener('mouseenter', handleMouseEnter);
        card?.removeEventListener('mouseleave', handleMouseLeave);
      };
    }, cardRef);

    return () => ctx.revert();
  }, []);

  return (
    <div
      ref={cardRef}
      className="rounded-lg border bg-card p-6 shadow-sm"
    >
      {children}
    </div>
  );
}
```

## Accessibility Checklist

- [ ] Semantic HTML (button for buttons, not div)
- [ ] ARIA labels for icons-only buttons
- [ ] Focus visible styles
- [ ] Keyboard navigation support
- [ ] Color contrast (4.5:1 minimum)
- [ ] Form labels associated with inputs
- [ ] Error messages linked with aria-describedby
- [ ] Loading states announced to screen readers

## Performance Checklist

- [ ] Use `forwardRef` for all components
- [ ] Memoize callbacks with `useCallback`
- [ ] Memoize expensive computations with `useMemo`
- [ ] Lazy load heavy components
- [ ] Use CSS for animations when possible
- [ ] Avoid inline styles
- [ ] Keep bundle size in mind (check with `npx next build`)

## Current Context
- Git branch: {{git_branch}}
- Node version: {{node_version}}
- Date: {{today}}
