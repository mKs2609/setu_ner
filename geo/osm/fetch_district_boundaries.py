"""
Phase 2: district boundaries for the Barak Valley corridor.

Fetches administrative boundary polygons for the four districts the
corridor crosses, so road-graph edges can be spatially joined to a
district -- the join key needed to bring in district-level hazard data
(e.g. the ASDMA Flood Memorandum, which reports impact by district) as a
first-pass hazard_exposure feature per edge.

This is a coarse proxy, not a precise per-road hazard signal -- worth
being upfront about that. District-level flood severity as a starting
feature is a reasonable baseline (matches the project's "establish a
baseline first" approach); refining to finer granularity is later work
once flood-extent polygons (Sentinel-1) are in the pipeline.

RUN THIS LOCALLY -- same Overpass dependency as the road graph script,
and uses the same mirror + retry approach that's already proven to work
from this machine.

    pip install -r requirements.txt
    python fetch_district_boundaries.py

OUTPUT
------
    districts.geojson -- one polygon per district, with name + geometry
"""

import sys
import time
from pathlib import Path

try:
    import osmnx as ox
    import geopandas as gpd
except ImportError:
    print("Missing dependencies. Run: pip install -r requirements.txt")
    sys.exit(1)

DISTRICTS = [
    "Cachar district, Assam, India",
    "Karimganj district, Assam, India",
    "Hailakandi district, Assam, India",
    "Dima Hasao district, Assam, India",
]

OUTPUT_DIR = Path(__file__).parent

# Same working pattern as build_road_graph.py -- Kumi first (worked
# reliably from this network), overpass-api.de as fallback.
OVERPASS_MIRRORS = [
    "https://overpass.kumi.systems/api",
    "https://overpass-api.de/api",
]
ATTEMPTS_PER_MIRROR = 2
RETRY_WAIT_SECONDS = 20


def fetch_one_with_retries(place_name: str):
    last_error = None
    for mirror in OVERPASS_MIRRORS:
        ox.settings.overpass_url = mirror
        ox.settings.requests_timeout = 180
        for attempt in range(1, ATTEMPTS_PER_MIRROR + 1):
            print(f"-> {place_name}: trying {mirror} (attempt {attempt}/{ATTEMPTS_PER_MIRROR})...")
            try:
                gdf = ox.geocode_to_gdf(place_name)
                print(f"   Success via {mirror}")
                return gdf
            except Exception as e:
                print(f"   Failed: {e}")
                last_error = e
                if attempt < ATTEMPTS_PER_MIRROR:
                    print(f"   Waiting {RETRY_WAIT_SECONDS}s before retrying...")
                    time.sleep(RETRY_WAIT_SECONDS)
    raise RuntimeError(f"All mirrors failed for {place_name!r}") from last_error


def main():
    all_gdfs = []
    for place in DISTRICTS:
        gdf = fetch_one_with_retries(place)
        gdf["district_query"] = place
        all_gdfs.append(gdf)

    import pandas as pd
    combined = gpd.GeoDataFrame(pd.concat(all_gdfs, ignore_index=True), crs=all_gdfs[0].crs)

    keep_cols = [c for c in ["display_name", "district_query", "geometry"] if c in combined.columns]
    combined_out = combined[keep_cols]

    out_path = OUTPUT_DIR / "districts.geojson"
    combined_out.to_file(out_path, driver="GeoJSON")

    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    for _, row in combined_out.iterrows():
        area_km2 = None
        try:
            area_km2 = combined.to_crs(epsg=32646).loc[row.name, "geometry"].area / 1_000_000
        except Exception:
            pass
        name = row.get("display_name", row.get("district_query"))
        area_str = f"{area_km2:.0f} km2" if area_km2 else "area unknown"
        print(f"  {name} -- {area_str}")
    print(f"\nSaved: {out_path.name}")
    print(
        "\nNext: open districts.geojson alongside edges.geojson at geojson.io "
        "and confirm the four district polygons actually cover the road "
        "network -- if a district looks off, it's usually a name-matching "
        "issue (OSM's admin boundary for that name might be split/renamed)."
    )


if __name__ == "__main__":
    main()