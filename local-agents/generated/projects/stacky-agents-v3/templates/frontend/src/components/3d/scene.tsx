'use client';

import { Suspense, useRef, useMemo, useEffect } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import {
  Environment,
  Float,
  MeshDistortMaterial,
  MeshWobbleMaterial,
  MeshTransmissionMaterial,
  Sphere,
  Box,
  Torus,
  TorusKnot,
  OrbitControls,
  PerspectiveCamera,
  Stars,
  Sparkles,
  Trail,
  useTexture,
  GradientTexture,
  ContactShadows,
  Lightformer,
  Html,
  useProgress,
} from '@react-three/drei';
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
import { useTheme } from 'next-themes';
import gsap from 'gsap';

// Types
interface SceneProps {
  variant?: 'hero' | 'product' | 'abstract' | 'minimal' | 'interactive';
  intensity?: number;
  className?: string;
}

interface AnimatedMeshProps {
  position?: [number, number, number];
  scale?: number;
  color?: string;
  speed?: number;
}

// Loading component
function Loader() {
  const { progress } = useProgress();
  return (
    <Html center>
      <div className="flex flex-col items-center gap-2">
        <div className="h-1 w-32 overflow-hidden rounded-full bg-white/20">
          <div
            className="h-full bg-white transition-all duration-300"
            style={{ width: `${progress}%` }}
          />
        </div>
        <span className="text-xs text-white/60">{progress.toFixed(0)}%</span>
      </div>
    </Html>
  );
}

// Animated gradient sphere with distortion
function GradientSphere({ position = [0, 0, 0], scale = 1, speed = 1 }: AnimatedMeshProps) {
  const meshRef = useRef<THREE.Mesh>(null);
  const { resolvedTheme } = useTheme();
  const isDark = resolvedTheme === 'dark';

  useFrame((state) => {
    if (!meshRef.current) return;
    meshRef.current.rotation.x = state.clock.elapsedTime * 0.1 * speed;
    meshRef.current.rotation.y = state.clock.elapsedTime * 0.15 * speed;
  });

  return (
    <Float speed={2} rotationIntensity={0.5} floatIntensity={1}>
      <Sphere ref={meshRef} args={[1, 128, 128]} position={position} scale={scale}>
        <MeshDistortMaterial
          color={isDark ? '#3b82f6' : '#2563eb'}
          distort={0.4}
          speed={2}
          roughness={0.2}
          metalness={0.8}
        >
          <GradientTexture
            stops={[0, 0.5, 1]}
            colors={isDark 
              ? ['#3b82f6', '#8b5cf6', '#ec4899']
              : ['#2563eb', '#7c3aed', '#db2777']
            }
          />
        </MeshDistortMaterial>
      </Sphere>
    </Float>
  );
}

// Glass morphism sphere
function GlassSphere({ position = [0, 0, 0], scale = 1 }: AnimatedMeshProps) {
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

// Animated torus knot with trail
function AnimatedTorusKnot({ position = [0, 0, 0], color = '#8b5cf6' }: AnimatedMeshProps) {
  const meshRef = useRef<THREE.Mesh>(null);

  useFrame((state) => {
    if (!meshRef.current) return;
    meshRef.current.rotation.x = state.clock.elapsedTime * 0.5;
    meshRef.current.rotation.y = state.clock.elapsedTime * 0.3;
  });

  return (
    <Trail
      width={0.5}
      length={6}
      color={new THREE.Color(color)}
      attenuation={(t) => t * t}
    >
      <Float speed={2} rotationIntensity={1} floatIntensity={2}>
        <TorusKnot ref={meshRef} args={[0.6, 0.2, 128, 32]} position={position}>
          <meshStandardMaterial
            color={color}
            emissive={color}
            emissiveIntensity={0.5}
            roughness={0.3}
            metalness={0.8}
          />
        </TorusKnot>
      </Float>
    </Trail>
  );
}

// Floating cubes with wobble
function FloatingCubes({ count = 20 }: { count?: number }) {
  const cubes = useMemo(() => {
    return Array.from({ length: count }, (_, i) => ({
      position: [
        (Math.random() - 0.5) * 10,
        (Math.random() - 0.5) * 10,
        (Math.random() - 0.5) * 10,
      ] as [number, number, number],
      scale: Math.random() * 0.3 + 0.1,
      speed: Math.random() * 0.5 + 0.2,
      color: ['#3b82f6', '#8b5cf6', '#ec4899', '#10b981'][Math.floor(Math.random() * 4)],
    }));
  }, [count]);

  return (
    <>
      {cubes.map((cube, i) => (
        <Float key={i} speed={cube.speed} rotationIntensity={0.5} floatIntensity={1}>
          <Box args={[1, 1, 1]} position={cube.position} scale={cube.scale}>
            <MeshWobbleMaterial
              color={cube.color}
              factor={0.5}
              speed={1}
              roughness={0.4}
              metalness={0.6}
            />
          </Box>
        </Float>
      ))}
    </>
  );
}

// Particle field
function ParticleField({ count = 500, color = '#ffffff' }: { count?: number; color?: string }) {
  const points = useMemo(() => {
    const positions = new Float32Array(count * 3);
    for (let i = 0; i < count; i++) {
      positions[i * 3] = (Math.random() - 0.5) * 20;
      positions[i * 3 + 1] = (Math.random() - 0.5) * 20;
      positions[i * 3 + 2] = (Math.random() - 0.5) * 20;
    }
    return positions;
  }, [count]);

  const pointsRef = useRef<THREE.Points>(null);

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
          array={points}
          itemSize={3}
        />
      </bufferGeometry>
      <pointsMaterial
        size={0.02}
        color={color}
        transparent
        opacity={0.6}
        sizeAttenuation
      />
    </points>
  );
}

