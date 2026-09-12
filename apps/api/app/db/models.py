"""
Database models for the road graph and districts.

Every column here maps directly to something a real script in geo/osm/
already produces -- there's no speculative schema here, this mirrors
exactly what build_road_graph.py, assign_district_hazard_context.py, and
compute_baseline_accessibility.py actually output today.

current_accessibility, predicted_accessibility, hazard_exposure, and
confidence stay nullable and unpopulated -- those are for live/forecast
data (Phase 3+), genuinely different from the historical baseline columns
here. Keeping them separate columns, not overloading baseline_accessibility
to mean two different things, is deliberate (see
docs/decisions/0001-gap-analysis-and-enhancements.md section 2.3 on why
observed/derived/historical needs to stay distinguishable).
"""

from geoalchemy2 import Geometry
from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    Column,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import declarative_base

Base = declarative_base()


class Road(Base):
    __tablename__ = "roads"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # from build_road_graph.py
    osm_u = Column(BigInteger, nullable=True)
    osm_v = Column(BigInteger, nullable=True)
    osm_key = Column(Integer, nullable=True)
    name = Column(String, nullable=True)
    road_class = Column(String, nullable=True, index=True)
    is_bridge = Column(Boolean, nullable=False, default=False, index=True)
    length_km = Column(Float, nullable=True)
    assumed_speed_kmh = Column(Float, nullable=True)
    baseline_travel_time_min = Column(Float, nullable=True)
    edge_type = Column(String, nullable=True, default="road")  # "road" | "ferry" later

    # from assign_district_hazard_context.py
    district = Column(String, nullable=True, index=True)
    hist_flood_severity_2025 = Column(Float, nullable=True)
    hist_population_affected_2025 = Column(Integer, nullable=True)
    hist_flood_deaths_2025 = Column(Integer, nullable=True)

    # from geo/dem/sample_road_elevation.py
    #
    # Terrain is the missing half of why a road floods. Two roads with the
    # same district flood severity are not equally at risk if one sits on a
    # ridge and the other in the floodplain -- and the corridor spans both,
    # from the Barak valley floor around 20 m to the Dima Hasao hills above
    # 700 m. These columns are what lets a model say so.
    elevation_m = Column(Float, nullable=True, index=True)
    slope_pct = Column(Float, nullable=True)
    elevation_source = Column(String, nullable=True)

    # from compute_baseline_accessibility.py
    baseline_accessibility = Column(Float, nullable=True, index=True)
    baseline_accessibility_basis = Column(String, nullable=True)
    baseline_accessibility_confidence = Column(String, nullable=True)

    # reserved for Phase 3+ (live/forecast) -- intentionally empty for now
    current_accessibility = Column(Float, nullable=True)
    predicted_accessibility = Column(String, nullable=True)  # will hold a forecast vector, not a scalar -- see gap-analysis 2.2
    hazard_exposure = Column(Float, nullable=True)
    confidence = Column(String, nullable=True)
    scenario_state = Column(String, nullable=True, default="baseline")

    geometry = Column(Geometry(geometry_type="LINESTRING", srid=4326), nullable=False)


class District(Base):
    __tablename__ = "districts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    display_name = Column(String, nullable=True)
    district_query = Column(String, nullable=True)
    geometry = Column(Geometry(geometry_type="MULTIPOLYGON", srid=4326), nullable=False)

class IngestRun(Base):
    """
    One attempt to pull from one source. Written before the fetch starts and
    updated when it ends, so a crashed or hung run is still visible as
    'running' rather than vanishing.

    This table is why a failed fetch is safe: ingestion never deletes or
    blanks existing observations, it only ever adds. A source that goes down
    therefore shows up as stale data plus a failed run -- never as an empty
    map that looks like "no flooding".
    """

    __tablename__ = "ingest_runs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    source = Column(String, nullable=False, index=True)
    hazard_type = Column(String, nullable=True, index=True)

    started_at = Column(DateTime(timezone=True), nullable=False, index=True)
    finished_at = Column(DateTime(timezone=True), nullable=True)

    # running | success | no_data | failed
    status = Column(String, nullable=False, index=True, default="running")

    target_date = Column(Date, nullable=True)
    source_url = Column(String, nullable=True)
    rows_parsed = Column(Integer, nullable=False, default=0)
    rows_written = Column(Integer, nullable=False, default=0)
    rows_duplicate = Column(Integer, nullable=False, default=0)
    error = Column(Text, nullable=True)


