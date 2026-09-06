"""
Named places in the study corridor, so a scenario can be expressed as
"Silchar to Haflong" instead of a pair of raw coordinates.

PROVENANCE -- these are APPROXIMATE town-centre coordinates, hand-entered,
NOT surveyed and not pulled from an authoritative gazetteer. They are
accurate enough for their only job: picking which junction of the road
graph a route starts from. Each one gets snapped to the nearest graph node
and the API reports that snap distance, so a bad coordinate shows up as a
large snap rather than hiding inside a plausible-looking answer.

Before any of this goes in a pitch or a published figure, replace this
dict with real gazetteer coordinates (Survey of India / LGD codes). Logged
as an open item rather than quietly trusted -- same reason
compute_baseline_accessibility.py flags its 0.7 bridge factor.

WHY THESE SIX
They are the corridor's actual decision points. Silchar is the hub the
whole Barak Valley depends on; Haflong is the Dima Hasao waypoint on the
NH-6 route out; Badarpur is the rail/road junction to Tripura and Mizoram;
Karimganj and Hailakandi are the other two district headquarters with real
2025 flood data; Kalain is where the 2025 Silchar-Kalain bridge collapse
happened, which is the historical event the demo scenario replays.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Landmark:
    key: str
    display_name: str
    lon: float
    lat: float
    district: str
    why: str


LANDMARKS: dict[str, Landmark] = {
    lm.key: lm
    for lm in [
        Landmark("silchar", "Silchar", 92.7789, 24.8333, "Cachar",
                 "Barak Valley's hub; origin of most relief movement"),
        Landmark("haflong", "Haflong", 93.0167, 25.1672, "Dima Hasao",
                 "Dima Hasao HQ; waypoint on the NH-6 route out of the valley"),
        Landmark("badarpur", "Badarpur", 92.5996, 24.8687, "Karimganj",
                 "Rail/road junction toward Tripura and Mizoram"),
        Landmark("karimganj", "Karimganj", 92.3592, 24.8697, "Karimganj",
                 "District HQ, real 2025 flood severity data"),
        Landmark("hailakandi", "Hailakandi", 92.5667, 24.6833, "Hailakandi",
                 "District HQ; worst mean baseline accessibility in the corridor"),
        Landmark("kalain", "Kalain", 92.6167, 24.9333, "Cachar",
                 "Site of the 2025 Silchar-Kalain bridge collapse"),
    ]
}


def resolve_place(value: str) -> tuple[float, float, str]:
    """
    Accept either a landmark key ("silchar") or a raw "lon,lat" pair.

    Returns (lon, lat, label). Raises ValueError with a usable message --
    the router turns that into a 400 rather than a 500, because a typo'd
    place name is a client mistake, not a server fault.
    """
    key = value.strip().lower()
    if key in LANDMARKS:
        lm = LANDMARKS[key]
        return lm.lon, lm.lat, lm.display_name

    if "," in value:
        lon_s, _, lat_s = value.partition(",")
        try:
            lon, lat = float(lon_s), float(lat_s)
        except ValueError:
            raise ValueError(
                f"Could not read {value!r} as 'lon,lat'. "
                f"Known places: {', '.join(sorted(LANDMARKS))}"
            ) from None
        return lon, lat, f"{lon:.4f},{lat:.4f}"

    raise ValueError(
        f"Unknown place {value!r}. Use 'lon,lat' or one of: "
        f"{', '.join(sorted(LANDMARKS))}"
    )
