import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";

import FloodOnsetChart from "@/components/dashboard/FloodOnsetChart";
import ReliabilityChart from "@/components/model/ReliabilityChart";
import { CACHAR_JUNE_2025 } from "@/lib/floodEvent";
import type { Calibration } from "@/lib/api";

/**
 * Both charts are server components with no client JavaScript, so the static
 * markup is exactly what a reader gets -- including someone with scripting
 * off, and a screen reader.
 */

describe("the flood onset chart", () => {
  const html = renderToStaticMarkup(<FloodOnsetChart />);

  it("draws a bar for every day that has rainfall", () => {
    const withRain = CACHAR_JUNE_2025.filter((d) => d.rain !== null).length;
    // Each rain bar carries a <title> for hover; count those rather than
    // rects, which the affected band also uses.
    expect((html.match(/<title>/g) ?? []).length).toBe(withRain);
  });

  it("describes itself for a reader who cannot see it", () => {
    expect(html).toContain('role="img"');
    expect(html).toMatch(/aria-label="[^"]{80,}"/);
  });

  it("does not render a day without a report as a clear day", () => {
    // The gap marker uses the neutral line colour, never the ok colour.
    const unreported = CACHAR_JUNE_2025.filter((d) => d.affected === null).length;
    expect(unreported).toBeGreaterThan(0);
    expect(html).toContain("var(--line)");
  });
});

describe("the reliability chart", () => {
  const calibration: Calibration = {
    n: 1000,
    positives: 120,
    base_rate: 0.12,
    bins: [
      { from: 0, to: 0.01, n: 600, predicted: 0.006, observed: 0.008 },
      { from: 0.01, to: 0.02, n: 0, predicted: null, observed: null },
      { from: 0.2, to: 0.35, n: 400, predicted: 0.27, observed: 0.45 },
    ],
    decomposition: {
      brier: 0.04,
      reliability: 0.0007,
      resolution: 0.066,
      uncertainty: 0.1055,
      residual: 0.0003,
    },
  };

  it("plots one point per populated band and skips the empty ones", () => {
    const html = renderToStaticMarkup(<ReliabilityChart calibration={calibration} />);
    expect((html.match(/<circle/g) ?? []).length).toBe(2);
  });

  it("reports the decomposition rather than only the picture", () => {
    const html = renderToStaticMarkup(<ReliabilityChart calibration={calibration} />);
    expect(html).toContain("0.00070");
    expect(html).toContain("reliability");
  });

  it("renders nothing rather than an empty pair of axes", () => {
    const empty = { ...calibration, bins: [], n: 0 };
    expect(renderToStaticMarkup(<ReliabilityChart calibration={empty} />)).toBe("");
  });
});