class HazardObservation(Base):
    """
    One measured or reported fact about a hazard, from one source, at one time.

    HAZARD-AGNOSTIC ON PURPOSE (docs/decisions/0001 section 3)
    The original spec promised extensibility to landslides and other hazards
    while every table was flood-specific. This one is not: `hazard_type` and
    `metric` carry the meaning, so a landslide or rainfall row lands in the
    same table with the same provenance columns. The DRIMS source already
    publishes eleven hazard types behind one endpoint, so this is a real
    capability rather than a slide claim.

    TWO TIMESTAMPS, DELIBERATELY
    `observed_at` is when the world was in this state; `fetched_at` is when we
    pulled it. Staleness is the gap between observed_at and now, and it cannot
    be computed honestly without both. The gap-analysis asked for staleness
    tracking from day one rather than bolted on later.

    RAW IS KEPT
    `raw` holds the original parsed row verbatim. A parsing bug is then
    auditable and re-derivable from stored data instead of requiring a
    re-fetch, and nobody has to trust the parser to inspect the source.

    IDEMPOTENT
    `observation_key` is unique, so re-running an ingest for the same day
    updates nothing and inserts nothing. Re-running is therefore always safe.
    """

    __tablename__ = "hazard_observations"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # --- what ---
    hazard_type = Column(String, nullable=False, index=True)  # flood, landslide, ...
    metric = Column(String, nullable=False, index=True)       # villages_affected, ...
    value_num = Column(Float, nullable=True)
    value_text = Column(String, nullable=True)
    unit = Column(String, nullable=True)

    # --- where ---
    # place_name is whatever the source printed; district is our normalised
    # name. Both are kept because the source renamed Karimganj to Sribhumi in
    # 2024 and the road graph still says Karimganj -- losing the original
    # would make that mapping unverifiable.
    place_name = Column(String, nullable=True, index=True)
    district = Column(String, nullable=True, index=True)
    geometry = Column(Geometry(geometry_type="POINT", srid=4326), nullable=True)

    # --- when ---
    observed_at = Column(DateTime(timezone=True), nullable=True, index=True)
    fetched_at = Column(DateTime(timezone=True), nullable=False, index=True)

    # --- provenance and trust, same discipline as the roads table ---
    source = Column(String, nullable=False, index=True)
    source_url = Column(String, nullable=False)
    source_document_date = Column(Date, nullable=True, index=True)
    basis = Column(String, nullable=False)
    confidence = Column(String, nullable=False)
    raw = Column(JSON, nullable=True)

    observation_key = Column(String, nullable=False, unique=True, index=True)
    ingest_run_id = Column(Integer, ForeignKey("ingest_runs.id"), nullable=True, index=True)


class Reporter(Base):
    """
    Whoever is sending field reports, and how much weight their reports carry.

    NO PERSONAL DATA, DELIBERATELY. `id` is a device-scoped opaque string the
    client generates and keeps -- not a name, phone number, or account. The
    people best placed to report a washed-out road are often reporting from a
    disaster zone, and a system that demands identity to accept that report
    gets fewer reports and creates a record that could be misused. Trust is
    built from behaviour over time, which needs continuity of identity but
    not knowledge of it.

    Trust starts neutral rather than at zero: a new reporter's first message
    about a collapsed bridge should still be visible, just not decisive.
    """

    __tablename__ = "reporters"

    id = Column(String, primary_key=True)
    trust_score = Column(Float, nullable=False, default=0.5)
    reports_submitted = Column(Integer, nullable=False, default=0)
    times_corroborated = Column(Integer, nullable=False, default=0)
    times_contradicted = Column(Integer, nullable=False, default=0)
    first_seen_at = Column(DateTime(timezone=True), nullable=False)
    last_seen_at = Column(DateTime(timezone=True), nullable=False)


