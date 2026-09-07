"use client";

/**
 * Holds the scenario state and wires the control panel to the map.
 *
 * Landmarks are fetched from the API rather than hardcoded, unlike the
 * district list on the dashboard: the backend already exposes them with the
 * coordinates and the reason each one is in the corridor, so duplicating that
 * list here would just be a second copy to keep in sync.
 */

import { useCallback, useEffect, useState } from "react";

import {
  fetchLandmarks,
  simulateScenario,
  type Landmark,
  type ScenarioResult,
} from "@/lib/api";
import ScenarioMap from "./ScenarioMap";
import ScenarioPanel, { PRESETS, type ScenarioForm } from "./ScenarioPanel";

export default function ScenarioWorkbench() {
  const [landmarks, setLandmarks] = useState<Landmark[]>([]);
  const [form, setForm] = useState<ScenarioForm>(PRESETS[0].form);
  const [result, setResult] = useState<ScenarioResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    fetchLandmarks()
      .then((ls) => !cancelled && setLandmarks(ls))
      .catch((e) =>
        !cancelled &&
        setError(
          e instanceof Error
            ? `${e.message} — is the API running on port 8000?`
            : "Could not reach the API."
        )
      );
    return () => {
      cancelled = true;
    };
  }, []);

  const run = useCallback(async () => {
    setLoading(true);
    setError(null);
    const closing = form.effect === "close";
    try {
      const res = await simulateScenario({
        label: `${closing ? "Bridges down" : "Bridges flooded"} in ${form.district}`,
        origin: form.origin,
        destination: form.destination,
        close_bridges_in_district: closing ? form.district : null,
        degrade_bridges_in_district: closing ? null : form.district,
        degrade_factor: form.degradeFactor,
        include_geometry: true,
      });
      setResult(res);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Scenario failed.");
      setResult(null);
    } finally {
      setLoading(false);
    }
  }, [form]);

  return (
    <div className="grid grid-cols-1 md:h-full md:grid-cols-[22rem_1fr]">
      <ScenarioPanel
        landmarks={landmarks}
        form={form}
        setForm={setForm}
        onRun={run}
        loading={loading}
        error={error}
        result={result}
      />
      <div className="relative h-[26rem] md:h-full">
        <ScenarioMap result={result} />
      </div>
    </div>
  );
}
