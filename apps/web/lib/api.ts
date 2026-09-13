const API_BASE = process.env.NEXT_PUBLIC_API_URL || "http://localhost:8000";

export interface RoadFeatureProperties {
  road_class: string | null;
  is_bridge: boolean;
  district: string | null;
  baseline_accessibility: number | null;
  // Phase 3. Null when unscored; the as-of date travels with the value so a
  // stale forecast is never drawn as though it were current.
  current_accessibility?: number | null;
  hazard_exposure?: number | null;
  current_accessibility_as_of?: string | null;
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
  kind?: "severed" | "origin_isolated" | "destination_isolated" | "both_isolated" | null;
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

export interface AffectedRoad {
  road_id: number;
  effect: "closed" | "degraded";
  travel_time_multiplier: number | null;
  reason: string;
  source: string;
  confidence: number | null;
}

export interface StartingConditions {
  closed_count: number;
  degraded_count: number;
  roads_with_recent_reports: number;
  report_window_hours: number;
  affected_roads: AffectedRoad[];
  caveats: Record<string, string>;
}

export interface ScenarioResult {
  scenario: string;
  start_from?: "clean" | "current_conditions";
  starting_conditions?: StartingConditions;
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
  start_from?: "clean" | "current_conditions";
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

// ---------------------------------------------------------------------------
// Field reports (Phase 2, gap-analysis section 4).
//
// The reporter id is device-scoped and generated in the browser -- no account,
// no name, no phone number. People best placed to report a washed-out road are
// often standing in a disaster zone, and demanding identity to accept that
// report gets fewer reports and creates a record that could be misused.
// ---------------------------------------------------------------------------

export type ReportStatus = "clear" | "slow" | "blocked";

export interface FieldReportIn {
  status: ReportStatus;
  latitude: number;
  longitude: number;
  reporter_id: string;
  note?: string | null;
}

export interface EvidenceItem {
  kind: string;
  strength: number;
  detail: string;
  observed_at: string | null;
  source: string;
}

export interface IndependentEvidence {
  score: number;
  supports: boolean;
  window_hours: number;
  evidence: EvidenceItem[];
  note: string;
  caveat: string;
}

export interface FieldReportAck {
  id: number;
  road_id: number | null;
  status: ReportStatus;
  submitted_at: string;
  snapped_distance_m: number | null;
  counted_in_fusion: boolean;
  reporter_trust_score: number;
  trust_outcome: "corroborated" | "contradicted" | "no_consensus";
  trust_basis: "peers" | "independent_evidence" | "both" | "none";
  trust_explanation: string;
  independent_evidence: IndependentEvidence;
  note: string | null;
}

export interface StoredReport {
  id: number;
  road_id: number | null;
  status: ReportStatus;
  note: string | null;
  submitted_at: string;
  snapped_distance_m: number | null;
  trust_at_submission: number;
  longitude: number;
  latitude: number;
}

export interface RoadReportView {
  road_id: number;
  road: {
    name: string | null;
    road_class: string | null;
    district: string | null;
    is_bridge: boolean;
    baseline_accessibility: number | null;
  };
  field_reported: {
    status: ReportStatus | null;
    confidence: number;
    report_count: number;
    weight_by_status: Record<string, number>;
    newest_report_at: string | null;
    window_hours: number;
  };
  independent_evidence: IndependentEvidence;
  reports: StoredReport[];
  caveats: Record<string, string>;
}

const REPORTER_KEY = "setuner.reporter_id";

/** A stable, opaque, device-scoped id. Created once and kept in this browser. */
export function getReporterId(): string {
  if (typeof window === "undefined") return "server";
  try {
    const existing = window.localStorage.getItem(REPORTER_KEY);
    if (existing) return existing;
    const fresh = `device-${crypto.randomUUID()}`;
    window.localStorage.setItem(REPORTER_KEY, fresh);
    return fresh;
  } catch {
    // Private mode, or storage blocked. A per-session id still works; it just
    // means this reporter builds no trust history, which is the right
    // trade-off versus refusing the report altogether.
    return `device-ephemeral-${Math.random().toString(36).slice(2, 12)}`;
  }
}

export async function submitFieldReport(body: FieldReportIn): Promise<FieldReportAck> {
  const res = await fetch(`${API_BASE}/api/v1/field-reports`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const j = await res.json();
      if (j?.detail) detail = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail);
    } catch {
      /* not JSON; keep the status line */
    }
    throw new Error(detail);
  }
  return res.json();
}

