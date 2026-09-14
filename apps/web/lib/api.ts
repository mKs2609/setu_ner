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

// ---------------------------------------------------------------------------
// Phase 4: demand and supply planning. See docs/decisions/0011.
//
// Stock and fleet are operator inputs the system cannot know. The API echoes
// `example_inputs` so a plan built on the example figures says so on screen.
// ---------------------------------------------------------------------------

export type Commodity = "water" | "food";

export interface SupplyDay {
  date: string;
  people: number;
}

export interface CircleNeed {
  district: string;
  circle: string;
  people_to_supply: number;
  camp_inmates: number;
  centre_inmates: number;
  population_affected: number | null;
  needs: Record<Commodity, number>;
  location: { lon: number; lat: number; resolved_by: string; note: string | null } | null;
  location_problem: string | null;
  conflicts: string[];
}

export interface NormInfo {
  label: string;
  unit: string;
  per_person_per_day: number;
  kg_per_unit: number;
  urgency: number;
  source: string;
  basis: string;
}

export interface DemandResponse {
  as_of: string;
  horizon_days: number;
  totals: {
    people_to_supply: number;
    people_located: number;
    people_unlocated: number;
    needs: Record<Commodity, number>;
  };
  circles: CircleNeed[];
  unattributed_by_district: Record<string, Record<string, number>>;
  norms: Record<Commodity, NormInfo>;
  caveats: Record<string, string>;
}

export interface DepotForm {
  name: string;
  place?: string;
  stock: Record<Commodity, number>;
  trucks: number;
}

export interface ExampleInputs {
  depots: DepotForm[];
  fleet: { truck_capacity_kg: number; hours_per_day: number; loading_hours_per_trip: number };
  note: string;
}

export interface PlanRequest {
  as_of?: string;
  horizon_days: number;
  depots: DepotForm[];
  fleet: { truck_capacity_kg: number; hours_per_day: number; loading_hours_per_trip: number };
  risk_minutes_per_exposure_km: number;
  fairness_first: boolean;
  example_inputs: boolean;
  save?: boolean;
  label?: string;
}

export interface RouteSummary {
  reachable: boolean;
  travel_min?: number;
  distance_km?: number;
  exposure_km?: number;
  unscored_km?: number;
  weakest_accessibility?: number | null;
  bridges?: number;
}

export interface PlanRoute {
  depot: string;
  circle: string;
  used_in_plan: boolean;
  fastest: RouteSummary;
  lower_exposure: RouteSummary | null;
  routes_diverge: boolean;
  chosen: "fastest" | "lower_exposure";
  local_delivery: boolean;
  geometry?: [number, number][];
  alternative_geometry?: [number, number][];
}

export interface PlanRun {
  depot: string;
  circle: string;
  kg: number;
  items: Partial<Record<Commodity, number>>;
  one_way_min: number;
  truckloads: number;
  truck_hours: number;
}

export interface PlanResponse {
  as_of: string;
  latest_report: string;
  is_replay: boolean;
  example_inputs: boolean;
  example_note: string | null;
  demand: DemandResponse;
  depots: {
    key: string;
    name: string;
    located_by: string;
    snap_km: number;
    lon: number;
    lat: number;
    stock: Record<Commodity, number>;
    trucks: number;
  }[];
  plan: {
    status: string;
    policy: "coverage_first" | "fairness_first";
    runs: PlanRun[];
    shortfalls: {
      circle: string;
      commodity: Commodity;
      short: number;
      unit: string;
      fraction: number | null;
      reason: string;
    }[];
    worst_shortfall_fraction: number | null;
    person_days_needed_all_commodities: number;
    person_days_covered_all_commodities: number;
    truck_hours: number;
    people_outside_plan: number;
    limits: { kind: string; depot: string; plain: string }[];
    depot_use: {
      depot: string;
      name: string;
      sent: Record<Commodity, number>;
      truck_hours_used: number;
      truck_hours_available: number;
    }[];
  };
  routes: PlanRoute[];
  risk: {
    accessibility_source: string;
    district_p_affected_next_day: Record<string, number>;
    risk_minutes_per_exposure_km: number;
    live_conditions_applied: boolean;
    closed_roads: number;
    degraded_roads: number;
  };
  problems: string[];
  caveats: Record<string, string>;
  explanation: PlanExplanation;
  recommendation_id: string | null;
}

export async function fetchSupplyDays(): Promise<SupplyDay[]> {
  const res = await fetch(`${API_BASE}/api/v1/logistics/supply-days`);
  if (!res.ok) throw new Error(`Failed to load supply days: ${res.status}`);
  return (await res.json()).days;
}

export async function fetchExampleInputs(): Promise<ExampleInputs> {
  const res = await fetch(`${API_BASE}/api/v1/logistics/example-inputs`);
  if (!res.ok) throw new Error(`Failed to load example inputs: ${res.status}`);
  return res.json();
}

