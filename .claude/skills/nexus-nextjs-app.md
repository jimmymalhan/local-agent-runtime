---
name: Advanced Next.js Application
description: Production-ready Next.js 14 with App Router, 3D, animations, state, auth, and API integration
category: frontend
agents: [nexus-frontend]
triggers: [nextjs, app, page, layout, application, website, landing, dashboard]
tokenCost: 8000
---

# Advanced Next.js Application Skill

## Complete App Structure

```
src/
├── app/
│   ├── (auth)/
│   │   ├── login/page.tsx
│   │   ├── signup/page.tsx
│   │   └── layout.tsx
│   ├── (dashboard)/
│   │   ├── dashboard/page.tsx
│   │   ├── settings/page.tsx
│   │   └── layout.tsx
│   ├── (marketing)/
│   │   ├── page.tsx          # Landing
│   │   ├── pricing/page.tsx
│   │   ├── about/page.tsx
│   │   └── layout.tsx
│   ├── api/
│   │   └── [...route]/route.ts
│   ├── layout.tsx            # Root layout
│   ├── loading.tsx
│   ├── error.tsx
│   ├── not-found.tsx
│   └── globals.css
├── components/
│   ├── ui/                   # Primitive components
│   ├── features/             # Feature components
│   ├── layouts/              # Layout components
│   ├── 3d/                   # Three.js scenes
│   └── animations/           # GSAP components
├── hooks/
├── lib/
├── stores/
└── styles/
```

## Root Layout (Complete)

```tsx
// src/app/layout.tsx
import type { Metadata, Viewport } from 'next';
import { Inter, Space_Grotesk, JetBrains_Mono } from 'next/font/google';
import { Providers } from '@/components/providers';
import { Toaster } from '@/components/ui/toaster';
import { Analytics } from '@/components/analytics';
import '@/styles/globals.css';

const inter = Inter({ subsets: ['latin'], variable: '--font-inter' });
const spaceGrotesk = Space_Grotesk({ subsets: ['latin'], variable: '--font-space' });
const jetbrainsMono = JetBrains_Mono({ subsets: ['latin'], variable: '--font-mono' });

export const metadata: Metadata = {
  metadataBase: new URL(process.env.NEXT_PUBLIC_APP_URL || 'http://localhost:3000'),
  title: { default: 'App Name', template: '%s | App Name' },
  description: 'Your app description',
  keywords: ['keyword1', 'keyword2'],
  authors: [{ name: 'Your Name' }],
  creator: 'Your Name',
  openGraph: {
    type: 'website',
    locale: 'en_US',
    siteName: 'App Name',
    title: 'App Name',
    description: 'Your app description',
    images: [{ url: '/og-image.png', width: 1200, height: 630 }],
  },
  twitter: {
    card: 'summary_large_image',
    title: 'App Name',
    description: 'Your app description',
    images: ['/og-image.png'],
  },
  robots: { index: true, follow: true },
  icons: {
    icon: '/favicon.ico',
    shortcut: '/favicon-16x16.png',
    apple: '/apple-touch-icon.png',
  },
  manifest: '/site.webmanifest',
};

export const viewport: Viewport = {
  themeColor: [
    { media: '(prefers-color-scheme: light)', color: '#ffffff' },
    { media: '(prefers-color-scheme: dark)', color: '#0a0a0a' },
  ],
  width: 'device-width',
  initialScale: 1,
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en" suppressHydrationWarning className={`${inter.variable} ${spaceGrotesk.variable} ${jetbrainsMono.variable}`}>
      <body className="min-h-screen bg-background font-sans antialiased">
        <Providers>
          <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:p-4 focus:bg-background">
            Skip to main content
          </a>
          <div className="relative flex min-h-screen flex-col">
            <main id="main" className="flex-1">{children}</main>
          </div>
          <Toaster />
        </Providers>
        <Analytics />
      </body>
    </html>
  );
}
```

## Complete Providers

