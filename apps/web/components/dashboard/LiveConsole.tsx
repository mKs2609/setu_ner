"use client";

/**
 * The live operations console.
 *
 * WHAT "LIVE" MEANS HERE, AND WHAT IT DOES NOT
 * The data behind this updates once a day, when the scheduled job ingests
 * the morning's report. So this polls to stay *current*, not to animate: it
 * refetches every 60s, and says plainly how old the underlying report is.
 * A dashboard that pulses convincingly over day-old data is a lie told with
 * CSS.
 *
 * POLLING IS POLITE
 * The API sleeps when idle on a free instance, and every request wakes it.
 * So the timer pauses while the tab is hidden and resumes (with an immediate
 * refetch) when it comes back. A background tab left open overnight should
 * not keep a server awake for nobody.
 */

import Link from "next/link";

import { CountUp } from "@/components/chrome/ScrollEffects";
import { useCallback, useEffect, useRef, useState } from "react";

import {
  fetchDistrictForecasts,
  fetchModelStatus,
  fetchReadiness,
  type DistrictForecasts,
  type ModelStatus,
  type Readiness,
} from "@/lib/api";

const REFRESH_MS = 60_000;

type Snapshot = {
  status: ModelStatus;
  forecasts: DistrictForecasts;
  readiness: Readiness;
  at: number;
};

/**
 * How far through the refresh interval we are, 0 to 1. Drives the thin bar
 * under the status strip so the page's own heartbeat is visible rather than
 * implied -- and so a stalled fetch is obvious, because the bar sits full.
 */
