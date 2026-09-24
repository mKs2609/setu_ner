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

  if (error) return <p className="p-4 text-sm text-alert">{error}</p>;
  if (!items) return <p className="p-4 text-sm text-muted">Loading…</p>;
  if (items.length === 0) {
    return (
      <p className="p-4 text-sm text-muted">
        No saved plans yet. Tick &ldquo;Save this plan as a record&rdquo; on the{" "}
        <Link href="/logistics" className="text-accent underline-grow">
          supply planning
        </Link>{" "}
        screen.
      </p>
    );
  }
  return (
    <div className="m-6 card overflow-hidden">
      <table className="w-full text-ui">
        <thead>
          <tr className="border-b border-line text-left font-mono text-micro uppercase tracking-[0.12em] text-muted [&>th]:px-4 [&>th]:py-3">
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
            <tr key={r.id} className="border-t border-line transition-colors hover:bg-accent-wash/40 [&>td]:px-4 [&>td]:py-3">
              <td>
                <Link href={`/recommendations/${r.id}`} className="text-accent underline-grow">
                  {r.label || r.id.slice(0, 8)}
                </Link>
                {r.example_inputs && <span className="ml-2 text-xs text-caution">example stock</span>}
              </td>
              <td>
                {r.data_as_of}
                {r.is_replay ? " (replay)" : ""}
              </td>
              <td className="tabular-nums">{r.people_to_supply?.toLocaleString() ?? "—"}</td>
              <td className="tabular-nums">{r.coverage == null ? "—" : `${Math.round(r.coverage * 100)}%`}</td>
              <td className="tabular-nums">{r.override_count ?? 0}</td>
              <td className="text-xs text-muted">{new Date(r.created_at).toLocaleString()}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
