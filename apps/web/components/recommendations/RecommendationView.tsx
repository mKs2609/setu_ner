"use client";

/**
 * One saved recommendation: what was decided, why, and what operators did.
 *
 * The record is shown as frozen, with its report day and model versions,
 * because it will usually be read after conditions have moved on. The
 * override form requires a reason: an override without one teaches nothing.
 */

import { useCallback, useEffect, useState } from "react";

import OperatorAccess from "@/components/auth/OperatorAccess";
import PlanWhy from "@/components/explain/PlanWhy";
import {
  fetchOverrides,
  fetchRecommendation,
  fetchRecommendationExplanation,
  postOverride,
  REASON_CATEGORIES,
  type OverrideAction,
  type OverrideRecord,
  type PlanExplanation,
  type RecommendationRecord,
} from "@/lib/api";

function pct(v: number | null | undefined) {
  return v == null ? "—" : `${Math.round(v * 100)}%`;
}

export default function RecommendationView({ id }: { id: string }) {
  const [rec, setRec] = useState<RecommendationRecord | null>(null);
  const [why, setWhy] = useState<PlanExplanation | null>(null);
  const [overrides, setOverrides] = useState<OverrideRecord[]>([]);
  const [error, setError] = useState<string | null>(null);

  const [action, setAction] = useState<OverrideAction>("modified");
  const [category, setCategory] = useState<string>(REASON_CATEGORIES[0][0]);
  const [target, setTarget] = useState("");
  const [reason, setReason] = useState("");
  const [sending, setSending] = useState(false);
  const [formError, setFormError] = useState<string | null>(null);

  useEffect(() => {
    Promise.all([fetchRecommendation(id), fetchRecommendationExplanation(id), fetchOverrides(id)])
      .then(([r, w, o]) => {
        setRec(r);
        setWhy(w);
        setOverrides(o);
      })
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load the record"));
  }, [id]);

  const submit = useCallback(async () => {
    setSending(true);
    setFormError(null);
    try {
      const row = await postOverride(id, {
        action,
        reason_category: category,
        reason: reason.trim(),
        target: target.trim() || undefined,
      });
      setOverrides((o) => [...o, row]);
      setReason("");
      setTarget("");
    } catch (e) {
      setFormError(e instanceof Error ? e.message : "Could not record the override");
    } finally {
      setSending(false);
    }
  }, [id, action, category, reason, target]);

  if (error) return <p className="p-4 text-sm text-red-700">{error}</p>;
  if (!rec || !why) return <p className="p-4 text-sm text-gray-500">Loading…</p>;

  const runs = rec.outputs.plan.runs ?? [];

  return (
    <div className="mx-auto grid max-w-6xl gap-6 p-4 text-sm md:grid-cols-[1fr_22rem]">
      <div className="space-y-4">
        <section className="space-y-1">
          <h2 className="text-lg font-semibold">{rec.label || "Supply plan"}</h2>
          <div className="flex flex-wrap gap-2 text-xs">
            <span className="rounded bg-gray-100 px-1.5 py-0.5">
              Saved {new Date(rec.created_at).toLocaleString()}
            </span>
            <span className="rounded bg-indigo-50 px-1.5 py-0.5 text-indigo-800">
              Demand from the {rec.data_as_of} report{rec.is_replay ? " (replay)" : ""}
            </span>
            {rec.example_inputs && (
              <span className="rounded bg-amber-50 px-1.5 py-0.5 text-amber-800">
                Example stock — demonstration only
              </span>
            )}
          </div>
          <p className="text-xs text-amber-800">{rec.note}</p>
          <p>
            {rec.people_to_supply?.toLocaleString()} people · {pct(rec.coverage)} of need covered · worst circle{" "}
            {pct(rec.worst_shortfall_fraction)} short
          </p>
        </section>

        <section>
          <h3 className="font-semibold">Why this plan</h3>
          <div className="mt-1">
            <PlanWhy explanation={why} />
          </div>
        </section>

        <section>
          <h3 className="font-semibold">Runs as planned</h3>
          <table className="mt-1 w-full text-xs">
            <thead>
              <tr className="text-left text-gray-500">
                <th className="font-normal">From → to</th>
                <th className="font-normal">Water (L)</th>
                <th className="font-normal">Food</th>
                <th className="font-normal">Loads</th>
              </tr>
            </thead>
            <tbody>
              {runs.map((r) => (
                <tr key={`${r.depot}-${r.circle}`} className="border-t border-gray-100">
                  <td className="py-1">
                    {r.depot} → {r.circle}
                  </td>
                  <td className="py-1 tabular-nums">{r.items.water?.toLocaleString() ?? "—"}</td>
                  <td className="py-1 tabular-nums">{r.items.food?.toLocaleString() ?? "—"}</td>
                  <td className="py-1 tabular-nums">{r.truckloads}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </section>

        <section>
          <h3 className="font-semibold">Model and data versions</h3>
          <ul className="mt-1 text-xs text-gray-600">
            {Object.entries(rec.model_versions).map(([k, v]) => (
              <li key={k}>
                {k}: <span className="font-mono">{v ?? "—"}</span>
              </li>
            ))}
          </ul>
        </section>
      </div>

      <aside className="space-y-4">
        <section className="space-y-2 rounded border border-gray-200 p-3">
          <h3 className="font-semibold">Record an override</h3>
          <p className="text-xs text-gray-500">
            What you did instead of the plan, and why. Appended to the record; nothing here edits the plan.
          </p>
          <select
            value={action}
            onChange={(e) => setAction(e.target.value as OverrideAction)}
            className="w-full rounded border border-gray-300 px-2 py-1 text-xs"
          >
            <option value="accepted">Accepted as planned</option>
            <option value="modified">Modified</option>
            <option value="rejected">Rejected</option>
          </select>
          <select
            value={category}
            onChange={(e) => setCategory(e.target.value)}
            className="w-full rounded border border-gray-300 px-2 py-1 text-xs"
          >
            {REASON_CATEGORIES.map(([k, l]) => (
              <option key={k} value={k}>
                {l}
              </option>
            ))}
          </select>
          <input
            value={target}
            onChange={(e) => setTarget(e.target.value)}
            maxLength={200}
            placeholder="Which run? e.g. run:Silchar->Sonai (optional)"
            className="w-full rounded border border-gray-300 px-2 py-1 text-xs"
          />
          <textarea
            value={reason}
            onChange={(e) => setReason(e.target.value)}
            maxLength={1000}
            rows={3}
            placeholder="Reason (required)"
            className="w-full rounded border border-gray-300 px-2 py-1 text-xs"
          />
          <OperatorAccess compact />
          {formError && <p className="text-xs text-red-700">{formError}</p>}
          <button
            onClick={submit}
            disabled={sending || reason.trim().length < 5}
            className="w-full rounded bg-teal-700 px-3 py-1.5 text-xs font-medium text-white disabled:opacity-50"
          >
            {sending ? "Recording…" : "Record override"}
          </button>
        </section>

        <section>
          <h3 className="font-semibold">Overrides ({overrides.length})</h3>
          {overrides.length === 0 ? (
            <p className="text-xs text-gray-500">None recorded.</p>
          ) : (
            <ul className="mt-1 space-y-2">
              {overrides.map((o) => (
                <li key={o.id} className="rounded bg-gray-50 p-2 text-xs">
                  <p className="font-medium">
                    {o.action} ·{" "}
                    {REASON_CATEGORIES.find(([k]) => k === o.reason_category)?.[1] ?? o.reason_category}
                  </p>
                  {o.target && <p className="text-gray-600">{o.target}</p>}
                  <p className="text-gray-800">{o.reason}</p>
                  <p className="text-[10px] text-gray-500">{new Date(o.created_at).toLocaleString()}</p>
                </li>
              ))}
            </ul>
          )}
        </section>
      </aside>
    </div>
  );
}
