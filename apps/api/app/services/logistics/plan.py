"""
One supply plan: demand, routes and allocation, with the working shown.

    demand.py    who needs what, per revenue circle, from the DRIMS report
    routes.py    how each depot reaches each circle, fastest and lower-exposure
    optimize.py  what to send where with the stock and trucks available

Inputs the system cannot know -- how much stock sits in which depot, how many
trucks there are -- come from the operator. `EXAMPLE_DEPOTS` exists so the
screen is not blank, and every response echoes whether example inputs were
used, because a plan built on made-up stock is a demonstration, not a plan.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import date

from app.services.logistics import demand as demand_mod
from app.services.logistics import gazetteer, optimize, routes
from app.services.routing.graph import get_corridor_graph

# A snapped destination further than this from the road graph means the
# gazetteer point is somewhere the graph does not reach; routing to the
# nearest junction would deliver to the wrong place.
MAX_SNAP_KM = 5.0

EXAMPLE_DEPOTS = [
    {"name": "Silchar", "place": "Silchar", "stock": {"water": 60000, "food": 8000}, "trucks": 4},
    {"name": "Karimganj", "place": "Karimganj", "stock": {"water": 20000, "food": 3000}, "trucks": 2},
    {"name": "Hailakandi", "place": "Hailakandi", "stock": {"water": 15000, "food": 2000}, "trucks": 2},
    {"name": "Haflong", "place": "Haflong", "stock": {"water": 10000, "food": 1500}, "trucks": 1},
]
EXAMPLE_NOTE = (
    "Example stock and fleet figures, not real depot holdings. Replace them with what "
    "is actually in each depot before treating the plan as anything but a demonstration."
)


@dataclass
class DepotSpec:
    name: str
    stock: dict[str, float]
    trucks: float
    place: str | None = None
    lon: float | None = None
    lat: float | None = None


def _locate_depot(spec: DepotSpec) -> tuple[float, float, str] | str:
    if spec.lon is not None and spec.lat is not None:
        return spec.lon, spec.lat, "given coordinates"
    r = gazetteer.resolve(spec.place or spec.name)
    if r.place is None:
        return f"could not locate depot {spec.name!r}: {r.note}"
    return r.place.lon, r.place.lat, f"OpenStreetMap {r.place.place} {r.place.name}"


def build_plan(
    db,
    *,
    depots: list[DepotSpec],
    as_of: date | None = None,
    horizon_days: int = 1,
    fleet: optimize.FleetInput | None = None,
    risk_minutes_per_exposure_km: float = 0.0,
    fairness_first: bool = False,
    water_litres_per_person_day: float | None = None,
    food_kg_per_ration_day: float | None = None,
    example_inputs: bool = False,
) -> dict:
    fleet = fleet or optimize.FleetInput()
    fleet = replace(fleet, horizon_days=horizon_days)

    norms = dict(demand_mod.NORMS)
    if water_litres_per_person_day is not None:
        norms["water"] = replace(norms["water"], per_person_per_day=water_litres_per_person_day,
                                 basis="operator override")
    if food_kg_per_ration_day is not None:
        norms["food"] = replace(norms["food"], kg_per_unit=food_kg_per_ration_day,
                                basis="operator override")

    est = demand_mod.estimate(db, as_of, horizon_days, norms)
    latest = demand_mod.published_days(db)[-1]
    cgraph = get_corridor_graph(db)
    ctx = routes.risk_context(db, cgraph, est.as_of, latest)

    problems: list[str] = []

    depot_nodes: dict[str, tuple[int, float, DepotSpec, str]] = {}
    for i, spec in enumerate(depots):
        located = _locate_depot(spec)
        if isinstance(located, str):
            problems.append(located)
            continue
        lon, lat, how = located
        node, snap_km = cgraph.snap(lon, lat)
        if snap_km > MAX_SNAP_KM:
            problems.append(f"depot {spec.name!r} is {snap_km:.1f} km from the road graph; skipped")
            continue
        key = spec.name if spec.name not in depot_nodes else f"{spec.name}-{i + 1}"
        depot_nodes[key] = (node, snap_km, spec, how)

    circle_nodes: dict[str, tuple[int, float, demand_mod.CircleDemand]] = {}
    unrouted_people = 0.0
    for c in est.located:
        node, snap_km = cgraph.snap(c.lon, c.lat)
        if snap_km > MAX_SNAP_KM:
            problems.append(
                f"{c.circle} ({c.district}): {int(c.people):,} people not planned for -- the "
                f"place is {snap_km:.1f} km from the road graph, outside the corridor it covers"
            )
            unrouted_people += c.people
            continue
        circle_nodes[c.circle] = (node, snap_km, c)

    targets = [n for n, _, _ in circle_nodes.values()]
    pair_routes: dict[tuple[str, str], dict] = {}
    one_way: dict[tuple[str, str], float] = {}
    for dkey, (dnode, _, _, _) in depot_nodes.items():
        fastest = routes.routes_from(cgraph, dnode, targets, ctx, 0.0)
        safer = (
            routes.routes_from(cgraph, dnode, targets, ctx, risk_minutes_per_exposure_km)
            if risk_minutes_per_exposure_km > 0
            else fastest
        )
        for cname, (cnode, _, _) in circle_nodes.items():
            f, s = fastest[cnode], safer[cnode]
            chosen = s if risk_minutes_per_exposure_km > 0 else f
            pair_routes[(dkey, cname)] = {"fastest": f, "lower_exposure": s, "chosen": chosen}
            if chosen.reachable:
                one_way[(dkey, cname)] = chosen.travel_min

    needs = {
        cname: c.quantities(norms, horizon_days) for cname, (_, _, c) in circle_nodes.items()
    }
    result = optimize.solve(
        [
            optimize.DepotInput(k, spec.name, spec.stock, spec.trucks)
            for k, (_, _, spec, _) in depot_nodes.items()
        ],
        needs,
        one_way,
        norms,
        fleet,
        fairness_first=fairness_first,
    )

    shipped_pairs = {(s["depot"], s["circle"]) for s in result.shipments}
    route_rows = []
    for (dkey, cname), r in pair_routes.items():
        f, s, chosen = r["fastest"], r["lower_exposure"], r["chosen"]
        diverges = f.reachable and s.reachable and f.road_ids != s.road_ids
        row = {
            "depot": dkey,
            "circle": cname,
            "used_in_plan": (dkey, cname) in shipped_pairs,
            "fastest": f.as_dict(),
            "lower_exposure": s.as_dict() if risk_minutes_per_exposure_km > 0 else None,
            "routes_diverge": diverges,
            "chosen": "lower_exposure" if risk_minutes_per_exposure_km > 0 else "fastest",
            # Depot and circle headquarters snap to the same junction: supply
            # stays in town, so there is no road route to draw or weigh.
            "local_delivery": chosen.reachable and not chosen.road_ids,
        }
        if row["used_in_plan"] and chosen.reachable:
            row["geometry"] = routes.geometry(db, chosen.road_ids)
            if diverges:
                other = f if chosen is s else s
                row["alternative_geometry"] = routes.geometry(db, other.road_ids)
        route_rows.append(row)

    return {
        "as_of": est.as_of.isoformat(),
        "latest_report": latest.isoformat(),
        "is_replay": est.as_of != latest,
        "example_inputs": example_inputs,
        "example_note": EXAMPLE_NOTE if example_inputs else None,
        "demand": demand_mod.as_dict(est),
        "depots": [
            {
                "key": k, "name": spec.name, "located_by": how,
                "snap_km": round(snap, 2), "stock": spec.stock, "trucks": spec.trucks,
                "lon": float(cgraph.node_coords[cgraph.node_ids == node][0][0]),
                "lat": float(cgraph.node_coords[cgraph.node_ids == node][0][1]),
            }
            for k, (node, snap, spec, how) in depot_nodes.items()
        ],
        "plan": {
            "status": result.status,
            "policy": "fairness_first" if fairness_first else "coverage_first",
            "shipments": result.shipments,
            "runs": result.runs,
            "shortfalls": result.shortfalls,
            "worst_shortfall_fraction": result.worst_shortfall_fraction,
            "person_days_needed_all_commodities": result.needed_person_days,
            "person_days_covered_all_commodities": result.covered_person_days,
            "truck_hours": result.truck_hours,
            # Coverage above counts only circles the road graph reaches; people
            # at unlocated or off-graph circles are excluded and totalled here.
            "people_outside_plan": int(unrouted_people + sum(c.people for c in est.unlocated)),
            "omitted_residue_kg": round(result.omitted_residue_kg, 2),
            "limits": result.limits,
            "depot_use": result.depot_use,
        },
        "routes": route_rows,
        "risk": {
            "accessibility_source": ctx.source,
            "district_p_affected_next_day": ctx.district_probability,
            "risk_minutes_per_exposure_km": risk_minutes_per_exposure_km,
            "live_conditions_applied": ctx.live_conditions_applied,
            "closed_roads": len(ctx.closed),
            "degraded_roads": len(ctx.degraded),
        },
        "fleet": {
            "truck_capacity_kg": fleet.truck_capacity_kg,
            "hours_per_day": fleet.hours_per_day,
            "loading_hours_per_trip": fleet.loading_hours_per_trip,
            "horizon_days": fleet.horizon_days,
        },
        "problems": problems,
        "caveats": {
            "exposure_is_a_preference": (
                "Lower-exposure routes trade minutes for kilometres on roads the model "
                "rates at risk, at the rate the operator sets. It is not a probability "
                "that a route will be passable."
            ),
            "replay": (
                "Planning from a past report uses that day's demand and what the model "
                "would have forecast then. Live field reports and damage closures are "
                "applied only when planning from the latest report."
            ),
            "fractional_loads": (
                "The optimiser works in continuous quantities; truckloads are rounded up "
                "per shipment and fleet time is enforced in aggregate, not as a schedule."
            ),
            "round_trips": "Trucks are assumed to return by the same route.",
            "small_runs": (
                "The plan has no fixed cost per truck dispatched, so it may propose a long "
                "run for a small load. Consolidate or skip such runs by judgement."
            ),
            **demand_mod.as_dict(est)["caveats"],
        },
    }
