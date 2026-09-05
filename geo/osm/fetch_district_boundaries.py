"""
Phase 2: district boundaries for the Barak Valley corridor.

Fetches administrative boundary polygons for every district the corridor
crosses, so road-graph edges can be spatially joined to a district.

Includes East Jaintia Hills and West Jaintia Hills (Meghalaya) alongside
the original four Assam districts -- the Phase 1 bounding box reaches
into Meghalaya to capture the NH-6/Sonapur tunnel stretch, and those
roads had no district match at all until now.

IMPORTANT: getting the Meghalaya district boundary does NOT mean those
roads get a real accessibility score. There's no ASDMA-equivalent clean
statistical flood report for Meghalaya (checked -- MSDMA's public output
is news-cited district mentions and a general risk-planning document, not
an annual per-district damage table), and this area's real documented
disruption pattern is landslide, not flood, which our current formula
doesn't model anyway. See assign_district_hazard_context.py -- these
roads get correctly labeled by district, but stay unscored rather than
being assigned a fabricated or wrong-hazard-type number.

RUN THIS LOCALLY -- same Overpass dependency and mirror/retry pattern as
before.

    python fetch_district_boundaries.py

OUTPUT
------
    districts.geojson -- overwrites the previous 4-district version with
    a 6-district version.
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
    "East Jaintia Hills district, Meghalaya, India",
    "West Jaintia Hills district, Meghalaya, India",
]

OUTPUT_DIR = Path(__file__).parent

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
    print(f"\nSaved: {out_path.name} ({len(combined_out)} districts)")


if __name__ == "__main__":
    main()