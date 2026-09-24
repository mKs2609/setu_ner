"use client";

/**
 * Scenario controls and results.
 *
 * The results half deliberately mirrors what the API returns rather than
 * simplifying it. Three things stay visible that a prettier UI would be
 * tempted to drop:
 *
 *   - the verdict in plain language, including "no change" when the closure
 *     missed the route entirely;
 *   - the causal line (how many of the closed roads were actually on the
 *     baseline route), because a big closure count with none on the route
 *     means the scenario did nothing;
 *   - the modelled-time caveat, because travel times come from an assumed
 *     speed per road class, not measurement.
 *
 * Dropping any of those would make the screen look more confident than the
 * data underneath it actually is.
 */

import { useState } from "react";

import type { Landmark, RouteStats, ScenarioResult } from "@/lib/api";

const DISTRICTS = ["Cachar", "Hailakandi", "Karimganj", "Dima Hasao"] as const;

export type Effect = "close" | "degrade";
export type StartFrom = "clean" | "current_conditions";

export interface ScenarioForm {
  origin: string;
  destination: string;
  district: string;
  effect: Effect;
  degradeFactor: number;
  startFrom: StartFrom;
}

interface Preset {
  name: string;
  blurb: string;
  form: ScenarioForm;
}

export const PRESETS: Preset[] = [
  {
    name: "Cachar bridges down",
    blurb: "Severs the corridor — the headline finding",
    form: { origin: "silchar", destination: "haflong", district: "Cachar", effect: "close", degradeFactor: 3, startFrom: "clean" },
  },
  {
    name: "Karimganj bridges down",
    blurb: "Big closure, zero impact on this route",
    form: { origin: "silchar", destination: "haflong", district: "Karimganj", effect: "close", degradeFactor: 3, startFrom: "clean" },
  },
  {
    name: "Cachar bridges flooded",
    blurb: "Passable but 3x slower, not severed",
    form: { origin: "silchar", destination: "haflong", district: "Cachar", effect: "degrade", degradeFactor: 3, startFrom: "clean" },
  },
  {
    name: "Silchar to Kalain, 2025 route",
    blurb: "The corridor's real 2025 failure point",
    form: { origin: "silchar", destination: "kalain", district: "Cachar", effect: "close", degradeFactor: 3, startFrom: "clean" },
  },
];

// Labels for the four ways a route can fail. "Cut off" is reserved for a
// genuine severance -- using it for a blocked road at the origin would
// overstate the situation in exactly the direction that costs trust, which is
// the whole reason the engine distinguishes them.
const UNREACHABLE_LABELS: Record<string, string> = {
  severed: "Cut off",
  origin_isolated: "Cannot set out",
  destination_isolated: "Cannot arrive",
  both_isolated: "Both ends isolated",
};

function verdictTone(result: ScenarioResult) {
  if (result.delta.severed) {
    const kind = result.scenario_result.kind ?? "severed";
    return {
      ring: "ring-alert/30",
      bg: "bg-alert/10",
      text: "text-alert",
      label: UNREACHABLE_LABELS[kind] ?? "No route",
    };
  }
  if (!result.delta.added_minutes) return { ring: "ring-line", bg: "bg-surface", text: "text-ink", label: "No change" };
  return { ring: "ring-caution/30", bg: "bg-caution/10", text: "text-caution", label: "Delayed" };
}

function Stat({ label, value, sub }: { label: string; value: string; sub?: string }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wide text-muted">{label}</div>
      <div className="text-sm font-semibold text-ink">{value}</div>
      {sub && <div className="text-[11px] text-muted">{sub}</div>}
    </div>
  );
}

