"use client";

/**
 * Relative time that keeps moving.
 *
 * WHY IT TICKS
 * "updated 2 minutes ago" rendered once is a lie within a minute, and on a
 * screen somebody leaves open — which a corridor map is — it becomes a
 * confident lie. Re-rendering on a timer costs one render a minute and keeps
 * the claim true.
 *
 * It is also the honest kind of live motion: nothing moves for decoration,
 * the number moves because the fact it states has changed.
 */

import { useEffect, useState } from "react";

/** Coarse, because "1h ago" is as much precision as any of this deserves. */
export function ago(iso: string, now: number = Date.now()): string {
  const seconds = Math.max(0, Math.round((now - new Date(iso).getTime()) / 1000));
  if (seconds < 10) return "just now";
  if (seconds < 90) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

/**
 * Re-renders the caller every `ms`, and pauses while the tab is hidden.
 *
 * A background tab does not need to know what time it is, and browsers
 * throttle its timers unpredictably anyway; this resyncs on return rather
 * than trusting whatever the timer did while nobody was looking.
 */
export function useTicker(ms = 30_000): number {
  const [tick, setTick] = useState(0);

  useEffect(() => {
    let id: ReturnType<typeof setInterval> | null = null;

    const start = () => {
      if (id === null) id = setInterval(() => setTick((n) => n + 1), ms);
    };
    const stop = () => {
      if (id !== null) {
        clearInterval(id);
        id = null;
      }
    };
    const onVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        setTick((n) => n + 1); // catch up immediately on return
        start();
      }
    };

    if (!document.hidden) start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [ms]);

  return tick;
}