class FieldReport(Base):
    """
    One person's report that a specific place is clear, slow, or blocked.

    WHY THIS TABLE EXISTS AT ALL (docs/decisions/0001 section 4)
    The problem statement asks for real-time field inputs alongside AI/ML and
    GIS. Official telemetry across the NER is genuinely sparse, so human
    reports are not a UX nicety -- they are how the data gap actually gets
    filled. In the 2022 Bethukandi dyke breach an on-site engineer reported it
    by radio before it appeared in any feed.

    A REPORT IS AN OBSERVATION, NOT A VERDICT
    Reports are stored exactly as submitted and never overwrite anything.
    Whatever the fusion layer concludes from them is derived at read time and
    kept separate, so a wrong or malicious report can be reweighted or
    excluded later without the original record having been lost.

    `trust_at_submission` freezes the reporter's trust as it stood when the
    report arrived. Trust changes afterwards; freezing it here is what keeps
    an old fused result reproducible instead of silently shifting under you.
    """

    __tablename__ = "field_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Nullable on purpose: a report from outside the corridor snaps to nothing.
    # It is still stored, flagged, and excluded from fusion -- discarding it
    # would hide the fact that someone is reporting from an area we do not cover.
    road_id = Column(Integer, ForeignKey("roads.id"), nullable=True, index=True)
    snapped_distance_m = Column(Float, nullable=True)

    status = Column(String, nullable=False, index=True)  # clear | slow | blocked
    note = Column(String, nullable=True)
    geometry = Column(Geometry(geometry_type="POINT", srid=4326), nullable=False)

    reporter_id = Column(String, ForeignKey("reporters.id"), nullable=False, index=True)
    trust_at_submission = Column(Float, nullable=False)

    submitted_at = Column(DateTime(timezone=True), nullable=False, index=True)


class SatelliteAcquisition(Base):
    """
    A radar pass that actually covered the corridor.

    WHY THIS EXISTS AND FLOOD EXTENT DOES NOT
    Phase 2 wanted Sentinel-1 flood-extent polygons. Two things stand in the
    way, and neither is solved by writing more code here:

      Download needs credentials. The Copernicus catalogue answers search
      queries anonymously -- that is how these rows get written -- but asking
      for the scene itself returns 401 without a registered account.

      Turning a 1.7 GB GRD scene into flood polygons needs calibration,
      speckle filtering, terrain correction and water thresholding. That is a
      SAR processing pipeline, and `0001` section 1 already concluded the
      bottleneck there is expertise rather than access, and said to keep it
      optional rather than let it block the vertical slice.

    Producing polygons anyway, from a rushed threshold on an unprocessed
    scene, would put flood boundaries on a map that nobody could defend. So
    this table records what it can honestly record: when radar looked, what
    it captured, and therefore how stale the *potential* evidence is.

    That is genuinely useful on its own. An operator asking "could anything
    have confirmed this report?" gets a real answer, and the observed cadence
    says when the next chance arrives. It is also the discovery half of the
    pipeline, so adding download and processing later is an extension rather
    than a rewrite.
    """

    __tablename__ = "satellite_acquisitions"

    id = Column(Integer, primary_key=True, autoincrement=True)

    # Copernicus product id -- stable, and what makes re-fetching idempotent.
    product_id = Column(String, nullable=False, unique=True, index=True)
    name = Column(String, nullable=False)

    mission = Column(String, nullable=False, index=True)  # SENTINEL-1
    product_type = Column(String, nullable=True, index=True)  # IW_GRDH_1S, SLC, RAW
    acquired_at = Column(DateTime(timezone=True), nullable=False, index=True)

    size_bytes = Column(BigInteger, nullable=True)
    online = Column(Boolean, nullable=True)

    footprint = Column(Geometry(geometry_type="POLYGON", srid=4326), nullable=True)

    source = Column(String, nullable=False)
    source_url = Column(String, nullable=False)
    fetched_at = Column(DateTime(timezone=True), nullable=False, index=True)