```tsx
// src/components/providers.tsx
'use client';

import { useState, useEffect, type ReactNode } from 'react';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { ReactQueryDevtools } from '@tanstack/react-query-devtools';
import { ThemeProvider } from 'next-themes';
import { SessionProvider } from 'next-auth/react';
import Lenis from 'lenis';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

function makeQueryClient() {
  return new QueryClient({
    defaultOptions: {
      queries: {
        staleTime: 60 * 1000,
        gcTime: 5 * 60 * 1000,
        retry: 3,
        retryDelay: (attempt) => Math.min(1000 * 2 ** attempt, 30000),
        refetchOnWindowFocus: process.env.NODE_ENV === 'production',
      },
    },
  });
}

let browserQueryClient: QueryClient | undefined;
function getQueryClient() {
  if (typeof window === 'undefined') return makeQueryClient();
  if (!browserQueryClient) browserQueryClient = makeQueryClient();
  return browserQueryClient;
}

function SmoothScrollProvider({ children }: { children: ReactNode }) {
  useEffect(() => {
    const lenis = new Lenis({
      duration: 1.2,
      easing: (t) => Math.min(1, 1.001 - Math.pow(2, -10 * t)),
      orientation: 'vertical',
      smoothWheel: true,
    });

    lenis.on('scroll', ScrollTrigger.update);
    gsap.ticker.add((time) => lenis.raf(time * 1000));
    gsap.ticker.lagSmoothing(0);

    return () => {
      lenis.destroy();
      ScrollTrigger.getAll().forEach((t) => t.kill());
    };
  }, []);

  return <>{children}</>;
}

export function Providers({ children }: { children: ReactNode }) {
  const queryClient = getQueryClient();
  const [mounted, setMounted] = useState(false);

  useEffect(() => setMounted(true), []);

  return (
    <SessionProvider>
      <QueryClientProvider client={queryClient}>
        <ThemeProvider attribute="class" defaultTheme="system" enableSystem disableTransitionOnChange>
          {mounted ? <SmoothScrollProvider>{children}</SmoothScrollProvider> : children}
        </ThemeProvider>
        {process.env.NODE_ENV === 'development' && <ReactQueryDevtools />}
      </QueryClientProvider>
    </SessionProvider>
  );
}
```

## Landing Page with 3D Hero

```tsx
// src/app/(marketing)/page.tsx
import { Suspense } from 'react';
import { HeroSection } from '@/components/features/hero-section';
import { FeaturesSection } from '@/components/features/features-section';
import { PricingSection } from '@/components/features/pricing-section';
import { TestimonialsSection } from '@/components/features/testimonials-section';
import { CTASection } from '@/components/features/cta-section';
import { Footer } from '@/components/layouts/footer';
import { Header } from '@/components/layouts/header';

export default function LandingPage() {
  return (
    <>
      <Header />
      <Suspense fallback={<div className="h-screen animate-pulse bg-muted" />}>
        <HeroSection />
      </Suspense>
      <FeaturesSection />
      <TestimonialsSection />
      <PricingSection />
      <CTASection />
      <Footer />
    </>
  );
}
```

## Hero Section with 3D

