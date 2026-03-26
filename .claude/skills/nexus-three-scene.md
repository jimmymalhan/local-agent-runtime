---
name: Three.js 3D Scene Builder
description: Build interactive 3D scenes with React Three Fiber, post-processing, and scroll animations
category: frontend
agents: [nexus-frontend]
triggers: [3d, three, scene, webgl, r3f, fiber, sphere, cube, animation, interactive]
tokenCost: 3500
dependencies: [frontend/react-component]
---

# Three.js 3D Scene Builder Skill

## Architecture

```
src/components/3d/
├── canvas-wrapper.tsx     # Canvas setup with Suspense
├── scenes/
│   ├── hero-scene.tsx     # Landing page hero
│   ├── product-scene.tsx  # Product showcase
│   └── abstract-scene.tsx # Background visuals
├── objects/
│   ├── gradient-sphere.tsx
│   ├── glass-material.tsx
│   └── particle-field.tsx
├── effects/
│   └── post-processing.tsx
└── hooks/
    ├── use-scroll-rig.ts
    └── use-mouse-position.ts
```

## Canvas Wrapper (Required)

```tsx
'use client';

import { Suspense, type ReactNode } from 'react';
import { Canvas } from '@react-three/fiber';
import { Preload } from '@react-three/drei';

interface CanvasWrapperProps {
  children: ReactNode;
  className?: string;
  camera?: {
    position?: [number, number, number];
    fov?: number;
  };
}

function Loader() {
  return (
    <div className="absolute inset-0 flex items-center justify-center bg-black/50">
      <div className="h-8 w-8 animate-spin rounded-full border-2 border-white border-t-transparent" />
    </div>
  );
}

export function CanvasWrapper({
  children,
  className = '',
  camera = { position: [0, 0, 5], fov: 45 },
}: CanvasWrapperProps) {
  return (
    <div className={`relative ${className}`}>
      <Suspense fallback={<Loader />}>
        <Canvas
          gl={{
            antialias: true,
            alpha: true,
            powerPreference: 'high-performance',
            stencil: false,
          }}
          dpr={[1, 2]} // Responsive pixel ratio
          camera={camera}
          style={{ position: 'absolute', inset: 0 }}
        >
          <Suspense fallback={null}>
            {children}
            <Preload all />
          </Suspense>
        </Canvas>
      </Suspense>
    </div>
  );
}
```

## Gradient Sphere with Distortion

```tsx
'use client';

import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Sphere, MeshDistortMaterial, GradientTexture, Float } from '@react-three/drei';
import * as THREE from 'three';

interface GradientSphereProps {
  position?: [number, number, number];
  scale?: number;
  colors?: [string, string, string];
  speed?: number;
  distort?: number;
}

export function GradientSphere({
  position = [0, 0, 0],
  scale = 1,
  colors = ['#3b82f6', '#8b5cf6', '#ec4899'],
  speed = 1,
  distort = 0.4,
}: GradientSphereProps) {
  const meshRef = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    if (!meshRef.current) return;
    meshRef.current.rotation.x = state.clock.elapsedTime * 0.1 * speed;
    meshRef.current.rotation.y = state.clock.elapsedTime * 0.15 * speed;
  });

  return (
    <Float speed={2} rotationIntensity={0.5} floatIntensity={1}>
      <Sphere ref={meshRef} args={[1, 128, 128]} position={position} scale={scale}>
        <MeshDistortMaterial
          distort={distort}
          speed={2}
          roughness={0.2}
          metalness={0.8}
        >
          <GradientTexture stops={[0, 0.5, 1]} colors={colors} />
        </MeshDistortMaterial>
      </Sphere>
    </Float>
  );
}
```

## Glass/Transmission Material

```tsx
'use client';

import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import { Sphere, MeshTransmissionMaterial, Float } from '@react-three/drei';
import * as THREE from 'three';

interface GlassSphereProps {
  position?: [number, number, number];
  scale?: number;
}

export function GlassSphere({ position = [0, 0, 0], scale = 1 }: GlassSphereProps) {
  const meshRef = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    if (!meshRef.current) return;
    meshRef.current.rotation.y = state.clock.elapsedTime * 0.2;
  });

  return (
    <Float speed={1.5} rotationIntensity={0.3} floatIntensity={0.5}>
      <Sphere ref={meshRef} args={[1, 64, 64]} position={position} scale={scale}>
        <MeshTransmissionMaterial
          backside
          samples={16}
          resolution={512}
          transmission={0.95}
          roughness={0.1}
          thickness={0.5}
          ior={1.5}
          chromaticAberration={0.06}
          anisotropy={0.1}
          distortion={0.1}
          distortionScale={0.2}
          temporalDistortion={0.1}
          clearcoat={1}
          attenuationDistance={0.5}
          attenuationColor="#ffffff"
          color="#ffffff"
        />
      </Sphere>
    </Float>
  );
}
```

## Particle Field Background

