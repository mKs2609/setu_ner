"use client";

/**
 * Scroll behaviour: a hero that drifts and zooms as you leave it, and
 * sections that arrive as you reach them.
 *
 * RULES THIS FOLLOWS
 *   - Everything is driven by transform and opacity only, inside a
 *     requestAnimationFrame, so scrolling never triggers layout.
 *   - Nothing moves for a viewer who asked for reduced motion: they get the
 *     final state immediately, not a slower animation.
 *   - Content is visible without JavaScript. Reveal starts at full opacity
 *     and is only hidden once the observer is attached, so a failed script
 *     leaves a readable page rather than an empty one.
 */

import { useEffect, useRef, useState } from "react";

const REDUCED = "(prefers-reduced-motion: reduce)";

/**
 * Subscribes to the motion preference rather than sampling it once.
 *
 * Sampling at mount was wrong twice over: a viewer who turns the setting on
 * later keeps the animations until they reload, and a browser that answers
 * the query before it has settled disables them permanently for that page
 * load -- which is exactly what happened in testing, with motion silently
 * dead on a page that had asked for it.
 */
function useReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);

  useEffect(() => {
    const query = window.matchMedia(REDUCED);
    const update = () => setReduced(query.matches);
    update();
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);

  return reduced;
}

/**
 * Full-bleed image that zooms slowly as the page scrolls past it, with the
 * text staying put. The zoom is capped: past the first viewport nothing
 * more happens, so a long page does not end up at 4x.
 */
export function ZoomImage({
  src,
  alt,
  children,
  className = "",
}: {
  src: string;
  alt: string;
  children?: React.ReactNode;
  className?: string;
}) {
  const imageRef = useRef<HTMLDivElement | null>(null);
  const frame = useRef<number | null>(null);
  const reduced = useReducedMotion();

  useEffect(() => {
    const node = imageRef.current;
    if (!node) return;
    if (reduced) {
      node.style.transform = "";
      node.style.opacity = "";
      return;
    }

    const onScroll = () => {
      if (frame.current !== null) return;
      frame.current = requestAnimationFrame(() => {
        frame.current = null;
        const y = window.scrollY;
        const progress = Math.min(1, y / (window.innerHeight || 1));
        // 1 -> 1.12 zoom, and a slight downward drift, so the land opens up
        // as the reader descends into the numbers.
        node.style.transform = `scale(${1 + progress * 0.12}) translate3d(0, ${progress * 24}px, 0)`;
        node.style.opacity = `${1 - progress * 0.45}`;
      });
    };

    onScroll();
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => {
      window.removeEventListener("scroll", onScroll);
      if (frame.current !== null) cancelAnimationFrame(frame.current);
    };
  }, [reduced]);

  return (
    <div className={`relative overflow-hidden ${className}`}>
      <div
        ref={imageRef}
        className="absolute inset-0 will-change-transform"
        style={{
          backgroundImage: `url(${src})`,
          backgroundSize: "cover",
          backgroundPosition: "center",
        }}
        role="img"
        aria-label={alt}
      />
      {/* Ink, not canvas: the page is light but the photograph is dark, and
          the text on it is white. Fading to the page colour would leave the
          last line of type white-on-white. */}
      <div className="absolute inset-0 bg-gradient-to-b from-ink/55 via-ink/35 to-ink/65" />
      <div className="relative">{children}</div>
    </div>
  );
}

/** Fades and lifts its children into place the first time they are reached. */
export function Reveal({
  children,
  delay = 0,
  className = "",
}: {
  children: React.ReactNode;
  delay?: number;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [shown, setShown] = useState(true);
  const reduced = useReducedMotion();

  useEffect(() => {
    const node = ref.current;
    if (!node || reduced) {
      setShown(true);
      return;
    }

    setShown(false); // only now: without JS the content stays visible
    const observer = new IntersectionObserver(
      ([entry]) => {
        if (entry.isIntersecting) {
          setShown(true);
          observer.disconnect();
        }
      },
      { rootMargin: "0px 0px -10% 0px", threshold: 0.05 },
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [reduced]);

  return (
    <div
      ref={ref}
      className={`transition-all duration-700 ease-out ${
        shown ? "translate-y-0 opacity-100" : "translate-y-4 opacity-0"
      } ${className}`}
      style={{ transitionDelay: `${delay}ms` }}
    >
      {children}
    </div>
  );
}

/** A number that counts up to its value the first time it is seen. */
export function CountUp({
  value,
  decimals = 0,
  suffix = "",
}: {
  value: number;
  decimals?: number;
  suffix?: string;
}) {
  const ref = useRef<HTMLSpanElement | null>(null);
  const [shown, setShown] = useState(value);
  const reduced = useReducedMotion();

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    if (reduced) {
      setShown(value);
      return;
    }

    let raf: number | null = null;
    const observer = new IntersectionObserver(([entry]) => {
      if (!entry.isIntersecting) return;
      observer.disconnect();
      const start = performance.now();
      const duration = 900;
      const step = (now: number) => {
        const t = Math.min(1, (now - start) / duration);
        // ease-out cubic: fast first, settling on the real number
        setShown(value * (1 - Math.pow(1 - t, 3)));
        if (t < 1) raf = requestAnimationFrame(step);
      };
      raf = requestAnimationFrame(step);
    });
    observer.observe(node);
    return () => {
      observer.disconnect();
      if (raf !== null) cancelAnimationFrame(raf);
    };
  }, [value, reduced]);

  return (
    <span ref={ref} className="tabular-nums">
      {shown.toLocaleString(undefined, {
        minimumFractionDigits: decimals,
        maximumFractionDigits: decimals,
      })}
      {suffix}
    </span>
  );
}
