"""Vehicles, resources, demand, and OR-Tools-driven allocation/routing."""
from fastapi import APIRouter

router = APIRouter()


@router.get("/plan")
def get_current_plan():
    # TODO: OR-Tools optimization run -- risk-aware, see gap-analysis §7 Tier 1 item 3
    return {"plan": None, "note": "stub -- optimization engine not yet built"}
