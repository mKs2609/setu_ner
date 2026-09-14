import Link from "next/link";

import RecommendationView from "@/components/recommendations/RecommendationView";

export const metadata = {
  title: "Saved plan — SetuNER",
};

export default function RecommendationPage({ params }: { params: { id: string } }) {
  return (
    <main className="min-h-screen w-full">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 border-b border-gray-200 px-4 py-3">
        <h1 className="text-xl font-semibold">SetuNER — Saved plan</h1>
        <nav className="flex gap-4 text-sm">
          <Link href="/recommendations" className="text-teal-700 underline underline-offset-2">
            All saved plans
          </Link>
          <Link href="/logistics" className="text-teal-700 underline underline-offset-2">
            Supply planning
          </Link>
        </nav>
      </header>
      <RecommendationView id={params.id} />
    </main>
  );
}
