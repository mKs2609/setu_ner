"""Road graph: nodes, edges, current state. Backed by the road graph in PostGIS."""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session
from geoalchemy2.shape import to_shape

from app.db.session import get_db
from app.db.models import Road

router = APIRouter()


def road_to_dict(road: Road) -> dict:
    geom = to_shape(road.geometry)
    return {
        "id": road.id,
        "name": road.name,
        "road_class": road.road_class,
        "is_bridge": road.is_bridge,
        "length_km": road.length_km,
        "baseline_travel_time_min": road.baseline_travel_time_min,
        "district": road.district,
        "baseline_accessibility": road.baseline_accessibility,
        "hist_flood_severity_2025": road.hist_flood_severity_2025,
        # Forecast score -- see /api/v1/accessibility/{id} for its components
        "current_accessibility": road.current_accessibility,
        "current_accessibility_as_of": (
            road.current_accessibility_as_of.isoformat()
            if road.current_accessibility_as_of else None
        ),
        "elevation_m": road.elevation_m,
        "geometry": {
            "type": "LineString",
            "coordinates": list(geom.coords),
        },
    }


@router.get("")
def list_roads(
    district: str | None = Query(None, description="Filter by district name, e.g. 'Cachar'"),
    min_accessibility: float | None = Query(None, ge=0, le=1),
    max_accessibility: float | None = Query(None, ge=0, le=1),
    limit: int = Query(100, le=1000, description="Capped to keep responses reasonable -- this corridor has 100k+ edges"),
    db: Session = Depends(get_db),
):
    """List road segments, with optional district and accessibility filters.

    Returns whole geometries, so the limit is capped: this corridor has over
    100,000 edges and an unbounded response would not fit in the host's memory.
    For the map layer use `/roads/geojson`, which is built in PostGIS and
    gzipped instead of serialised row by row.
    """
    stmt = select(Road)
    if district:
        stmt = stmt.where(Road.district == district)
    if min_accessibility is not None:
        stmt = stmt.where(Road.baseline_accessibility >= min_accessibility)
    if max_accessibility is not None:
        stmt = stmt.where(Road.baseline_accessibility <= max_accessibility)
    stmt = stmt.limit(limit)

    roads = db.execute(stmt).scalars().all()
    return {"count": len(roads), "roads": [road_to_dict(r) for r in roads]}


@router.get("/{road_id}")
def get_road(road_id: int, db: Session = Depends(get_db)):
    """One road segment: geometry, class, terrain, and its current score.

    `current_accessibility` is the forecast score and `current_accessibility_as_of`
    is the report date it was computed from — always read them together, because
    a score with no date cannot be judged. 404 if the id is unknown.
    """
    road = db.get(Road, road_id)
    if road is None:
        raise HTTPException(status_code=404, detail=f"Road {road_id} not found")
    return road_to_dict(road)