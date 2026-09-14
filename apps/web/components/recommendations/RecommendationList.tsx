"use client";

import Link from "next/link";
import { useEffect, useState } from "react";

import { fetchRecommendations, type RecommendationSummary } from "@/lib/api";

export default function RecommendationList() {
  const [items, setItems] = useState<RecommendationSummary[] | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchRecommendations()
      .then(setItems)
      .catch((e) => setError(e instanceof Error ? e.message : "Could not load records"));
  }, []);

  if (error) return <p className="p-4 text-sm text-red-700">{error}</p>;
  if (!items) return <p className="p-4 text-sm text-gray-500">Loading…</p>;
  if (items.length === 0) {
    return (
      <p className="p-4 text-sm text-gray-600">
        No saved plans yet. Tick &ldquo;Save this plan as a record&rdquo; on the{" "}
        <Link href="/logistics" className="text-teal-700 underline underline-offset-2">
          supply planning
        </Link>{" "}
        screen.
      </p>
    );
  }
  return (
    <div className="overflow-x-auto p-4">
      <table className="w-full text-sm">
        <thead>
          <tr className="text-left text-xs text-gray-500">
            <th className="font-normal">Plan</th>
            <th className="font-normal">Report day</th>
            <th className="font-normal">People</th>
            <th className="font-normal">Covered</th>
            <th className="font-normal">Overrides</th>
            <th className="font-normal">Saved</th>
          </tr>
        </thead>
        <tbody>
          {items.map((r) => (
            <tr key={r.id} className="border-t border-gray-100">
              <td className="py-1.5">
                <Link href={`/recommendations/${r.id}`} className="text-teal-700 underline underline-offset-2">
                  {r.label || r.id.slice(0, 8)}
                </Link>
                {r.example_inputs && <span className="ml-2 text-xs text-amber-700">example stock</span>}
              </td>
              <td>
                {r.data_as_of}
                {r.is_replay ? " (replay)" : ""}
              </td>
              <td className="tabular-nums">{r.people_to_supply?.toLocaleString() ?? "—"}</td>
              <td className="tabular-nums">{r.coverage == null ? "—" : `${Math.round(r.coverage * 100)}%`}</td>
              <td className="tabular-nums">{r.override_count ?? 0}</td>
              <td className="text-xs text-gray-500">{new Date(r.created_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