// Interactive cursor follower
function CursorFollower() {
  const meshRef = useRef<THREE.Mesh>(null);
  const { viewport, mouse } = useThree();

  useFrame(() => {
    if (!meshRef.current) return;
    const x = (mouse.x * viewport.width) / 2;
    const y = (mouse.y * viewport.height) / 2;
    
    meshRef.current.position.x = THREE.MathUtils.lerp(meshRef.current.position.x, x, 0.1);
    meshRef.current.position.y = THREE.MathUtils.lerp(meshRef.current.position.y, y, 0.1);
  });

  return (
    <Sphere ref={meshRef} args={[0.2, 32, 32]} position={[0, 0, 2]}>
      <meshStandardMaterial
        color="#3b82f6"
        emissive="#3b82f6"
        emissiveIntensity={0.5}
        transparent
        opacity={0.8}
      />
    </Sphere>
  );
}

// Post-processing effects
function Effects() {
  return (
    <EffectComposer multisampling={0}>
      <SMAA />
      <Bloom
        luminanceThreshold={0.5}
        luminanceSmoothing={0.9}
        intensity={0.5}
        mipmapBlur
      />
      <ChromaticAberration
        blendFunction={BlendFunction.NORMAL}
        offset={new THREE.Vector2(0.001, 0.001)}
      />
      <Vignette offset={0.3} darkness={0.5} />
      <Noise opacity={0.02} blendFunction={BlendFunction.SOFT_LIGHT} />
    </EffectComposer>
  );
}

// Scene variants
function HeroScene() {
  return (
    <>
      <GradientSphere position={[0, 0, 0]} scale={2} />
      <Sparkles count={100} scale={10} size={2} speed={0.5} color="#ffffff" />
      <ParticleField count={300} />
    </>
  );
}

function ProductScene() {
  return (
    <>
      <GlassSphere position={[0, 0, 0]} scale={1.5} />
      <ContactShadows
        position={[0, -1.5, 0]}
        opacity={0.4}
        scale={10}
        blur={2}
        far={4}
      />
      <Environment preset="studio" />
    </>
  );
}

function AbstractScene() {
  return (
    <>
      <AnimatedTorusKnot position={[0, 0, 0]} color="#8b5cf6" />
      <FloatingCubes count={15} />
      <Stars radius={50} depth={50} count={1000} factor={4} />
    </>
  );
}

function MinimalScene() {
  return (
    <>
      <ParticleField count={1000} color="#3b82f6" />
      <Stars radius={100} depth={50} count={2000} factor={2} fade />
    </>
  );
}

function InteractiveScene() {
  return (
    <>
      <CursorFollower />
      <GradientSphere position={[0, 0, -2]} scale={1.5} speed={0.5} />
      <FloatingCubes count={10} />
      <Sparkles count={50} scale={8} size={3} speed={0.3} color="#3b82f6" />
    </>
  );
}

// Main Scene component
export function Scene3D({ variant = 'hero', intensity = 1, className }: SceneProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  // GSAP scroll-based effects
  useEffect(() => {
    if (!containerRef.current) return;

    const ctx = gsap.context(() => {
      gsap.to(containerRef.current, {
        scrollTrigger: {
          trigger: containerRef.current,
          start: 'top top',
          end: 'bottom top',
          scrub: true,
        },
        opacity: 0.3,
        scale: 1.1,
      });
    }, containerRef);

    return () => ctx.revert();
  }, []);

  return (
    <div 
      ref={containerRef}
      className={`absolute inset-0 -z-10 ${className}`}
      style={{ opacity: intensity }}
    >
      <Canvas
        gl={{ 
          antialias: true, 
          alpha: true,
          powerPreference: 'high-performance',
          stencil: false,
          depth: true,
        }}
        dpr={[1, 2]}
        camera={{ position: [0, 0, 5], fov: 45 }}
        performance={{ min: 0.5 }}
      >
        <Suspense fallback={<Loader />}>
          {/* Lighting */}
          <ambientLight intensity={0.4} />
          <directionalLight position={[10, 10, 5]} intensity={1} />
          <pointLight position={[-10, -10, -5]} intensity={0.5} color="#8b5cf6" />
          
          {/* Environment */}
          <Environment preset="city" />
          
          {/* Scene content based on variant */}
          {variant === 'hero' && <HeroScene />}
          {variant === 'product' && <ProductScene />}
          {variant === 'abstract' && <AbstractScene />}
          {variant === 'minimal' && <MinimalScene />}
          {variant === 'interactive' && <InteractiveScene />}
          
          {/* Post-processing */}
          <Effects />
          
          {/* Controls (disabled for production, enable for debugging) */}
          {process.env.NODE_ENV === 'development' && (
            <OrbitControls enableZoom={false} enablePan={false} />
          )}
        </Suspense>
      </Canvas>
    </div>
  );
}

// Preload assets
export function Scene3DPreloader() {
  return null; // Add texture preloading here if needed
}

export default Scene3D;
