/**
 * Does 12% mean 12%?
 *
 * WHY THIS IS HERE AT ALL
 * The page already reports Brier and AUC. Brier says the numbers are close
 * on average; AUC says the risky days are ranked above the quiet ones.
 * Neither answers the question somebody routing a truck is actually asking,
 * and a model can score well on both while being reliably overconfident.
 *
 * HOW TO READ IT
 * Every forecast is sorted into a band by what it predicted. For each band,
 * one dot: across the bottom what the model said, up the side what actually
 * happened. A perfectly honest model sits on the diagonal. Above it means it
 * understated the risk; below means it cried wolf. Dot area is proportional
 * to how many forecasts are in the band, because a dot built from 32
 * district-days deserves less of your attention than one built from 1,574.
 *
 * Plain SVG, no chart library and no client JavaScript: it renders on the
 * server and is readable before anything hydrates.
 */

import type { Calibration } from "@/lib/api";

const WIDTH = 420;
const HEIGHT = 420;
const PAD = { top: 16, right: 16, bottom: 44, left: 48 };
const PLOT = { w: WIDTH - PAD.left - PAD.right, h: HEIGHT - PAD.top - PAD.bottom };

const TICKS = [0, 0.25, 0.5, 0.75, 1];

/** Square root, so a band's *area* tracks its count rather than its radius. */
function radius(n: number, biggest: number): number {
  if (!n) return 0;
  return 3 + 9 * Math.sqrt(n / biggest);
}

const x = (v: number) => PAD.left + v * PLOT.w;
const y = (v: number) => PAD.top + PLOT.h - v * PLOT.h;

export default function ReliabilityChart({
  calibration,
  caption,
}: {
  calibration: Calibration;
  caption?: string;
}) {
  const bins = calibration.bins.filter(
    (b) => b.n > 0 && b.predicted !== null && b.observed !== null
  );
  if (!bins.length) return null;

  const biggest = Math.max(...bins.map((b) => b.n));
  const d = calibration.decomposition;

  return (
    <figure className="card overflow-hidden">
      <div className="px-5 pt-5">
        <p className="font-mono text-micro uppercase tracking-[0.14em] text-accent">
          Does the probability mean what it says
        </p>
        <p className="mt-1 text-caption text-muted">
          {calibration.n.toLocaleString()} forecasts
          {calibration.period ? ` · ${calibration.period.from} to ${calibration.period.to}` : ""}
          {calibration.served_kind ? ` · ${calibration.served_kind}` : ""}
        </p>
      </div>

      <svg
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        className="mt-2 w-full"
        role="img"
        aria-label={
          `Reliability diagram over ${calibration.n} forecasts. ` +
          bins
            .map(
              (b) =>
                `Predicted ${(b.predicted! * 100).toFixed(0)} percent, observed ` +
                `${(b.observed! * 100).toFixed(0)} percent, over ${b.n} district-days.`
            )
            .join(" ")
        }
      >
        {TICKS.map((t) => (
          <g key={t}>
            <line
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--line)"
              strokeWidth={1}
            />
            <text
              x={PAD.left - 8}
              y={y(t) + 3}
              textAnchor="end"
              fontSize={9}
              fill="var(--muted)"
              fontFamily="var(--font-jetbrains-mono), monospace"
            >
              {Math.round(t * 100)}%
            </text>
            <text
              x={x(t)}
              y={HEIGHT - 26}
              textAnchor="middle"
              fontSize={9}
              fill="var(--muted)"
              fontFamily="var(--font-jetbrains-mono), monospace"
            >
              {Math.round(t * 100)}%
            </text>
          </g>
        ))}

        {/* Perfect honesty. Everything else is read against this line. */}
        <line
          x1={x(0)}
          y1={y(0)}
          x2={x(1)}
          y2={y(1)}
          stroke="var(--ink)"
          strokeWidth={1}
          strokeDasharray="3 3"
        />
        <text
          x={x(0.72)}
          y={y(0.76)}
          fontSize={9}
          fill="var(--muted)"
          fontFamily="var(--font-jetbrains-mono), monospace"
        >
          perfectly calibrated
        </text>

        {/* The gap each band has to the diagonal: the error, drawn. */}
        {bins.map((b) => (
          <line
            key={`gap-${b.from}`}
            x1={x(b.predicted!)}
            y1={y(b.predicted!)}
            x2={x(b.predicted!)}
            y2={y(b.observed!)}
            stroke="var(--accent-mist)"
            strokeWidth={1.5}
          />
        ))}

        {bins.map((b) => (
          <circle
            key={b.from}
            cx={x(b.predicted!)}
            cy={y(b.observed!)}
            r={radius(b.n, biggest)}
            fill="var(--accent)"
            fillOpacity={0.55}
            stroke="var(--accent-deep)"
            strokeWidth={1}
          >
            <title>
              {`Said ${(b.predicted! * 100).toFixed(1)}%, happened ${(b.observed! * 100).toFixed(1)}% — ${b.n} district-days`}
            </title>
          </circle>
        ))}

        <text
          x={PAD.left + PLOT.w / 2}
          y={HEIGHT - 8}
          textAnchor="middle"
          fontSize={9.5}
          fill="var(--muted)"
        >
          what the model said
        </text>
        <text
          x={-(PAD.top + PLOT.h / 2)}
          y={13}
          transform="rotate(-90)"
          textAnchor="middle"
          fontSize={9.5}
          fill="var(--muted)"
        >
          what actually happened
        </text>
      </svg>

      {d && (
        <figcaption className="border-t border-line px-5 py-3">
          <dl className="flex flex-wrap gap-x-5 gap-y-1 font-mono text-micro text-muted">
            <span>
              <dt className="inline">reliability</dt>{" "}
              <dd className="inline text-ink">{d.reliability.toFixed(5)}</dd> (0 is perfect)
            </span>
            <span>
              <dt className="inline">resolution</dt>{" "}
              <dd className="inline text-ink">{d.resolution.toFixed(4)}</dd> (higher is better)
            </span>
            <span>
              <dt className="inline">uncertainty</dt>{" "}
              <dd className="inline text-ink">{d.uncertainty.toFixed(4)}</dd>
            </span>
          </dl>
          {caption && <p className="mt-2 text-caption text-muted">{caption}</p>}
          {calibration.rows?.note && (
            <p className="mt-2 text-micro text-muted">{calibration.rows.note}</p>
          )}
        </figcaption>
      )}
    </figure>
  );
}
