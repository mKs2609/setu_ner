"use client";

/**
 * Supply planning: pick a report day, state what the depots hold, and see
 * what can reach whom.
 *
 * Kept on screen deliberately:
 *   - the example-inputs banner until the operator edits the depots, because
 *     a plan on invented stock must never pass for a real one;
 *   - replay versus live, because June 2025 conditions are not today's;
 *   - what is limiting the plan, in plain words from the optimiser's duals;
 *   - circles that could not be located, which get no marker and no supply,
 *     rather than a marker at a guessed position.
 */

import Link from "next/link";
import { useCallback, useEffect, useMemo, useState } from "react";

import OperatorAccess from "@/components/auth/OperatorAccess";
import PlanWhy from "@/components/explain/PlanWhy";
import {
  fetchExampleInputs,
  fetchSupplyDays,
  requestPlan,
  type DepotForm,
  type ExampleInputs,
  type PlanResponse,
  type SupplyDay,
} from "@/lib/api";
import LogisticsMap from "./LogisticsMap";

function pct(v: number | null | undefined): string {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

function n(v: number | undefined, digits = 0): string {
  return v == null ? "—" : v.toLocaleString(undefined, { maximumFractionDigits: digits });
}

export default function LogisticsWorkbench() {
  const [days, setDays] = useState<SupplyDay[]>([]);
  const [asOf, setAsOf] = useState<string>("");
  const [example, setExample] = useState<ExampleInputs | null>(null);
  const [depots, setDepots] = useState<DepotForm[]>([]);
  const [edited, setEdited] = useState(false);
  const [horizon, setHorizon] = useState(1);
  const [penalty, setPenalty] = useState(30);
  const [fairnessFirst, setFairnessFirst] = useState(false);
  const [save, setSave] = useState(false);
  const [label, setLabel] = useState("");
  const [plan, setPlan] = useState<PlanResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchSupplyDays(), fetchExampleInputs()])
      .then(([d, ex]) => {
        const byPeople = [...d].sort((a, b) => b.people - a.people);
        setDays(byPeople);
        setAsOf(byPeople[0]?.date ?? "");
        setExample(ex);
        setDepots(ex.depots);
      })
      .catch((e) =>
        setError(e instanceof Error ? `${e.message} — is the API running on port 8000?` : "API unreachable")
      );
  }, []);

  const updateDepot = (i: number, patch: Partial<DepotForm>) => {
    setEdited(true);
    setDepots((ds) => ds.map((d, j) => (j === i ? { ...d, ...patch } : d)));
  };

  const run = useCallback(async () => {
    if (!example) return;
    setLoading(true);
    setError(null);
    try {
      setPlan(
        await requestPlan({
          as_of: asOf || undefined,
          horizon_days: horizon,
          depots,
          fleet: example.fleet,
          risk_minutes_per_exposure_km: penalty,
          fairness_first: fairnessFirst,
          example_inputs: !edited,
          save,
          label: save && label.trim() ? label.trim() : undefined,
        })
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "Planning failed");
    } finally {
      setLoading(false);
    }
  }, [asOf, horizon, depots, example, penalty, fairnessFirst, edited, save, label]);

  const coverage = useMemo(() => {
    if (!plan) return null;
    const need = plan.plan.person_days_needed_all_commodities;
    return need > 0 ? plan.plan.person_days_covered_all_commodities / need : null;
  }, [plan]);

  return (
    <div className="flex h-full flex-col md:flex-row">
      <aside className="w-full space-y-4 overflow-y-auto border-gray-200 p-4 text-sm md:w-[30rem] md:border-r">
        {error && <p className="rounded bg-red-50 p-2 text-red-700">{error}</p>}

        <section className="space-y-2">
          <h2 className="font-semibold">1. Report day</h2>
          <select
            value={asOf}
            onChange={(e) => setAsOf(e.target.value)}
            className="w-full rounded border border-gray-300 px-2 py-1"
          >
            {days.map((d) => (
              <option key={d.date} value={d.date}>
                {d.date} — {d.people.toLocaleString()} people in camps / at relief centres
              </option>
            ))}
          </select>
          <p className="text-xs text-gray-500">
            Days on which the DRIMS report lists people being supplied in the corridor, busiest first.
          </p>
          <label className="flex items-center gap-2">
            <span className="text-gray-700">Plan for</span>
            <input
              type="number" min={1} max={7} value={horizon}
              onChange={(e) => setHorizon(Math.min(7, Math.max(1, Number(e.target.value) || 1)))}
              className="w-16 rounded border border-gray-300 px-2 py-0.5"
            />
            <span className="text-gray-700">day(s)</span>
          </label>
        </section>

        <section className="space-y-2">
          <h2 className="font-semibold">2. Depots</h2>
          {!edited && example && (
            <p className="rounded bg-amber-50 p-2 text-xs text-amber-800">{example.note}</p>
          )}
          <table className="w-full text-xs">
            <thead>
              <tr className="text-left text-gray-500">
                <th className="font-normal">Depot</th>
                <th className="font-normal">Water (L)</th>
                <th className="font-normal">Food (ration-days)</th>
                <th className="font-normal">Trucks</th>
              </tr>
            </thead>
            <tbody>
              {depots.map((d, i) => (
                <tr key={d.name}>
                  <td className="py-1 pr-1">{d.name}</td>
                  {(["water", "food"] as const).map((c) => (
                    <td key={c} className="py-1 pr-1">
                      <input
                        type="number" min={0} value={d.stock[c]}
                        onChange={(e) =>
                          updateDepot(i, { stock: { ...d.stock, [c]: Math.max(0, Number(e.target.value) || 0) } })
                        }
                        className="w-24 rounded border border-gray-300 px-1 py-0.5"
                      />
                    </td>
                  ))}
                  <td className="py-1">
                    <input
                      type="number" min={0} value={d.trucks}
                      onChange={(e) => updateDepot(i, { trucks: Math.max(0, Number(e.target.value) || 0) })}
                      className="w-14 rounded border border-gray-300 px-1 py-0.5"
                    />
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {example && (
            <p className="text-xs text-gray-500">
              Trucks carry {n(example.fleet.truck_capacity_kg)} kg and run {example.fleet.hours_per_day} h/day,
              with {example.fleet.loading_hours_per_trip} h loading per trip.
            </p>
          )}
        </section>

        <section className="space-y-2">
          <h2 className="font-semibold">3. Trade-offs</h2>
          <label className="block">
            <span className="text-gray-700">
              Avoid at-risk roads: accept up to <strong>{penalty} min</strong> of detour per exposure-km
            </span>
            <input
              type="range" min={0} max={120} step={5} value={penalty}
              onChange={(e) => setPenalty(Number(e.target.value))}
              className="w-full"
            />
          </label>
          <p className="text-xs text-gray-500">
            0 = always the fastest route. This is your preference, not a probability that a road is passable.
          </p>
          <label className="flex items-start gap-2">
            <input
              type="checkbox" checked={fairnessFirst}
              onChange={(e) => setFairnessFirst(e.target.checked)}
              className="mt-0.5"
            />
            <span>
              <span className="text-gray-700">Fairness first</span>
              <span className="block text-xs text-gray-500">
                Every circle gets the same shortfall fraction, even if fewer people are covered overall.
                Off: cover the most people first, then spread what is left evenly.
              </span>
            </span>
          </label>
        </section>

        <section className="space-y-1">
          <label className="flex items-start gap-2">
            <input type="checkbox" checked={save} onChange={(e) => setSave(e.target.checked)} className="mt-0.5" />
            <span>
              <span className="text-gray-700">Save this plan as a record</span>
              <span className="block text-xs text-gray-500">
                Freezes the inputs, result, explanation and model versions so the plan can be reviewed and
                overridden later. Records cannot be edited.
              </span>
            </span>
          </label>
          {save && <OperatorAccess compact />}
          {save && (
            <input
              type="text"
              maxLength={120}
              placeholder="Label (optional)"
              value={label}
              onChange={(e) => setLabel(e.target.value)}
              className="w-full rounded border border-gray-300 px-2 py-1 text-xs"
            />
          )}
        </section>

        <button
          onClick={run}
          disabled={loading || !asOf}
          className="w-full rounded bg-teal-700 px-3 py-2 font-medium text-white disabled:opacity-50"
        >
          {loading ? "Planning…" : "Build plan"}
        </button>

        {plan && (
          <>
            <section className="space-y-1 rounded border border-gray-200 p-3">
              <div className="flex flex-wrap gap-2 text-xs">
                <span className={`rounded px-1.5 py-0.5 ${plan.is_replay ? "bg-indigo-50 text-indigo-800" : "bg-green-50 text-green-800"}`}>
                  {plan.is_replay ? `Replay of ${plan.as_of}` : `Live — report of ${plan.as_of}`}
                </span>
                {plan.example_inputs && (
                  <span className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-800">Example stock — demonstration only</span>
                )}
                <span className="rounded bg-gray-100 px-1.5 py-0.5 text-gray-700">
                  {plan.plan.policy === "fairness_first" ? "Fairness first" : "Coverage first"}
                </span>
              </div>
              <p className="pt-1">
                <strong>{pct(coverage)}</strong> of need at reachable circles covered · worst circle{" "}
                <strong>{pct(plan.plan.worst_shortfall_fraction)}</strong> short ·{" "}
                {n(plan.plan.truck_hours, 1)} truck-hours
              </p>
              <p className="text-xs text-gray-500">
                {plan.demand.totals.people_to_supply.toLocaleString()} people to supply;{" "}
                {n(plan.demand.totals.needs.water)} L water and {n(plan.demand.totals.needs.food)} ration-days
                over {plan.demand.horizon_days} day(s).
                {plan.plan.people_outside_plan > 0 && (
                  <span className="text-amber-800">
                    {" "}{plan.plan.people_outside_plan.toLocaleString()} of them are at circles this plan cannot
                    reach (listed below).
                  </span>
                )}
              </p>
            </section>

            {plan.recommendation_id && (
              <p className="rounded bg-teal-50 p-2 text-xs text-teal-900">
                Saved as a record.{" "}
                <Link href={`/recommendations/${plan.recommendation_id}`} className="underline underline-offset-2">
                  Open it to review or record an override
                </Link>
                .
              </p>
            )}

            <section>
              <h3 className="font-semibold">Why this plan</h3>
              <div className="mt-1">
                <PlanWhy explanation={plan.explanation} />
              </div>
            </section>

            {plan.plan.limits.length > 0 && (
              <section>
                <h3 className="font-semibold">What limits this plan</h3>
                <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-gray-700">
                  {plan.plan.limits.map((l, i) => (
                    <li key={i}>{l.plain}</li>
                  ))}
                </ul>
              </section>
            )}

            <section>
              <h3 className="font-semibold">Runs</h3>
              {plan.plan.runs.length === 0 ? (
                <p className="text-xs text-gray-500">No shipments.</p>
              ) : (
                <table className="mt-1 w-full text-xs">
                  <thead>
                    <tr className="text-left text-gray-500">
                      <th className="font-normal">From → to</th>
                      <th className="font-normal">Water</th>
                      <th className="font-normal">Food</th>
                      <th className="font-normal">Loads</th>
                      <th className="font-normal">One way</th>
                    </tr>
                  </thead>
                  <tbody>
                    {plan.plan.runs.map((r) => {
                      const route = plan.routes.find((x) => x.depot === r.depot && x.circle === r.circle);
                      return (
                        <tr key={`${r.depot}-${r.circle}`} className="border-t border-gray-100 align-top">
                          <td className="py-1 pr-1">
                            {r.depot} → {r.circle}
                            {route?.routes_diverge && (
                              <span className="block text-[11px] text-gray-500">
                                fastest {n(route.fastest.travel_min)} min / {n(route.fastest.exposure_km, 1)} exp-km vs
                                chosen {n(route.lower_exposure?.travel_min)} min / {n(route.lower_exposure?.exposure_km, 1)} exp-km
                              </span>
                            )}
                            {route?.local_delivery && (
                              <span className="block text-[11px] text-gray-500">same town, no road leg</span>
                            )}
                          </td>
                          <td className="py-1 pr-1 tabular-nums">{r.items.water != null ? `${n(r.items.water)} L` : "—"}</td>
                          <td className="py-1 pr-1 tabular-nums">{n(r.items.food)}</td>
                          <td className="py-1 pr-1 tabular-nums">{r.truckloads}</td>
                          <td className="py-1 tabular-nums">{n(r.one_way_min)} min</td>
                        </tr>
                      );
                    })}
                  </tbody>
                </table>
              )}
            </section>

            {plan.plan.shortfalls.length > 0 && (
              <section>
                <h3 className="font-semibold">Shortfalls</h3>
                <ul className="mt-1 space-y-0.5 text-xs text-red-700">
                  {plan.plan.shortfalls.map((s, i) => (
                    <li key={i}>
                      {s.circle}: {n(s.short)} {s.unit} of {s.commodity} short ({pct(s.fraction)}) — {s.reason}
                    </li>
                  ))}
                </ul>
              </section>
            )}

            {(plan.demand.totals.people_unlocated > 0 || plan.problems.length > 0 ||
              Object.keys(plan.demand.unattributed_by_district).length > 0) && (
              <section>
                <h3 className="font-semibold">Not planned for</h3>
                <ul className="mt-1 list-disc space-y-0.5 pl-4 text-xs text-amber-800">
                  {plan.demand.circles
                    .filter((c) => !c.location && c.people_to_supply > 0)
                    .map((c) => (
                      <li key={c.circle}>
                        {c.circle} ({c.district}): {c.people_to_supply.toLocaleString()} people — {c.location_problem}
                      </li>
                    ))}
                  {Object.entries(plan.demand.unattributed_by_district).map(([d, gap]) => (
                    <li key={d}>
                      {d}: {Object.values(gap).reduce((a, b) => a + b, 0).toLocaleString()} people reported for the
                      district but not assigned to a circle in the report
                    </li>
                  ))}
                  {plan.problems.map((p, i) => (
                    <li key={i}>{p}</li>
                  ))}
                </ul>
              </section>
            )}

            <section>
              <h3 className="font-semibold">Assumptions</h3>
              <ul className="mt-1 list-disc space-y-1 pl-4 text-xs text-gray-600">
                <li>Accessibility: {plan.risk.accessibility_source}.</li>
                {Object.values(plan.demand.norms).map((nm) => (
                  <li key={nm.label}>
                    {nm.label}: {nm.per_person_per_day} {nm.unit}/person/day, {nm.kg_per_unit} kg each ({nm.basis}). {nm.source}
                  </li>
                ))}
                {Object.entries(plan.caveats).map(([k, v]) => (
                  <li key={k}>{v}</li>
                ))}
              </ul>
            </section>
          </>
        )}
      </aside>
      <div className="h-[60vh] flex-1 md:h-auto">
        <LogisticsMap plan={plan} />
      </div>
    </div>
  );
}
