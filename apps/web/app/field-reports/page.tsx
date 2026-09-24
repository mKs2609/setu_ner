import Link from "next/link";

import FieldReportsWorkbench from "@/components/field-reports/FieldReportsWorkbench";

export const metadata = {
  title: "Field reports — SetuNER",
  description:
    "Report road conditions from the ground, and see what everyone else is reporting across the Barak Valley corridor.",
};

export default function FieldReportsPage() {
  // Full-height split only from md up; below that the form alone is taller
  // than a phone viewport, and this is the one screen most likely to be used
  // on a phone.
  return (
    <main className="flex min-h-screen w-full flex-col md:h-screen md:overflow-hidden">
      <header className="wash flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2 border-b border-line px-6 py-5">
        <div>
          <h1 className="text-[28px] font-extralight leading-tight tracking-[-0.02em]">Field reports</h1>
          <p className="mt-1 text-caption text-muted">
            Ground truth from people on the road, fused by reporter trust and recency.
          </p>
        </div>
        <nav className="flex gap-5 text-caption">
          <Link href="/dashboard" className="text-accent underline-grow">
            Accessibility map
          </Link>
          <Link href="/scenarios" className="text-accent underline-grow">
            Scenarios
          </Link>
        </nav>
      </header>
      <div className="flex-1 md:overflow-hidden">
        <FieldReportsWorkbench />
      </div>
    </main>
  );
}
