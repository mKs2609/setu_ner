"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { fetchRoadsGeoJSON, KNOWN_DISTRICTS, type RoadsGeoJSON } from "@/lib/api";

const INITIAL_CENTER: [number, number] = [92.7, 24.9];
const INITIAL_ZOOM = 9;

const SOURCE_ID = "roads";
const LAYER_ID = "roads-line";

// Two different things, never blended on one layer: a 2025 historical proxy,
// and the Phase 3 forecast. The toggle switches which one colours the roads;
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
    "#999999",
    ["interpolate", ["linear"], ["get", metric], 0, "#c62828", 0.5, "#f9d423", 1, "#2e7d32"],
  ];
}

function fmt(value: unknown): string {
  return value != null && value !== "null" ? Number(value).toFixed(2) : "not scored";
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
      style: "https://demotiles.maplibre.org/style.json",
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
      <div className="absolute top-3 left-3 z-10 bg-white rounded-md shadow-md p-3 text-sm space-y-2 max-w-xs">
        <label className="block font-medium text-gray-700">District</label>
        <select
          value={district}
          onChange={(e) => setDistrict(e.target.value)}
          className="border border-gray-300 rounded px-2 py-1 w-full"
        >
          {KNOWN_DISTRICTS.map((d) => (
            <option key={d} value={d}>
              {d}
            </option>
          ))}
        </select>

        <label className="block font-medium text-gray-700">Colour roads by</label>
        <select
          value={metric}
          onChange={(e) => setMetric(e.target.value as AccessibilityMetric)}
          className="border border-gray-300 rounded px-2 py-1 w-full"
        >
          {(Object.keys(METRIC_LABELS) as AccessibilityMetric[]).map((m) => (
            <option key={m} value={m}>
              {METRIC_LABELS[m]}
            </option>
          ))}
        </select>

        {loading && <p className="text-gray-500">Loading roads…</p>}
        {error && (
          <p className="text-red-600">
            Couldn&apos;t reach the API ({error}). Is the backend running on port 8000?
          </p>
        )}
        {meta && !loading && !error && (
          <p className="text-gray-600">
            {meta.count} road{meta.count === 1 ? "" : "s"} shown
            {meta.truncated ? " (capped — see note below)" : ""}
          </p>
        )}
        {meta?.note && <p className="text-amber-700 text-xs">{meta.note}</p>}
        <p className="text-xs text-gray-500">Red = worst, green = best, gray = not scored.</p>
      </div>

      <div ref={mapContainerRef} className="w-full h-full" />
    </div>
  );
}
