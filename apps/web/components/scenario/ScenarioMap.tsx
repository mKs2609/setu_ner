"use client";

/**
 * Draws a scenario's two routes: the baseline, and the route once the
 * scenario's closures are applied.
 *
 * WHY BOTH ROUTES ARE ALWAYS DRAWN
 * The scenario engine's whole point is the difference between them, so
 * showing only the result would throw away the comparison. The baseline is
 * drawn underneath in a muted blue and the scenario route on top in amber,
 * so where they overlap you see one line and where they diverge you see the
 * detour. When the scenario severs the corridor there is no second route to
 * draw, and the map says so rather than silently showing one line.
 */

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import { BASEMAP_ATTRIBUTION, BASEMAP_STYLE } from "@/lib/basemap";

import type { ScenarioResult } from "@/lib/api";

const FALLBACK_CENTER: [number, number] = [92.8, 24.95];
const FALLBACK_ZOOM = 8.5;

const BASELINE_SRC = "route-baseline";
const SCENARIO_SRC = "route-scenario";
const BASELINE_LAYER = "route-baseline-line";
const SCENARIO_LAYER = "route-scenario-line";

type Coords = [number, number][];

function lineFeature(coords: Coords): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: coords.length
      ? [{ type: "Feature", properties: {}, geometry: { type: "LineString", coordinates: coords } }]
      : [],
  };
}

export default function ScenarioMap({ result }: { result: ScenarioResult | null }) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const readyRef = useRef(false);
  const markersRef = useRef<maplibregl.Marker[]>([]);

  useEffect(() => {
    if (!containerRef.current || mapRef.current) return;

    const map = new maplibregl.Map({
      container: containerRef.current,
      style: BASEMAP_STYLE,
      attributionControl: { compact: true, customAttribution: BASEMAP_ATTRIBUTION },
      center: FALLBACK_CENTER,
      zoom: FALLBACK_ZOOM,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");

    map.once("load", () => {
      map.addSource(BASELINE_SRC, { type: "geojson", data: lineFeature([]) });
      map.addSource(SCENARIO_SRC, { type: "geojson", data: lineFeature([]) });

      map.addLayer({
        id: BASELINE_LAYER,
        type: "line",
        source: BASELINE_SRC,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#1d4ed8", "line-width": 5, "line-opacity": 0.55 },
      });
      map.addLayer({
        id: SCENARIO_LAYER,
        type: "line",
        source: SCENARIO_SRC,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#d97706", "line-width": 3, "line-dasharray": [2, 1.4] },
      });

      readyRef.current = true;
      mapRef.current = map;
      // The first result can arrive before the style finishes loading; this
      // forces a redraw once the layers actually exist.
      map.fire("scenario:ready");
    });

    mapRef.current = map;
    return () => {
      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
      map.remove();
      mapRef.current = null;
      readyRef.current = false;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const draw = () => {
      if (!readyRef.current || !map.getSource(BASELINE_SRC)) return;

      const baseline = (result?.geometry?.baseline ?? []) as Coords;
      const scenario = (result?.geometry?.scenario ?? []) as Coords;

      (map.getSource(BASELINE_SRC) as maplibregl.GeoJSONSource).setData(lineFeature(baseline));
      (map.getSource(SCENARIO_SRC) as maplibregl.GeoJSONSource).setData(lineFeature(scenario));

      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];

      const all = [...baseline, ...scenario];
      if (!all.length) return;

      const ends: [number, number][] = [baseline[0], baseline[baseline.length - 1]];
      const labels = [result?.origin.place ?? "Origin", result?.destination.place ?? "Destination"];
      ends.forEach((pt, i) => {
        if (!pt) return;
        const marker = new maplibregl.Marker({ color: i === 0 ? "#15803d" : "#b91c1c" })
          .setLngLat(pt)
          .setPopup(new maplibregl.Popup({ offset: 18 }).setText(labels[i]))
          .addTo(map);
        markersRef.current.push(marker);
      });

      const bounds = all.reduce(
        (b, c) => b.extend(c),
        new maplibregl.LngLatBounds(all[0], all[0])
      );
      map.fitBounds(bounds, { padding: 60, duration: 600, maxZoom: 13 });
    };

    if (readyRef.current) draw();
    else map.once("scenario:ready", draw);
  }, [result]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />

      <div className="pointer-events-none absolute bottom-4 left-4 card px-4 py-3 text-caption">
        <div className="mb-1 font-semibold text-ink">Routes</div>
        <div className="flex items-center gap-2">
          <span className="inline-block h-1 w-6 rounded" style={{ background: "#1d4ed8", opacity: 0.55 }} />
          <span className="text-muted">Baseline (nothing closed)</span>
        </div>
        <div className="mt-1 flex items-center gap-2">
          <span
            className="inline-block h-1 w-6 rounded"
            style={{ background: "repeating-linear-gradient(90deg,#d97706 0 5px,transparent 5px 8px)" }}
          />
          <span className="text-muted">
            {result?.delta.severed ? "Scenario — no route exists" : "Scenario route"}
          </span>
        </div>
        {result && !result.delta.severed && !result.delta.detour_taken && (
          <div className="mt-1.5 max-w-[15rem] text-[11px] leading-snug text-muted">
            The two routes are identical here, so only one line is visible.
          </div>
        )}
      </div>

      {!result && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <p className="card-pill px-4 py-2 text-caption text-muted">
            Pick a scenario on the left and run it to see the routes.
          </p>
        </div>
      )}
    </div>
  );
}