```tsx
'use client';

import { useRef, useMemo } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

interface ParticleFieldProps {
  count?: number;
  color?: string;
  size?: number;
  spread?: number;
}

export function ParticleField({
  count = 500,
  color = '#ffffff',
  size = 0.02,
  spread = 20,
}: ParticleFieldProps) {
  const pointsRef = useRef<THREE.Points>(null);

  const positions = useMemo(() => {
    const pos = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      pos[i * 3] = (Math.random() - 0.5) * spread;
      pos[i * 3 + 1] = (Math.random() - 0.5) * spread;
      pos[i * 3 + 2] = (Math.random() - 0.5) * spread;
    }
    return pos;
  }, [count, spread]);

  useFrame((state) => {
    if (!pointsRef.current) return;
    pointsRef.current.rotation.y = state.clock.elapsedTime * 0.02;
    pointsRef.current.rotation.x = state.clock.elapsedTime * 0.01;
  });

  return (
    <points ref={pointsRef}>
      <bufferGeometry>
        <bufferAttribute
          attach="attributes-position"
          count={count}
          array={positions}
          itemSize={3}
        />
      </bufferGeometry>
      <pointsMaterial
        size={size}
        color={color}
        transparent
        opacity={0.6}
        sizeAttenuation
      />
    </points>
  );
}
```

## Post-Processing Effects

```tsx
'use client';

import {
  EffectComposer,
  Bloom,
  ChromaticAberration,
  Vignette,
  Noise,
  SMAA,
} from '@react-three/postprocessing';
import { BlendFunction } from 'postprocessing';
import * as THREE from 'three';

interface EffectsProps {
  bloom?: boolean;
  chromatic?: boolean;
  vignette?: boolean;
  noise?: boolean;
}

export function PostEffects({
  bloom = true,
  chromatic = true,
  vignette = true,
  noise = true,
}: EffectsProps) {
  return (
    <EffectComposer multisampling={0}>
      <SMAA />
      {bloom && (
        <Bloom
          luminanceThreshold={0.5}
          luminanceSmoothing={0.9}
          intensity={0.5}
          mipmapBlur
        />
      )}
      {chromatic && (
        <ChromaticAberration
          blendFunction={BlendFunction.NORMAL}
          offset={new THREE.Vector2(0.001, 0.001)}
        />
      )}
      {vignette && <Vignette offset={0.3} darkness={0.5} />}
      {noise && <Noise opacity={0.02} blendFunction={BlendFunction.SOFT_LIGHT} />}
    </EffectComposer>
  );
}
```

## Scroll-Linked Animation Hook

```tsx
'use client';

import { useEffect, useRef } from 'react';
import { useThree, useFrame } from '@react-three/fiber';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

export function useScrollRig(
  callback: (progress: number) => void,
  options?: {
    start?: string;
    end?: string;
    scrub?: boolean | number;
  }
) {
  const progressRef = useRef(0);

  useEffect(() => {
    const trigger = ScrollTrigger.create({
      trigger: document.body,
      start: options?.start || 'top top',
      end: options?.end || 'bottom bottom',
      scrub: options?.scrub ?? true,
      onUpdate: (self) => {
        progressRef.current = self.progress;
      },
    });

    return () => trigger.kill();
  }, [options]);

  useFrame(() => {
    callback(progressRef.current);
  });

  return progressRef;
}

// Usage in component:
// useScrollRig((progress) => {
//   if (meshRef.current) {
//     meshRef.current.rotation.y = progress * Math.PI * 2;
//     meshRef.current.position.y = progress * 5 - 2.5;
//   }
// });
```

## Complete Hero Scene Example

```tsx
'use client';

import { Environment, ContactShadows } from '@react-three/drei';
import { CanvasWrapper } from './canvas-wrapper';
import { GradientSphere } from './objects/gradient-sphere';
import { ParticleField } from './objects/particle-field';
import { PostEffects } from './effects/post-processing';

export function HeroScene() {
  return (
    <CanvasWrapper className="h-screen w-full">
      {/* Lighting */}
      <ambientLight intensity={0.4} />
      <directionalLight position={[10, 10, 5]} intensity={1} />
      <pointLight position={[-10, -10, -5]} intensity={0.5} color="#8b5cf6" />

      {/* Environment for reflections */}
      <Environment preset="city" />

      {/* Objects */}
      <GradientSphere position={[0, 0, 0]} scale={2} />
      <ParticleField count={300} />

      {/* Shadow */}
      <ContactShadows
        position={[0, -2, 0]}
        opacity={0.4}
        scale={10}
        blur={2}
        far={4}
      />

      {/* Post-processing */}
      <PostEffects />
    </CanvasWrapper>
  );
}
```

## Performance Guidelines

1. **Geometry**: Use `args` for BufferGeometry, avoid creating in render
2. **Materials**: Reuse materials with `useMemo`
3. **Textures**: Compress and use appropriate resolution
4. **Shadows**: Use `ContactShadows` or baked shadows
5. **Post-processing**: Limit effects on mobile
6. **LOD**: Use Level of Detail for complex scenes
7. **Instances**: Use `InstancedMesh` for repeated objects

## Mobile Considerations

```tsx
import { useDetectGPU } from '@react-three/drei';

function AdaptiveScene() {
  const gpu = useDetectGPU();
  
  // Reduce quality on low-end devices
  const quality = gpu.tier < 2 ? 'low' : gpu.tier < 3 ? 'medium' : 'high';
  
  return (
    <Canvas dpr={quality === 'low' ? 1 : [1, 2]}>
      {quality !== 'low' && <PostEffects />}
      {/* ... */}
    </Canvas>
  );
}
```

## Current Context
- Date: {{today}}
- Git branch: {{git_branch}}
