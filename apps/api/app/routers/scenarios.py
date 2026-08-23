"""Scenario / what-if engine, including historical replay mode (gap-analysis §7 Tier 2)."""
from fastapi import APIRouter
from pydantic import BaseModel

router = APIRouter()


class ScenarioRequest(BaseModel):
    label: str
    changes: dict


@router.post("/simulate")
def simulate_scenario(request: ScenarioRequest):
    # TODO: clone state, apply changes, recompute accessibility/demand/optimization
    return {"scenario": request.label, "result": None, "note": "stub -- scenario engine not yet built"}
