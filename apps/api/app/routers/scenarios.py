"""
Scenario / what-if endpoints (Phase 5).

Three endpoints, deliberately small:

  GET  /landmarks  -- the named places a scenario can route between
  GET  /route      -- baseline route only, no closures
  POST /simulate   -- baseline vs scenario, with the delta and its cause

/route exists separately from /simulate because the frontend wants to draw
the normal route before anyone builds a scenario on top of it, and asking
for a simulation with an empty closure set to get that would be a confusing
way to express it.

Historical replay (gap-analysis section 7, Tier 2) is not a separate mode:
replaying the 2025 Silchar-Kalain bridge collapse is just a /simulate call
with those bridge road_ids closed. Keeping one code path means the replay
and the live what-if cannot silently diverge.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app import limits
from app.db.session import get_db
from app.services.routing.graph import get_corridor_graph
from app.services.routing.landmarks import LANDMARKS, resolve_place
from app.services.scenario import conditions as live_conditions
from app.services.scenario import engine

router = APIRouter()


class ScenarioRequest(BaseModel):
    label: str = Field("untitled scenario", max_length=120, description="Name for this what-if")
    origin: str = Field("silchar", max_length=80, description="Landmark key, or 'lon,lat'")
    destination: str = Field("haflong", max_length=80, description="Landmark key, or 'lon,lat'")

    # Bounded: an unbounded list is a free way to make the server do
    # arbitrary work. 2000 is far more than any real scenario -- the whole
    # corridor has 110k edges and a plausible closure is a handful.
    close_road_ids: list[int] = Field(
        default_factory=list, max_length=2000, description="Road ids made impassable"
    )
    close_bridges_in_district: str | None = Field(
        None,
        description=(
            "Close every bridge in this district, e.g. 'Cachar'. Combines "
            "with close_road_ids."
        ),
    )
    degrade_road_ids: list[int] = Field(
        default_factory=list,
        max_length=2000,
        description="Road ids that stay passable but slower (flooded, not severed)",
    )
    degrade_bridges_in_district: str | None = Field(
        None,
        description=(
            "Slow every bridge in this district rather than closing it -- the "
            "'under water but still passable' case. Symmetric with "
            "close_bridges_in_district; a road named by both is closed, since "
            "that is the stronger claim."
        ),
    )
    degrade_factor: float = Field(
        2.0, gt=1.0, le=20.0, description="Travel-time multiplier for degraded roads"
    )
    bidirectional: bool = Field(
        True,
        description=(
            "Also close the reverse direction of each road. True is right "
            "for a collapsed bridge; set False only for a genuine one-way "
            "closure."
        ),
    )
    start_from: str = Field(
        "clean",
        description=(
            "'clean' routes on an undamaged network -- a pure hypothetical. "
            "'current_conditions' starts from what is actually reported right "
            "now (field reports and hazard damage points) and applies your "
            "closures on top of that."
        ),
    )
    include_geometry: bool = Field(
        False,
        description=(
            "Return both routes as coordinate lists for the map. Off by "
            "default -- a route is a few hundred segments of geometry."
        ),
    )


@router.get("/landmarks")
def list_landmarks():
    """Named places a scenario can route between."""
    return {
        "landmarks": [
            {
                "key": lm.key,
                "display_name": lm.display_name,
                "lon": lm.lon,
                "lat": lm.lat,
                "district": lm.district,
                "why": lm.why,
            }
            for lm in LANDMARKS.values()
        ],
        "note": (
            "Approximate hand-entered town-centre coordinates, snapped to the "
            "nearest road-graph junction at query time. Not gazetteer data -- "
            "replace before any published figure depends on them."
        ),
    }


@router.get("/route")
def baseline_route(
    origin: str = Query("silchar"),
    destination: str = Query("haflong"),
    include_geometry: bool = Query(False),
    db: Session = Depends(get_db),
):
    """Fastest route with no closures -- the baseline a scenario is measured against."""
    try:
        o_lon, o_lat, o_label = resolve_place(origin)
        d_lon, d_lat, d_label = resolve_place(destination)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    cgraph = get_corridor_graph(db)
    src, src_km = cgraph.snap(o_lon, o_lat)
    dst, dst_km = cgraph.snap(d_lon, d_lat)
    result = engine.route(cgraph, src, dst)

    payload = {
        "origin": {"place": o_label, "snapped_km_away": round(src_km, 3)},
        "destination": {"place": d_label, "snapped_km_away": round(dst_km, 3)},
        "route": result.as_dict(),
        "caveats": {"travel_time": engine.MODELLED_TIME_CAVEAT},
    }
    if include_geometry and result.reachable:
        payload["geometry"] = {
            "type": "LineString",
            "coordinates": engine.route_geometry(db, result.road_ids),
        }
    return payload


@router.post("/simulate", dependencies=[Depends(limits.rate_limited)])
def simulate_scenario(request: ScenarioRequest, db: Session = Depends(get_db)):
    """Run a what-if: close or slow a set of roads, and report what it costs."""
    with limits.heavy_slot():
        return _simulate(request, db)


def _simulate(request: ScenarioRequest, db: Session) -> dict:
    try:
        origin = resolve_place(request.origin)
        destination = resolve_place(request.destination)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    cgraph = get_corridor_graph(db)

    close_ids = set(request.close_road_ids)
    if request.close_bridges_in_district:
        district_bridges = engine.select_bridge_ids(
            db, request.close_bridges_in_district
        )
        if not district_bridges:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No bridges found in district "
                    f"{request.close_bridges_in_district!r}. Districts with "
                    f"data: Cachar, Hailakandi, Karimganj, Dima Hasao."
                ),
            )
        close_ids |= set(district_bridges)

    # Reported conditions are applied first, so a hand-specified closure lands
    # on top of the network as it actually stands rather than an imaginary
    # undamaged one.
    conditions = None
    if request.start_from == "current_conditions":
        conditions = live_conditions.derive(db)
        close_ids |= conditions.closed_road_ids

    # A factor map, not a set: conditions derived from live reports grade the
    # slowdown by how strong the evidence is, and collapsing that to one number
    # would discard the distinction.
    degrade_ids: dict[int, float] = {
        rid: request.degrade_factor for rid in request.degrade_road_ids
    }
    if conditions is not None:
        degrade_ids.update(conditions.degraded)

    if request.degrade_bridges_in_district:
        district_bridges = engine.select_bridge_ids(
            db, request.degrade_bridges_in_district
        )
        if not district_bridges:
            raise HTTPException(
                status_code=404,
                detail=(
                    f"No bridges found in district "
                    f"{request.degrade_bridges_in_district!r}. Districts with "
                    f"data: Cachar, Hailakandi, Karimganj, Dima Hasao."
                ),
            )
        for rid in district_bridges:
            degrade_ids.setdefault(rid, request.degrade_factor)

    if request.bidirectional:
        close_ids = engine.expand_bidirectional(cgraph, close_ids)
        degrade_ids = engine.expand_bidirectional_map(cgraph, degrade_ids)

    # A road cannot be both severed and merely slowed; closure is the
    # stronger claim, so it wins.
    degrade_ids = {k: v for k, v in degrade_ids.items() if k not in close_ids}

    result = engine.simulate(
        db,
        cgraph,
        label=request.label,
        origin=origin,
        destination=destination,
        close_road_ids=close_ids,
        degrade_road_ids=degrade_ids,
        degrade_factor=request.degrade_factor,
    )
    result["start_from"] = request.start_from
    if conditions is not None:
        result["starting_conditions"] = conditions.as_dict()
        result["caveats"]["baseline_is_still_clean"] = (
            "The baseline route is the undamaged network, so the delta shown "
            "includes the effect of current reported conditions as well as any "
            "closures you specified. starting_conditions lists what was already "
            "applied before your scenario."
        )

    if request.include_geometry:
        baseline = engine.route(cgraph, *_endpoints(cgraph, origin, destination))
        scenario = engine.route(
            cgraph,
            *_endpoints(cgraph, origin, destination),
            closed=close_ids,
            degraded=degrade_ids,
            degrade_factor=request.degrade_factor,
        )
        result["geometry"] = {
            "baseline": engine.route_geometry(db, baseline.road_ids),
            "scenario": (
                engine.route_geometry(db, scenario.road_ids)
                if scenario.reachable
                else None
            ),
        }

    return result


def _endpoints(cgraph, origin, destination) -> tuple[int, int]:
    src, _ = cgraph.snap(origin[0], origin[1])
    dst, _ = cgraph.snap(destination[0], destination[1])
    return src, dst


@router.get("/current-conditions")
def current_conditions(db: Session = Depends(get_db)):
    """What the live layers currently say about the network.

    Exposed on its own, not just inside a simulation, because "which roads are
    reported bad right now, and who says so" is a question worth asking
    directly -- and because it makes the basis of a current-conditions
    scenario inspectable rather than something the engine does invisibly.
    """
    return live_conditions.derive(db).as_dict()
