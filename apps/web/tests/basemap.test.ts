import { describe, expect, it } from "vitest";

import { CUT_OFF_BELOW, DEGRADED_BELOW, RAMP } from "@/lib/basemap";

/**
 * The map's colours used to separate "impassable" from "fine" by hue alone,
 * at a contrast ratio of 1.08 -- unreadable in greyscale and for a large
 * share of men (docs/decisions/0018). These tests exist so that cannot come
 * back by someone tidying the palette.
 */

/** WCAG relative luminance. */
function luminance(hex: string): number {
  const channels = [1, 3, 5].map((i) => {
    const c = parseInt(hex.slice(i, i + 2), 16) / 255;
    return c <= 0.04045 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4;
  });
  return 0.2126 * channels[0] + 0.7152 * channels[1] + 0.0722 * channels[2];
}

function contrast(a: string, b: string): number {
  const [hi, lo] = [luminance(a), luminance(b)].sort((x, y) => y - x);
  return (hi + 0.05) / (lo + 0.05);
}

describe("the road colour ramp", () => {
  it("separates cut off from clear by brightness, not only hue", () => {
    // The distinction that decides whether a truck is sent into water. The
    // old palette scored 1.08 here.
    expect(contrast(RAMP.cutOff, RAMP.clear)).toBeGreaterThan(2.5);
  });

  it("makes cut off the darkest band, so dark reads as bad", () => {
    expect(luminance(RAMP.cutOff)).toBeLessThan(luminance(RAMP.clear));
    expect(luminance(RAMP.cutOff)).toBeLessThan(luminance(RAMP.degraded));
  });

  it("keeps every band visible against a light basemap", () => {
    const positron = "#f2f0ed";
    for (const [name, colour] of Object.entries(RAMP)) {
      expect(contrast(colour, positron), `${name} on the basemap`).toBeGreaterThan(1.5);
    }
  });

  it("uses band edges that are ordered and inside the score range", () => {
    expect(CUT_OFF_BELOW).toBeGreaterThan(0);
    expect(CUT_OFF_BELOW).toBeLessThan(DEGRADED_BELOW);
    expect(DEGRADED_BELOW).toBeLessThan(1);
  });
});
