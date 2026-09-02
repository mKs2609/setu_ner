"""
Public read-only accessibility API + GeoJSON endpoint for the map.

/api/v1/roads/geojson is deliberately separate from the general /roads
endpoint (roads.py). The general endpoint returns full detail per road as
JSON, meant for looking up one road. This one returns a proper GeoJSON
FeatureCollection with only what a map needs to render and color roads --
different shape, different purpose, and lighter payload.

SAFETY LIMIT: with 110k+ edges in the real corridor, returning everything
at once in one response is genuinely heavy for a browser to fetch and
render. Defaults to requiring a district filter; an explicit "all" flag
is needed to fetch everything, and even then it's capped. This is a
deliberate scaling limit, not an oversight -- proper large-scale map
rendering (vector tiles) is real future work, not something to fake now.
"""

from fastapi import APIRouter, Query, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session
from geoalchemy2.shape import to_shape

from app.db.session import get_db
from app.db.models import Road

router = APIRouter()

MAX_FEATURES_NO_FILTER = 5000
MAX_FEATURES_WITH_DISTRICT = 60000
HARD_CAP = 20000


@router.get("/geojson")
def roads_geojson(
    district: str | None = Query(None, description="Filter by district, e.g. 'Cachar'. Strongly recommended -- see module docstring on why."),
    min_accessibility: float | None = Query(None, ge=0, le=1),
    max_accessibility: float | None = Query(None, ge=0, le=1),
    fetch_all: bool = Query(False, description="Required to fetch without a district filter. Still capped."),
    db: Session = Depends(get_db),
):
    stmt = select(Road)
    if district:
        stmt = stmt.where(Road.district == district)
    if min_accessibility is not None:
        stmt = stmt.where(Road.baseline_accessibility >= min_accessibility)
    if max_accessibility is not None:
        stmt = stmt.where(Road.baseline_accessibility <= max_accessibility)

    if fetch_all:
        limit = HARD_CAP
    elif district:
        limit = MAX_FEATURES_WITH_DISTRICT
    else:
        limit = MAX_FEATURES_NO_FILTER
    stmt = stmt.limit(limit)

    roads = db.execute(stmt).scalars().all()

    features = []
    for road in roads:
        geom = to_shape(road.geometry)
        features.append({
            "type": "Feature",
            "id": road.id,
            "geometry": {
                "type": "LineString",
                "coordinates": list(geom.coords),
            },
            "properties": {
                "road_class": road.road_class,
                "is_bridge": road.is_bridge,
                "district": road.district,
                "baseline_accessibility": road.baseline_accessibility,
            },
        })

    truncated = len(roads) == limit
    return {
        "type": "FeatureCollection",
        "features": features,
        "meta": {
            "count": len(features),
            "truncated": truncated,
            "note": (
                f"Capped at {limit} features. Pass district= to see a specific "
                f"district's full data, or fetch_all=true for the (still capped) "
                f"full corridor."
            ) if truncated else None,
        },
    }