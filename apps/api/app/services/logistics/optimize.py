"""
Allocating depot stock to revenue circles with a limited fleet.

THE MODEL (a linear programme, solved with OR-Tools GLOP)

  x[d,j,c]  quantity of commodity c sent from depot d to circle j
  u[j,c]    quantity of c that circle j does not receive

  stock     sum_j x[d,j,c]                  <= stock[d,c]
  demand    sum_d x[d,j,c] + u[j,c]          = need[j,c]
  fleet     sum_{j,c} kg_c x[d,j,c] * trip_hours[d,j] / truck_kg
                                             <= trucks[d] * hours_per_day * days
  where     trip_hours = 2 x one-way route time + loading time per trip

Pairs with no route are simply absent: nothing can be sent along them.

THREE PRIORITIES, SOLVED IN ORDER, NOT BLENDED
A single weighted objective would let a travel-time saving buy a shortfall
somewhere if the weights happened to allow it, and nobody could say what the
weights meant. So the plan is lexicographic:

  1. Cover as much need as possible, weighted by urgency and counted in
     person-days (15 litres of water and one ration-day are each one
     person-day, so the two commodities are comparable).
  2. Among plans that achieve (1), spread any shortfall as evenly as
     possible: minimise the worst shortfall fraction any circle suffers.
     Without this step the cheapest plan can starve the most remote circle
     entirely while fully supplying the nearest.
  3. Among those, use the fewest truck-hours.

Each stage fixes the previous stage's optimum (with a tiny tolerance) before
solving the next.

THE ORDER OF 1 AND 2 IS A POLICY CHOICE, AND THE OPERATOR MAKES IT
When trucks rather than stock are short, covering the most need favours
nearby circles -- a truck-hour feeds more people close by. Covering-first can
therefore leave a remote circle almost unsupplied; fairness-first guarantees
every circle the same shortfall fraction at the cost of fewer people covered
overall. Neither is correct in general. `fairness_first` selects which comes
first, and the result reports both total coverage and the worst shortfall so
the cost of the choice is visible.

WHAT IS LIMITING THE PLAN
Stage 1's dual values say how much weighted need one more unit of a
resource would cover: an extra thousand litres of water at Silchar, or one
more truck-hour at Karimganj. They are reported as marginal values -- valid
for small changes, not a promise about large ones.

WHAT IT IS NOT
A linear programme has no fixed cost for dispatching a truck, so it can send
one on a four-hour run for a few hundred litres when that is what the stock
arithmetic calls for. A real dispatcher would consolidate or skip such a
run; modelling that needs integer variables (a MILP), which is future work.
A linear programme also allows fractional truckloads. Trips are reported rounded
up per shipment, and the fleet-hours constraint is what keeps the plan
drivable in aggregate; an exact vehicle schedule is a routing problem this
does not solve.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from ortools.linear_solver import pywraplp

from app.services.logistics.demand import Norm

TOLERANCE = 1e-6

# Below this a shipment is solver residue, not a delivery anyone would make
# (the LP happily returns 0.4 litres from one depot). Omitted from the output;
# the omitted total is reported so nothing disappears silently.
MIN_SHIPMENT_KG = 1.0


@dataclass
class DepotInput:
    key: str
    name: str
    stock: dict[str, float]
    trucks: float


@dataclass
class FleetInput:
    truck_capacity_kg: float = 8000.0
    hours_per_day: float = 10.0
    loading_hours_per_trip: float = 1.0
    horizon_days: int = 1


@dataclass
class PlanResult:
    status: str
    shipments: list[dict] = field(default_factory=list)
    runs: list[dict] = field(default_factory=list)
    omitted_residue_kg: float = 0.0
    shortfalls: list[dict] = field(default_factory=list)
    worst_shortfall_fraction: float | None = None
    covered_person_days: float = 0.0
    needed_person_days: float = 0.0
    truck_hours: float = 0.0
    limits: list[dict] = field(default_factory=list)
    depot_use: list[dict] = field(default_factory=list)


def solve(
    depots: list[DepotInput],
    needs: dict[str, dict[str, float]],       # circle -> commodity -> quantity
    one_way_minutes: dict[tuple[str, str], float],  # (depot, circle) -> minutes; absent = no route
    norms: dict[str, Norm],
    fleet: FleetInput,
    fairness_first: bool = False,
) -> PlanResult:
    commodities = list(norms)
    circles = [j for j, n in needs.items() if any(v > 0 for v in n.values())]
    if not circles:
        return PlanResult(status="nothing_to_supply")

    def trip_hours(d: str, j: str) -> float:
        return 2 * one_way_minutes[(d, j)] / 60.0 + fleet.loading_hours_per_trip

    def build():
        s = pywraplp.Solver.CreateSolver("GLOP")
        x = {
            (d.key, j, c): s.NumVar(0, s.infinity(), f"x_{d.key}_{j}_{c}")
            for d in depots
            for j in circles
            for c in commodities
            if (d.key, j) in one_way_minutes
        }
        u = {
            (j, c): s.NumVar(0, max(needs[j].get(c, 0.0), 0.0), f"u_{j}_{c}")
            for j in circles
            for c in commodities
        }
        cons = {"stock": {}, "fleet": {}}
        for d in depots:
            for c in commodities:
                terms = [x[k] for k in x if k[0] == d.key and k[2] == c]
                if terms:
                    cons["stock"][(d.key, c)] = s.Add(sum(terms) <= d.stock.get(c, 0.0))
            fleet_terms = [
                x[k] * norms[k[2]].kg_per_unit * trip_hours(k[0], k[1]) / fleet.truck_capacity_kg
                for k in x
                if k[0] == d.key
            ]
            if fleet_terms:
                cons["fleet"][d.key] = s.Add(
                    sum(fleet_terms) <= d.trucks * fleet.hours_per_day * fleet.horizon_days
                )
        for j in circles:
            for c in commodities:
                inflow = [x[k] for k in x if k[1] == j and k[2] == c]
                s.Add(sum(inflow) + u[(j, c)] == needs[j].get(c, 0.0))

        weighted_unmet = sum(
            norms[c].urgency * u[(j, c)] / norms[c].per_person_per_day
            for j in circles
            for c in commodities
        )
        truck_hours = sum(
            x[k] * norms[k[2]].kg_per_unit * trip_hours(k[0], k[1]) / fleet.truck_capacity_kg
            for k in x
        )
        return s, x, u, cons, weighted_unmet, truck_hours

    def fairness_constraints(s, u):
        z = s.NumVar(0, 1, "worst_shortfall_fraction")
        for j in circles:
            for c in commodities:
                need = needs[j].get(c, 0.0)
                if need > 0:
                    s.Add(u[(j, c)] <= z * need)
        return z

    # What limits the plan: dual values of the plain coverage problem. Solved
    # on its own in both modes, so the explanation always means the same thing.
    s, x, u, cons, weighted_unmet, truck_hours = build()
    s.Minimize(weighted_unmet)
    if s.Solve() != pywraplp.Solver.OPTIMAL:
        return PlanResult(status="solver_failed")
    best_unmet = weighted_unmet.solution_value()
    limits = _limits(cons, norms)

    if fairness_first:
        s, x, u, cons, weighted_unmet, truck_hours = build()
        z = fairness_constraints(s, u)
        s.Minimize(z)
        if s.Solve() != pywraplp.Solver.OPTIMAL:
            return PlanResult(status="solver_failed")
        best_z = z.solution_value()

        s, x, u, cons, weighted_unmet, truck_hours = build()
        z = fairness_constraints(s, u)
        s.Add(z <= best_z + TOLERANCE)
        s.Minimize(weighted_unmet)
        if s.Solve() != pywraplp.Solver.OPTIMAL:
            return PlanResult(status="solver_failed")
        best_unmet = weighted_unmet.solution_value()
    else:
        s, x, u, cons, weighted_unmet, truck_hours = build()
        s.Add(weighted_unmet <= best_unmet * (1 + TOLERANCE) + TOLERANCE)
        z = fairness_constraints(s, u)
        s.Minimize(z)
        if s.Solve() != pywraplp.Solver.OPTIMAL:
            return PlanResult(status="solver_failed")
        best_z = z.solution_value()

    # Last: fewest truck-hours among plans that keep both optima.
    s, x, u, cons, weighted_unmet, truck_hours = build()
    s.Add(weighted_unmet <= best_unmet * (1 + TOLERANCE) + TOLERANCE)
    z = fairness_constraints(s, u)
    s.Add(z <= best_z + TOLERANCE)
    s.Minimize(truck_hours)
    if s.Solve() != pywraplp.Solver.OPTIMAL:
        return PlanResult(status="solver_failed")

    result = PlanResult(status="optimal", limits=limits)
    result.worst_shortfall_fraction = round(best_z, 4)
    result.truck_hours = round(truck_hours.solution_value(), 1)

    for (d, j, c), var in x.items():
        q = var.solution_value()
        if q <= 1e-6:
            continue
        kg = q * norms[c].kg_per_unit
        if kg < MIN_SHIPMENT_KG:
            result.omitted_residue_kg += kg
            continue
        result.shipments.append({
            "depot": d, "circle": j, "commodity": c,
            "quantity": round(q, 1), "unit": norms[c].unit,
            "kg": round(kg, 1),
            "one_way_min": round(one_way_minutes[(d, j)], 1),
        })

    # Commodities for the same circle travel together, so truckloads are
    # counted per depot-to-circle run, not per commodity.
    by_pair: dict[tuple[str, str], dict] = {}
    for sh in result.shipments:
        run = by_pair.setdefault(
            (sh["depot"], sh["circle"]),
            {"depot": sh["depot"], "circle": sh["circle"], "kg": 0.0, "items": {},
             "one_way_min": sh["one_way_min"]},
        )
        run["kg"] += sh["kg"]
        run["items"][sh["commodity"]] = sh["quantity"]
    for run in by_pair.values():
        run["kg"] = round(run["kg"], 1)
        run["truckloads"] = math.ceil(run["kg"] / fleet.truck_capacity_kg - 1e-9)
        run["truck_hours"] = round(
            run["truckloads"] * trip_hours(run["depot"], run["circle"]), 1
        )
    result.runs = sorted(by_pair.values(), key=lambda r: (r["depot"], -r["kg"]))

    for j in circles:
        for c in commodities:
            need = needs[j].get(c, 0.0)
            short = u[(j, c)].solution_value()
            result.needed_person_days += need / norms[c].per_person_per_day
            result.covered_person_days += (need - short) / norms[c].per_person_per_day
            if short >= 0.05:
                reachable = any((d.key, j) in one_way_minutes for d in depots)
                result.shortfalls.append({
                    "circle": j, "commodity": c,
                    "short": round(short, 1), "unit": norms[c].unit,
                    "fraction": round(short / need, 4) if need else None,
                    "reason": (
                        "no depot has a route to this circle"
                        if not reachable
                        else "stock or fleet insufficient"
                    ),
                })

    for d in depots:
        sent = {c: sum(s_["quantity"] for s_ in result.shipments
                       if s_["depot"] == d.key and s_["commodity"] == c) for c in commodities}
        hours = sum(
            s_["kg"] * trip_hours(d.key, s_["circle"]) / fleet.truck_capacity_kg
            for s_ in result.shipments if s_["depot"] == d.key
        )
        result.depot_use.append({
            "depot": d.key, "name": d.name,
            "sent": {c: round(v, 1) for c, v in sent.items()},
            "stock": d.stock,
            "truck_hours_used": round(hours, 1),
            "truck_hours_available": d.trucks * fleet.hours_per_day * fleet.horizon_days,
        })

    result.needed_person_days = round(result.needed_person_days, 1)
    result.covered_person_days = round(result.covered_person_days, 1)
    return result


def _limits(cons: dict, norms: dict[str, Norm]) -> list[dict]:
    """Binding resources, from the coverage problem's dual values."""
    limits = []
    for (d, c), con in cons["stock"].items():
        dual = -con.dual_value()
        if dual > TOLERANCE:
            unit = norms[c].unit[:-1] if norms[c].unit.endswith("s") else norms[c].unit
            limits.append({
                "kind": "stock", "depot": d, "commodity": c, "unit": norms[c].unit,
                "weighted_person_days_per_extra_unit": round(dual, 4),
                "plain": (
                    f"Stock of {norms[c].label.lower()} at {d} is binding: each extra "
                    f"{unit} would cover about {dual:.3g} more urgency-weighted person-days."
                ),
            })
    for d, con in cons["fleet"].items():
        dual = -con.dual_value()
        if dual > TOLERANCE:
            limits.append({
                "kind": "fleet", "depot": d,
                "weighted_person_days_per_extra_truck_hour": round(dual, 2),
                "plain": (
                    f"Trucks at {d} are binding: one more truck-hour would cover about "
                    f"{dual:.3g} more urgency-weighted person-days."
                ),
            })
    return limits
