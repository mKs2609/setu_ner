import Link from "next/link";

/**
 * Landing page. States what the system does, where its data comes from and
 * what it does not claim, then points at the working screens. Every figure
 * here is a property of the deployed data, not a projection.
 */

const SCREENS = [
  {
    href: "/accessibility",
    title: "Accessibility model",
    body: "Next-day flood forecasts for every Assam district, turned into per-road accessibility for the corridor — each one explained, and judged against a persistence baseline.",
  },
  {
    href: "/logistics",
    title: "Supply planning",
    body: "Plan water and food runs to relief camps from real DRIMS demand, on routes that weigh time against exposure to at-risk roads, with the binding constraints spelled out.",
  },
  {
    href: "/scenarios",
    title: "Scenarios",
    body: "Close or flood roads and bridges and see what it does to a route across the Barak Valley — the corridor's single points of failure made visible.",
  },
  {
    href: "/field-reports",
    title: "Field reports",
    body: "Report a road as clear, slow or blocked. Reports are weighted by reporter trust and checked against official damage data.",
  },
  {
    href: "/recommendations",
    title: "Saved plans",
    body: "An audit trail: plans frozen with their inputs, explanation and model versions, and the overrides operators recorded against them.",
  },
  {
    href: "/dashboard",
    title: "Baseline map",
    body: "The 2025 historical accessibility baseline for every road the model is compared against.",
  },
];

export default function Home() {
  return (
    <main className="mx-auto max-w-5xl px-6 py-10">
      <p className="text-sm font-medium text-teal-700">SIH 2026 · PS SIH26002 · MDoNER</p>
      <h1 className="mt-1 text-3xl font-semibold">SetuNER</h1>
      <p className="mt-2 max-w-3xl text-gray-700">
        Road accessibility forecasting and relief logistics for the Barak Valley corridor in Assam —
        Cachar, Karimganj, Hailakandi and Dima Hasao. Existing systems report that a flood is happening;
        this estimates which roads will still work tomorrow, and what can reach the people who need
        supplying.
      </p>

      <div className="mt-8 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
        {SCREENS.map((s) => (
          <Link
            key={s.href}
            href={s.href}
            className="rounded-lg border border-gray-200 p-4 transition hover:border-teal-600 hover:shadow-sm"
          >
            <h2 className="font-semibold text-teal-800">{s.title} →</h2>
            <p className="mt-1 text-sm text-gray-600">{s.body}</p>
          </Link>
        ))}
      </div>

      <section className="mt-10 grid gap-6 text-sm text-gray-700 md:grid-cols-2">
        <div>
          <h2 className="font-semibold text-gray-900">Built on</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>110,266 road segments from OpenStreetMap, with terrain from the Copernicus DEM</li>
            <li>ASDMA DRIMS daily flood reports since May 2025, ingested every day</li>
            <li>Relief-camp populations per revenue circle, from the same reports</li>
            <li>Field reports from people on the ground</li>
          </ul>
        </div>
        <div>
          <h2 className="font-semibold text-gray-900">What it does not claim</h2>
          <ul className="mt-2 list-disc space-y-1 pl-5">
            <li>Rainfall is collected daily but not yet used by the served model — it has to beat it on new days first</li>
            <li>Per-road risk uses a stated terrain assumption, not a fitted model</li>
            <li>Depot stock and fleet are operator inputs; the defaults are examples</li>
          </ul>
        </div>
      </section>

      <p className="mt-10 text-xs text-gray-500">
        The API runs on a free instance that sleeps when idle: the first request after a quiet spell can
        take up to a minute.
      </p>
    </main>
  );
}
