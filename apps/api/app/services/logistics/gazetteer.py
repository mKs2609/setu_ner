"""
Where revenue circles and depots actually are.

    cd apps/api
    python -m app.services.logistics.gazetteer --fetch    # refresh the file

WHY A COMMITTED FILE
Demand arrives per revenue circle, by name. A plan needs a point on the road
graph for each. The places come from OpenStreetMap (city, town and village
nodes in the corridor), fetched once and committed to
`geo/gazetteer/corridor_places.json`, so planning never depends on a live
third-party service and the coordinates are reviewable in a diff.

Fetched through the polite client from the overpass.kumi.systems mirror.
The main overpass-api.de instance disallows /api/ in robots.txt; the mirror
publishes no robots.txt, which the client treats as allow-all (the same
mirror the road-graph build used). One request, not a crawl.

    Data (c) OpenStreetMap contributors, ODbL 1.0.

HOW A CIRCLE NAME BECOMES A POINT
  1. An explicit alias, when DRIMS and OSM spell the same place differently.
     Every alias is listed below with its reason; there is no fuzzy matching.
  2. Otherwise an exact name match, ignoring case and diacritics
     ("Jirighāt" matches "Jirighat").
  3. Otherwise NOT LOCATED. The circle's demand is still reported, but it is
     not routed to -- a plan that silently delivered to a guessed point would
     be worse than one that says it cannot place a destination.

A town node is where OSM puts the town's centre, which is a reasonable
stand-in for the circle headquarters and not the location of any relief
camp. Snap distance to the road graph is reported for every point.
"""

from __future__ import annotations

import argparse
import json
import math
import os
import sys
import unicodedata
import urllib.parse
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

# geo/gazetteer at the repo root; overridable for a container that copies only
# apps/api (same arrangement as the model artifacts).
GAZETTEER_PATH = Path(
    os.environ.get("SETUNER_GAZETTEER")
    or Path(__file__).resolve().parents[5] / "geo" / "gazetteer" / "corridor_places.json"
)
OVERPASS_URL = "https://overpass.kumi.systems/api/interpreter"
CORRIDOR_BBOX = (24.3, 92.0, 25.8, 93.5)  # south, west, north, east
QUERY = (
    '[out:json][timeout:90];'
    'node["place"~"^(city|town|village)$"]["name"]'
    f"({CORRIDOR_BBOX[0]},{CORRIDOR_BBOX[1]},{CORRIDOR_BBOX[2]},{CORRIDOR_BBOX[3]});out;"
)

# DRIMS spelling -> OSM name. Each needs a reason, not a similarity score.
ALIASES: dict[str, tuple[str, str]] = {
    "sribhumi sadar": (
        "Karimganj",
        "Sadar circle of Sribhumi district, which was Karimganj until 2024; "
        "OSM still names the headquarters town Karimganj.",
    ),
    "rk nagar": ("Ramkrishna Nagar", "RK is the report's abbreviation of Ramkrishna."),
    "katigorah": ("Katigora", "Transliteration variant; the only Katigora in the corridor."),
    "patherkandi": ("Pathar Kandi", "Transliteration variant; the only Patharkandi in the corridor."),
    "maibang": ("Maibong", "Transliteration variant; OSM spells the Dima Hasao town Maibong."),
}

# Several equally ranked nodes this close together are one place mapped
# twice (e.g. "Algapur" and "Algāpur", 1.2 km apart) and are averaged.
# Further apart they are different places, and resolution refuses.
SAME_PLACE_KM = 3.0

# Rank used when one name matches several places: a town beats a village of
# the same name, because circle headquarters are towns where one exists.
PLACE_RANK = {"city": 0, "town": 1, "village": 2}


@dataclass(frozen=True)
class Place:
    name: str
    place: str
    lon: float
    lat: float
    osm_id: int


@dataclass(frozen=True)
class Resolution:
    query: str
    place: Place | None
    how: str            # alias | exact | not_located
    note: str | None = None


def _fold(name: str) -> str:
    stripped = "".join(
        c for c in unicodedata.normalize("NFKD", name) if not unicodedata.combining(c)
    )
    return " ".join(stripped.lower().split())


