'use client';

import { useRef, useEffect, type ReactNode, type CSSProperties } from 'react';
import gsap from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';
import { TextPlugin } from 'gsap/TextPlugin';
import { SplitText } from 'gsap/SplitText';

// Register GSAP plugins
if (typeof window !== 'undefined') {
  gsap.registerPlugin(ScrollTrigger, TextPlugin);
  // Note: SplitText requires GSAP Club membership
  // For free alternative, use custom text splitting below
}

// Types
interface AnimationProps {
  children: ReactNode;
  className?: string;
  style?: CSSProperties;
  delay?: number;
  duration?: number;
  ease?: string;
  once?: boolean;
  threshold?: number;
}

interface ScrollTriggerConfig {
  trigger?: string | Element;
  start?: string;
  end?: string;
  scrub?: boolean | number;
  pin?: boolean;
  markers?: boolean;
}

// Hook for scroll-based Lenis integration
function useSmoothScroll() {
  useEffect(() => {
    // Sync ScrollTrigger with Lenis
    const lenis = (window as unknown as { lenis?: { on: (event: string, callback: () => void) => void } }).lenis;
    
    if (lenis) {
      lenis.on('scroll', ScrollTrigger.update);
    }

    gsap.ticker.add((time) => {
      lenis?.raf?.(time * 1000);
    });

    gsap.ticker.lagSmoothing(0);

    return () => {
      ScrollTrigger.getAll().forEach((trigger) => trigger.kill());
    };
  }, []);
}

// ============ FADE ANIMATIONS ============

export function FadeIn({
  children,
  className,
  delay = 0,
  duration = 0.8,
  ease = 'power3.out',
  once = true,
  threshold = 0.2,
}: AnimationProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;

    const ctx = gsap.context(() => {
      gsap.fromTo(
        ref.current,
        { opacity: 0, y: 40 },
        {
          opacity: 1,
          y: 0,
          duration,
          delay,
          ease,
          scrollTrigger: {
            trigger: ref.current,
            start: `top ${100 - threshold * 100}%`,
            toggleActions: once ? 'play none none none' : 'play reverse play reverse',
          },
        }
      );
    }, ref);

    return () => ctx.revert();
  }, [delay, duration, ease, once, threshold]);

  return (
    <div ref={ref} className={className} style={{ opacity: 0 }}>
      {children}
    </div>
  );
}

export function FadeInScale({
  children,
  className,
  delay = 0,
  duration = 0.8,
}: AnimationProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;

    const ctx = gsap.context(() => {
      gsap.fromTo(
        ref.current,
        { opacity: 0, scale: 0.9 },
        {
          opacity: 1,
          scale: 1,
          duration,
          delay,
          ease: 'back.out(1.7)',
          scrollTrigger: {
            trigger: ref.current,
            start: 'top 85%',
          },
        }
      );
    }, ref);

    return () => ctx.revert();
  }, [delay, duration]);

  return (
    <div ref={ref} className={className} style={{ opacity: 0 }}>
      {children}
    </div>
  );
}

// ============ STAGGER ANIMATIONS ============

interface StaggerProps extends AnimationProps {
  staggerAmount?: number;
  childSelector?: string;
}

export function StaggerChildren({
  children,
  className,
  staggerAmount = 0.1,
  delay = 0,
  duration = 0.6,
  childSelector = ':scope > *',
}: StaggerProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;

    const ctx = gsap.context(() => {
      const elements = ref.current!.querySelectorAll(childSelector);

      gsap.fromTo(
        elements,
        { opacity: 0, y: 30 },
        {
          opacity: 1,
          y: 0,
          duration,
          delay,
          stagger: staggerAmount,
          ease: 'power3.out',
          scrollTrigger: {
            trigger: ref.current,
            start: 'top 80%',
          },
        }
      );
    }, ref);

    return () => ctx.revert();
  }, [childSelector, delay, duration, staggerAmount]);

  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}

export function StaggerGrid({
  children,
  className,
  staggerAmount = 0.05,
}: StaggerProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;

    const ctx = gsap.context(() => {
      const elements = ref.current!.children;

      gsap.fromTo(
        elements,
        { opacity: 0, y: 40, scale: 0.95 },
        {
          opacity: 1,
          y: 0,
          scale: 1,
          duration: 0.6,
          stagger: {
            amount: staggerAmount * elements.length,
            grid: 'auto',
            from: 'start',
          },
          ease: 'power3.out',
          scrollTrigger: {
            trigger: ref.current,
            start: 'top 85%',
          },
        }
      );
    }, ref);

    return () => ctx.revert();
  }, [staggerAmount]);

  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}

// ============ TEXT ANIMATIONS ============

interface TextRevealProps extends AnimationProps {
  text: string;
  tag?: 'h1' | 'h2' | 'h3' | 'h4' | 'p' | 'span';
}

