"use client";

/**
 * What the system has actually been doing, newest first.
 *
 * WHY A RUN LOG AND NOT AN ACTIVITY FEED
 * Every line here is a row from `ingest_runs` -- a real attempt to fetch a
 * real source, with what came back. Nothing is invented to make the panel
 * look busy, and a failed run appears exactly as prominently as a successful
 * one. On a quiet day this list is short and boring, which is the correct
 * appearance of a quiet day.
 *
 * Rows arrive with a brief highlight so a new one is noticeable without the
 * list jumping; the highlight is suppressed under reduced-motion by the
 * animation's own media query in globals.css.
 */

import { useCallback, useEffect, useRef, useState } from "react";

import { fetchFreshness, type IngestRun } from "@/lib/api";

const REFRESH_MS = 60_000;
const SHOWN = 6;

const STATUS: Record<string, { label: string; tone: string }> = {
  success: { label: "ok", tone: "text-ok" },
  no_data: { label: "none published", tone: "text-muted" },
  running: { label: "running", tone: "text-accent" },
  failed: { label: "failed", tone: "text-alert" },
};

const SOURCE_LABEL: Record<string, string> = {
  nasa_gpm_imerg_late: "NASA rainfall",
};

function sourceLabel(run: IngestRun): string {
  const base = SOURCE_LABEL[run.source] ?? "ASDMA report";
  return run.hazard_type && !SOURCE_LABEL[run.source]
    ? `${base} · ${run.hazard_type}`
    : base;
}

function ago(iso: string): string {
  const seconds = Math.max(0, Math.round((Date.now() - new Date(iso).getTime()) / 1000));
  if (seconds < 90) return `${seconds}s ago`;
  const minutes = Math.round(seconds / 60);
  if (minutes < 90) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  if (hours < 36) return `${hours}h ago`;
  return `${Math.round(hours / 24)}d ago`;
}

export default function ActivityTicker() {
  const [runs, setRuns] = useState<IngestRun[] | null>(null);
  const [error, setError] = useState(false);
  const seen = useRef<Set<number>>(new Set());
  const [fresh, setFresh] = useState<Set<number>>(new Set());

  const load = useCallback(async () => {
    try {
      const data = await fetchFreshness();
      const latest = data.recent_runs.slice(0, SHOWN);
      // First load: everything is "already seen", so the list does not flash
      // six rows at once on arrival.
      const isFirst = seen.current.size === 0;
      const added = new Set<number>();
      for (const r of latest) {
        if (!isFirst && !seen.current.has(r.id)) added.add(r.id);
        seen.current.add(r.id);
      }
      setRuns(latest);
      setFresh(added);
      setError(false);
    } catch {
      setError(true);
    }
  }, []);

  useEffect(() => {
    load();
    const id = setInterval(() => {
      if (!document.hidden) load();
    }, REFRESH_MS);
    return () => clearInterval(id);
  }, [load]);

  if (error || !runs) return null;
  if (runs.length === 0) {
    return (
      <p className="font-mono text-micro text-muted">No ingestion runs recorded yet.</p>
    );
  }

  return (
    <div className="card p-5">
      <h3 className="font-mono text-micro uppercase tracking-[0.18em] text-muted">
        Ingestion log · live
      </h3>
      <ul className="mt-4 divide-y divide-line/70">
        {runs.map((run) => {
          const status = STATUS[run.status] ?? { label: run.status, tone: "text-muted" };
          return (
            <li
              key={run.id}
              className={`flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1 py-2.5 ${
                fresh.has(run.id) ? "flash-in" : ""
              }`}
            >
              <span className="text-ui">
                {sourceLabel(run)}
                {run.target_date && (
                  <span className="ml-2 font-mono text-micro text-muted">{run.target_date}</span>
                )}
              </span>
              <span className="flex items-baseline gap-3 font-mono text-micro">
                {run.rows_written > 0 && (
                  <span className="text-muted">+{run.rows_written} rows</span>
                )}
                <span className={status.tone}>{status.label}</span>
                <span className="text-muted">{ago(run.started_at)}</span>
              </span>
            </li>
          );
        })}
      </ul>
      <p className="mt-3 text-caption text-muted">
        Straight from the run log: each line is one attempt to fetch one source, including the
        ones that came back empty.
      </p>
    </div>
  );
}