function useRefreshProgress(since: number | null, intervalMs: number): number {
  const [progress, setProgress] = useState(0);
  useEffect(() => {
    if (since === null) return;
    const tick = () => setProgress(Math.min(1, (Date.now() - since) / intervalMs));
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [since, intervalMs]);
  return progress;
}

function useRelativeTime(since: number | null): string {
  const [, tick] = useState(0);
  useEffect(() => {
    const id = setInterval(() => tick((n) => n + 1), 10_000);
    return () => clearInterval(id);
  }, []);
  if (since === null) return "—";
  const seconds = Math.round((Date.now() - since) / 1000);
  if (seconds < 15) return "just now";
  if (seconds < 90) return `${seconds}s ago`;
  return `${Math.round(seconds / 60)}m ago`;
}

function pct(p: number | null | undefined): string {
  return p == null ? "—" : `${(p * 100).toFixed(1)}%`;
}

/** A probability as a bar: the number is the truth, the bar is the glance. */
function RiskBar({ p }: { p: number }) {
  const width = Math.max(2, Math.min(100, p * 100));
  const tone = p >= 0.5 ? "bg-alert" : p >= 0.2 ? "bg-caution" : "bg-accent";
  return (
    <div className="h-1.5 w-full overflow-hidden rounded-pill bg-line">
      <div className={`h-full rounded-pill ${tone} transition-[width] duration-700`} style={{ width: `${width}%` }} />
    </div>
  );
}

function Readout({
  label,
  value,
  count,
  decimals = 0,
  suffix = "",
  unit,
  note,
}: {
  label: string;
  /** Shown as-is when there is nothing to count (a dash, a formatted date). */
  value?: string;
  /** Counted up from zero the first time the card is scrolled into view. */
  count?: number;
  decimals?: number;
  suffix?: string;
  unit?: string;
  note?: string;
}) {
  return (
    <div className="lift card p-5">
      <p className="font-mono text-micro uppercase tracking-[0.14em] text-muted">{label}</p>
      <p className="mt-3 font-mono text-readout font-light text-ink">
        {count === undefined ? (
          value
        ) : (
          <CountUp value={count} decimals={decimals} suffix={suffix} />
        )}
        {unit && <span className="ml-1 text-caption text-muted">{unit}</span>}
      </p>
      {note && <p className="mt-2 text-caption text-muted">{note}</p>}
    </div>
  );
}

export default function LiveConsole() {
  const [snap, setSnap] = useState<Snapshot | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  const load = useCallback(async () => {
    try {
      const [status, forecasts, readiness] = await Promise.all([
        fetchModelStatus(),
        fetchDistrictForecasts(),
        fetchReadiness(),
      ]);
      setSnap({ status, forecasts, readiness, at: Date.now() });
      setError(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not reach the API");
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
    const start = () => {
      if (timer.current === null) timer.current = setInterval(load, REFRESH_MS);
    };
    const stop = () => {
      if (timer.current !== null) {
        clearInterval(timer.current);
        timer.current = null;
      }
    };
    const onVisibility = () => {
      if (document.hidden) {
        stop();
      } else {
        load();
        start();
      }
    };
    start();
    document.addEventListener("visibilitychange", onVisibility);
    return () => {
      stop();
      document.removeEventListener("visibilitychange", onVisibility);
    };
  }, [load]);

  const updated = useRelativeTime(snap?.at ?? null);
  const progress = useRefreshProgress(snap?.at ?? null, REFRESH_MS);

  if (loading) {
    return (
      <div className="animate-pulse card p-6 font-mono text-caption text-muted">
        Reading the corridor…
      </div>
    );
  }

  if (error || !snap) {
    return (
      <div className="card border-alert/40 p-6 font-mono text-caption text-alert">
        {error ?? "No data"}.{" "}
        <span className="text-muted">
          The API sleeps when idle; the first request after a quiet spell can take up to a
          minute. This page retries every 60 seconds.
        </span>
      </div>
    );
  }

  const { status, forecasts, readiness } = snap;
  const freshness = readiness.checks.data_freshness;
  const stale = Boolean(freshness?.stale ?? forecasts.stale);
  const corridor = forecasts.districts
    .map((d) => ({
      district: d.district,
      affected: d.affected_on_as_of,
      h1: d.forecasts.find((f) => f.horizon_days === 1),
      h3: d.forecasts.find((f) => f.horizon_days === 3),
    }))
    .sort((a, b) => (b.h1?.probability ?? 0) - (a.h1?.probability ?? 0));

  const highest = corridor[0]?.h1?.probability ?? 0;
  const affectedNow = corridor.filter((c) => c.affected).length;
  const roads = status.scoring?.roads_scored;
  const shadow = status.shadow_test?.["1"];

  return (
    <section className="space-y-4">
      {/* Status strip: what the system knows about itself, in one line. */}
      <div className="flex flex-wrap items-center gap-x-6 gap-y-2 card-pill px-5 py-3 font-mono text-micro uppercase">
        <span className="flex items-center gap-2">
          <span
            className={`live-dot inline-block h-2 w-2 rounded-full ${
              readiness.ready && !stale ? "bg-accent" : "bg-caution"
            }`}
          />
          <span className="text-ink">{readiness.ready ? "Systems ready" : "Degraded"}</span>
        </span>
        <span className={stale ? "text-caution" : "text-muted"}>
          Report {forecasts.as_of ?? "—"}
          {forecasts.age_days != null && ` · ${forecasts.age_days}d old`}
          {stale && " · stale"}
        </span>
        <span className="text-muted">
          Rain {readiness.checks.rainfall_freshness?.latest_day ?? "—"}
        </span>
        <span className="hidden text-muted sm:inline">
          Model {status.scoring?.model_version?.split("+")[0] ?? "—"}
        </span>
        <span className="ml-auto text-muted">Checked {updated}</span>
      </div>

      {/* The heartbeat: fills over the refresh interval, resets on new data. */}
      <div className="h-px w-full overflow-hidden bg-line/70">
        <div
          className="h-px bg-accent/70 transition-[width] duration-1000 ease-linear"
          style={{ width: `${progress * 100}%` }}
        />
      </div>

      {/* Four numbers that answer "should I look closer?" */}
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <Readout
          label="Highest risk tomorrow"
          count={highest * 100}
          decimals={1}
          suffix="%"
          note={corridor[0]?.district ?? "—"}
        />
        <Readout
          label="Affected today"
          count={affectedNow}
          unit={`/${corridor.length}`}
          note="corridor districts in the report"
        />
        <Readout
          label="Roads scored"
          value={roads ? undefined : "—"}
          count={roads ?? undefined}
          note={`as of ${status.scoring?.as_of ?? "—"}`}
        />
        <Readout
          label="Live forecasts graded"
          count={status.live_track_record?.["1"]?.n ?? 0}
          note={`1-day skill vs persistence ${
            status.live_track_record?.["1"]?.skill_vs_persistence == null
              ? "—"
              : `${((status.live_track_record["1"].skill_vs_persistence ?? 0) * 100).toFixed(1)}%`
          }`}
        />
      </div>

      {/* The corridor itself. */}
      <div className="card overflow-hidden">
        <div className="flex items-baseline justify-between border-b border-line px-5 py-4">
          <h2 className="font-mono text-micro uppercase text-muted">
            Probability a district is flood-affected
          </h2>
          <Link href="/accessibility" className="font-mono text-micro text-accent hover:underline">
            Open the map →
          </Link>
        </div>
        <table className="w-full border-collapse font-mono text-caption">
          <thead>
            <tr className="text-muted">
              <th className="px-4 py-2 text-left font-normal">District</th>
              <th className="px-4 py-2 text-right font-normal">Today</th>
              <th className="px-4 py-2 text-right font-normal">+1 day</th>
              <th className="w-1/3 px-4 py-2 text-left font-normal">&nbsp;</th>
              <th className="px-4 py-2 text-right font-normal">+3 days</th>
            </tr>
          </thead>
          <tbody>
            {corridor.map((c) => (
              <tr key={c.district} className="border-t border-line">
                <td className="px-4 py-3 text-ink">{c.district}</td>
                <td className="px-4 py-3 text-right">
                  <span className={c.affected ? "text-alert" : "text-muted"}>
                    {c.affected ? "affected" : "clear"}
                  </span>
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-ink">
                  {pct(c.h1?.probability)}
                </td>
                <td className="px-4 py-3">
                  <RiskBar p={c.h1?.probability ?? 0} />
                </td>
                <td className="px-4 py-3 text-right tabular-nums text-muted">
                  {pct(c.h3?.probability)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
        <p className="border-t border-line px-4 py-2 font-mono text-micro text-muted">
          Against a persistence baseline: {pct(corridor[0]?.h1?.persistence_probability)} for the
          same district. A forecast only means something next to what it beat.
        </p>
      </div>

      {/* The experiment currently running, counted honestly. */}
      {shadow?.challenger_version && (
        <div className="flex flex-wrap items-center gap-x-6 gap-y-2 card px-5 py-4 font-mono text-micro">
          <span className="uppercase text-muted">Shadow test · rainfall model</span>
          <span className="text-ink">
            {shadow.pairs ?? 0}/{shadow.rule?.min_pairs ?? "?"} graded
          </span>
          <span className="text-ink">
            {shadow.onsets_that_flooded ?? 0}/{shadow.rule?.min_flood_onsets ?? "?"} onsets
          </span>
          <span className="text-muted">
            frozen {shadow.frozen_on} · decision {shadow.decision}
          </span>
        </div>
      )}
    </section>
  );
}
