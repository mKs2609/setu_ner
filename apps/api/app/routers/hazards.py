"""Hazard events and features. Hazard-agnostic by design (docs/decisions/0001 §3)."""
from fastapi import APIRouter

router = APIRouter()


@router.get("")
def list_hazards():
    # TODO: query hazard_events table (hazard-agnostic schema, see gap-analysis §3)
    return {"hazards": [], "note": "stub -- flood is the first hazard_type implemented"}
