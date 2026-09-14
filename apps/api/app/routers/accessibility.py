"""
Accessibility scoring per edge.

Serves three things that must never be confused with one another:

  baseline_accessibility   2025 district flood severity x bridge factor, from
                           geo/osm/compute_baseline_accessibility.py. A
                           historical proxy.
  current_accessibility    Phase 3: 1 - P(district affected tomorrow) x terrain
                           exposure, from app/services/model/score.py. Returned
                           with its model version, as-of date, staleness and
                           both of its components, never as a bare number.
  predicted_accessibility  The same, by horizon.

An operator reading this response should never mistake a 2025 historical
proxy for a live prediction, or a live prediction for a measurement.
"""

import json
from datetime import date

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.models import DistrictFloodForecast, Road
from app.db.session import get_db
from app.services.model.score import MAX_STALE_DAYS
from app.routers.model import CAVEATS
from app.services.explain import road as road_explain

router = APIRouter()


@router.get("/{road_id}")
def get_accessibility(road_id: int, db: Session = Depends(get_db)):
    road = db.get(Road, road_id)
    if road is None:
        raise HTTPException(status_code=404, detail=f"Road {road_id} not found")

    model = None
    if road.current_accessibility is not None:
        as_of = road.current_accessibility_as_of
        age = (date.today() - as_of).days if as_of else None
        district_p = None
        if as_of and road.district:
            f = (
                db.query(DistrictFloodForecast)
                .filter(
                    DistrictFloodForecast.district_key == road.district,
                    DistrictFloodForecast.as_of_date == as_of,
                    DistrictFloodForecast.horizon_days == 1,
                )
                .order_by(DistrictFloodForecast.created_at.desc())
                .first()
            )
            district_p = f.probability if f else None
        model = {
            "current_accessibility": road.current_accessibility,
            "by_horizon": (
                json.loads(road.predicted_accessibility) if road.predicted_accessibility else None
            ),
            "components": {
                "district_p_affected_tomorrow": district_p,
                "terrain_exposure_prior": road.hazard_exposure,
            },
            "as_of": as_of.isoformat() if as_of else None,
            "age_days": age,
            "stale": age is None or age > MAX_STALE_DAYS,
            "model_version": road.accessibility_model_version,
            "confidence": road.confidence,
        }

    return {
        "road_id": road_id,
        "district": road.district,
        "model": model,
        "baseline_accessibility": road.baseline_accessibility,
        "baseline_basis": road.baseline_accessibility_basis,
        "baseline_confidence": road.baseline_accessibility_confidence,
        "note": (
            "baseline_accessibility is a 2025 historical proxy. `model` is the Phase 3 "
            "forecast, or null when this road has not been scored (no elevation, or a "
            "district outside Assam's daily reporting). See /api/v1/model/status for how "
            "good the forecast is."
        ),
        "caveats": {
            "what_is_predicted": CAVEATS["what_is_predicted"],
            "per_road_is_a_prior": CAVEATS["per_road_is_a_prior"],
        },
    }


@router.get("/{road_id}/explanation")
def explain_accessibility(road_id: int, db: Session = Depends(get_db)):
    road = db.get(Road, road_id)
    if road is None:
        raise HTTPException(status_code=404, detail=f"Road {road_id} not found")
    return road_explain.explain(db, road)
