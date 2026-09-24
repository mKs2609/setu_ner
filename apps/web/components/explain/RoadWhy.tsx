"use client";

/**
 * Why one road has its accessibility: the district forecast and the terrain
 * prior, shown as the two separate halves they are.
 */

import { useEffect, useState } from "react";

import { fetchRoadExplanation, type RoadExplanation } from "@/lib/api";

export default function RoadWhy({ roadId, onClose }: { roadId: number; onClose: () => void }) {
  const [data, setData] = useState<RoadExplanation | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setData(null);
    setError(null);
    fetchRoadExplanation(roadId)
      .then(setData)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load explanation"));
  }, [roadId]);

  return (
    <div className="rounded bg-surface p-3 text-xs border border-line shadow-card">
      <div className="flex items-baseline justify-between gap-2">
        <h3 className="text-sm font-semibold">Why this road? (#{roadId})</h3>
        <button onClick={onClose} className="text-muted hover:text-gray-800" aria-label="Close">
          ✕
        </button>
      </div>
      {error && <p className="mt-1 text-alert">{error}</p>}
      {!data && !error && <p className="mt-1 text-muted">Loading…</p>}
      {data && (
        <div className="mt-1 space-y-2">
          <p className="text-ink">{data.headline}</p>
          {data.model_mismatch_note && <p className="text-caution">{data.model_mismatch_note}</p>}
          {data.district_forecast && (
            <div>
              <p className="font-medium text-ink">District half — an evaluated forecast</p>
              <p className="text-ink">{data.district_forecast.headline}</p>
            </div>
          )}
          {data.terrain && (
            <div>
              <p className="font-medium text-ink">Terrain half — a stated prior, not fitted</p>
              <p className="text-ink">
                Elevation {data.terrain.elevation_m?.toFixed(0)} m; district low ground{" "}
                {data.terrain.district_floor_m?.toFixed(0)} m; exposure = {data.terrain.formula} ={" "}
                {data.terrain.exposure?.toFixed(2)}.
              </p>
            </div>
          )}
          {data.baseline_comparison && <p className="text-muted">{data.baseline_comparison}</p>}
          {data.trust && <p className="text-muted">{data.trust}</p>}
        </div>
      )}
    </div>
  );
}
