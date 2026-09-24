"use client";

/**
 * Replay: drag back through the stored forecasts and watch the corridor
 * change day by day.
 *
 * WHY IT SHOWS THE OUTCOME TOO
 * A slider that only replays predictions is a showreel. Each day here also
 * carries what actually happened on its target day, so scrubbing through
 * shows the misses as plainly as the hits -- including the days the model
 * said "quiet" and the district flooded.
 *
 * WHAT IT IS NOT
 * Not a recomputation. Every value is the forecast that was served that
 * morning, from the model version of the day. Re-scoring history with
 * today's model would look better and prove nothing, because the model was
 * trained on those days.
 */

import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { fetchForecastHistory, type ForecastHistory } from "@/lib/api";

const STEP_MS = 900;

function pct(p: number): string {
  return `${(p * 100).toFixed(1)}%`;
}

function dayLabel(iso: string): string {
  const d = new Date(`${iso}T00:00:00`);
  return d.toLocaleDateString(undefined, { day: "numeric", month: "short" });
}

export default function ForecastReplay({ horizonDays = 1 }: { horizonDays?: number }) {
  const [history, setHistory] = useState<ForecastHistory | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [index, setIndex] = useState(0);
  const [playing, setPlaying] = useState(false);
  const timer = useRef<ReturnType<typeof setInterval> | null>(null);

  useEffect(() => {
    fetchForecastHistory(30, horizonDays)
      .then((h) => {
        setHistory(h);
        setIndex(Math.max(0, h.days.length - 1)); // open on the newest day
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the history"));
  }, [horizonDays]);

  const total = history?.days.length ?? 0;

  const stop = useCallback(() => {
    setPlaying(false);
    if (timer.current !== null) {
      clearInterval(timer.current);
      timer.current = null;
    }
  }, []);

  useEffect(() => {
    if (!playing || total === 0) return;
    timer.current = setInterval(() => {
      setIndex((i) => {
        if (i >= total - 1) {
          // Stop at the end rather than looping: a loop makes it ambient
          // decoration, and this is a record of what was predicted.
          setPlaying(false);
          return i;
        }
        return i + 1;
      });
    }, STEP_MS);
    return () => {
      if (timer.current !== null) clearInterval(timer.current);
      timer.current = null;
    };
  }, [playing, total]);

  const day = history?.days[index];
  const districts = useMemo(
    () => [...(day?.districts ?? [])].sort((a, b) => b.probability - a.probability),
    [day],
  );

  if (error) {
    return <p className="text-caption text-alert">{error}</p>;
  }
  if (!history) {
    return <p className="text-caption text-muted">Loading the record…</p>;
  }
  if (total === 0) {
    return (
      <p className="text-caption text-muted">
        No stored forecasts yet. They accumulate one day at a time, from the day scoring first
        ran.
      </p>
    );
  }

  return (
    <div className="card p-5">
      <div className="flex flex-wrap items-baseline justify-between gap-3">
        <div>
          <h3 className="font-mono text-micro uppercase tracking-[0.18em] text-muted">
            Replay · {history.horizon_days}-day forecast
          </h3>
          <p className="mt-2 text-subheading font-extralight">
            Forecast made on {dayLabel(day!.as_of)}, for {dayLabel(day!.target_date)}
          </p>
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={() => {
              if (playing) {
                stop();
              } else {
                if (index >= total - 1) setIndex(0);
                setPlaying(true);
              }
            }}
            className="rounded-pill bg-ink px-4 py-2 text-caption font-medium text-white transition-colors hover:bg-accent-deep"
          >
            {playing ? "Pause" : "Play"}
          </button>
          <span className="font-mono text-micro text-muted">
            {index + 1}/{total}
          </span>
        </div>
      </div>

      <label className="mt-5 block">
        <span className="sr-only">Report day</span>
        <input
          type="range"
          min={0}
          max={total - 1}
          value={index}
          onChange={(e) => {
            stop();
            setIndex(Number(e.target.value));
          }}
          className="h-1 w-full cursor-pointer appearance-none rounded-pill bg-line accent-accent"
        />
      </label>
      <div className="mt-2 flex justify-between font-mono text-micro text-muted">
        <span>{dayLabel(history.days[0].as_of)}</span>
        <span>{dayLabel(history.days[total - 1].as_of)}</span>
      </div>

      <ul className="mt-5 space-y-3">
        {districts.map((d) => {
          const outcome = d.affected_on_target;
          const flagged = d.probability >= 0.2;
          return (
            <li key={d.district_key} className="grid grid-cols-[1fr_auto] gap-x-4 gap-y-1">
              <div className="flex items-baseline gap-2">
                <span className="text-ui font-medium">{d.district}</span>
                {d.affected_on_as_of && (
                  <span className="font-mono text-micro uppercase text-caution">
                    affected that day
                  </span>
                )}
              </div>
              <span className="font-mono text-ui tabular-nums">{pct(d.probability)}</span>

              <div className="col-span-2 h-1.5 overflow-hidden rounded-pill bg-line">
                <div
                  className="h-full rounded-pill bg-accent transition-[width] duration-500"
                  style={{ width: `${Math.max(1.5, Math.min(100, d.probability * 100))}%` }}
                />
              </div>

              <p className="col-span-2 font-mono text-micro text-muted">
                persistence said {pct(d.persistence_probability)} ·{" "}
                {outcome === null ? (
                  <span>outcome not published yet</span>
                ) : outcome ? (
                  <span className={flagged ? "text-ok" : "text-alert"}>
                    flooded — {flagged ? "the model had flagged it" : "the model had not"}
                  </span>
                ) : (
                  <span className={flagged ? "text-alert" : "text-ok"}>
                    did not flood{flagged ? " — a false alarm" : ""}
                  </span>
                )}
              </p>
            </li>
          );
        })}
      </ul>

      <p className="mt-5 border-t border-line pt-3 text-caption text-muted">{history.note}</p>
    </div>
  );
}
