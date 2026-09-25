"""
First-pass hazard context per road edge, via district spatial join.

Takes the road graph (edges.geojson) and district boundaries
(districts.geojson, now 6 districts -- see fetch_district_boundaries.py),
spatially joins each edge to its district, and attaches 2025 flood
severity for the four Assam districts we have real ASDMA Memorandum data
for.

East Jaintia Hills and West Jaintia Hills (Meghalaya) are explicitly
RECOGNIZED but INTENTIONALLY UNSCORED: their entries in
DISTRICT_2025_DATA are None on purpose. There's no ASDMA-equivalent
annual statistical report for Meghalaya, and this area's real documented
hazard is landslide (Sonapur tunnel, recurring), not flood -- forcing our
Assam flood-severity formula onto it would mean fabricating a number for
the wrong hazard type. Roads here now get correctly labeled by district
(better than the previous "no match at all"), with an honest null score,
not a guessed one.

CRITICAL NAME MAPPING: Karimganj district was renamed to Sribhumi
district. The Memorandum's 2025 tables use "Sribhumi"; OSM's boundary
still uses "Karimganj". Mapped explicitly below.

RUN THIS LOCALLY, from geo/osm (no network needed, reads local files).

    python assign_district_hazard_context.py
"""

import sys
from pathlib import Path

try:
    import geopandas as gpd
except ImportError:
    print("Missing dependencies. Run: pip install geopandas")
    sys.exit(1)

HERE = Path(__file__).parent
EDGES_PATH = HERE / "edges.geojson"
DISTRICTS_PATH = HERE / "districts.geojson"
OUTPUT_PATH = HERE / "edges_with_hazard_context.geojson"

DISTRICT_2025_DATA = {
    "Cachar": {
        "memorandum_name": "Cachar",
        "data": {"total_villages": 1040, "villages_affected": 297, "population_affected": 171610, "flood_deaths": 4},
    },
    "Karimganj": {
        "memorandum_name": "Sribhumi",
        "data": {"total_villages": 936, "villages_affected": 389, "population_affected": 295502, "flood_deaths": 4},
    },
    "Hailakandi": {
        "memorandum_name": "Hailakandi",
        "data": {"total_villages": 331, "villages_affected": 221, "population_affected": 219009, "flood_deaths": 2},
    },
    "Dima Hasao": {
        "memorandum_name": "Dima Hasao",
        "data": {"total_villages": 695, "villages_affected": 17, "population_affected": 0, "flood_deaths": 0},
    },
    "East Jaintia Hills": {
        "memorandum_name": None,
        "data": None,  # no ASDMA-equivalent source; real hazard here is landslide, not flood -- see module docstring
    },
    "West Jaintia Hills": {
        "memorandum_name": None,
        "data": None,
    },
}


def severity_score(data: dict) -> float:
    return data["villages_affected"] / data["total_villages"]


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
        raise ValueError(f"Couldn't match {len(unmatched)} district(s) to our lookup table -- "
                          f"either a genuinely new district or a name mismatch to fix: "
                          f"{unmatched['district_query'].tolist()}")

    joined = gpd.sjoin(edges_gdf, districts_gdf[["district_key", "geometry"]],
                        how="left", predicate="intersects")
    joined = joined[~joined.index.duplicated(keep="first")]

    def lookup(key):
        if key is None or key not in DISTRICT_2025_DATA:
            return None, None, None
        data = DISTRICT_2025_DATA[key]["data"]
        if data is None:
            return None, None, None  # recognized district, genuinely no hazard data -- not an error
        return severity_score(data), data["population_affected"], data["flood_deaths"]

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
    print("\nEdges per district:")
    for district, group in result.groupby("district"):
        if district is None:
            continue
        severity = group["hist_flood_severity_2025"].iloc[0]
        if severity is not None and severity == severity:  # NaN-safe: NaN != NaN

            print(f"  {district:20s}: {len(group):6d} edges, severity {severity:.2f} "
                  f"({severity*100:.0f}% of villages affected in 2025)")
        else:
            print(f"  {district:20s}: {len(group):6d} edges, recognized but genuinely unscored "
                  f"(no hazard data source yet -- see module docstring)")
    unmatched_count = result["district"].isna().sum()
    if unmatched_count:
        print(f"\n{unmatched_count} edges fell outside all district boundaries "
              f"(may now be smaller than before -- Meghalaya coverage was just added).")
    print(f"\nSaved: {OUTPUT_PATH.name}")


if __name__ == "__main__":
    main()