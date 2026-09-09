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
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 border-b border-gray-200 px-4 py-3">
        <div>
          <h1 className="text-xl font-semibold">SetuNER — Field reports</h1>
          <p className="text-sm text-gray-600">
            Ground truth from people on the road, fused by reporter trust and recency.
          </p>
        </div>
        <nav className="flex gap-4 text-sm">
          <Link href="/dashboard" className="text-teal-700 underline underline-offset-2">
            Accessibility map
          </Link>
          <Link href="/scenarios" className="text-teal-700 underline underline-offset-2">
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