export function TextReveal({
  text,
  tag: Tag = 'h1',
  className,
  delay = 0,
  duration = 1,
}: TextRevealProps) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!ref.current) return;

    const ctx = gsap.context(() => {
      // Split text into characters
      const chars = text.split('');
      ref.current!.innerHTML = chars
        .map((char) => `<span class="inline-block">${char === ' ' ? '&nbsp;' : char}</span>`)
        .join('');

      const charElements = ref.current!.querySelectorAll('span');

      gsap.fromTo(
        charElements,
        { opacity: 0, y: 50, rotateX: -90 },
        {
          opacity: 1,
          y: 0,
          rotateX: 0,
          duration,
          delay,
          stagger: 0.02,
          ease: 'back.out(1.7)',
          scrollTrigger: {
            trigger: ref.current,
            start: 'top 85%',
          },
        }
      );
    }, ref);

    return () => ctx.revert();
  }, [text, delay, duration]);

  return <Tag ref={ref as unknown as React.RefObject<HTMLHeadingElement>} className={className} />;
}

export function TypeWriter({
  text,
  tag: Tag = 'p',
  className,
  delay = 0,
  duration = 2,
}: TextRevealProps) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!ref.current) return;

    const ctx = gsap.context(() => {
      gsap.fromTo(
        ref.current,
        { text: '' },
        {
          text,
          duration,
          delay,
          ease: 'none',
          scrollTrigger: {
            trigger: ref.current,
            start: 'top 85%',
          },
        }
      );
    }, ref);

    return () => ctx.revert();
  }, [text, delay, duration]);

  return <Tag ref={ref as unknown as React.RefObject<HTMLParagraphElement>} className={className} />;
}

export function WordReveal({
  text,
  tag: Tag = 'p',
  className,
  delay = 0,
}: TextRevealProps) {
  const ref = useRef<HTMLElement>(null);

  useEffect(() => {
    if (!ref.current) return;

    const ctx = gsap.context(() => {
      const words = text.split(' ');
      ref.current!.innerHTML = words
        .map((word) => `<span class="inline-block overflow-hidden"><span class="inline-block">${word}</span></span>`)
        .join(' ');

      const wordElements = ref.current!.querySelectorAll('span > span');

      gsap.fromTo(
        wordElements,
        { y: '100%' },
        {
          y: '0%',
          duration: 0.5,
          delay,
          stagger: 0.05,
          ease: 'power3.out',
          scrollTrigger: {
            trigger: ref.current,
            start: 'top 85%',
          },
        }
      );
    }, ref);

    return () => ctx.revert();
  }, [text, delay]);

  return <Tag ref={ref as unknown as React.RefObject<HTMLParagraphElement>} className={className} />;
}

// ============ SCROLL ANIMATIONS ============

interface PinSectionProps extends AnimationProps {
  pinDuration?: number;
}

export function PinSection({
  children,
  className,
  pinDuration = 1,
}: PinSectionProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;

    const ctx = gsap.context(() => {
      ScrollTrigger.create({
        trigger: ref.current,
        start: 'top top',
        end: `+=${window.innerHeight * pinDuration}`,
        pin: true,
        pinSpacing: true,
      });
    }, ref);

    return () => ctx.revert();
  }, [pinDuration]);

  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}

interface ParallaxProps extends AnimationProps {
  speed?: number;
  direction?: 'up' | 'down';
}

export function Parallax({
  children,
  className,
  speed = 0.5,
  direction = 'up',
}: ParallaxProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;

    const yPercent = direction === 'up' ? -100 * speed : 100 * speed;

    const ctx = gsap.context(() => {
      gsap.to(ref.current, {
        yPercent,
        ease: 'none',
        scrollTrigger: {
          trigger: ref.current,
          start: 'top bottom',
          end: 'bottom top',
          scrub: true,
        },
      });
    }, ref);

    return () => ctx.revert();
  }, [speed, direction]);

  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}

export function HorizontalScroll({
  children,
  className,
}: AnimationProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const wrapperRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current || !wrapperRef.current) return;

    const ctx = gsap.context(() => {
      const sections = gsap.utils.toArray<HTMLElement>(wrapperRef.current!.children);
      const totalWidth = sections.reduce((acc, section) => acc + section.offsetWidth, 0);

      gsap.to(sections, {
        xPercent: -100 * (sections.length - 1),
        ease: 'none',
        scrollTrigger: {
          trigger: containerRef.current,
          pin: true,
          scrub: 1,
          snap: 1 / (sections.length - 1),
          end: () => `+=${totalWidth}`,
        },
      });
    }, containerRef);

    return () => ctx.revert();
  }, []);

  return (
    <div ref={containerRef} className={`overflow-hidden ${className}`}>
      <div ref={wrapperRef} className="flex">
        {children}
      </div>
    </div>
  );
}

// ============ INTERACTIVE ANIMATIONS ============

interface MagneticProps extends AnimationProps {
  strength?: number;
}

