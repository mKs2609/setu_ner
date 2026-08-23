"""
Accessibility scoring + multi-horizon forecasts per edge.
See docs/decisions/0001 §2.1 (formal accessibility definition) and §2.2
(time-dependent routing) before wiring this up for real.
"""
from fastapi import APIRouter

router = APIRouter()


@router.get("/{road_id}")
def get_accessibility(road_id: str):
    # TODO: Model A output -- continuous reliability [0,1] + category + confidence band
    # TODO: multi-horizon forecast vector (t+1h, +3h, +6h, +12h, +24h), not a point estimate
    return {
        "road_id": road_id,
        "current_reliability": None,
        "forecast": [],
        "confidence": None,
        "note": "stub -- Model A not yet trained",
    }
