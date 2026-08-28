"""
Phase 2: first-pass hazard context per road edge, via district spatial join.

Takes the road graph (edges.geojson, from build_road_graph.py) and the
district boundaries (districts.geojson, from fetch_district_boundaries.py),
spatially joins each edge to the district it falls in, and attaches the
2025 flood severity for that district from the ASDMA Flood Memorandum.

IMPORTANT -- what this is and isn't:
- This is a HISTORICAL / RETROSPECTIVE severity proxy (the 2025 season,
  already over), not a live hazard_exposure value. It's saved as a
  separate column (hist_flood_severity_2025) rather than overwriting
  hazard_exposure, to keep observed/derived/historical data distinguishable
  (see docs/decisions/0001-gap-analysis-and-enhancements.md section 2.3).
- It's district-level granularity, not per-road. Every edge in a district
  gets the same score. This is a coarse first-pass baseline, not a
  precise hazard signal -- refine later with flood-extent polygons.

Severity metric: % of the district's villages affected during the 2025
flood season (villages affected / total villages, both from the
Memorandum). Chosen over raw population-affected count because it's
normalized and comparable across districts of very different sizes.

CRITICAL NAME MAPPING: Karimganj district was renamed to Sribhumi
district. The Memorandum's 2025 tables use "Sribhumi"; OSM's boundary
(and our districts.geojson) still uses "Karimganj". This script maps
them explicitly -- get this wrong and Sribhumi's real numbers (the
highest population-affected of our four districts) silently vanish.

RUN THIS LOCALLY, from the geo/osm folder where edges.geojson and
districts.geojson already exist (no network needed -- everything it
reads is already on disk).

    pip install -r requirements.txt
    python assign_district_hazard_context.py
"""

import sys
from pathlib import Path

try:
    import geopandas as gpd
except ImportError:
    print("Missing dependencies. Run: pip install -r requirements.txt")
    sys.exit(1)

HERE = Path(__file__).parent
EDGES_PATH = HERE / "edges.geojson"
DISTRICTS_PATH = HERE / "districts.geojson"
OUTPUT_PATH = HERE / "edges_with_hazard_context.geojson"

DISTRICT_2025_DATA = {
    "Cachar": {
        "memorandum_name": "Cachar",
        "total_villages": 1040,
        "villages_affected": 297,
        "population_affected": 171610,
        "flood_deaths": 4,
    },
    "Karimganj": {
        "memorandum_name": "Sribhumi",
        "total_villages": 936,
        "villages_affected": 389,
        "population_affected": 295502,
        "flood_deaths": 4,
    },
    "Hailakandi": {
        "memorandum_name": "Hailakandi",
        "total_villages": 331,
        "villages_affected": 221,
        "population_affected": 219009,
        "flood_deaths": 2,
    },
    "Dima Hasao": {
        "memorandum_name": "Dima Hasao",
        "total_villages": 695,
        "villages_affected": 17,
        "population_affected": 0,
        "flood_deaths": 0,  # 2 landslide deaths recorded separately -- a different hazard type
    },
}


def severity_score(d: dict) -> float:
    return d["villages_affected"] / d["total_villages"]


def match_district(district_query: str) -> str | None:
    for key in DISTRICT_2025_DATA:
        if key.lower() in district_query.lower():
            return key
    return None


def assign_hazard_context(edges_gdf: gpd.GeoDataFrame, districts_gdf: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    districts_gdf = districts_gdf.copy()
    districts_gdf["district_key"] = districts_gdf["district_query"].apply(match_district)
    unmatched = districts_gdf[districts_gdf["district_key"].isna()]
    if len(unmatched) > 0:
        raise ValueError(f"Couldn't match {len(unmatched)} district(s) to our lookup table: "
                          f"{unmatched['district_query'].tolist()}")

    joined = gpd.sjoin(edges_gdf, districts_gdf[["district_key", "geometry"]],
                        how="left", predicate="intersects")
    joined = joined[~joined.index.duplicated(keep="first")]

    def lookup(key):
        if key is None or key not in DISTRICT_2025_DATA:
            return None, None, None
        d = DISTRICT_2025_DATA[key]
        return severity_score(d), d["population_affected"], d["flood_deaths"]

    scores, pops, deaths = [], [], []
    for key in joined["district_key"]:
        s, p, dth = lookup(key)
        scores.append(s)
        pops.append(p)
        deaths.append(dth)

    joined["district"] = joined["district_key"]
    joined["hist_flood_severity_2025"] = scores
    joined["hist_population_affected_2025"] = pops
    joined["hist_flood_deaths_2025"] = deaths
    joined = joined.drop(columns=["district_key", "index_right"], errors="ignore")

    return joined


def main():
    if not EDGES_PATH.exists() or not DISTRICTS_PATH.exists():
        print(f"Missing input file(s). Expected both:\n  {EDGES_PATH}\n  {DISTRICTS_PATH}\n"
              f"Run build_road_graph.py and fetch_district_boundaries.py first.")
        sys.exit(1)

    print("Loading edges and districts...")
    edges_gdf = gpd.read_file(EDGES_PATH)
    districts_gdf = gpd.read_file(DISTRICTS_PATH)

    print("Assigning district hazard context to each edge...")
    result = assign_hazard_context(edges_gdf, districts_gdf)

    result.to_file(OUTPUT_PATH, driver="GeoJSON")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print(f"Total edges: {len(result)}")
    matched = result["district"].notna().sum()
    print(f"Edges matched to a district: {matched} ({matched / len(result) * 100:.0f}%)")
    print("\nEdges per district and their 2025 severity score:")
    for district, group in result.groupby("district"):
        if district is None:
            continue
        severity = group["hist_flood_severity_2025"].iloc[0]
        print(f"  {district:15s}: {len(group):6d} edges, severity {severity:.2f} "
              f"({severity*100:.0f}% of villages affected in 2025)")
    unmatched_count = result["district"].isna().sum()
    if unmatched_count:
        print(f"\n{unmatched_count} edges fell outside all four district boundaries "
              f"(expected at the edges of the bounding box used in Phase 1).")
    print(f"\nSaved: {OUTPUT_PATH.name}")


if __name__ == "__main__":
    main()