export async function requestPlan(body: PlanRequest): Promise<PlanResponse> {
  const res = await fetch(`${API_BASE}/api/v1/logistics/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(
      typeof detail?.detail === "string" ? detail.detail : `Planning failed: ${res.status}`
    );
  }
  return res.json();
}

// ---------------------------------------------------------------------------
// Phase 6: explanations and the audit trail. See docs/decisions/0012.
//
// Every explanation is filled in from the figures it explains; statements
// carry their evidence so the UI can show the numbers behind a sentence.
// ---------------------------------------------------------------------------

export interface Statement {
  text: string;
  evidence: Record<string, unknown>;
}

export interface PlanExplanation {
  summary: string;
  sections: { title: string; statements: Statement[] }[];
  method: string;
}

export interface Contribution {
  feature: string;
  value: number;
  log_odds: number;
  direction: "raises" | "lowers" | "none";
  sentence: string;
}

export interface ForecastExplanation {
  district: string;
  horizon_days: number;
  model_kind: string;
  model_version: string;
  probability: number;
  method: "exact_linear_attribution" | "rule" | "none";
  headline: string;
  contributions: Contribution[];
  average_district_probability?: number;
  check?: { reconstructed_probability: number; matches_prediction: boolean };
  how_to_read?: string;
  why_this_model?: string;
}

export interface RoadExplanation {
  road_id: number;
  scored: boolean;
  as_of?: string | null;
  headline: string;
  district_forecast?: ForecastExplanation | null;
  terrain?: {
    elevation_m: number | null;
    district_floor_m: number | null;
    height_above_floor_m: number | null;
    exposure: number | null;
    is_a_prior: boolean;
    formula: string;
  };
  baseline_comparison?: string | null;
  explains_stored_value?: boolean;
  model_mismatch_note?: string | null;
  trust?: string;
}

export interface RecommendationSummary {
  id: string;
  kind: string;
  label: string | null;
  created_at: string;
  data_as_of: string;
  is_replay: boolean;
  example_inputs: boolean;
  people_to_supply: number | null;
  coverage: number | null;
  worst_shortfall_fraction: number | null;
  override_count: number | null;
}

export interface RecommendationRecord extends RecommendationSummary {
  model_versions: Record<string, string | null>;
  inputs: Record<string, unknown>;
  outputs: Omit<PlanResponse, "explanation" | "recommendation_id">;
  note: string;
}

export type OverrideAction = "accepted" | "modified" | "rejected";

export const REASON_CATEGORIES = [
  ["road_condition_differs", "Road was not as forecast"],
  ["stock_figure_wrong", "Depot stock figure was wrong"],
  ["fleet_unavailable", "Trucks or drivers unavailable"],
  ["demand_differs", "People on the ground differ from the report"],
  ["priority_judgement", "Chose a different priority"],
  ["other", "Other"],
] as const;

export interface OverrideRecord {
  id: number;
  created_at: string;
  operator_id: string;
  action: OverrideAction;
  target: string | null;
  reason_category: string;
  reason: string;
}

async function getJson<T>(path: string, what: string): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`);
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(typeof detail?.detail === "string" ? detail.detail : `Failed to load ${what}: ${res.status}`);
  }
  return res.json();
}

export function fetchDistrictExplanation(district: string): Promise<{
  district: string;
  as_of: string;
  explanations: ForecastExplanation[];
  caveat: string;
}> {
  return getJson(`/api/v1/model/explain/${encodeURIComponent(district)}`, "explanation");
}

export function fetchRoadExplanation(roadId: number): Promise<RoadExplanation> {
  return getJson(`/api/v1/accessibility/${roadId}/explanation`, "road explanation");
}

export async function fetchRecommendations(): Promise<RecommendationSummary[]> {
  return (await getJson<{ recommendations: RecommendationSummary[] }>(
    "/api/v1/recommendations", "recommendations"
  )).recommendations;
}

export function fetchRecommendation(id: string): Promise<RecommendationRecord> {
  return getJson(`/api/v1/recommendations/${encodeURIComponent(id)}`, "recommendation");
}

export function fetchRecommendationExplanation(id: string): Promise<PlanExplanation & { id: string }> {
  return getJson(`/api/v1/recommendations/${encodeURIComponent(id)}/explanation`, "explanation");
}

export async function fetchOverrides(id: string): Promise<OverrideRecord[]> {
  return (await getJson<{ overrides: OverrideRecord[] }>(
    `/api/v1/recommendations/${encodeURIComponent(id)}/overrides`, "overrides"
  )).overrides;
}

const OPERATOR_KEY = "setuner.operator_id";

/** Opaque, device-scoped operator id, same approach as the reporter id. */
export function getOperatorId(): string {
  if (typeof window === "undefined") return "server";
  try {
    const existing = window.localStorage.getItem(OPERATOR_KEY);
    if (existing) return existing;
    const fresh = `operator-${crypto.randomUUID()}`;
    window.localStorage.setItem(OPERATOR_KEY, fresh);
    return fresh;
  } catch {
    return `operator-session-${Math.random().toString(36).slice(2, 12)}`;
  }
}

export async function postOverride(
  id: string,
  body: { action: OverrideAction; reason_category: string; reason: string; target?: string }
): Promise<OverrideRecord> {
  const res = await fetch(`${API_BASE}/api/v1/recommendations/${encodeURIComponent(id)}/overrides`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...body, operator_id: getOperatorId() }),
  });
  if (!res.ok) {
    const detail = await res.json().catch(() => null);
    throw new Error(typeof detail?.detail === "string" ? detail.detail : `Could not record override: ${res.status}`);
  }
  return res.json();
}