export function Magnetic({
  children,
  className,
  strength = 0.3,
}: MagneticProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;

    const element = ref.current;

    const handleMouseMove = (e: MouseEvent) => {
      const rect = element.getBoundingClientRect();
      const x = e.clientX - rect.left - rect.width / 2;
      const y = e.clientY - rect.top - rect.height / 2;

      gsap.to(element, {
        x: x * strength,
        y: y * strength,
        duration: 0.3,
        ease: 'power3.out',
      });
    };

    const handleMouseLeave = () => {
      gsap.to(element, {
        x: 0,
        y: 0,
        duration: 0.5,
        ease: 'elastic.out(1, 0.5)',
      });
    };

    element.addEventListener('mousemove', handleMouseMove);
    element.addEventListener('mouseleave', handleMouseLeave);

    return () => {
      element.removeEventListener('mousemove', handleMouseMove);
      element.removeEventListener('mouseleave', handleMouseLeave);
    };
  }, [strength]);

  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}

export function TiltCard({
  children,
  className,
}: AnimationProps) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;

    const element = ref.current;

    const handleMouseMove = (e: MouseEvent) => {
      const rect = element.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = (e.clientY - rect.top) / rect.height;

      const rotateX = (y - 0.5) * -20;
      const rotateY = (x - 0.5) * 20;

      gsap.to(element, {
        rotateX,
        rotateY,
        transformPerspective: 1000,
        duration: 0.3,
        ease: 'power3.out',
      });
    };

    const handleMouseLeave = () => {
      gsap.to(element, {
        rotateX: 0,
        rotateY: 0,
        duration: 0.5,
        ease: 'power3.out',
      });
    };

    element.addEventListener('mousemove', handleMouseMove);
    element.addEventListener('mouseleave', handleMouseLeave);

    return () => {
      element.removeEventListener('mousemove', handleMouseMove);
      element.removeEventListener('mouseleave', handleMouseLeave);
    };
  }, []);

  return (
    <div ref={ref} className={className} style={{ transformStyle: 'preserve-3d' }}>
      {children}
    </div>
  );
}

// ============ COUNTER ANIMATION ============

interface CounterProps extends AnimationProps {
  from?: number;
  to: number;
  prefix?: string;
  suffix?: string;
  decimals?: number;
}

export function Counter({
  from = 0,
  to,
  prefix = '',
  suffix = '',
  decimals = 0,
  className,
  duration = 2,
}: CounterProps) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    if (!ref.current) return;

    const ctx = gsap.context(() => {
      const obj = { value: from };

      gsap.to(obj, {
        value: to,
        duration,
        ease: 'power3.out',
        scrollTrigger: {
          trigger: ref.current,
          start: 'top 85%',
        },
        onUpdate: () => {
          if (ref.current) {
            ref.current.textContent = `${prefix}${obj.value.toFixed(decimals)}${suffix}`;
          }
        },
      });
    }, ref);

    return () => ctx.revert();
  }, [from, to, prefix, suffix, decimals, duration]);

  return <span ref={ref} className={className}>{prefix}{from}{suffix}</span>;
}

// ============ LINE DRAWING ANIMATION ============

export function DrawSVGLine({
  children,
  className,
  duration = 2,
}: AnimationProps) {
  const ref = useRef<SVGSVGElement>(null);

  useEffect(() => {
    if (!ref.current) return;

    const ctx = gsap.context(() => {
      const paths = ref.current!.querySelectorAll('path, line, polyline, circle, rect');

      paths.forEach((path) => {
        const length = (path as SVGGeometryElement).getTotalLength?.() || 0;
        gsap.set(path, {
          strokeDasharray: length,
          strokeDashoffset: length,
        });
      });

      gsap.to(paths, {
        strokeDashoffset: 0,
        duration,
        stagger: 0.2,
        ease: 'power3.inOut',
        scrollTrigger: {
          trigger: ref.current,
          start: 'top 80%',
        },
      });
    }, ref);

    return () => ctx.revert();
  }, [duration]);

  return (
    <svg ref={ref} className={className}>
      {children}
    </svg>
  );
}

// ============ REVEAL MASK ANIMATION ============

export function RevealMask({
  children,
  className,
  direction = 'up',
}: AnimationProps & { direction?: 'up' | 'down' | 'left' | 'right' }) {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!ref.current) return;

    const directions = {
      up: { y: '100%', clipPath: 'inset(100% 0 0 0)' },
      down: { y: '-100%', clipPath: 'inset(0 0 100% 0)' },
      left: { x: '100%', clipPath: 'inset(0 100% 0 0)' },
      right: { x: '-100%', clipPath: 'inset(0 0 0 100%)' },
    };

    const ctx = gsap.context(() => {
      gsap.fromTo(
        ref.current,
        { clipPath: directions[direction].clipPath },
        {
          clipPath: 'inset(0 0 0 0)',
          duration: 1,
          ease: 'power3.inOut',
          scrollTrigger: {
            trigger: ref.current,
            start: 'top 85%',
          },
        }
      );
    }, ref);

    return () => ctx.revert();
  }, [direction]);

  return (
    <div ref={ref} className={className}>
      {children}
    </div>
  );
}

// Export scroll hook
export { useSmoothScroll };
