import Link from "next/link";

import RecommendationView from "@/components/recommendations/RecommendationView";

export const metadata = {
  title: "Saved plan — SetuNER",
};

export default function RecommendationPage({ params }: { params: { id: string } }) {
  return (
    <main className="min-h-screen w-full">
      <header className="wash flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2 border-b border-line px-6 py-5">
        <h1 className="text-[28px] font-extralight leading-tight tracking-[-0.02em]">Saved plan</h1>
        <nav className="flex gap-5 text-caption">
          <Link href="/recommendations" className="text-accent underline-grow">
            All saved plans
          </Link>
          <Link href="/logistics" className="text-accent underline-grow">
            Supply planning
          </Link>
        </nav>
      </header>
      <RecommendationView id={params.id} />
    </main>
  );
}
