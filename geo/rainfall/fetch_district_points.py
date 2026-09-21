"""
District reference points for rainfall lookup, fetched once from OSM.

WHY A POINT AND NOT A POLYGON
Rainfall comes from IMERG's 0.1-degree grid (about 11 km). An Assam district
is typically 40-100 km across, so a district covers a handful of grid cells.
We average the cells inside a box around the district's centre rather than
clipping to the true boundary: the boundary polygons for all 35 districts are
tens of megabytes, they would have to be kept in step with district splits,
and at this grid size the difference between "cells in the polygon" and
"cells in a box the size of the district" is small next to IMERG's own error.
The box half-width comes from the district's own bounding box, so a large
district averages more cells than a small one.

Nominatim is not usable here -- its robots.txt disallows /search (see
docs/decisions/0010). Overpass publishes no robots.txt and is the same
service geo/osm already uses for boundaries.

    python fetch_district_points.py

OUTPUT
    assam_district_points.json -- one entry per district, committed to the
    repo so the API never needs Overpass at runtime.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

# requests, not urllib, only because urllib on this machine verifies against a
# Windows certificate store that rejects Overpass's chain while every browser
# and requests (which ships certifi) accepts it. Nothing is skipped: the
# certificate is still verified, just against an up-to-date bundle.
import requests

OVERPASS = "https://overpass-api.de/api/interpreter"
OUT = Path(__file__).with_name("assam_district_points.json")

USER_AGENT = (
    "SetuNER-district-points/0.1 "
    "(SIH26002 student project, non-commercial; one-off build script)"
)

# admin_level 5 is the district level in India in OSM; 4 is the state.
# `bb` returns each relation's bounding box without its geometry: 35 boxes
# instead of tens of megabytes of boundary. Overpass allows one geometry
# mode per `out`, so the centre is the box's midpoint -- which is what the
# averaging box wants anyway.
QUERY = """[out:json][timeout:180];
area["name"="Assam"]["admin_level"="4"]->.assam;
relation(area.assam)["boundary"="administrative"]["admin_level"="5"];
out tags bb;"""


def fetch(attempts: int = 4) -> dict:
    """One query, retried on the public endpoint's load-shedding.

    Overpass runs a handful of free slots and answers 429 or 504 when they
    are taken. Both mean "come back later", so this waits longer each time
    rather than reissuing the same heavy query immediately.
    """
    wait = 30
    for attempt in range(1, attempts + 1):
        resp = requests.post(
            OVERPASS,
            data=QUERY.encode("utf-8"),
            headers={"User-Agent": USER_AGENT, "Content-Type": "text/plain"},
            timeout=300,
        )
        if resp.status_code in (429, 503, 504) and attempt < attempts:
            print(f"  Overpass is busy (HTTP {resp.status_code}); waiting {wait}s")
            time.sleep(wait)
            wait *= 2
            continue
        resp.raise_for_status()
        return resp.json()
    raise RuntimeError("unreachable")


def main() -> int:
    print("asking Overpass for Assam district boundaries...")
    payload = fetch()

    districts = []
    for el in payload.get("elements", []):
        tags = el.get("tags", {})
        name = tags.get("name:en") or tags.get("name")
        bounds = el.get("bounds")
        if not name or not bounds:
            continue
        centre = {
            "lat": (bounds["minlat"] + bounds["maxlat"]) / 2,
            "lon": (bounds["minlon"] + bounds["maxlon"]) / 2,
        }
        # Half-width of the district's own bounding box, in degrees, floored
        # at one grid cell so a small district still gets a cell of its own.
        half_lat = max((bounds["maxlat"] - bounds["minlat"]) / 2, 0.1)
        half_lon = max((bounds["maxlon"] - bounds["minlon"]) / 2, 0.1)
        districts.append(
            {
                "name": name,
                "osm_relation": el.get("id"),
                "lat": round(centre["lat"], 4),
                "lon": round(centre["lon"], 4),
                "half_lat": round(half_lat, 3),
                "half_lon": round(half_lon, 3),
            }
        )

    districts.sort(key=lambda d: d["name"])
    if not districts:
        print("Overpass returned no districts -- not overwriting the existing file.")
        return 1

    OUT.write_text(
        json.dumps(
            {
                "source": "OpenStreetMap via Overpass",
                "licence": "ODbL 1.0",
                "admin_level": 5,
                "districts": districts,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"wrote {len(districts)} districts to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
