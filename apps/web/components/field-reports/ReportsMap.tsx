"use client";

/**
 * Recent field reports as points on the corridor map.
 *
 * Colour carries the status, which is the only thing an operator scanning
 * this needs at a glance: red means somebody says a road is impassable.
 *
 * Reports that snapped to no road are drawn hollow rather than hidden. They
 * are excluded from fusion, but a cluster of them is a real signal -- either
 * a GPS problem or people reporting from somewhere the road graph does not
 * cover, and both are worth seeing.
 */

import { useEffect, useRef } from "react";
import maplibregl from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";

import { BASEMAP_ATTRIBUTION, BASEMAP_STYLE } from "@/lib/basemap";

import type { StoredReport } from "@/lib/api";

const CENTER: [number, number] = [92.8, 24.9];
const ZOOM = 8.5;
const SRC = "field-reports";
const LAYER = "field-reports-circles";

const COLOURS: Record<string, string> = {
  clear: "#15803d",
  slow: "#d97706",
  blocked: "#b91c1c",
};

export default function ReportsMap({
  reports,
  onSelect,
}: {
  reports: StoredReport[];
  onSelect?: (roadId: number) => void;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<maplibregl.Map | null>(null);
  const readyRef = useRef(false);
  const selectRef = useRef(onSelect);
  selectRef.current = onSelect;

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
      map.addSource(SRC, {
        type: "geojson",
        data: { type: "FeatureCollection", features: [] },
      });
      map.addLayer({
        id: LAYER,
        type: "circle",
        source: SRC,
        paint: {
          "circle-radius": 7,
          "circle-color": [
            "match",
            ["get", "status"],
            "clear", COLOURS.clear,
            "slow", COLOURS.slow,
            "blocked", COLOURS.blocked,
            "#6b7280",
          ],
          // Hollow when the report snapped to no road: still visible, visibly
          // different from one that counts.
          "circle-opacity": ["case", ["get", "counted"], 0.85, 0.15],
          "circle-stroke-width": 2,
          "circle-stroke-color": [
            "match",
            ["get", "status"],
            "clear", COLOURS.clear,
            "slow", COLOURS.slow,
            "blocked", COLOURS.blocked,
            "#6b7280",
          ],
        },
      });

      map.on("click", LAYER, (e) => {
        const feature = e.features?.[0];
        if (!feature) return;
        const props = feature.properties as Record<string, unknown>;
        const roadId = props.road_id;
        new maplibregl.Popup()
          .setLngLat(e.lngLat)
          .setHTML(
            `<strong>${String(props.status).toUpperCase()}</strong><br/>` +
              (roadId ? `Road ${roadId}<br/>` : "Snapped to no road<br/>") +
              (props.note ? `${props.note}<br/>` : "") +
              `<span style="color:#666">${new Date(
                String(props.submitted_at)
              ).toLocaleString()}</span>`
          )
          .addTo(map);
        if (roadId && selectRef.current) selectRef.current(Number(roadId));
      });
      map.on("mouseenter", LAYER, () => {
        map.getCanvas().style.cursor = "pointer";
      });
      map.on("mouseleave", LAYER, () => {
        map.getCanvas().style.cursor = "";
      });

      readyRef.current = true;
      map.fire("reports:ready");
    });

    mapRef.current = map;
    return () => {
      map.remove();
      mapRef.current = null;
      readyRef.current = false;
    };
  }, []);

  useEffect(() => {
    const map = mapRef.current;
    if (!map) return;

    const draw = () => {
      const source = map.getSource(SRC) as maplibregl.GeoJSONSource | undefined;
      if (!source) return;
      source.setData({
        type: "FeatureCollection",
        features: reports.map((r) => ({
          type: "Feature",
          properties: {
            status: r.status,
            road_id: r.road_id,
            note: r.note,
            submitted_at: r.submitted_at,
            counted: r.road_id !== null,
          },
          geometry: { type: "Point", coordinates: [r.longitude, r.latitude] },
        })),
      });

      const inCorridor = reports.filter((r) => r.road_id !== null);
      if (inCorridor.length) {
        const bounds = inCorridor.reduce(
          (b, r) => b.extend([r.longitude, r.latitude] as [number, number]),
          new maplibregl.LngLatBounds(
            [inCorridor[0].longitude, inCorridor[0].latitude],
            [inCorridor[0].longitude, inCorridor[0].latitude]
          )
        );
        map.fitBounds(bounds, { padding: 80, duration: 600, maxZoom: 12 });
      }
    };

    if (readyRef.current) draw();
    else map.once("reports:ready", draw);
  }, [reports]);

  return (
    <div className="relative h-full w-full">
      <div ref={containerRef} className="h-full w-full" />
      <div className="pointer-events-none absolute bottom-4 left-4 card px-4 py-3 text-caption">
        <div className="mb-1 font-semibold text-ink">Reports</div>
        {(["clear", "slow", "blocked"] as const).map((s) => (
          <div key={s} className="flex items-center gap-2">
            <span
              className="inline-block h-3 w-3 rounded-full"
              style={{ background: COLOURS[s] }}
            />
            <span className="capitalize text-muted">{s}</span>
          </div>
        ))}
        <div className="mt-1.5 max-w-[14rem] text-[11px] leading-snug text-muted">
          Hollow points landed too far from any road to count toward fusion.
        </div>
      </div>
    </div>
  );
}
