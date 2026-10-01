"use client";

/**
 * Waiting, explained.
 *
 * WHY THIS EXISTS
 * Two of this app's waits are genuinely long, and neither is a bug:
 *
 *   the road GeoJSON   51,839 segments for Cachar, about 14 seconds
 *   a cold API         the free instance sleeps between visitors, and the
 *                      first request after a quiet spell takes most of a
 *                      minute while it wakes
 *
 * Every screen used to answer both with the words "Loading…" in grey. A
 * first-time visitor — which is nearly everyone who is ever sent the link —
 * therefore met a near-empty page for up to a minute with no sign that
 * anything was happening. The most likely conclusion is that the site is
 * broken, and it is reached by someone looking at a system that is working
 * perfectly.
 *
 * So: draw the shape of what is coming, count the seconds so the wait is
 * visibly progressing, and once it runs long, say why.
 *
 * HOW THE COLD START IS DETECTED
 * It is not, and cannot be from the browser -- there is no signal that
 * distinguishes "asleep" from "busy". It is inferred from elapsed time, and
 * the wording says "taking longer than usual" rather than asserting a cause
 * it cannot know. Honest about the uncertainty, useful either way.
 */

import { useEffect, useRef, useState } from "react";

import { useReducedMotion } from "@/components/chrome/ScrollEffects";

/** Past this, a wait stops being normal and deserves an explanation. */
const EXPLAIN_AFTER_S = 4;

/** True of almost every call here, and the reason a first visit feels slow. */
const COLD_START_NOTE =
  "Taking longer than usual. The API runs on a free instance that sleeps when " +
  "idle, so the first request after a quiet spell can take up to a minute.";

/** A block standing in for content that has not arrived. */
export function Skeleton({ className = "" }: { className?: string }) {
  return <div className={`skeleton ${className}`} aria-hidden="true" />;
}

/**
 * Seconds since `active` became true, or 0 when it is false.
 *
 * Ticks once a second rather than per frame: the number is for reassurance,
 * not precision, and a whole-second counter costs one render a second.
 */
export function useElapsed(active: boolean): number {
  const [seconds, setSeconds] = useState(0);
  const startedAt = useRef<number | null>(null);

  useEffect(() => {
    if (!active) {
      startedAt.current = null;
      setSeconds(0);
      return;
    }
    startedAt.current = Date.now();
    setSeconds(0);
    const id = setInterval(() => {
      if (startedAt.current !== null) {
        setSeconds(Math.floor((Date.now() - startedAt.current) / 1000));
      }
    }, 1000);
    return () => clearInterval(id);
  }, [active]);

  return seconds;
}

/**
 * What is being waited for, how long it has taken, and — once it is slow —
 * why that might be.
 *
 * `aria-live="polite"` so the explanation reaches a screen reader when it
 * appears, without interrupting whatever is being read.
 */
export function LoadingNote({
  active,
  what,
  slowNote = COLD_START_NOTE,
  className = "",
}: {
  active: boolean;
  /** What is being fetched, as a phrase: "Fetching road segments for Cachar". */
  what: string;
  /**
   * Why it might be slow, once it is. Defaults to the cold start, which is
   * the usual cause -- but a caller that knows better should say so rather
   * than let this assert a reason that does not apply to it.
   */
  slowNote?: string;
  className?: string;
}) {
  const seconds = useElapsed(active);
  const reduced = useReducedMotion();
  if (!active) return null;

  const slow = seconds >= EXPLAIN_AFTER_S;

  return (
    <div className={`text-caption text-muted ${className}`} aria-live="polite">
      <p className="flex items-center gap-2">
        {!reduced && (
          <span
            className="live-dot inline-block h-1.5 w-1.5 shrink-0 rounded-full bg-accent"
            aria-hidden="true"
          />
        )}
        <span>
          {what}
          {seconds > 0 && <span className="ml-1.5 font-mono text-micro">{seconds}s</span>}
        </span>
      </p>
      {slow && <p className="mt-1 text-micro">{slowNote}</p>}
    </div>
  );
}

/** A card-shaped placeholder: a heading line and a few rows of text. */
export function SkeletonCard({
  rows = 3,
  className = "",
}: {
  rows?: number;
  className?: string;
}) {
  return (
    <div className={`card p-5 ${className}`} aria-hidden="true">
      <Skeleton className="h-2.5 w-1/3" />
      <div className="mt-4 space-y-2">
        {Array.from({ length: rows }, (_, i) => (
          <Skeleton
            key={i}
            className="h-2"
            // Ragged edges read as text; equal bars read as a table.
            {...{ style: { width: `${92 - i * 11}%` } }}
          />
        ))}
      </div>
    </div>
  );
}
