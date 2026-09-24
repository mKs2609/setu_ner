import Link from "next/link";

import AccessibilityWorkbench from "@/components/map/AccessibilityWorkbench";

export const metadata = {
  title: "Accessibility model — SetuNER",
  description:
    "Next-day district flood-state forecasts for Assam, turned into per-road accessibility for the Barak Valley corridor, shown next to the baselines they have to beat.",
};

export default function AccessibilityPage() {
  // Same split as the scenario and field-report screens: side by side from
  // md up, stacked and scrolling below that.
  return (
    <main className="flex min-h-screen w-full flex-col md:h-screen md:overflow-hidden">
      <header className="wash flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2 border-b border-line px-6 py-5">
        <div>
          <h1 className="text-[28px] font-extralight leading-tight tracking-[-0.02em]">Accessibility model</h1>
          <p className="mt-1 text-caption text-muted">
            A forecast, with its evaluation and its limits on the same screen.
          </p>
        </div>
        <nav className="flex gap-5 text-caption">
          <Link href="/dashboard" className="text-accent underline-grow">
            Baseline map
          </Link>
          <Link href="/scenarios" className="text-accent underline-grow">
            Scenarios
          </Link>
          <Link href="/logistics" className="text-accent underline-grow">
            Supply planning
          </Link>
        </nav>
      </header>
      <AccessibilityWorkbench />
    </main>
  );
}