function RouteColumn({ title, stats, accent }: { title: string; stats: RouteStats; accent: string }) {
  return (
    <div className="flex-1 rounded border border-line p-3">
      <div className="mb-2 flex items-center gap-2">
        <span className="inline-block h-2 w-2 rounded-full" style={{ background: accent }} />
        <span className="text-xs font-semibold text-ink">{title}</span>
      </div>
      {stats.reachable ? (
        <div className="space-y-2">
          <Stat label="Travel time" value={`${stats.travel_time_min} min`} />
          <Stat label="Distance" value={`${stats.distance_km} km`} />
          <Stat label="Segments" value={String(stats.segment_count)} sub={`${stats.bridges_crossed} bridges`} />
        </div>
      ) : (
        <p className="text-xs leading-snug text-alert">No route exists.</p>
      )}
    </div>
  );
}

export default function ScenarioPanel({
  landmarks,
  form,
  setForm,
  onRun,
  loading,
  error,
  result,
}: {
  landmarks: Landmark[];
  form: ScenarioForm;
  setForm: (f: ScenarioForm) => void;
  onRun: () => void;
  loading: boolean;
  error: string | null;
  result: ScenarioResult | null;
}) {
  const [showCaveats, setShowCaveats] = useState(false);
  const set = <K extends keyof ScenarioForm>(k: K, v: ScenarioForm[K]) => setForm({ ...form, [k]: v });

  const tone = result ? verdictTone(result) : null;
  const farSnap =
    result && Math.max(result.origin.snapped_km_away, result.destination.snapped_km_away) > 2;

  return (
    <div className="flex flex-col gap-4 border-b border-line bg-surface p-4 md:h-full md:overflow-y-auto md:border-b-0 md:border-r">
      <div>
        <h2 className="text-sm font-semibold text-ink">Build a scenario</h2>
        <p className="mt-0.5 text-xs leading-snug text-muted">
          Take out a set of roads and see what it does to the route.
        </p>
      </div>

      {/* ---------------- presets ---------------- */}
      <div>
        <label className="mb-1.5 block text-xs font-medium text-ink">Start from a preset</label>
        <div className="grid gap-1.5">
          {PRESETS.map((p) => (
            <button
              key={p.name}
              type="button"
              onClick={() => setForm(p.form)}
              className="card px-2.5 py-2 text-left text-xs transition hover:border-teal-400 hover:bg-teal-50"
            >
              <div className="font-medium text-ink">{p.name}</div>
              <div className="text-[11px] text-muted">{p.blurb}</div>
            </button>
          ))}
        </div>
      </div>

      {/* ---------------- starting network ---------------- */}
      <div>
        <label className="mb-1.5 block text-xs font-medium text-ink">
          Start from
        </label>
        <div className="flex gap-1.5">
          <button
            type="button"
            onClick={() => set("startFrom", "clean")}
            className={`flex-1 rounded border px-2 py-1.5 text-xs transition ${
              form.startFrom === "clean"
                ? "border-accent/40 bg-accent-wash font-medium text-accent"
                : "border-line bg-surface text-muted hover:bg-accent-wash/60"
            }`}
          >
            Clean network
          </button>
          <button
            type="button"
            onClick={() => set("startFrom", "current_conditions")}
            className={`flex-1 rounded border px-2 py-1.5 text-xs transition ${
              form.startFrom === "current_conditions"
                ? "border-accent/40 bg-accent-wash font-medium text-accent"
                : "border-line bg-surface text-muted hover:bg-accent-wash/60"
            }`}
          >
            Conditions now
          </button>
        </div>
        <p className="mt-1 text-[11px] leading-snug text-muted">
          {form.startFrom === "clean"
            ? "A pure hypothetical on an undamaged network."
            : "Applies what is actually reported right now — field reports and hazard damage points — before your closures."}
        </p>
      </div>

      {/* ---------------- route ---------------- */}
      <div className="grid grid-cols-2 gap-2">
        <div>
          <label className="mb-1 block text-xs font-medium text-ink">From</label>
          <select
            value={form.origin}
            onChange={(e) => set("origin", e.target.value)}
            className="w-full card px-2 py-1.5 text-xs"
          >
            {landmarks.map((l) => (
              <option key={l.key} value={l.key}>{l.display_name}</option>
            ))}
          </select>
        </div>
        <div>
          <label className="mb-1 block text-xs font-medium text-ink">To</label>
          <select
            value={form.destination}
            onChange={(e) => set("destination", e.target.value)}
            className="w-full card px-2 py-1.5 text-xs"
          >
            {landmarks.map((l) => (
              <option key={l.key} value={l.key}>{l.display_name}</option>
            ))}
          </select>
        </div>
      </div>

      {/* ---------------- what happens ---------------- */}
      <div>
        <label className="mb-1 block text-xs font-medium text-ink">
          What happens to the bridges in
        </label>
        <select
          value={form.district}
          onChange={(e) => set("district", e.target.value)}
          className="w-full card px-2 py-1.5 text-xs"
        >
          {DISTRICTS.map((d) => (
            <option key={d} value={d}>{d}</option>
          ))}
        </select>

        <div className="mt-2 flex gap-1.5">
          <button
            type="button"
            onClick={() => set("effect", "close")}
            className={`flex-1 rounded border px-2 py-1.5 text-xs transition ${
              form.effect === "close"
                ? "border-alert/40 bg-alert/10 font-medium text-alert"
                : "border-line bg-surface text-muted hover:bg-accent-wash/60"
            }`}
          >
            Collapsed
          </button>
          <button
            type="button"
            onClick={() => set("effect", "degrade")}
            className={`flex-1 rounded border px-2 py-1.5 text-xs transition ${
              form.effect === "degrade"
                ? "border-caution/40 bg-caution/10 font-medium text-caution"
                : "border-line bg-surface text-muted hover:bg-accent-wash/60"
            }`}
          >
            Flooded
          </button>
        </div>
        <p className="mt-1 text-[11px] leading-snug text-muted">
          {form.effect === "close"
            ? "Impassable — removed from the network entirely."
            : "Still passable, but slower."}
        </p>

        {form.effect === "degrade" && (
          <div className="mt-2">
            <label className="mb-1 block text-xs font-medium text-ink">
              How much slower: {form.degradeFactor}x
            </label>
            <input
              type="range"
              min={1.5}
              max={10}
              step={0.5}
              value={form.degradeFactor}
              onChange={(e) => set("degradeFactor", Number(e.target.value))}
              className="w-full"
            />
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={onRun}
        disabled={loading}
        className="rounded-pill bg-accent px-4 py-2 text-sm font-medium text-white transition hover:bg-accent-deep disabled:cursor-not-allowed disabled:bg-gray-400"
      >
        {loading ? "Running..." : "Run scenario"}
      </button>

      {error && (
        <div className="rounded bg-alert/10 p-2.5 text-xs leading-snug text-alert ring-1 ring-alert/30">
          <div className="font-semibold">Could not run the scenario</div>
          <div className="mt-0.5">{error}</div>
        </div>
      )}

      {/* ---------------- results ---------------- */}
      {result && tone && (
        <div className="space-y-3 border-t border-line pt-3">
          <div className={`rounded p-3 ring-1 ${tone.bg} ${tone.ring}`}>
            <div className={`text-[11px] font-bold uppercase tracking-wide ${tone.text}`}>
              {tone.label}
            </div>
            <p className={`mt-1 text-xs leading-snug ${tone.text}`}>{result.verdict}</p>
          </div>

          {!result.delta.severed && result.delta.added_minutes !== undefined && (
            <div className="grid grid-cols-3 gap-2 card p-3">
              <Stat
                label="Added time"
                value={`${result.delta.added_minutes > 0 ? "+" : ""}${result.delta.added_minutes} min`}
              />
              <Stat
                label="Slower by"
                value={result.delta.percent_slower != null ? `${result.delta.percent_slower}%` : "—"}
              />
              <Stat label="Extra distance" value={`${result.delta.added_km} km`} />
            </div>
          )}

          <div className="flex gap-2">
            <RouteColumn title="Baseline" stats={result.baseline} accent="#1d4ed8" />
            <RouteColumn title="Scenario" stats={result.scenario_result} accent="#d97706" />
          </div>

          {result.starting_conditions && (
            <div className="rounded border border-teal-200 bg-accent/10/60 p-3 text-xs">
              <div className="mb-1 font-semibold text-accent">
                Already applied before your scenario
              </div>
              {result.starting_conditions.affected_roads.length === 0 ? (
                <p className="leading-snug text-accent">
                  Nothing is currently reported on the network, so this ran on a clean
                  graph anyway.
                </p>
              ) : (
                <>
                  <p className="leading-snug text-accent">
                    <b>{result.starting_conditions.closed_count}</b> road
                    {result.starting_conditions.closed_count === 1 ? "" : "s"} closed and{" "}
                    <b>{result.starting_conditions.degraded_count}</b> slowed, from{" "}
                    {result.starting_conditions.roads_with_recent_reports} road
                    {result.starting_conditions.roads_with_recent_reports === 1 ? "" : "s"}{" "}
                    reported in the last {result.starting_conditions.report_window_hours} h.
                  </p>
                  <ul className="mt-1.5 space-y-1">
                    {result.starting_conditions.affected_roads.slice(0, 5).map((r) => (
                      <li key={`${r.road_id}-${r.effect}`} className="leading-snug text-accent">
                        • Road {r.road_id} —{" "}
                        {r.effect === "closed" ? "closed" : `slowed ${r.travel_time_multiplier}x`}:{" "}
                        {r.reason}
                      </li>
                    ))}
                  </ul>
                </>
              )}
              <p className="mt-1.5 text-[11px] leading-snug text-accent/80">
                Reported conditions, not a forecast. Silence about a road means nobody
                has reported it, not that it is known to be open.
              </p>
            </div>
          )}

          <div className="card p-3 text-xs">
            <div className="mb-1 font-semibold text-ink">Why</div>
            <p className="leading-snug text-muted">
              {result.explanation.roads_closed > 0 && (
                <>
                  <b>{result.explanation.roads_closed}</b> road
                  {result.explanation.roads_closed === 1 ? "" : "s"} closed,{" "}
                  <b>{result.explanation.closed_roads_on_baseline_route.length}</b> of them on the
                  baseline route.{" "}
                </>
              )}
              {result.explanation.roads_degraded > 0 && (
                <>
                  <b>{result.explanation.roads_degraded}</b> road
                  {result.explanation.roads_degraded === 1 ? "" : "s"} slowed,{" "}
                  <b>{result.explanation.degraded_roads_on_baseline_route.length}</b> of them on the
                  baseline route.{" "}
                </>
              )}
            </p>
            <p className="mt-1.5 text-[11px] leading-snug text-muted">
              Only roads on the baseline route can change it. A large count with none on the route
              means the scenario missed.
            </p>
          </div>

          {farSnap && (
            <div className="rounded bg-caution/10 p-2.5 text-[11px] leading-snug text-caution ring-1 ring-caution/30">
              An endpoint snapped more than 2 km to the nearest junction, so this result should not
              be trusted. Check the place coordinates.
            </div>
          )}

          <div>
            <button
              type="button"
              onClick={() => setShowCaveats((v) => !v)}
              className="text-[11px] font-medium text-accent underline underline-offset-2"
            >
              {showCaveats ? "Hide" : "What these numbers do and don't mean"}
            </button>
            {showCaveats && (
              <div className="mt-1.5 space-y-1.5 rounded-lg border border-line bg-surface p-3 text-micro leading-snug text-muted">
                <p>{result.caveats.travel_time}</p>
                <p>{result.caveats.snapping}</p>
                <p>{result.caveats.not_a_logistics_plan}</p>
                <p className="text-muted">
                  Snapped {result.origin.snapped_km_away} km (origin) and{" "}
                  {result.destination.snapped_km_away} km (destination).
                </p>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
