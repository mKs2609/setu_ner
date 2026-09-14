import Link from "next/link";

import RecommendationList from "@/components/recommendations/RecommendationList";

export const metadata = {
  title: "Saved plans — SetuNER",
  description: "Saved supply plans, their explanations, and the overrides operators recorded against them.",
};

export default function RecommendationsPage() {
  return (
    <main className="min-h-screen w-full">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 border-b border-gray-200 px-4 py-3">
        <div>
          <h1 className="text-xl font-semibold">SetuNER — Saved plans</h1>
          <p className="text-sm text-gray-600">An audit trail: what was planned, why, and what was done instead.</p>
        </div>
        <Link href="/logistics" className="text-sm text-teal-700 underline underline-offset-2">
          Supply planning
        </Link>
      </header>
      <RecommendationList />
    </main>
  );
}
