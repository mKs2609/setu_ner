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