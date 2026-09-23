"""
Loads the geo/osm pipeline's output files into PostGIS.

Reads edges_with_baseline_accessibility.geojson (the final, richest
output -- has everything from every earlier script) and districts.geojson,
and writes them into the roads and districts tables.

This REPLACES table contents each run (truncate + reload), not append --
these are regenerable outputs, re-running the geo/osm scripts and then
this loader is the intended workflow when data updates, not accumulating
duplicate rows over time.

RUN THIS LOCALLY, from geo/osm, with Postgres running.

    pip install -r requirements.txt
    python load_into_postgis.py
"""

import sys
from pathlib import Path

try:
    import geopandas as gpd
    from sqlalchemy import create_engine, text
except ImportError:
    print("Missing dependencies. Run: pip install -r requirements.txt")
    sys.exit(1)

# Import the real models from apps/api rather than duplicating them here --
# this script and the API must always agree on the schema, so there's only
# ever one models.py, not two copies that can drift apart.
API_APP_DIR = Path(__file__).resolve().parents[2] / "apps" / "api"
sys.path.insert(0, str(API_APP_DIR))
from app.db.models import Road, District

HERE = Path(__file__).parent
EDGES_PATH = HERE / "edges_with_baseline_accessibility.geojson"
DISTRICTS_PATH = HERE / "districts.geojson"

DATABASE_URL = "postgresql://setuner:setuner@localhost:5432/setuner"


def load_roads(engine, edges_path: Path):
    print(f"Loading {edges_path.name}...")
    edges = gpd.read_file(edges_path)

    rename_map = {"u": "osm_u", "v": "osm_v", "key": "osm_key"}
    edges = edges.rename(columns={k: v for k, v in rename_map.items() if k in edges.columns})

    valid_columns = {
        "osm_u", "osm_v", "osm_key", "name", "road_class", "is_bridge",
        "length_km", "assumed_speed_kmh", "baseline_travel_time_min",
        "edge_type", "district", "hist_flood_severity_2025",
        "hist_population_affected_2025", "hist_flood_deaths_2025",
        "baseline_accessibility", "baseline_accessibility_basis",
        "baseline_accessibility_confidence", "current_accessibility",
        "hazard_exposure", "confidence", "scenario_state",
    }
    keep_cols = [c for c in edges.columns if c in valid_columns]

    if "is_bridge" in edges.columns:
        edges["is_bridge"] = edges["is_bridge"].fillna(False).astype(bool)

    print(f"  {len(edges)} rows, columns: {sorted(keep_cols)}")

    from geoalchemy2.shape import from_shape

    records = []
    for _, row in edges.iterrows():
        record = {col: _to_scalar(row[col]) for col in keep_cols}
        record["geometry"] = from_shape(row["geometry"], srid=4326)
        records.append(record)

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE roads RESTART IDENTITY"))

    roads_table = Road.__table__
    with engine.begin() as conn:
        conn.execute(roads_table.insert(), records)

    print(f"  Loaded {len(records)} roads into PostGIS")


def _to_scalar(value):
    """Converts any value to something psycopg2 can actually insert.
    Handles the normal cases (None, NaN) but also array-like values --
    OSM road segments merged during simplification can end up with a
    name field holding multiple names (a list/array), not one string,
    and Postgres correctly refuses to insert an array into a text
    column. Joins array values into a readable string instead of
    silently dropping data or crashing."""
    import math
    import numpy as np

    if value is None:
        return None
    if isinstance(value, float) and math.isnan(value):
        return None
    if isinstance(value, (list, tuple, np.ndarray)):
        return "; ".join(str(v) for v in value)
    if isinstance(value, np.generic):
        return value.item()
    return value


def load_districts(engine, districts_path: Path):
    if not districts_path.exists():
        print(f"{districts_path.name} not found, skipping districts load")
        return

    print(f"Loading {districts_path.name}...")
    districts = gpd.read_file(districts_path)

    from shapely.geometry import MultiPolygon, Polygon
    from geoalchemy2.shape import from_shape

    def to_multipolygon(geom):
        if isinstance(geom, Polygon):
            return MultiPolygon([geom])
        return geom
    districts["geometry"] = districts["geometry"].apply(to_multipolygon)

    valid_columns = {"display_name", "district_query"}
    keep_cols = [c for c in districts.columns if c in valid_columns]

    records = []
    for _, row in districts.iterrows():
        record = {col: _to_scalar(row[col]) for col in keep_cols}
        record["geometry"] = from_shape(row["geometry"], srid=4326)
        records.append(record)

    with engine.begin() as conn:
        conn.execute(text("TRUNCATE TABLE districts RESTART IDENTITY"))

    districts_table = District.__table__
    with engine.begin() as conn:
        conn.execute(districts_table.insert(), records)

    print(f"  Loaded {len(records)} districts into PostGIS")


def main():
    if not EDGES_PATH.exists():
        print(f"Missing {EDGES_PATH.name}. Run the geo/osm pipeline scripts first "
              f"(build_road_graph.py -> assign_district_hazard_context.py -> "
              f"compute_baseline_accessibility.py).")
        sys.exit(1)

    print(f"Connecting to {DATABASE_URL}...")
    try:
        engine = create_engine(DATABASE_URL)
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as e:
        print(f"Couldn't connect to Postgres: {e}")
        print("Is it running and did you create the setuner database/user?")
        sys.exit(1)

    load_roads(engine, EDGES_PATH)
    load_districts(engine, DISTRICTS_PATH)

    with engine.connect() as conn:
        road_count = conn.execute(text("SELECT COUNT(*) FROM roads")).scalar()
        scored_count = conn.execute(text("SELECT COUNT(*) FROM roads WHERE baseline_accessibility IS NOT NULL")).scalar()
        district_count = conn.execute(text("SELECT COUNT(*) FROM districts")).scalar()

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"roads table: {road_count} rows ({scored_count} with a baseline_accessibility score)")
    print(f"districts table: {district_count} rows")
    print("\nDone. The API can now query real data instead of stubs.")


if __name__ == "__main__":
    main()