```tsx
// src/components/features/hero-section.tsx
'use client';

import { useRef, useEffect } from 'react';
import dynamic from 'next/dynamic';
import gsap from 'gsap';
import { Button } from '@/components/ui/button';
import { ArrowRight, Play } from 'lucide-react';

const Scene3D = dynamic(() => import('@/components/3d/hero-scene'), { ssr: false });

export function HeroSection() {
  const containerRef = useRef<HTMLElement>(null);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const descRef = useRef<HTMLParagraphElement>(null);
  const ctaRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const ctx = gsap.context(() => {
      const tl = gsap.timeline({ defaults: { ease: 'power3.out' } });

      // Split title into words for animation
      if (titleRef.current) {
        const words = titleRef.current.innerText.split(' ');
        titleRef.current.innerHTML = words.map(w => `<span class="inline-block">${w}</span>`).join(' ');
        
        tl.from(titleRef.current.querySelectorAll('span'), {
          y: 100,
          opacity: 0,
          rotateX: -90,
          stagger: 0.08,
          duration: 1,
        });
      }

      tl.from(descRef.current, { y: 30, opacity: 0, duration: 0.8 }, '-=0.5');
      tl.from(ctaRef.current?.children || [], { y: 20, opacity: 0, stagger: 0.15, duration: 0.6 }, '-=0.4');
    }, containerRef);

    return () => ctx.revert();
  }, []);

  return (
    <section ref={containerRef} className="relative min-h-screen flex items-center overflow-hidden">
      {/* 3D Background */}
      <Scene3D className="absolute inset-0 -z-10" />
      
      {/* Gradient overlay */}
      <div className="absolute inset-0 bg-gradient-to-b from-background/0 via-background/50 to-background -z-10" />

      <div className="container mx-auto px-4 py-32">
        <div className="max-w-4xl mx-auto text-center">
          <div className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-primary/10 text-primary text-sm font-medium mb-8">
            <span className="relative flex h-2 w-2">
              <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-primary opacity-75" />
              <span className="relative inline-flex rounded-full h-2 w-2 bg-primary" />
            </span>
            Now in public beta
          </div>

          <h1 ref={titleRef} className="text-5xl md:text-7xl font-bold tracking-tight mb-6 [perspective:1000px]">
            Build faster with AI-powered development
          </h1>

          <p ref={descRef} className="text-xl md:text-2xl text-muted-foreground max-w-2xl mx-auto mb-10">
            Ship production-ready features in minutes, not days. Our AI agents handle the complexity while you focus on what matters.
          </p>

          <div ref={ctaRef} className="flex flex-col sm:flex-row items-center justify-center gap-4">
            <Button size="lg" className="text-lg px-8 py-6 group">
              Get Started Free
              <ArrowRight className="ml-2 h-5 w-5 transition-transform group-hover:translate-x-1" />
            </Button>
            <Button size="lg" variant="outline" className="text-lg px-8 py-6 group">
              <Play className="mr-2 h-5 w-5" />
              Watch Demo
            </Button>
          </div>

          <p className="text-sm text-muted-foreground mt-6">
            No credit card required • Free tier available • Cancel anytime
          </p>
        </div>
      </div>

      {/* Scroll indicator */}
      <div className="absolute bottom-8 left-1/2 -translate-x-1/2 animate-bounce">
        <div className="w-6 h-10 border-2 border-muted-foreground/30 rounded-full flex justify-center pt-2">
          <div className="w-1.5 h-3 bg-muted-foreground/50 rounded-full animate-pulse" />
        </div>
      </div>
    </section>
  );
}
```

## Complete 3D Scene

