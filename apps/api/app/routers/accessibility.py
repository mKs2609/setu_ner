"""
Accessibility scoring per edge. Currently serves the real baseline score
(district 2025 severity x bridge factor) computed by
geo/osm/compute_baseline_accessibility.py -- current_accessibility and
predicted_accessibility stay None until Phase 3's live model exists.
Keeping baseline and live/forecast fields visibly distinct here in the API
response, not just in the DB schema, matters for the same reason it did
there: an operator reading this response should never mistake a 2025
historical proxy for a live prediction.
"""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.db.models import Road

router = APIRouter()


@router.get("/{road_id}")
def get_accessibility(road_id: int, db: Session = Depends(get_db)):
    road = db.get(Road, road_id)
    if road is None:
        raise HTTPException(status_code=404, detail=f"Road {road_id} not found")

    return {
        "road_id": road_id,
        "current_accessibility": road.current_accessibility,  # None -- Phase 3, not built yet
        "predicted_accessibility": road.predicted_accessibility,  # None -- Phase 3, not built yet
        "baseline_accessibility": road.baseline_accessibility,
        "baseline_basis": road.baseline_accessibility_basis,
        "baseline_confidence": road.baseline_accessibility_confidence,
        "note": (
            "baseline_accessibility is a real, computed value (2025 district "
            "flood severity x bridge factor). current_accessibility and "
            "predicted_accessibility are genuinely None -- Phase 3 (the live "
            "model) hasn't been built yet, not a bug."
        ),
    }