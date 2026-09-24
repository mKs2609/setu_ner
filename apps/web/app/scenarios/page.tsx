import Link from "next/link";

import ScenarioWorkbench from "@/components/scenario/ScenarioWorkbench";

export const metadata = {
  title: "Scenarios — SetuNER",
  description:
    "Close or flood a set of roads and see what it does to the route through the Barak Valley corridor.",
};

export default function ScenariosPage() {
  // The full-height split only applies from md up. On a narrow screen the
  // control panel alone is taller than the viewport, so forcing h-screen
  // there would clip the results rather than letting the page scroll.
  return (
    <main className="flex min-h-screen w-full flex-col md:h-screen md:overflow-hidden">
      <header className="wash flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2 border-b border-line px-6 py-5">
        <div>
          <h1 className="text-[28px] font-extralight leading-tight tracking-[-0.02em]">Scenario workbench</h1>
          <p className="mt-1 text-caption text-muted">
            What-if analysis on the real corridor. Routes are recomputed live over 110,266 road
            segments.
          </p>
        </div>
        <Link href="/dashboard" className="text-caption text-accent underline-grow">
          Accessibility map
        </Link>
      </header>
      <div className="flex-1 md:overflow-hidden">
        <ScenarioWorkbench />
      </div>
    </main>
  );
}
