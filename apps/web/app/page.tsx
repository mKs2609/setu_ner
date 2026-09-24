import Image from "next/image";
import Link from "next/link";

import { Reveal, ZoomImage } from "@/components/chrome/ScrollEffects";
import ActivityTicker from "@/components/dashboard/ActivityTicker";
import FloodOnsetChart from "@/components/dashboard/FloodOnsetChart";
import LiveConsole from "@/components/dashboard/LiveConsole";

/**
 * Home: a hero statement, then the live console.
 *
 * The order is deliberate. A visitor who knows nothing needs one sentence
 * about what this is; a visitor who already knows wants the numbers. So the
 * statement is one screen tall and the console starts immediately below it,
 * rather than three sections of explanation first.
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
    body: "Plan water and food runs to relief camps from real demand, on routes that weigh time against exposure to at-risk roads, with the binding constraints spelled out.",
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
    body: "The 2025 historical accessibility baseline every forecast is compared against.",
  },
];

const COMPARISON = [
  {
    src: "/imagery/brahmaputra-dry-2026-02-10.jpg",
    alt: "False-colour satellite view of the Assam valley in the dry season",
    title: "10 February 2026",
    note: "Dry season. The Brahmaputra is a thread inside its own bed.",
  },
  {
    src: "/imagery/brahmaputra-flood-2025-06-08.jpg",
    alt: "False-colour satellite view of the same valley in flood, the water spread wide",
    title: "8 June 2025",
    note: "The week 22 districts were listed as flood-affected in this project record.",
  },
];

export default function Home() {
  return (
    <div>
      {/* Hero: the corridor itself, from orbit, zooming out as you descend. */}
      <ZoomImage
        src="/imagery/corridor-clear.jpg"
        alt="Satellite view of the Barak Valley, Assam: forested ridges around a braided valley floor"
        className="min-h-[88vh] border-b border-line"
      >
        <div className="mx-auto flex min-h-[88vh] max-w-page flex-col justify-end px-6 pb-16 pt-28 sm:pb-20">
          <p className="font-mono text-micro uppercase tracking-[0.18em] text-white/70">
            Cachar · Karimganj · Hailakandi · Dima Hasao
          </p>
          <h1 className="mt-6 max-w-4xl text-display font-extralight text-white">
            Which roads still work <em className="not-italic text-accent-mist">tomorrow</em>.
          </h1>
          <p className="mt-8 max-w-2xl text-body font-medium text-white/85">
            Existing systems report that a flood is happening. SetuNER estimates which roads will
            still carry a truck tomorrow, and what can reach the people who need supplying — from
            daily government reports, satellite rainfall, terrain and reports from the ground.
          </p>
          <div className="mt-10 flex flex-wrap gap-3">
            <Link
              href="/accessibility"
              className="rounded-pill bg-accent px-6 py-3 text-ui font-medium text-white transition-colors hover:bg-accent-deep"
            >
              Open the forecast
            </Link>
            <Link
              href="/logistics"
              className="rounded-pill border border-white/40 px-6 py-3 text-ui font-medium text-white backdrop-blur transition-colors hover:border-white hover:bg-white/10"
            >
              Plan a delivery
            </Link>
          </div>
          <p className="mt-10 font-mono text-micro text-white/55">
            The Barak Valley · MODIS Terra · 10 Feb 2026 · NASA Worldview
          </p>
        </div>
      </ZoomImage>

      <div className="mx-auto max-w-page px-6">
      {/* Live console */}
      <section className="py-12">
        <LiveConsole />
        <div className="mt-4">
          <ActivityTicker />
        </div>
      </section>

      {/* What a flood looks like from orbit, in the project own record. */}
      <Reveal>
        <section className="border-t border-line py-14">
          <h2 className="font-mono text-micro uppercase tracking-[0.18em] text-muted">
            What the water does
          </h2>
          <p className="mt-4 max-w-3xl text-heading font-extralight">
            The same valley, eight months apart.
          </p>
          <div className="mt-8 grid gap-4 md:grid-cols-2">
            {COMPARISON.map((img) => (
              <figure key={img.src} className="card overflow-hidden">
                <div className="relative aspect-[1600/480]">
                  <Image
                    src={img.src}
                    alt={img.alt}
                    fill
                    sizes="(min-width: 768px) 50vw, 100vw"
                    className="object-cover"
                  />
                </div>
                <figcaption className="px-4 py-3">
                  <p className="font-mono text-micro uppercase tracking-[0.14em] text-accent">
                    {img.title}
                  </p>
                  <p className="mt-1 text-caption text-muted">{img.note}</p>
                </figcaption>
              </figure>
            ))}
          </div>
          <p className="mt-4 max-w-3xl text-caption text-muted">
            False colour: water reads as deep blue, vegetation as green, cloud as white.
            MODIS Terra bands 7-2-1, NASA Worldview.
          </p>
        </section>
      </Reveal>

      {/* The event itself: what the data said while it was happening, then
          the picture that only arrived afterwards. */}
      <Reveal>
        <section className="border-t border-line py-14">
          <h2 className="font-mono text-micro uppercase tracking-[0.18em] text-muted">
            The 2025 flood, as it happened
          </h2>
          <p className="mt-4 max-w-3xl text-heading font-extralight">
            The rain arrives days before the report does.
          </p>

          <div className="mt-8 grid gap-8 lg:grid-cols-[1.3fr_1fr] lg:items-start">
            <FloodOnsetChart />

            <div className="space-y-5">
              <div>
                <h3 className="text-ui font-medium">What the chart shows</h3>
                <p className="mt-2 text-ui text-muted">
                  Each bar is a day of rainfall over Cachar, measured by satellite. The red band
                  underneath marks the days the government report listed the district as
                  flood-affected, and the dashed line is the first of them.
                </p>
              </div>

              <div>
                <h3 className="text-ui font-medium">Why it matters</h3>
                <p className="mt-2 text-ui text-muted">
                  Rain builds from <span className="text-ink">25 May</span>, five days before the
                  district appears in any report. The heaviest day of all —{" "}
                  <span className="text-ink">90 mm on 31 May</span> — lands after the flood is
                  already declared. A system that waits for the report is always reading the past;
                  the rainfall was there to be read the whole time.
                </p>
              </div>

              <div>
                <h3 className="text-ui font-medium">What is not claimed</h3>
                <p className="mt-2 text-ui text-muted">
                  This is one district in one season, shown to explain the idea. Whether rainfall
                  actually improves the forecast is a separate question, tested properly and
                  answered honestly on the{" "}
                  <Link href="/accessibility" className="text-accent underline-grow">
                    forecast page
                  </Link>
                  : it won on the held-out season, lost on validation, and is now on trial rather
                  than in service.
                </p>
              </div>
            </div>
          </div>

          {/* The picture, and how late it was. */}
          <div className="mt-10 grid gap-8 md:grid-cols-[1.2fr_1fr] md:items-center">
            <figure className="card overflow-hidden">
              <div className="relative aspect-[1440/1200]">
                <Image
                  src="/imagery/corridor-flooded-2025-06-12.jpg"
                  alt="False-colour satellite view of the Barak Valley on 12 June 2025, with standing floodwater visible as dark navy across the valley floor"
                  fill
                  sizes="(min-width: 768px) 55vw, 100vw"
                  className="object-cover"
                />
              </div>
              <figcaption className="px-5 py-3">
                <p className="font-mono text-micro uppercase tracking-[0.14em] text-accent">
                  12 June 2025 · the corridor, finally visible
                </p>
                <p className="mt-1 text-caption text-muted">
                  Dark navy is water standing on the valley floor. MODIS Terra bands 7-2-1.
                </p>
              </figcaption>
            </figure>

            <div>
              <h3 className="text-ui font-medium">And this is the picture</h3>
              <p className="mt-3 text-body text-muted">
                It is a clear view of the flooded corridor — and it is dated{" "}
                <span className="text-ink">12 June</span>, thirteen days after the district was
                first listed and long after the trucks needed routing.
              </p>
              <p className="mt-4 text-body text-muted">
                On 1 June, the day it flooded, the same satellite returned solid cloud. That is
                the ordinary case during a monsoon, not bad luck: the weather that causes the
                flood is the weather that hides it. Radar can see through cloud, which is why
                Sentinel-1 flood extent is on the roadmap and honestly marked as not built.
              </p>
            </div>
          </div>
        </section>
      </Reveal>

      {/* Screens */}
      <Reveal>
        <section className="border-t border-line py-12">
        <h2 className="font-mono text-micro uppercase tracking-[0.18em] text-muted">Screens</h2>
        <div className="mt-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          {SCREENS.map((s) => (
            <Link
              key={s.href}
              href={s.href}
              className="lift card group p-5"
            >
              <h3 className="text-ui font-medium text-ink group-hover:text-accent">
                {s.title} →
              </h3>
              <p className="mt-2 text-ui leading-relaxed text-muted">{s.body}</p>
            </Link>
          ))}
        </div>
        </section>
      </Reveal>

      {/* What it is built on, and what it does not claim. */}
      <Reveal>
        <section className="grid gap-10 border-t border-line py-12 md:grid-cols-2">
        <div>
          <h2 className="font-mono text-micro uppercase tracking-[0.18em] text-muted">Built on</h2>
          <ul className="mt-4 space-y-3 text-ui text-ink">
            <li>110,266 road segments from OpenStreetMap, with terrain from the Copernicus DEM</li>
            <li>ASDMA DRIMS daily flood reports since May 2025, ingested every morning</li>
            <li>NASA GPM IMERG satellite rainfall, one file per day</li>
            <li>Relief-camp populations per revenue circle, from the same reports</li>
          </ul>
        </div>
        <div>
          <h2 className="font-mono text-micro uppercase tracking-[0.18em] text-muted">What it does not claim</h2>
          <ul className="mt-4 space-y-3 text-ui text-muted">
            <li>
              <span className="text-ink">Rainfall is collected but not yet served</span> — a model
              using it has to beat the current one on days neither has seen first.
            </li>
            <li>
              <span className="text-ink">Per-road risk uses a stated terrain assumption</span>, not
              a fitted model.
            </li>
            <li>
              <span className="text-ink">Depot stock and fleet are operator inputs</span>; the
              defaults are examples.
            </li>
            <li>
              <span className="text-ink">Not an official advisory service.</span> It is an
              engineering project built on public data.
            </li>
          </ul>
        </div>
        </section>
      </Reveal>
      </div>
    </div>
  );
}
