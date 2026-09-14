import Link from "next/link";

import LogisticsWorkbench from "@/components/logistics/LogisticsWorkbench";

export const metadata = {
  title: "Supply planning — SetuNER",
  description:
    "Plan water and food runs to relief camps in the Barak Valley from real DRIMS demand, depot stock and the accessibility forecast.",
};

export default function LogisticsPage() {
  return (
    <main className="flex min-h-screen w-full flex-col md:h-screen md:overflow-hidden">
      <header className="flex flex-wrap items-baseline justify-between gap-x-4 border-b border-gray-200 px-4 py-3">
        <div>
          <h1 className="text-xl font-semibold">SetuNER — Supply planning</h1>
          <p className="text-sm text-gray-600">
            Who needs supplying, what can reach them, and what is stopping the rest.
          </p>
        </div>
        <nav className="flex gap-4 text-sm">
          <Link href="/accessibility" className="text-teal-700 underline underline-offset-2">
            Accessibility model
          </Link>
          <Link href="/scenarios" className="text-teal-700 underline underline-offset-2">
            Scenarios
          </Link>
          <Link href="/recommendations" className="text-teal-700 underline underline-offset-2">
            Saved plans
          </Link>
        </nav>
      </header>
      <div className="flex-1 md:overflow-hidden">
        <LogisticsWorkbench />
      </div>
    </main>
  );
}
