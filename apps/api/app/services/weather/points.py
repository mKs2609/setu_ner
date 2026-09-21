"""
Where to look up rainfall for each district the flood report names.

The report and OpenStreetMap do not spell districts the same way, and the
model keys districts by `dataset.district_key` (lowercase letters only, which
is what repairs the PDF's mid-word line breaks). Most names match once
squashed -- "Kokrajhar" and "kokrajhar" -- and the handful that do not are
listed in ALIASES below, each with the reason it differs. An unmatched
district is not an error: it simply gets no rainfall feature, and
`coverage()` reports it rather than letting it pass unnoticed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from app.services.model.dataset import district_key

POINTS_PATH = Path(
    os.environ.get("SETUNER_DISTRICT_POINTS")
    or Path(__file__).resolve().parents[5] / "geo" / "rainfall" / "assam_district_points.json"
)

# OSM name (squashed) -> the key the flood report produces. Every entry is a
# real naming difference, not a guess:
ALIASES = {
    # OSM spells it Marigaon; the report and the road graph say Morigaon.
    "marigaon": "morigaon",
    # The report abbreviates Kamrup Metropolitan to "Kamrup (M)".
    "kamrupmetropolitan": "kamrupm",
    # Word order: OSM leads with West, the report trails it.
    "westkarbianglong": "karbianglongwest",
    # OSM carries the full name of the district; the report drops Mankachar.
    "southsalmaramankachar": "southsalmara",
    # OSM includes the word "district" in this one relation's name.
    "hailakandidistrict": "Hailakandi",
}


@dataclass(frozen=True)
class DistrictPoint:
    """A district's rainfall box: centre, and how far to average around it."""

    key: str
    name: str
    lat: float
    lon: float
    half_lat: float
    half_lon: float


@lru_cache(maxsize=1)
def load_points(path: str | None = None) -> dict[str, DistrictPoint]:
    raw = json.loads(Path(path or POINTS_PATH).read_text(encoding="utf-8"))
    out: dict[str, DistrictPoint] = {}
    for d in raw["districts"]:
        squashed = district_key(d["name"])
        key = ALIASES.get(squashed, district_key(d["name"]))
        # A corridor district keeps its canonical name so it joins to the
        # road graph; district_key already does that for names it recognises.
        out[key] = DistrictPoint(
            key=key,
            name=d["name"],
            lat=d["lat"],
            lon=d["lon"],
            half_lat=d["half_lat"],
            half_lon=d["half_lon"],
        )
    return out


def coverage(district_keys: list[str]) -> tuple[list[str], list[str]]:
    """(matched, unmatched) for the districts a caller cares about."""
    points = load_points()
    matched = [k for k in district_keys if k in points]
    unmatched = [k for k in district_keys if k not in points]
    return matched, unmatched
