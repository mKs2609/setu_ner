"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import {
  BASEMAP_ATTRIBUTION,
  BASEMAP_STYLE,
  CUT_OFF_BELOW,
  DEGRADED_BELOW,
  RAMP,
} from "@/lib/basemap";
import { fetchRoadsGeoJSON, KNOWN_DISTRICTS, type RoadsGeoJSON } from "@/lib/api";

const INITIAL_CENTER: [number, number] = [92.7, 24.9];
const INITIAL_ZOOM = 9;

const SOURCE_ID = "roads";
const LAYER_ID = "roads-line";
// Drawn over the top of the first layer, and only for roads in the worst
// band. It exists so "impassable" is stated by something other than colour;
// see the ramp's note in lib/basemap.ts. It needs to be a second layer
// because `line-dasharray` cannot be driven by a feature's own properties in
// MapLibre -- only by zoom -- so one layer cannot dash some roads and not
// others.
const CUT_OFF_LAYER_ID = "roads-cut-off";
const CUT_OFF_DASH: [number, number] = [2, 1.6];

// Two different things, never blended on one layer: a 2025 historical proxy,
// and the live forecast. The toggle switches which one colours the roads;
// the popup always shows both so neither is mistaken for the other.
export type AccessibilityMetric = "baseline_accessibility" | "current_accessibility";

const METRIC_LABELS: Record<AccessibilityMetric, string> = {
  baseline_accessibility: "Baseline (2025 history)",
  current_accessibility: "Model (next-day forecast)",
};

function colorExpression(metric: AccessibilityMetric): maplibregl.ExpressionSpecification {
  return [
    "case",
    ["==", ["get", metric], null as unknown as maplibregl.ExpressionInputType],
    RAMP.unknown,
    ["interpolate", ["linear"], ["get", metric], 0, RAMP.cutOff, 0.5, RAMP.degraded, 1, RAMP.clear],
  ];
}

/** Which roads get the dashed overlay: scored, and in the worst band. */
function cutOffFilter(metric: AccessibilityMetric): maplibregl.FilterSpecification {
  return [
    "all",
    ["!", ["==", ["get", metric], null as unknown as maplibregl.ExpressionInputType]],
    ["<", ["get", metric], CUT_OFF_BELOW],
  ];
}

function fmt(value: unknown): string {
  return value != null && value !== "null" ? Number(value).toFixed(2) : "not scored";
}

/**
 * The legend, which is also the place the redundant encoding is explained.
 * Each band is drawn the way the map draws it -- including the dash -- so the
 * key works for a reader who cannot use the colours at all.
 */
function Legend({ metric }: { metric: AccessibilityMetric }) {
  const bands = [
    { label: `Cut off · below ${CUT_OFF_BELOW.toFixed(2)}`, color: RAMP.cutOff, dashed: true },
    { label: `Degraded · to ${DEGRADED_BELOW.toFixed(2)}`, color: RAMP.degraded, dashed: false },
    { label: "Clear · above that", color: RAMP.clear, dashed: false },
    { label: "Not scored", color: RAMP.unknown, dashed: false },
  ];
  return (
    <div className="card absolute bottom-8 left-3 z-10 p-3">
      <p className="font-mono text-micro uppercase tracking-[0.14em] text-muted">
        {METRIC_LABELS[metric]}
      </p>
      <ul className="mt-2 space-y-1.5">
        {bands.map((band) => (
          <li key={band.label} className="flex items-center gap-2 text-caption">
            <svg width="26" height="8" aria-hidden="true" className="shrink-0">
              <line
                x1="1"
                y1="4"
                x2="25"
                y2="4"
                stroke={band.color}
                strokeWidth={band.dashed ? 4 : 3}
                strokeDasharray={band.dashed ? "4 3" : undefined}
              />
            </svg>
            {band.label}
          </li>
        ))}
      </ul>
      <p className="mt-2 max-w-[13rem] text-micro text-muted">
        Cut-off roads are dashed as well as dark, so the map still reads without colour.
      </p>
    </div>
  );
}

