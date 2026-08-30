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
from sqlalchemy import Column, Integer, String, Float, Boolean, BigInteger
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