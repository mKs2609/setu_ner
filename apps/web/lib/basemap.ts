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
 * Required credit. The style's own JSON carries no `attribution` field, so
 * MapLibre cannot derive it -- without this the map would render CARTO's
 * tiles and OpenStreetMap's data with no credit at all, which their terms
 * (and ours, see the footer) do not allow.
 */
export const BASEMAP_ATTRIBUTION =
  '© <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors © <a href="https://carto.com/attributions">CARTO</a>';

/** Road colour ramp, worst to best, from the design tokens. */
export const RAMP = {
  cutOff: "#c03a3a", // alert
  degraded: "#b06a15", // caution
  clear: "#2f7d5d", // ok
  unknown: "#c9c5d4", // unscored: visible, but clearly not a judgement
} as const;
