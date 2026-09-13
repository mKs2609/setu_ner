"use client";

/**
 * The Phase 3 model, explained next to its own numbers.
 *
 * Three things stay on screen that a slicker panel would drop:
 *
 *   - the persistence baseline beside every probability, because "70% chance
 *     of flooding" means little until you know "flooded today" already
 *     implies about that;
 *   - which predictor is actually served, including when it is the baseline
 *     because the logistic model lost;
 *   - the caveats, because the per-road spread is a stated terrain prior,
 *     not something fitted.
 */

import { useEffect, useState } from "react";

import {
  fetchDistrictForecasts,
  fetchModelStatus,
  type DistrictForecasts,
  type MetricScore,
  type ModelArtifact,
  type ModelStatus,
} from "@/lib/api";

function pct(p: number | null | undefined): string {
  return p == null ? "—" : `${Math.round(p * 100)}%`;
}

function num(v: number | null | undefined, digits = 3): string {
  return v == null ? "—" : v.toFixed(digits);
}

function skill(v: number | null | undefined): string {
  if (v == null) return "—";
  return `${v > 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
}

function MetricRow({ label, m }: { label: string; m: MetricScore | undefined }) {
  return (
    <tr className="border-t border-gray-100">
      <td className="py-1 pr-2 text-gray-700">{label}</td>
      <td className="py-1 pr-2 text-right tabular-nums">{num(m?.brier, 4)}</td>
      <td className="py-1 text-right tabular-nums">{num(m?.roc_auc)}</td>
    </tr>
  );
}

function ArtifactCard({ a }: { a: ModelArtifact }) {
  const tm = a.test_metrics;
  return (
    <div className="rounded border border-gray-200 p-3">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="font-medium">{a.horizon_days}-day horizon</h3>
        <span
          className={`rounded px-1.5 py-0.5 text-xs ${
            a.served_kind === "logistic" ? "bg-teal-50 text-teal-800" : "bg-amber-50 text-amber-800"
          }`}
        >
          serving: {a.served_kind}
        </span>
      </div>
      <p className="mt-1 text-xs text-gray-600">{a.verdict.summary}</p>
      {a.test_period && (
        <p className="mt-1 text-xs text-gray-500">
          Held-out season {a.test_period.from} → {a.test_period.to}, {a.test_period.examples}{" "}
          district-days. Trained on {a.train_period?.from} → {a.train_period?.to}.
        </p>
      )}
      <table className="mt-2 w-full text-xs">
        <thead>
          <tr className="text-gray-500">
            <th className="text-left font-normal">Test season</th>
            <th className="text-right font-normal">Brier ↓</th>
            <th className="text-right font-normal">AUC ↑</th>
          </tr>
        </thead>
        <tbody>
          <MetricRow label="Served" m={tm.served?.all} />
          {tm.logistic && <MetricRow label="Logistic" m={tm.logistic.all} />}
          <MetricRow label="Persistence" m={tm.persistence?.all} />
          <MetricRow label="Climatology" m={tm.climatology?.all} />
          <tr>
            <td colSpan={3} className="pt-2 text-gray-500">
              Onset only (not affected today)
            </td>
          </tr>
          {tm.logistic && <MetricRow label="Logistic" m={tm.logistic.onset} />}
          <MetricRow label="Persistence" m={tm.persistence?.onset} />
        </tbody>
      </table>
      <p className="mt-2 text-xs text-gray-600">
        Logistic skill vs persistence on test: {skill(a.verdict.logistic_test_skill_vs_persistence)}
      </p>
    </div>
  );
}

export default function ModelPanel() {
  const [status, setStatus] = useState<ModelStatus | null>(null);
  const [forecasts, setForecasts] = useState<DistrictForecasts | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchModelStatus(), fetchDistrictForecasts()])
      .then(([s, f]) => {
        setStatus(s);
        setForecasts(f);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Failed to load the model"));
  }, []);

  if (error) {
    return (
      <p className="p-4 text-sm text-red-600">
        Couldn&apos;t reach the API ({error}). Is the backend running on port 8000?
      </p>
    );
  }
  if (!status || !forecasts) {
    return <p className="p-4 text-sm text-gray-500">Loading model…</p>;
  }

  const artifacts = Object.values(status.artifacts).filter(Boolean) as ModelArtifact[];

  return (
    <div className="space-y-5 p-4 text-sm">
      <section>
        <h2 className="font-semibold">District flood-state forecast</h2>
        {forecasts.as_of ? (
          <p className={`text-xs ${forecasts.stale ? "text-red-700" : "text-gray-600"}`}>
            From the DRIMS report of {forecasts.as_of}
            {forecasts.stale
              ? ` — ${forecasts.age_days} days old. Stale: do not read as current.`
              : ` (${forecasts.age_days} day${forecasts.age_days === 1 ? "" : "s"} ago).`}
          </p>
        ) : (
          <p className="text-xs text-amber-700">No forecasts stored yet. Run the scoring job.</p>
        )}
        <div className="mt-2 grid grid-cols-1 gap-2 sm:grid-cols-2">
          {forecasts.districts.map((d) => {
            const h1 = d.forecasts.find((f) => f.horizon_days === 1);
            const h3 = d.forecasts.find((f) => f.horizon_days === 3);
            return (
              <div key={d.district} className="rounded border border-gray-200 p-2">
                <div className="flex items-baseline justify-between">
                  <span className="font-medium">{d.district}</span>
                  <span className={`text-xs ${d.affected_on_as_of ? "text-red-700" : "text-gray-500"}`}>
                    {d.affected_on_as_of ? "affected today" : "not listed today"}
                  </span>
                </div>
                <p className="mt-1 tabular-nums">
                  Tomorrow <strong>{pct(h1?.probability)}</strong>
                  <span className="text-xs text-gray-500"> (persistence {pct(h1?.persistence_probability)})</span>
                </p>
                <p className="tabular-nums">
                  In 3 days <strong>{pct(h3?.probability)}</strong>
                  <span className="text-xs text-gray-500"> (persistence {pct(h3?.persistence_probability)})</span>
                </p>
              </div>
            );
          })}
        </div>
        <p className="mt-2 text-xs text-gray-500">{status.caveats.what_is_predicted}</p>
      </section>

      <section>
        <h2 className="font-semibold">How good is it?</h2>
        <p className="text-xs text-gray-600">
          Built from {status.data.published_report_days} daily reports across{" "}
          {status.data.districts_seen} Assam districts ({status.data.first_report} →{" "}
          {status.data.latest_report}). Every score is shown next to the baselines it has to beat.
        </p>
        <div className="mt-2 space-y-2">
          {artifacts.length ? (
            artifacts.map((a) => <ArtifactCard key={a.version} a={a} />)
          ) : (
            <p className="text-xs text-amber-700">No trained model yet.</p>
          )}
        </div>
        <p className="mt-2 text-xs text-gray-600">
          Live track record:{" "}
          {Object.entries(status.live_track_record)
            .map(([h, r]) =>
              r.n
                ? `${h}-day: ${r.n} forecasts graded, skill vs persistence ${skill(r.skill_vs_persistence)}`
                : `${h}-day: none graded yet`
            )
            .join(" · ")}
        </p>
      </section>

      <section>
        <h2 className="font-semibold">Per-road values</h2>
        <p className="text-xs text-gray-600">
          accessibility = 1 − P(district affected tomorrow) × terrain exposure.
        </p>
        <p className="mt-1 text-xs text-gray-600">
          Exposure prior (not fitted): {status.exposure_prior.formula}.
        </p>
        <p className="mt-1 text-xs text-gray-500">
          {status.exposure_prior.check.matched_damage_reports} DRIMS damage reports matched to corridor
          roads. {status.exposure_prior.check.note}
        </p>
      </section>

      <section>
        <h2 className="font-semibold">Caveats</h2>
        <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-gray-600">
          {Object.entries(status.caveats)
            .filter(([k]) => k !== "what_is_predicted")
            .map(([k, v]) => (
              <li key={k}>{v}</li>
            ))}
        </ul>
      </section>
    </div>
  );
}