_cache: list[Place] | None = None


def load(path: Path = GAZETTEER_PATH) -> list[Place]:
    global _cache
    if _cache is not None and path == GAZETTEER_PATH:
        return _cache
    payload = json.loads(path.read_text(encoding="utf-8"))
    places = [Place(p["name"], p["place"], p["lon"], p["lat"], p["osm_id"]) for p in payload["places"]]
    if path == GAZETTEER_PATH:
        _cache = places
    return places


def resolve(name: str, places: list[Place] | None = None) -> Resolution:
    places = places if places is not None else load()
    key = _fold(name)

    how, note, target = "exact", None, key
    if key in ALIASES:
        osm_name, note = ALIASES[key]
        how, target = "alias", _fold(osm_name)

    matches = sorted(
        (p for p in places if _fold(p.name) == target),
        key=lambda p: PLACE_RANK.get(p.place, 9),
    )
    if not matches:
        return Resolution(name, None, "not_located", "no OSM place of that name in the corridor")
    best = matches[0]
    same_rank = [m for m in matches if PLACE_RANK.get(m.place) == PLACE_RANK.get(best.place)]
    if len(same_rank) > 1:
        spread = max(_km(a, b) for a in same_rank for b in same_rank)
        if spread > SAME_PLACE_KM:
            # Genuinely different places: refusing is honest, picking is not.
            return Resolution(
                name, None, "not_located",
                f"{len(same_rank)} OSM {best.place}s share this name, "
                f"{spread:.1f} km apart; refusing to pick one",
            )
        best = Place(
            best.name, best.place,
            round(sum(p.lon for p in same_rank) / len(same_rank), 6),
            round(sum(p.lat for p in same_rank) / len(same_rank), 6),
            best.osm_id,
        )
        note = (note + " " if note else "") + (
            f"{len(same_rank)} OSM nodes within {spread:.1f} km treated as one place and averaged."
        )
    return Resolution(name, best, how, note)


def _km(a: Place, b: Place) -> float:
    dx = (a.lon - b.lon) * 111.32 * math.cos(math.radians((a.lat + b.lat) / 2))
    dy = (a.lat - b.lat) * 110.57
    return math.hypot(dx, dy)


def fetch(path: Path = GAZETTEER_PATH) -> int:
    from app.services.ingestion.http_client import PoliteClient

    client = PoliteClient(max_bytes=20_000_000, timeout=120)
    response = client.fetch(
        OVERPASS_URL,
        data=urllib.parse.urlencode({"data": QUERY}).encode(),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    raw = json.loads(response.text)
    places = sorted(
        (
            {
                "name": e["tags"]["name"],
                "place": e["tags"]["place"],
                "lon": round(e["lon"], 6),
                "lat": round(e["lat"], 6),
                "osm_id": e["id"],
            }
            for e in raw["elements"]
        ),
        key=lambda p: (p["name"], p["osm_id"]),
    )
    write(path, places, raw.get("osm3s", {}).get("timestamp_osm_base"))
    return len(places)


def write(path: Path, places: list[dict], osm_timestamp: str | None) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "attribution": "Data (c) OpenStreetMap contributors, ODbL 1.0 -- https://www.openstreetmap.org/copyright",
        "source": OVERPASS_URL,
        "query": QUERY,
        "osm_data_timestamp": osm_timestamp,
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "places": places,
    }
    path.write_text(json.dumps(payload, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Corridor gazetteer.")
    parser.add_argument("--fetch", action="store_true", help="Refresh from OpenStreetMap.")
    parser.add_argument("--resolve", nargs="*", help="Resolve names and print the result.")
    args = parser.parse_args(argv)
    if args.fetch:
        print(f"{fetch()} places written to {GAZETTEER_PATH}")
    for name in args.resolve or []:
        r = resolve(name)
        where = f"{r.place.name} ({r.place.place}) {r.place.lat},{r.place.lon}" if r.place else "-"
        print(f"{name!r}: {r.how} -> {where} {r.note or ''}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
