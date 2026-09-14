"use client";

/**
 * Why a district got its forecast, feature by feature.
 *
 * Bars show each input's contribution in log-odds, relative to an average
 * district. The reconstruction check is displayed rather than hidden: if the
 * contributions ever stopped adding up to the prediction, this panel would
 * say so instead of quietly showing a wrong story.
 */

import { useEffect, useState } from "react";

import { fetchDistrictExplanation, type ForecastExplanation } from "@/lib/api";

function Bars({ e }: { e: ForecastExplanation }) {
  const shown = e.contributions.filter((c) => Math.abs(c.log_odds) >= 0.01).slice(0, 6);
  const max = Math.max(0.01, ...shown.map((c) => Math.abs(c.log_odds)));
  return (
    <ul className="mt-1 space-y-1">
      {shown.map((c) => (
        <li key={c.feature} className="text-[11px] leading-snug">
          <div className="flex items-center gap-2">
            <div className="relative h-2 w-24 shrink-0 rounded bg-gray-100">
              <div
                className={`absolute top-0 h-2 rounded ${c.log_odds > 0 ? "left-1/2 bg-red-500" : "right-1/2 bg-teal-600"}`}
                style={{ width: `${(Math.abs(c.log_odds) / max) * 50}%` }}
              />
            </div>
            <span className="tabular-nums text-gray-500">
              {c.log_odds > 0 ? "+" : ""}
              {c.log_odds.toFixed(2)}
            </span>
          </div>
          <span className="text-gray-700">{c.sentence}</span>
        </li>
      ))}
    </ul>
  );
}

export default function ForecastWhy({ district }: { district: string }) {
  const [data, setData] = useState<ForecastExplanation[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchDistrictExplanation(district)
      .then((r) => setData(r.explanations))
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load explanation"));
  }, [district]);

  if (error) return <p className="mt-2 text-xs text-red-700">{error}</p>;
  if (!data) return <p className="mt-2 text-xs text-gray-500">Loading explanation…</p>;

  return (
    <div className="mt-2 space-y-2 border-t border-gray-100 pt-2">
      {data.map((e) => (
        <div key={e.horizon_days}>
          <p className="text-xs font-medium text-gray-700">
            {e.horizon_days}-day ({e.model_kind})
          </p>
          <p className="text-xs text-gray-700">{e.headline}</p>
          {e.method === "exact_linear_attribution" && (
            <>
              <Bars e={e} />
              <p className="mt-1 text-[11px] text-gray-500">
                Red raises, teal lowers, relative to an average district (
                {Math.round((e.average_district_probability ?? 0) * 100)}%).{" "}
                {e.check?.matches_prediction
                  ? "Contributions add up to the prediction."
                  : "Warning: contributions do not reconstruct the prediction."}
              </p>
            </>
          )}
          {e.why_this_model && <p className="text-[11px] text-gray-500">{e.why_this_model}</p>}
        </div>
      ))}
      {data[0]?.how_to_read && <p className="text-[11px] text-gray-500">{data[0].how_to_read}</p>}
    </div>
  );
}
