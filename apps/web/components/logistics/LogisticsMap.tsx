"use client";

/**
 * The plan on a map: depots, the circles being supplied, and the runs.
 *
 * A run's chosen route is solid. When the fastest and lower-exposure routes
 * differ, the one not chosen is drawn dashed underneath, so the trade-off the
 * operator set is visible as geography rather than only as numbers. Circles
 * the gazetteer could not place are not drawn at all -- the panel lists them --
 * because a marker at a guessed position would look exactly like a real one.
 */

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import { BASEMAP_ATTRIBUTION, BASEMAP_STYLE } from "@/lib/basemap";

import type { PlanResponse } from "@/lib/api";

const CENTER: [number, number] = [92.75, 24.9];
const ZOOM = 8.6;

const CHOSEN_SRC = "runs-chosen";
const ALT_SRC = "runs-alternative";

function lines(coordsList: [number, number][][]): GeoJSON.FeatureCollection {
  return {
    type: "FeatureCollection",
    features: coordsList
      .filter((c) => c.length > 1)
      .map((coordinates) => ({
        type: "Feature",
        properties: {},
        geometry: { type: "LineString", coordinates },
      })),
  };
}

export default function LogisticsMap({ plan }: { plan: PlanResponse | null }) {
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
      center: CENTER,
      zoom: ZOOM,
    });
    map.addControl(new maplibregl.NavigationControl(), "top-right");
    map.once("load", () => {
      map.addSource(ALT_SRC, { type: "geojson", data: lines([]) });
      map.addSource(CHOSEN_SRC, { type: "geojson", data: lines([]) });
      map.addLayer({
        id: `${ALT_SRC}-line`,
        type: "line",
        source: ALT_SRC,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#6b7280", "line-width": 3, "line-dasharray": [2, 1.5], "line-opacity": 0.8 },
      });
      map.addLayer({
        id: `${CHOSEN_SRC}-line`,
        type: "line",
        source: CHOSEN_SRC,
        layout: { "line-cap": "round", "line-join": "round" },
        paint: { "line-color": "#0f766e", "line-width": 4 },
      });
      map.jumpTo({ center: CENTER, zoom: ZOOM });
      readyRef.current = true;
      map.fire("logistics:ready");
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
      if (!readyRef.current) return;
      const used = (plan?.routes ?? []).filter((r) => r.used_in_plan);
      (map.getSource(CHOSEN_SRC) as maplibregl.GeoJSONSource).setData(
        lines(used.map((r) => r.geometry ?? []))
      );
      (map.getSource(ALT_SRC) as maplibregl.GeoJSONSource).setData(
        lines(used.map((r) => r.alternative_geometry ?? []))
      );

      markersRef.current.forEach((m) => m.remove());
      markersRef.current = [];
      if (!plan) return;

      const points: [number, number][] = [];
      for (const d of plan.depots) {
        points.push([d.lon, d.lat]);
        markersRef.current.push(
          new maplibregl.Marker({ color: "#1d4ed8" })
            .setLngLat([d.lon, d.lat])
            .setPopup(
              new maplibregl.Popup({ offset: 18 }).setText(
                `Depot: ${d.name} — ${d.trucks} truck(s)`
              )
            )
            .addTo(map)
        );
      }

      const maxPeople = Math.max(1, ...plan.demand.circles.map((c) => c.people_to_supply));
      // A circle with no route rows was never part of the optimisation (off the
      // road graph). It has no shortfall row either, so without this check it
      // would be drawn as "fully supplied" -- the most misleading colour possible.
      const planned = new Set(plan.routes.map((r) => r.circle));
      for (const c of plan.demand.circles) {
        if (!c.location || c.people_to_supply <= 0) continue;
        const short = plan.plan.shortfalls.filter((s) => s.circle === c.circle);
        const inPlan = planned.has(c.circle);
        const el = document.createElement("div");
        const size = 12 + 24 * Math.sqrt(c.people_to_supply / maxPeople);
        el.style.width = `${size}px`;
        el.style.height = `${size}px`;
        el.style.borderRadius = "9999px";
        el.style.background = !inPlan
          ? "rgba(107,114,128,0.7)"
          : short.length
            ? "rgba(220,38,38,0.75)"
            : "rgba(22,163,74,0.75)";
        el.style.border = "2px solid white";
        el.style.boxShadow = "0 0 0 1px rgba(0,0,0,0.25)";
        points.push([c.location.lon, c.location.lat]);
        markersRef.current.push(
          new maplibregl.Marker({ element: el })
            .setLngLat([c.location.lon, c.location.lat])
            .setPopup(
              new maplibregl.Popup({ offset: 12 }).setText(
                `${c.circle} (${c.district}): ${c.people_to_supply.toLocaleString()} people` +
                  (!inPlan ? " — not planned for (off the road graph)" : short.length ? " — shortfall" : " — fully supplied")
              )
            )
            .addTo(map)
        );
      }

      if (points.length) {
        const bounds = points.reduce(
          (b, p) => b.extend(p),
          new maplibregl.LngLatBounds(points[0], points[0])
        );
        map.fitBounds(bounds, { padding: 70, duration: 600, maxZoom: 11 });
      }
    };

    if (readyRef.current) draw();
    else map.once("logistics:ready", draw);
  }, [plan]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />
      <div className="pointer-events-none absolute bottom-4 left-4 card px-4 py-3 text-caption">
        <div className="mb-1 font-semibold text-ink">Plan</div>
        <div className="flex items-center gap-2">
          <span className="inline-block h-3 w-3 rounded-full" style={{ background: "#1d4ed8" }} />
          <span className="text-muted">Depot</span>
        </div>
        <div className="mt-1 flex items-center gap-2">
          <span className="inline-block h-3 w-3 rounded-full" style={{ background: "rgba(22,163,74,0.75)" }} />
          <span className="text-muted">Circle fully supplied (size = people)</span>
        </div>
        <div className="mt-1 flex items-center gap-2">
          <span className="inline-block h-3 w-3 rounded-full" style={{ background: "rgba(220,38,38,0.75)" }} />
          <span className="text-muted">Circle with a shortfall</span>
        </div>
        <div className="mt-1 flex items-center gap-2">
          <span className="inline-block h-3 w-3 rounded-full" style={{ background: "rgba(107,114,128,0.7)" }} />
          <span className="text-muted">Not planned for (road graph does not reach it)</span>
        </div>
        <div className="mt-1 flex items-center gap-2">
          <span className="inline-block h-1 w-6 rounded" style={{ background: "#0f766e" }} />
          <span className="text-muted">Route used</span>
        </div>
        <div className="mt-1 flex items-center gap-2">
          <span
            className="inline-block h-1 w-6 rounded"
            style={{ background: "repeating-linear-gradient(90deg,#6b7280 0 5px,transparent 5px 8px)" }}
          />
          <span className="text-muted">The other route, where they differ</span>
        </div>
      </div>
      {!plan && (
        <div className="pointer-events-none absolute inset-0 flex items-center justify-center">
          <p className="card-pill px-4 py-2 text-caption text-muted">
            Choose a report day and run a plan.
          </p>
        </div>
      )}
    </div>
  );
}
