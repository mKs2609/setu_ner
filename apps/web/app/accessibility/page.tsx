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
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 border-b border-gray-200 px-4 py-3">
        <div>
          <h1 className="text-xl font-semibold">SetuNER — Accessibility model</h1>
          <p className="text-sm text-gray-600">
            A forecast, with its evaluation and its limits on the same screen.
          </p>
        </div>
        <nav className="flex gap-4 text-sm">
          <Link href="/dashboard" className="text-teal-700 underline underline-offset-2">
            Baseline map
          </Link>
          <Link href="/scenarios" className="text-teal-700 underline underline-offset-2">
            Scenarios
          </Link>
          <Link href="/logistics" className="text-teal-700 underline underline-offset-2">
            Supply planning
          </Link>
        </nav>
      </header>
      <AccessibilityWorkbench />
    </main>
  );
}
