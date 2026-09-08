"""
Mapping district names as the hazard sources print them onto the names the
road graph uses.

WHY THIS IS NOT JUST `name.strip().title()`
Assam has renamed districts, and the live source has already moved while our
road graph has not. The 2026 daily reports say **Sribhumi**; the OSM-derived
road graph, the district polygons and every accessibility score say
**Karimganj**. Ingesting "Sribhumi" verbatim would silently produce hazard
data that joins to nothing -- the corridor would look unaffected during a
flood, which is the worst possible failure mode for this system.

Dima Hasao appears in older material as North Cachar Hills for the same
reason, so it is mapped too.

THE RULE THIS FILE FOLLOWS
Only map names we can actually justify. An unrecognised district is returned
as `None` rather than guessed at, and the caller keeps the source's original
spelling in `place_name` either way. An unmapped name should surface as an
ingestion warning so somebody looks at it -- quietly coercing it to the
nearest-looking district is how you end up attributing a flood to the wrong
place.
"""

from __future__ import annotations

# Canonical names, exactly as they appear in the roads/districts tables.
CORRIDOR_DISTRICTS = {"Cachar", "Karimganj", "Hailakandi", "Dima Hasao"}

# source spelling (lowercased) -> canonical name in our database
ALIASES: dict[str, str] = {
    # Renamed by the Government of Assam in 2024. The road graph predates the
    # rename, so the live feed and our geometry disagree unless we map it.
    "sribhumi": "Karimganj",
    "karimganj": "Karimganj",
    # Renamed from North Cachar Hills in 2010; older documents still use it.
    "dima hasao": "Dima Hasao",
    "north cachar hills": "Dima Hasao",
    "n c hills": "Dima Hasao",
    "cachar": "Cachar",
    "hailakandi": "Hailakandi",
}


def normalise_district(raw: str | None) -> str | None:
    """Canonical district name, or None when we cannot justify a mapping.

    None is a real answer here: most Assam districts are outside our corridor
    and have no road-graph coverage, so refusing to guess is correct rather
    than lossy.
    """
    if not raw:
        return None
    key = " ".join(raw.strip().lower().split())
    if not key:
        return None
    return ALIASES.get(key)


def is_corridor_district(name: str | None) -> bool:
    """True when the district is one the road graph actually covers."""
    return name in CORRIDOR_DISTRICTS
