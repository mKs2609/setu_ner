/**
 * The basemap, in one place so every map in the app agrees.
 *
 * CARTO's Positron style: free to use with attribution, which MapLibre
 * renders from the style's own metadata (OpenStreetMap contributors and
 * CARTO both appear in the corner). It is chosen over MapLibre's demo tiles
 * because those are a political map with no roads or rivers, which gives a
 * flood map no context at all.
 *
 * If this host is ever unreachable the maps still work: MapLibre renders our
 * own road layers on the canvas colour with no basemap underneath.
 */
export const BASEMAP_STYLE =
  "https://basemaps.cartocdn.com/gl/positron-gl-style/style.json";

/**
 * Required credit. The style's own JSON carries no `attribution` field --
 * re-checked 30 Sep 2026, still null at both the top level and on the
 * `carto` source -- so MapLibre cannot derive it from there. Without this
 * the map could render CARTO's tiles and OpenStreetMap's data with no credit
 * at all, which their terms (and ours, see the footer) do not allow.
 *
 * WHY THE CREDIT APPEARS TWICE
 * The TileJSON the source resolves to at runtime does carry an attribution,
 * so MapLibre shows that one as well as this. Deliberately left duplicated:
 * stripping ours would make the credit depend on a remote document that has
 * already changed once, and over-crediting breaks nobody's terms while
 * under-crediting breaks both.
 */
export const BASEMAP_ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>';

/**
 * Road colour ramp, worst to best.
 *
 * WHY THESE ARE NOT THE --ok / --caution / --alert TEXT TOKENS
 * They used to be, and it made the map unreadable for a lot of people. Those
 * tokens are tuned for *text on white*, which happens to put all three at
 * nearly the same brightness: measured relative luminance was 0.145 for cut
 * off, 0.161 for clear and 0.196 for degraded. The contrast ratio between a
 * cut-off road and a clear road was 1.08 -- essentially nothing.
 *
 * So the only thing separating "impassable" from "fine" was hue, red against
 * green. Roughly one man in twelve cannot reliably tell those apart, and in
 * greyscale or on a projector nobody can. For a flood map whose whole job is
 * to say three things at a glance, that is a defect, not a style preference.
 *
 * These keep the same meanings and pull the brightness apart:
 *
 *     cut off   #8a1f1f   luminance 0.065
 *     clear     #3f9c74   luminance 0.261    ratio to cut off  2.71
 *     degraded  #d4901c   luminance 0.340    ratio to cut off  3.40
 *
 * Dark-to-light now tracks bad-to-good on its own, with no hue involved.
 *
 * WHAT IS STILL ONLY HUE
 * Degraded against clear is 1.26 -- weak. A light basemap leaves little room
 * above mid-grey before a line stops being visible at all, so the brightness
 * budget went to the distinction that matters: passable or not. Cut-off roads
 * are also drawn dashed (AccessibilityMap), a channel colour vision cannot
 * affect. Mistaking "slow" for "clear" costs a delay; mistaking "impassable"
 * for "clear" sends a truck into water.
 */
export const RAMP = {
  cutOff: "#8a1f1f",
  degraded: "#d4901c",
  clear: "#3f9c74",
  unknown: "#b9b6c4", // unscored: visible, but clearly not a judgement
} as const;

/**
 * Band edges on the 0-1 accessibility scale, in even thirds.
 *
 * Only the lower one changes what is drawn -- roads below it get the dashed
 * treatment -- but both are quoted in the legend, so the colours are never
 * the only statement of what a band means.
 */
export const CUT_OFF_BELOW = 0.34;
export const DEGRADED_BELOW = 0.67;