export default function AccessibilityMap({
  initialMetric = "baseline_accessibility",
  onSelectRoad,
}: {
  initialMetric?: AccessibilityMetric;
  onSelectRoad?: (roadId: number) => void;
}) {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [district, setDistrict] = useState<string>("Cachar");
  const [metric, setMetric] = useState<AccessibilityMetric>(initialMetric);
  const metricRef = useRef(metric);
  // The click handler is registered once, so it reads the latest callback
  // through a ref rather than capturing the first render's.
  const onSelectRef = useRef(onSelectRoad);
  onSelectRef.current = onSelectRoad;
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [meta, setMeta] = useState<RoadsGeoJSON["meta"] | null>(null);

  useEffect(() => {
    if (!mapContainerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: mapContainerRef.current,
      style: BASEMAP_STYLE,
      attributionControl: { compact: true, customAttribution: BASEMAP_ATTRIBUTION },
      center: INITIAL_CENTER,
      zoom: INITIAL_ZOOM,
    });

    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.once("load", () => map.jumpTo({ center: INITIAL_CENTER, zoom: INITIAL_ZOOM }));
    mapRef.current = map;

    return () => {
      map.remove();
      mapRef.current = null;
    };
  }, []);

  useEffect(() => {
    metricRef.current = metric;
    const map = mapRef.current;
    if (map?.getLayer(LAYER_ID)) {
      map.setPaintProperty(LAYER_ID, "line-color", colorExpression(metric));
    }
    if (map?.getLayer(CUT_OFF_LAYER_ID)) {
      map.setFilter(CUT_OFF_LAYER_ID, cutOffFilter(metric));
    }
  }, [metric]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    let cancelled = false;
    setLoading(true);
    setError(null);

    const load = () => {
      fetchRoadsGeoJSON({ district })
        .then((data) => {
          if (cancelled) return;
          setMeta(data.meta);

          if (map.getSource(SOURCE_ID)) {
            (map.getSource(SOURCE_ID) as maplibregl.GeoJSONSource).setData(
              data as GeoJSON.FeatureCollection
            );
          } else {
            map.addSource(SOURCE_ID, { type: "geojson", data: data as GeoJSON.FeatureCollection });
            map.addLayer({
              id: LAYER_ID,
              type: "line",
              source: SOURCE_ID,
              paint: {
                "line-color": colorExpression(metricRef.current),
                "line-width": ["case", ["get", "is_bridge"], 4, 2],
              },
            });

            // Over the top, so the dash reads against the solid line beneath.
            // No handlers of its own: a click on a cut-off road still hits
            // the layer below, which carries them.
            map.addLayer({
              id: CUT_OFF_LAYER_ID,
              type: "line",
              source: SOURCE_ID,
              filter: cutOffFilter(metricRef.current),
              paint: {
                "line-color": RAMP.cutOff,
                "line-width": ["case", ["get", "is_bridge"], 5, 3],
                "line-dasharray": CUT_OFF_DASH,
              },
            });

            map.on("click", LAYER_ID, (e) => {
              const feature = e.features?.[0];
              if (!feature) return;
              const props = feature.properties as Record<string, unknown>;
              if (onSelectRef.current && typeof feature.id === "number") {
                onSelectRef.current(feature.id);
              }
              const asOf =
                props.current_accessibility_as_of && props.current_accessibility_as_of !== "null"
                  ? ` (as of ${props.current_accessibility_as_of})`
                  : "";
              new maplibregl.Popup()
                .setLngLat(e.lngLat)
                .setHTML(
                  `<strong>${props.road_class ?? "unknown road"}</strong><br/>` +
                    `District: ${props.district ?? "unmatched"}<br/>` +
                    `Bridge: ${props.is_bridge ? "yes" : "no"}<br/>` +
                    `Baseline (2025): ${fmt(props.baseline_accessibility)}<br/>` +
                    `Model forecast: ${fmt(props.current_accessibility)}${asOf}<br/>` +
                    `Terrain exposure prior: ${fmt(props.hazard_exposure)}`
                )
                .addTo(map);
            });
            map.on("mouseenter", LAYER_ID, () => {
              map.getCanvas().style.cursor = "pointer";
            });
            map.on("mouseleave", LAYER_ID, () => {
              map.getCanvas().style.cursor = "";
            });
          }

          setLoading(false);
        })
        .catch((err) => {
          if (cancelled) return;
          setError(err instanceof Error ? err.message : "Failed to load road data");
          setLoading(false);
        });
    };

    if (map.isStyleLoaded()) {
      load();
    } else {
      map.once("load", load);
    }

    return () => {
      cancelled = true;
    };
  }, [district]);

  return (
    <div className="relative w-full h-full">
      <div className="absolute top-3 left-3 z-10 bg-surface rounded shadow-md p-3 text-sm space-y-2 max-w-xs">
        <label className="block font-medium text-ink">District</label>
        <select
          value={district}
          onChange={(e) => setDistrict(e.target.value)}
          className="border border-line rounded px-2 py-1 w-full"
        >
          {KNOWN_DISTRICTS.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>

        <label className="block font-medium text-ink">Colour roads by</label>
        <select
          value={metric}
          onChange={(e) => setMetric(e.target.value as AccessibilityMetric)}
          className="border border-line rounded px-2 py-1 w-full"
        >
          {(Object.keys(METRIC_LABELS) as AccessibilityMetric[]).map((m) => (
            <option key={m} value={m}>
              {METRIC_LABELS[m]}
            </option>
          ))}
        </select>

        {loading && <p className="text-muted">Loading roads…</p>}
        {error && (
          <p className="text-alert">
            Couldn&apos;t reach the API ({error}). Is the backend running on port 8000?
          </p>
        )}
        {meta && !loading && !error && (
          <p className="text-muted">
            {meta.count} road{meta.count === 1 ? "" : "s"} shown
            {meta.truncated ? " (capped — see note below)" : ""}
          </p>
        )}
        {meta?.note && <p className="text-caution text-xs">{meta.note}</p>}
      </div>

      <Legend metric={metric} />

      <div ref={mapContainerRef} className="w-full h-full" />
    </div>
  );
}