export async function fetchRecentReports(limit = 100): Promise<StoredReport[]> {
  const res = await fetch(`${API_BASE}/api/v1/field-reports/recent?limit=${limit}`);
  if (!res.ok) throw new Error(`Failed to load reports: ${res.status}`);
  return (await res.json()).reports;
}

export async function fetchRoadReports(roadId: number): Promise<RoadReportView> {
  const res = await fetch(`${API_BASE}/api/v1/field-reports/road/${roadId}`);
  if (!res.ok) throw new Error(`Failed to load road ${roadId}: ${res.status}`);
  return res.json();
}

/** What the live layers currently say about the network, on its own. */
export async function fetchCurrentConditions(): Promise<StartingConditions> {
  const res = await fetch(`${API_BASE}/api/v1/scenarios/current-conditions`);
  if (!res.ok) throw new Error(`Failed to load current conditions: ${res.status}`);
  return res.json();
}

// ---------------------------------------------------------------------------
// Phase 3 accessibility model. See docs/decisions/0010-accessibility-model.md.
//
// Every metric arrives next to the persistence baseline it has to beat, and
// the UI is expected to show both: a probability with no reference point
// invites more trust than it has earned.
// ---------------------------------------------------------------------------

export interface MetricScore {
  n: number;
  positives?: number;
  brier?: number;
  log_loss?: number;
  roc_auc?: number | null;
  average_precision?: number | null;
}

export interface SplitMetrics {
  all: MetricScore;
  onset: MetricScore;
  recession: MetricScore;
}

export interface Period {
  from: string;
  to: string;
  examples: number;
  districts: number;
  positive_rate: number;
}

export interface ModelArtifact {
  version: string;
  horizon_days: number;
  served_kind: "logistic" | "persistence" | "climatology";
  trained_at: string;
  train_period: Period | null;
  test_period: Period | null;
  test_metrics: {
    served: SplitMetrics | null;
    logistic?: SplitMetrics | null;
    persistence: SplitMetrics | null;
    climatology: SplitMetrics | null;
  };
  verdict: {
    skill_vs_persistence: number | null;
    onset_skill_vs_persistence?: number | null;
    logistic_test_skill_vs_persistence?: number | null;
    logistic_test_onset_auc?: number | null;
    summary: string;
  };
}

export interface ModelStatus {
  artifacts: Record<string, ModelArtifact | null>;
  data: {
    published_report_days: number;
    districts_seen: number;
    first_report: string | null;
    latest_report: string | null;
  };
  scoring: {
    as_of: string;
    age_days: number;
    stale: boolean;
    model_version: string;
    roads_scored: number;
  } | null;
  live_track_record: Record<
    string,
    { n: number; note?: string; skill_vs_persistence?: number | null }
  >;
  exposure_prior: {
    formula: string;
    fitted: boolean;
    check: {
      matched_damage_reports: number;
      mean_exposure_of_damaged_roads: number | null;
      mean_exposure_all_scored_roads: number | null;
      enough_to_validate: boolean;
      note: string;
    };
  };
  caveats: Record<string, string>;
}

export interface DistrictForecast {
  district: string;
  in_corridor: boolean;
  affected_on_as_of: boolean;
  forecasts: {
    horizon_days: number;
    target_date: string;
    probability: number;
    persistence_probability: number;
    model_kind: string;
    model_version: string;
  }[];
}

export interface DistrictForecasts {
  as_of: string | null;
  age_days?: number;
  stale?: boolean;
  districts: DistrictForecast[];
  caveat?: string;
  note?: string;
}

export async function fetchModelStatus(): Promise<ModelStatus> {
  const res = await fetch(`${API_BASE}/api/v1/model/status`);
  if (!res.ok) throw new Error(`Failed to load model status: ${res.status}`);
  return res.json();
}

export async function fetchDistrictForecasts(): Promise<DistrictForecasts> {
  const res = await fetch(`${API_BASE}/api/v1/model/districts`);
  if (!res.ok) throw new Error(`Failed to load forecasts: ${res.status}`);
  return res.json();
}
