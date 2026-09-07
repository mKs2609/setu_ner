const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface RoadFeatureProperties {
  road_class: string | null;
  is_bridge: boolean;
  district: string | null;
  baseline_accessibility: number | null;
}

export interface RoadsGeoJSON {
  type: "FeatureCollection";
  features: GeoJSON.Feature<GeoJSON.LineString, RoadFeatureProperties>[];
  meta: {
    count: number;
    truncated: boolean;
    note: string | null;
  };
}

export interface FetchRoadsParams {
  district?: string;
  minAccessibility?: number;
  maxAccessibility?: number;
}

export async function fetchRoadsGeoJSON(params: FetchRoadsParams = {}): Promise<RoadsGeoJSON> {
  const search = new URLSearchParams();
  if (params.district) search.set("district", params.district);
  if (params.minAccessibility !== undefined) search.set("min_accessibility", String(params.minAccessibility));
  if (params.maxAccessibility !== undefined) search.set("max_accessibility", String(params.maxAccessibility));

  const url = `${API_BASE}/api/v1/roads/geojson${search.toString() ? `?${search}` : ""}`;
  const res = await fetch(url);
  if (!res.ok) {
    throw new Error(`Failed to fetch roads: ${res.status} ${res.statusText}`);
  }
  return res.json();
}

// The four districts the corridor currently has real hazard data for.
// Hardcoded rather than fetched from an endpoint for now -- there's no
// /districts list endpoint yet, and this list is small and stable enough
// not to be worth building one just for a dropdown. Revisit once the
// Meghalaya coverage gap closes and this list needs to grow.
export const KNOWN_DISTRICTS = ["Cachar", "Hailakandi", "Karimganj", "Dima Hasao"] as const;
// ---------------------------------------------------------------------------
// Scenario engine (Phase 5). See docs/decisions/0003-scenario-engine.md.
//
// The shapes below mirror the API responses exactly, including the caveat
// fields. Those are not decoration: travel times are modelled from an assumed
// speed per road class, so the UI is expected to surface the caveat rather
// than quietly present a modelled number as an observed one.
// ---------------------------------------------------------------------------

export interface Landmark {
  key: string;
  display_name: string;
  lon: number;
  lat: number;
  district: string;
  why: string;
}

export interface RouteStats {
  reachable: boolean;
  travel_time_min: number | null;
  distance_km: number | null;
  segment_count: number;
  bridges_crossed: number;
  reason?: string | null;
}

export interface ScenarioDelta {
  severed: boolean;
  added_minutes?: number;
  percent_slower?: number | null;
  added_km?: number;
  detour_taken?: boolean;
}

export interface ScenarioResult {
  scenario: string;
  origin: { place: string; snapped_km_away: number };
  destination: { place: string; snapped_km_away: number };
  verdict: string;
  baseline: RouteStats;
  scenario_result: RouteStats;
  delta: ScenarioDelta;
  explanation: {
    roads_closed: number;
    roads_degraded: number;
    closed_roads_on_baseline_route: number[];
    degraded_roads_on_baseline_route: number[];
    note: string;
  };
  caveats: {
    travel_time: string;
    snapping: string;
    not_a_logistics_plan: string;
  };
  geometry?: {
    baseline: [number, number][];
    scenario: [number, number][] | null;
  };
}

export interface SimulateRequest {
  label: string;
  origin: string;
  destination: string;
  close_bridges_in_district?: string | null;
  degrade_bridges_in_district?: string | null;
  degrade_factor?: number;
  include_geometry?: boolean;
}

export async function fetchLandmarks(): Promise<Landmark[]> {
  const res = await fetch(`${API_BASE}/api/v1/scenarios/landmarks`);
  if (!res.ok) throw new Error(`Failed to load landmarks: ${res.status}`);
  return (await res.json()).landmarks;
}

export async function simulateScenario(body: SimulateRequest): Promise<ScenarioResult> {
  const res = await fetch(`${API_BASE}/api/v1/scenarios/simulate`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ include_geometry: true, ...body }),
  });
  if (!res.ok) {
    // The API returns a useful message for a bad place name (400) or an
    // unknown district (404) -- surfacing it beats a generic failure.
    let detail = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* response wasn't JSON; keep the status line */
    }
    throw new Error(detail);
  }
  return res.json();
}
