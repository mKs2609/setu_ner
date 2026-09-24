import Link from "next/link";

import RecommendationList from "@/components/recommendations/RecommendationList";

export const metadata = {
  title: "Saved plans — SetuNER",
  description: "Saved supply plans, their explanations, and the overrides operators recorded against them.",
};

export default function RecommendationsPage() {
  return (
    <main className="min-h-screen w-full">
      <header className="wash flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2 border-b border-line px-6 py-5">
        <div>
          <h1 className="text-[28px] font-extralight leading-tight tracking-[-0.02em]">Saved plans</h1>
          <p className="mt-1 text-caption text-muted">An audit trail: what was planned, why, and what was done instead.</p>
        </div>
        <Link href="/logistics" className="text-caption text-accent underline-grow">
          Supply planning
        </Link>
      </header>
      <RecommendationList />
    </main>
  );
}