```tsx
// src/components/3d/hero-scene.tsx
'use client';

import { Suspense, useRef, useMemo } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import {
  Environment,
  Float,
  MeshDistortMaterial,
  MeshTransmissionMaterial,
  Sphere,
  Stars,
  Sparkles,
  ContactShadows,
  GradientTexture,
} from '@react-three/drei';
import { EffectComposer, Bloom, ChromaticAberration, Vignette, Noise, SMAA } from '@react-three/postprocessing';
import { BlendFunction } from 'postprocessing';
import * as THREE from 'three';
import { useTheme } from 'next-themes';

function GradientSphere({ position = [0, 0, 0], scale = 1 }: { position?: number[]; scale?: number }) {
  const mesh = useRef<THREE.Mesh>(null);
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';

  useFrame((state) => {
    if (!mesh.current) return;
    mesh.current.rotation.x = state.clock.elapsedTime * 0.1;
    mesh.current.rotation.y = state.clock.elapsedTime * 0.15;
  });

  return (
    <Float speed={2} rotationIntensity={0.5} floatIntensity={1}>
      <Sphere ref={mesh} args={[1, 128, 128]} position={position} scale={scale}>
        <MeshDistortMaterial distort={0.4} speed={2} roughness={0.2} metalness={0.8}>
          <GradientTexture
            stops={[0, 0.5, 1]}
            colors={isDark ? ['#3b82f6', '#8b5cf6', '#ec4899'] : ['#2563eb', '#7c3aed', '#db2777']}
          />
        </MeshDistortMaterial>
      </Sphere>
    </Float>
  );
}

function GlassSphere({ position = [0, 0, 0], scale = 1 }: { position?: number[]; scale?: number }) {
  const mesh = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    if (!mesh.current) return;
    mesh.current.rotation.y = state.clock.elapsedTime * 0.2;
  });

  return (
    <Float speed={1.5} rotationIntensity={0.3} floatIntensity={0.5}>
      <Sphere ref={mesh} args={[1, 64, 64]} position={position} scale={scale}>
        <MeshTransmissionMaterial
          backside
          samples={16}
          resolution={512}
          transmission={0.95}
          roughness={0.1}
          thickness={0.5}
          ior={1.5}
          chromaticAberration={0.06}
          distortion={0.1}
          distortionScale={0.2}
          color="#ffffff"
        />
      </Sphere>
    </Float>
  );
}

function ParticleField({ count = 500 }) {
  const points = useRef<THREE.Points>(null);

  const positions = useMemo(() => {
    const pos = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      pos[i * 3] = (Math.random() - 0.5) * 20;
      pos[i * 3 + 1] = (Math.random() - 0.5) * 20;
      pos[i * 3 + 2] = (Math.random() - 0.5) * 20;
    }
    return pos;
  }, [count]);

  useFrame((state) => {
    if (!points.current) return;
    points.current.rotation.y = state.clock.elapsedTime * 0.02;
    points.current.rotation.x = state.clock.elapsedTime * 0.01;
  });

  return (
    <points ref={points}>
      <bufferGeometry>
        <bufferAttribute attach="attributes-position" count={count} array={positions} itemSize={3} />
      </bufferGeometry>
      <pointsMaterial size={0.02} color="#ffffff" transparent opacity={0.6} sizeAttenuation />
    </points>
  );
}

function CursorFollower() {
  const mesh = useRef<THREE.Mesh>(null);
  const { viewport, pointer } = useThree();

  useFrame(() => {
    if (!mesh.current) return;
    const x = (pointer.x * viewport.width) / 2;
    const y = (pointer.y * viewport.height) / 2;
    mesh.current.position.x = THREE.MathUtils.lerp(mesh.current.position.x, x, 0.1);
    mesh.current.position.y = THREE.MathUtils.lerp(mesh.current.position.y, y, 0.1);
  });

  return (
    <Sphere ref={mesh} args={[0.15, 32, 32]} position={[0, 0, 2]}>
      <meshStandardMaterial color="#3b82f6" emissive="#3b82f6" emissiveIntensity={0.5} transparent opacity={0.8} />
    </Sphere>
  );
}

function Effects() {
  return (
    <EffectComposer multisampling={0}>
      <SMAA />
      <Bloom luminanceThreshold={0.5} luminanceSmoothing={0.9} intensity={0.5} mipmapBlur />
      <ChromaticAberration blendFunction={BlendFunction.NORMAL} offset={new THREE.Vector2(0.001, 0.001)} />
      <Vignette offset={0.3} darkness={0.5} />
      <Noise opacity={0.02} blendFunction={BlendFunction.SOFT_LIGHT} />
    </EffectComposer>
  );
}

function Scene() {
  return (
    <>
      <ambientLight intensity={0.4} />
      <directionalLight position={[10, 10, 5]} intensity={1} />
      <pointLight position={[-10, -10, -5]} intensity={0.5} color="#8b5cf6" />
      <Environment preset="city" />

      <GradientSphere position={[0, 0, 0]} scale={2} />
      <GlassSphere position={[3, 1, -2]} scale={0.8} />
      <GlassSphere position={[-3, -1, -1]} scale={0.6} />
      
      <ParticleField count={300} />
      <Sparkles count={100} scale={10} size={2} speed={0.5} color="#ffffff" />
      <Stars radius={50} depth={50} count={1000} factor={4} />
      
      <CursorFollower />
      
      <ContactShadows position={[0, -2, 0]} opacity={0.4} scale={10} blur={2} far={4} />
      
      <Effects />
    </>
  );
}

export default function HeroScene({ className }: { className?: string }) {
  return (
    <div className={className}>
      <Canvas
        gl={{ antialias: true, alpha: true, powerPreference: 'high-performance' }}
        dpr={[1, 2]}
        camera={{ position: [0, 0, 5], fov: 45 }}
        style={{ position: 'absolute', inset: 0 }}
      >
        <Suspense fallback={null}>
          <Scene />
        </Suspense>
      </Canvas>
    </div>
  );
}
```

