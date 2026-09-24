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
      <header className="wash flex flex-wrap items-baseline justify-between gap-x-4 gap-y-2 border-b border-line px-6 py-5">
        <div>
          <h1 className="text-[28px] font-extralight leading-tight tracking-[-0.02em]">Supply planning</h1>
          <p className="mt-1 text-caption text-muted">
            Who needs supplying, what can reach them, and what is stopping the rest.
          </p>
        </div>
        <nav className="flex gap-5 text-caption">
          <Link href="/accessibility" className="text-accent underline-grow">
            Accessibility model
          </Link>
          <Link href="/scenarios" className="text-accent underline-grow">
            Scenarios
          </Link>
          <Link href="/recommendations" className="text-accent underline-grow">
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
