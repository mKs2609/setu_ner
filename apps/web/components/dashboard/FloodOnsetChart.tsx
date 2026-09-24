/**
 * The 2025 Barak Valley flood, drawn from the two sources the system reads.
 *
 * WHY THIS REPLACED A PHOTOGRAPH
 * The satellite image of that week is solid cloud: true, and completely
 * uninformative to look at. This shows the same days in the data that was
 * actually available -- rainfall the microwave instruments measured through
 * the cloud, and the days the district appeared in the government report --
 * which is the point the section is making.
 *
 * HONEST BY CONSTRUCTION
 *   - Bars are millimetres, to scale, from the committed record.
 *   - A day with no published report is drawn as a gap, not as "no flood".
 *   - The onset marker sits where the report first listed the district, not
 *     where the story would be tidier.
 * Plain SVG, no chart library and no client JavaScript: it renders on the
 * server and is readable before anything hydrates.
 */

import { CACHAR_JUNE_2025, FIRST_AFFECTED } from "@/lib/floodEvent";

const WIDTH = 720;
const HEIGHT = 260;
const PAD = { top: 18, right: 14, bottom: 46, left: 38 };
const PLOT_H = HEIGHT - PAD.top - PAD.bottom;
const PLOT_W = WIDTH - PAD.left - PAD.right;

const MAX_MM = 100; // the record's peak is 89.7 mm; a round ceiling reads better
const days = CACHAR_JUNE_2025;
const band = PLOT_W / days.length;

function shortDate(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${Number(d)} ${["", "Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"][Number(m)]}`;
}

export default function FloodOnsetChart() {
  const onsetIndex = days.findIndex((d) => d.date === FIRST_AFFECTED);

  return (
    <figure className="card overflow-hidden">
      <div className="px-5 pt-5">
        <p className="font-mono text-micro uppercase tracking-[0.14em] text-accent">
          Cachar · 24 May – 18 June 2025
        </p>
        <p className="mt-1 text-caption text-muted">
          Rainfall, and the days the district was listed as flood-affected.
        </p>
      </div>

      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="mt-2 w-full"
        role="img"
        aria-label="Daily rainfall over Cachar from 24 May to 18 June 2025, with the days the district was listed as flood-affected. Rain rises through late May; the district is first listed on 30 May, and the heaviest day, 90 millimetres, falls on 31 May."
      >
        {/* Horizontal guides, in millimetres. */}
        {[0, 25, 50, 75, 100].map((mm) => {
          const y = PAD.top + PLOT_H - (mm / MAX_MM) * PLOT_H;
          return (
            <g key={mm}>
              <line
                x1={PAD.left}
                x2={WIDTH - PAD.right}
                y1={y}
                y2={y}
                stroke="var(--line)"
                strokeWidth={1}
              />
              <text
                x={PAD.left - 8}
                y={y + 3}
                textAnchor="end"
                fontSize={9}
                fill="var(--muted)"
                fontFamily="var(--font-jetbrains-mono), monospace"
              >
                {mm}
              </text>
            </g>
          );
        })}

        {/* The days the report listed the district: a band under the bars. */}
        {days.map((d, i) =>
          d.affected ? (
            <rect
              key={`a-${d.date}`}
              x={PAD.left + i * band}
              y={PAD.top + PLOT_H + 6}
              width={band - 2}
              height={7}
              rx={2}
              fill="var(--alert)"
              opacity={0.85}
            />
          ) : d.affected === null ? (
            // No report published: a gap, deliberately not a clear day.
            <rect
              key={`a-${d.date}`}
              x={PAD.left + i * band}
              y={PAD.top + PLOT_H + 8}
              width={band - 2}
              height={3}
              rx={1.5}
              fill="var(--line)"
            />
          ) : null,
        )}

        {/* Rainfall. */}
        {days.map((d, i) => {
          if (d.rain === null) return null;
          const h = Math.max(1.5, (Math.min(d.rain, MAX_MM) / MAX_MM) * PLOT_H);
          const heavy = d.rain >= 40;
          return (
            <rect
              key={`r-${d.date}`}
              x={PAD.left + i * band + 1}
              y={PAD.top + PLOT_H - h}
              width={band - 4}
              height={h}
              rx={2}
              fill={heavy ? "var(--accent-deep)" : "var(--accent)"}
              opacity={heavy ? 0.95 : 0.55}
            >
              <title>{`${shortDate(d.date)}: ${d.rain} mm${d.affected ? ", listed as affected" : ""}`}</title>
            </rect>
          );
        })}

        {/* Where the report first listed the district. */}
        {onsetIndex >= 0 && (
          <g>
            <line
              x1={PAD.left + onsetIndex * band}
              x2={PAD.left + onsetIndex * band}
              y1={PAD.top - 6}
              y2={PAD.top + PLOT_H + 16}
              stroke="var(--ink)"
              strokeWidth={1}
              strokeDasharray="3 3"
            />
            <text
              x={PAD.left + onsetIndex * band + 6}
              y={PAD.top + 2}
              fontSize={10}
              fill="var(--ink)"
              fontFamily="var(--font-jetbrains-mono), monospace"
            >
              first listed affected
            </text>
          </g>
        )}

        {/* Dates, every fourth day so they stay readable. */}
        {days.map((d, i) =>
          i % 4 === 0 ? (
            <text
              key={`t-${d.date}`}
              x={PAD.left + i * band + band / 2}
              y={HEIGHT - 20}
              textAnchor="middle"
              fontSize={9}
              fill="var(--muted)"
              fontFamily="var(--font-jetbrains-mono), monospace"
            >
              {shortDate(d.date)}
            </text>
          ) : null,
        )}
      </svg>

      <figcaption className="flex flex-wrap items-center gap-x-5 gap-y-2 border-t border-line px-5 py-3 font-mono text-micro text-muted">
        <span className="flex items-center gap-2">
          <span className="inline-block h-2 w-3 rounded-sm bg-accent-deep" /> rain, mm/day
        </span>
        <span className="flex items-center gap-2">
          <span className="inline-block h-2 w-3 rounded-sm bg-alert opacity-85" /> listed affected
        </span>
        <span className="flex items-center gap-2">
          <span className="inline-block h-1 w-3 rounded-sm bg-line" /> no report that day
        </span>
        <span className="ml-auto">NASA IMERG · ASDMA DRIMS</span>
      </figcaption>
    </figure>
  );
}