## Zustand Store (Complete)

```tsx
// src/stores/index.ts
import { create } from 'zustand';
import { devtools, persist, subscribeWithSelector } from 'zustand/middleware';
import { immer } from 'zustand/middleware/immer';

// User Store
interface User {
  id: string;
  email: string;
  name: string;
  avatar?: string;
  role: 'user' | 'admin';
  preferences: { theme: 'light' | 'dark' | 'system'; notifications: boolean };
}

interface UserState {
  user: User | null;
  isAuthenticated: boolean;
  isLoading: boolean;
  setUser: (user: User) => void;
  updateUser: (updates: Partial<User>) => void;
  logout: () => void;
}

export const useUserStore = create<UserState>()(
  devtools(
    persist(
      immer((set) => ({
        user: null,
        isAuthenticated: false,
        isLoading: false,
        setUser: (user) => set((s) => { s.user = user; s.isAuthenticated = true; }),
        updateUser: (updates) => set((s) => { if (s.user) Object.assign(s.user, updates); }),
        logout: () => set((s) => { s.user = null; s.isAuthenticated = false; }),
      })),
      { name: 'user-storage', partialize: (s) => ({ user: s.user }) }
    ),
    { name: 'UserStore' }
  )
);

// UI Store
interface UIState {
  sidebarOpen: boolean;
  commandPaletteOpen: boolean;
  toasts: Array<{ id: string; type: 'success' | 'error' | 'warning' | 'info'; message: string }>;
  toggleSidebar: () => void;
  toggleCommandPalette: () => void;
  addToast: (toast: Omit<UIState['toasts'][0], 'id'>) => void;
  removeToast: (id: string) => void;
}

export const useUIStore = create<UIState>()(
  devtools(
    immer((set) => ({
      sidebarOpen: true,
      commandPaletteOpen: false,
      toasts: [],
      toggleSidebar: () => set((s) => { s.sidebarOpen = !s.sidebarOpen; }),
      toggleCommandPalette: () => set((s) => { s.commandPaletteOpen = !s.commandPaletteOpen; }),
      addToast: (toast) => set((s) => { s.toasts.push({ ...toast, id: `toast-${Date.now()}` }); }),
      removeToast: (id) => set((s) => { s.toasts = s.toasts.filter((t) => t.id !== id); }),
    })),
    { name: 'UIStore' }
  )
);
```

## API Client Hooks

```tsx
// src/hooks/use-api.ts
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';

const API_URL = process.env.NEXT_PUBLIC_API_URL || '/api';

async function fetchAPI<T>(endpoint: string, options?: RequestInit): Promise<T> {
  const res = await fetch(`${API_URL}${endpoint}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...options?.headers,
    },
    credentials: 'include',
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ message: 'An error occurred' }));
    throw new Error(error.message || 'Request failed');
  }

  return res.json();
}

// Generic CRUD hooks
export function useList<T>(key: string, endpoint: string) {
  return useQuery<{ data: T[]; meta: { total: number } }>({
    queryKey: [key],
    queryFn: () => fetchAPI(endpoint),
  });
}

export function useGet<T>(key: string, endpoint: string, id: string) {
  return useQuery<{ data: T }>({
    queryKey: [key, id],
    queryFn: () => fetchAPI(`${endpoint}/${id}`),
    enabled: !!id,
  });
}

export function useCreate<T, D>(key: string, endpoint: string) {
  const queryClient = useQueryClient();
  return useMutation<{ data: T }, Error, D>({
    mutationFn: (data) => fetchAPI(endpoint, { method: 'POST', body: JSON.stringify(data) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [key] }),
  });
}

