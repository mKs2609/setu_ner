"use client";

import { useEffect, useRef, useState } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { fetchRoadsGeoJSON, KNOWN_DISTRICTS, type RoadsGeoJSON } from "@/lib/api";

const INITIAL_CENTER: [number, number] = [92.7, 24.9];
const INITIAL_ZOOM = 9;

const SOURCE_ID = "roads";
const LAYER_ID = "roads-line";

export default function AccessibilityMap() {
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const [district, setDistrict] = useState<string>("Cachar");
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
                "line-color": [
                  "case",
                  ["==", ["get", "baseline_accessibility"], null as unknown as maplibregl.ExpressionInputType],
                  "#999999",
                  [
                    "interpolate", ["linear"], ["get", "baseline_accessibility"],
                    0, "#c62828",
                    0.5, "#f9d423",
                    1, "#2e7d32",
                  ],
                ],
                "line-width": [
                  "case", ["get", "is_bridge"], 4, 2,
                ],
              },
            });

            map.on("click", LAYER_ID, (e) => {
              const feature = e.features?.[0];
              if (!feature) return;
              const props = feature.properties as Record<string, unknown>;
              new maplibregl.Popup()
                .setLngLat(e.lngLat)
                .setHTML(
                  `<strong>${props.road_class ?? "unknown road"}</strong><br/>` +
                  `District: ${props.district ?? "unmatched"}<br/>` +
                  `Bridge: ${props.is_bridge ? "yes" : "no"}<br/>` +
                  `Baseline accessibility: ${
                    props.baseline_accessibility != null
                      ? Number(props.baseline_accessibility).toFixed(2)
                      : "not scored"
                  }`
                )
                .addTo(map);
            });
            map.on("mouseenter", LAYER_ID, () => { map.getCanvas().style.cursor = "pointer"; });
            map.on("mouseleave", LAYER_ID, () => { map.getCanvas().style.cursor = ""; });
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
            <option key={d} value={d}>{d}</option>
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
      </div>

      <div ref={mapContainerRef} className="w-full h-full" />
    </div>
  );
}