import { describe, expect, it } from "vitest";

import { CACHAR_JUNE_2025, FIRST_AFFECTED } from "@/lib/floodEvent";

/**
 * The landing page's chart is drawn from committed data, so nothing at
 * runtime can catch it drifting from what the sources actually said. These
 * check the properties the page's argument depends on.
 */
describe("the committed 2025 flood record", () => {
  it("runs day by day with no gaps", () => {
    for (let i = 1; i < CACHAR_JUNE_2025.length; i += 1) {
      const previous = new Date(CACHAR_JUNE_2025[i - 1].date + "T00:00:00Z").getTime();
      const current = new Date(CACHAR_JUNE_2025[i].date + "T00:00:00Z").getTime();
      expect(current - previous, `after ${CACHAR_JUNE_2025[i - 1].date}`).toBe(86_400_000);
    }
  });

  it("marks a day with no published report as unknown, never as no flood", () => {
    // `null` has to stay a third state. Collapsing it to false is the exact
    // mistake the model's labelling rules exist to prevent.
    const states = new Set(CACHAR_JUNE_2025.map((d) => d.affected));
    expect(states.has(null)).toBe(true);
    for (const value of states) {
      expect([true, false, null]).toContain(value);
    }
  });

  it("names an onset day that is really the first one listed", () => {
    const onset = CACHAR_JUNE_2025.findIndex((d) => d.date === FIRST_AFFECTED);
    expect(onset, `${FIRST_AFFECTED} is in the series`).toBeGreaterThanOrEqual(0);
    expect(CACHAR_JUNE_2025[onset].affected).toBe(true);
    expect(CACHAR_JUNE_2025.slice(0, onset).every((d) => d.affected !== true)).toBe(true);
  });

  it("still supports the claim the page makes: rain builds before the report", () => {
    const onset = CACHAR_JUNE_2025.findIndex((d) => d.date === FIRST_AFFECTED);
    const before = CACHAR_JUNE_2025.slice(0, onset);
    // Something substantial fell in the days before the district was listed.
    expect(Math.max(...before.map((d) => d.rain ?? 0))).toBeGreaterThan(30);
  });

  it("carries rainfall in plausible millimetres", () => {
    for (const day of CACHAR_JUNE_2025) {
      if (day.rain === null) continue;
      expect(day.rain).toBeGreaterThanOrEqual(0);
      expect(day.rain, day.date).toBeLessThan(500);
    }
  });
});