export function useUpdate<T, D>(key: string, endpoint: string) {
  const queryClient = useQueryClient();
  return useMutation<{ data: T }, Error, { id: string; data: D }>({
    mutationFn: ({ id, data }) => fetchAPI(`${endpoint}/${id}`, { method: 'PATCH', body: JSON.stringify(data) }),
    onSuccess: (_, { id }) => {
      queryClient.invalidateQueries({ queryKey: [key] });
      queryClient.invalidateQueries({ queryKey: [key, id] });
    },
  });
}

export function useDelete(key: string, endpoint: string) {
  const queryClient = useQueryClient();
  return useMutation<void, Error, string>({
    mutationFn: (id) => fetchAPI(`${endpoint}/${id}`, { method: 'DELETE' }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: [key] }),
  });
}
```

## Global CSS

```css
/* src/styles/globals.css */
@tailwind base;
@tailwind components;
@tailwind utilities;

@layer base {
  :root {
    --background: 0 0% 100%;
    --foreground: 222.2 84% 4.9%;
    --card: 0 0% 100%;
    --card-foreground: 222.2 84% 4.9%;
    --popover: 0 0% 100%;
    --popover-foreground: 222.2 84% 4.9%;
    --primary: 221.2 83.2% 53.3%;
    --primary-foreground: 210 40% 98%;
    --secondary: 210 40% 96.1%;
    --secondary-foreground: 222.2 47.4% 11.2%;
    --muted: 210 40% 96.1%;
    --muted-foreground: 215.4 16.3% 46.9%;
    --accent: 210 40% 96.1%;
    --accent-foreground: 222.2 47.4% 11.2%;
    --destructive: 0 84.2% 60.2%;
    --destructive-foreground: 210 40% 98%;
    --border: 214.3 31.8% 91.4%;
    --input: 214.3 31.8% 91.4%;
    --ring: 221.2 83.2% 53.3%;
    --radius: 0.5rem;
  }

  .dark {
    --background: 222.2 84% 4.9%;
    --foreground: 210 40% 98%;
    --card: 222.2 84% 4.9%;
    --card-foreground: 210 40% 98%;
    --popover: 222.2 84% 4.9%;
    --popover-foreground: 210 40% 98%;
    --primary: 217.2 91.2% 59.8%;
    --primary-foreground: 222.2 47.4% 11.2%;
    --secondary: 217.2 32.6% 17.5%;
    --secondary-foreground: 210 40% 98%;
    --muted: 217.2 32.6% 17.5%;
    --muted-foreground: 215 20.2% 65.1%;
    --accent: 217.2 32.6% 17.5%;
    --accent-foreground: 210 40% 98%;
    --destructive: 0 62.8% 30.6%;
    --destructive-foreground: 210 40% 98%;
    --border: 217.2 32.6% 17.5%;
    --input: 217.2 32.6% 17.5%;
    --ring: 224.3 76.3% 48%;
  }
}

@layer base {
  * {
    @apply border-border;
  }
  body {
    @apply bg-background text-foreground;
  }
}

/* Smooth scrolling with Lenis */
html.lenis, html.lenis body {
  height: auto;
}

.lenis.lenis-smooth {
  scroll-behavior: auto !important;
}

.lenis.lenis-smooth [data-lenis-prevent] {
  overscroll-behavior: contain;
}

.lenis.lenis-stopped {
  overflow: hidden;
}

/* Selection */
::selection {
  @apply bg-primary/20 text-primary;
}

/* Focus ring */
*:focus-visible {
  @apply outline-none ring-2 ring-ring ring-offset-2 ring-offset-background;
}

/* Scrollbar */
::-webkit-scrollbar {
  @apply w-2 h-2;
}

::-webkit-scrollbar-track {
  @apply bg-transparent;
}

::-webkit-scrollbar-thumb {
  @apply bg-muted-foreground/20 rounded-full;
}

::-webkit-scrollbar-thumb:hover {
  @apply bg-muted-foreground/30;
}
```

This skill provides a complete Next.js 14 application structure with 3D graphics, animations, state management, and all the patterns needed for production.
