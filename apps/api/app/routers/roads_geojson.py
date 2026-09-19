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

import json

from fastapi import APIRouter, Depends, Query, Response
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.db.session import get_db

router = APIRouter()

MAX_FEATURES_NO_FILTER = 5000
MAX_FEATURES_WITH_DISTRICT = 60000
HARD_CAP = 20000


# PostGIS builds the whole FeatureCollection as one JSON text. The earlier
# version loaded every road as an ORM object, converted each geometry with
# shapely and serialised 51,839 Python dicts: a 28.7 MB response that took
# 7 s on a laptop and ran a 512 MB host out of memory (the first deployment
# returned 502 for the Cachar map and restarted). Now the API process only
# ever holds the finished text, coordinates are rounded to 5 decimals (about
# a metre, invisible at map zoom), and large responses are gzipped by the
# middleware in main.py.
COORD_DECIMALS = 5

GEOJSON_SQL = text(
    """
    SELECT count(*) AS n,
           COALESCE(json_agg(json_build_object(
               'type', 'Feature',
               'id', r.id,
               'geometry', ST_AsGeoJSON(r.geometry, :decimals)::json,
               'properties', json_build_object(
                   'road_class', r.road_class,
                   'is_bridge', r.is_bridge,
                   'district', r.district,
                   'baseline_accessibility', r.baseline_accessibility,
                   'current_accessibility', r.current_accessibility,
                   'hazard_exposure', r.hazard_exposure,
                   'current_accessibility_as_of', r.current_accessibility_as_of
               )
           ) ORDER BY r.id), '[]'::json)::text AS features
    FROM (
        SELECT * FROM roads
        WHERE (CAST(:district AS text) IS NULL OR district = :district)
          AND (CAST(:min_acc AS double precision) IS NULL OR baseline_accessibility >= :min_acc)
          AND (CAST(:max_acc AS double precision) IS NULL OR baseline_accessibility <= :max_acc)
        ORDER BY id
        LIMIT :lim
    ) r
    """
)


@router.get("/geojson")
def roads_geojson(
    district: str | None = Query(None, description="Filter by district, e.g. 'Cachar'. Strongly recommended -- see module docstring on why."),
    min_accessibility: float | None = Query(None, ge=0, le=1),
    max_accessibility: float | None = Query(None, ge=0, le=1),
    fetch_all: bool = Query(False, description="Required to fetch without a district filter. Still capped."),
    db: Session = Depends(get_db),
):
    if fetch_all:
        limit = HARD_CAP
    elif district:
        limit = MAX_FEATURES_WITH_DISTRICT
    else:
        limit = MAX_FEATURES_NO_FILTER

    row = db.execute(
        GEOJSON_SQL,
        {
            "decimals": COORD_DECIMALS,
            "district": district,
            "min_acc": min_accessibility,
            "max_acc": max_accessibility,
            "lim": limit,
        },
    ).one()

    truncated = row.n == limit
    meta = {
        "count": row.n,
        "truncated": truncated,
        "note": (
            f"Capped at {limit} features. Pass district= to see a specific "
            f"district's full data, or fetch_all=true for the (still capped) "
            f"full corridor."
        ) if truncated else None,
    }
    # Assembled as text so the features are never parsed back into Python.
    body = '{"type":"FeatureCollection","features":' + row.features + ',"meta":' + json.dumps(meta) + "}"
    return Response(content=body, media_type="application/json")
