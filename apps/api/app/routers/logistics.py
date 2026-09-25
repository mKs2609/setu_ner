"""
Demand estimation and supply planning (docs/decisions/0011).

    GET  /api/v1/logistics/supply-days       report days with people to supply
    GET  /api/v1/logistics/demand            demand per revenue circle
    GET  /api/v1/logistics/example-inputs    starting depots, clearly labelled
    POST /api/v1/logistics/plan              allocation + routes + what limits it

Requests are bounded (depots, horizon, penalty) because each depot costs two
shortest-path passes over the full corridor graph, and this endpoint is
reachable by anyone who can reach the API.
"""

from __future__ import annotations

from datetime import date


from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field, model_validator
from sqlalchemy.orm import Session

from app import security
from app.db.session import get_db
from app.services.explain import audit
from app.services.explain import plan as plan_explain
from app.services.logistics import demand as demand_mod
from app import limits
from app.services.logistics import optimize
from app.services.logistics import plan as plan_mod

router = APIRouter()

# Concurrency and per-address limits live in app/limits.py, shared with the
# scenario engine: both compete for the same memory on the same instance.


class StockIn(BaseModel):
    water: float = Field(0, ge=0, le=1e8, description="litres")
    food: float = Field(0, ge=0, le=1e8, description="ration-days")


class DepotIn(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    place: str | None = Field(None, max_length=80, description="Gazetteer place name")
    lon: float | None = Field(None, ge=91.5, le=94.0)
    lat: float | None = Field(None, ge=24.0, le=26.5)
    stock: StockIn
    trucks: float = Field(ge=0, le=500)

    @model_validator(mode="after")
    def _both_or_neither(self):
        if (self.lon is None) != (self.lat is None):
            raise ValueError("give both lon and lat, or neither")
        return self


class FleetIn(BaseModel):
    truck_capacity_kg: float = Field(8000, gt=0, le=40000)
    hours_per_day: float = Field(10, gt=0, le=24)
    loading_hours_per_trip: float = Field(1, ge=0, le=12)


class PlanRequest(BaseModel):
    as_of: date | None = None
    horizon_days: int = Field(1, ge=1, le=7)
    depots: list[DepotIn] = Field(min_length=1, max_length=10)
    fleet: FleetIn = FleetIn()
    risk_minutes_per_exposure_km: float = Field(0, ge=0, le=600)
    fairness_first: bool = False
    water_litres_per_person_day: float | None = Field(None, gt=0, le=100)
    food_kg_per_ration_day: float | None = Field(None, gt=0, le=5)
    example_inputs: bool = Field(
        False, description="Set when the depots are the example figures, so the response says so."
    )
    save: bool = Field(
        False, description="Store this plan as an immutable recommendation record (0012)."
    )
    label: str | None = Field(None, max_length=120)


@router.get("/supply-days")
def supply_days(db: Session = Depends(get_db)):
    return {"days": demand_mod.supply_days(db)}


@router.get("/demand")
def get_demand(
    as_of: date | None = Query(None),
    horizon_days: int = Query(1, ge=1, le=7),
    db: Session = Depends(get_db),
):
    try:
        est = demand_mod.estimate(db, as_of, horizon_days)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return demand_mod.as_dict(est)


@router.get("/example-inputs")
def example_inputs():
    return {
        "depots": plan_mod.EXAMPLE_DEPOTS,
        "fleet": FleetIn().model_dump(),
        "note": plan_mod.EXAMPLE_NOTE,
    }


@router.post("/plan", dependencies=[Depends(limits.rate_limited)])
def make_plan(
    body: PlanRequest,
    db: Session = Depends(get_db),
    authorization: str | None = Header(default=None),
):
    # Planning is public; making it part of the audit trail is not.
    if body.save and not security.is_authorised(authorization):
        raise HTTPException(
            status_code=401,
            detail="Saving a plan as a record needs an operator token. Planning without saving does not.",
            headers={"WWW-Authenticate": "Bearer"},
        )
    with limits.heavy_slot():
        return _make_plan(body, db)


def _make_plan(body: PlanRequest, db: Session) -> dict:
    try:
        result = plan_mod.build_plan(
            db,
            depots=[
                plan_mod.DepotSpec(
                    name=d.name, place=d.place, lon=d.lon, lat=d.lat,
                    stock=d.stock.model_dump(), trucks=d.trucks,
                )
                for d in body.depots
            ],
            as_of=body.as_of,
            horizon_days=body.horizon_days,
            fleet=optimize.FleetInput(**body.fleet.model_dump()),
            risk_minutes_per_exposure_km=body.risk_minutes_per_exposure_km,
            fairness_first=body.fairness_first,
            water_litres_per_person_day=body.water_litres_per_person_day,
            food_kg_per_ration_day=body.food_kg_per_ration_day,
            example_inputs=body.example_inputs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    result["explanation"] = plan_explain.narrate(result)
    result["recommendation_id"] = None
    if body.save:
        try:
            rec = audit.save(
                db,
                inputs=body.model_dump(mode="json", exclude={"save", "label"}),
                plan={k: v for k, v in result.items() if k not in ("explanation", "recommendation_id")},
                explanation=result["explanation"],
                label=body.label,
            )
        except audit.RateLimited as exc:
            raise HTTPException(status_code=429, detail=str(exc)) from exc
        result["recommendation_id"] = rec.id
    return result
