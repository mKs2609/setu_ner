"""
Phase 5: the what-if / scenario engine.

WHAT IT ANSWERS
"If these roads become unusable, what happens to the corridor?" Concretely:
take an origin and a destination, route between them on the real 110k-edge
graph, then route again with a set of roads closed or slowed, and report
the difference.

WHY DELTAS, NOT ABSOLUTES
Every travel time here inherits `assumed_speed_kmh` from the road graph --
a per-road-class assumption, not measured speed (see services/routing/
graph.py). An absolute "94 minutes" is therefore modelled, not observed,
and presenting it otherwise would be the kind of fabrication this project
has ruled out. But the DELTA between two routes over the same graph is far
more robust: the speed assumption is applied identically on both sides and
largely cancels. So the engine leads with "+47 min, +52%" and marks the
absolutes as modelled. Every response carries that caveat explicitly, in
the same spirit as baseline_accessibility_basis / _confidence on the roads
table -- the qualification travels with the number, rather than sitting in
a docstring the operator never reads.

WHAT A CLOSURE MEANS
A closed road is removed from the graph entirely -- impassable, not slow.
That is the right model for the corridor's real failure mode: the 2022
Bethukandi dyke breach and the 2025 Silchar-Kalain bridge collapse both
severed links outright. `degrade` covers the softer case (a road under
water but still passable) and multiplies travel time instead.

Closing a road does not by itself close its reverse direction, because the
graph is directed and a genuine one-way closure is a legitimate scenario.
The bidirectional option closes the reverse twin too, which is what a
collapsed bridge actually does -- and is the default for that reason.

CAUSAL EXPLANATION (early Phase 6 groundwork)
The engine reports which of the closed roads actually lay on the baseline
route. That distinction matters: closing 400 bridges when only 3 of them
are on the route is the difference between "this scenario caused the
delay" and "this scenario closed a lot of roads that were irrelevant to
it". It is not natural-language explanation yet -- it is the audit trail
such an explanation would have to be built from.

NOT IN SCOPE HERE
This engine recomputes ROUTES. It does not recompute accessibility scores
under the scenario, and it does not decide what to ship where -- that is
Phase 4, which needs population/vulnerability data nobody has sourced yet.
Keeping the boundary explicit so this endpoint is not mistaken for a
logistics plan.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field

import networkx as nx
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.services.routing.graph import Alternative, CorridorGraph

MODELLED_TIME_CAVEAT = (
    "Travel times are MODELLED, not observed: they come from "
    "length_km / assumed_speed_kmh, where the speed is a per-road-class "
    "assumption (trunk 60 km/h, residential 25) because no measured speed "
    "data exists for this corridor. Trust the delta, which is robust to "
    "that assumption; treat the absolute minutes as indicative only."
)


@dataclass
class RouteResult:
    reachable: bool
    travel_time_min: float | None = None
    distance_km: float | None = None
    road_ids: list[int] = field(default_factory=list)
    node_ids: list[int] = field(default_factory=list)
    bridges_crossed: int = 0
    unreachable_reason: str | None = None
    # severed | origin_isolated | destination_isolated | both_isolated
    unreachable_kind: str | None = None

    def as_dict(self) -> dict:
        if not self.reachable:
            return {
                "reachable": False,
                "reason": self.unreachable_reason,
                "travel_time_min": None,
                "distance_km": None,
                "segment_count": 0,
                "bridges_crossed": 0,
            }
        return {
            "reachable": True,
            "travel_time_min": round(self.travel_time_min, 1),
            "distance_km": round(self.distance_km, 2),
            "segment_count": len(self.road_ids),
            "bridges_crossed": self.bridges_crossed,
        }


def _as_factor_map(degraded, factor: float) -> dict[int, float]:
    """Accept either a set of road ids at one uniform factor, or a mapping of
    road id to its own factor.

    Both are needed. A hand-built what-if slows everything it names by the
    same amount, while conditions derived from live reports grade the penalty
    by how strong the evidence is -- a road somebody says is blocked deserves
    a heavier slowdown than one merely near reported damage. Flattening those
    to a single number would throw the distinction away.
    """
    if degraded is None:
        return {}
    if isinstance(degraded, dict):
        return {int(k): float(v) for k, v in degraded.items()}
    return {int(r): factor for r in degraded}


def _resolve_edge(
    alternatives: list[Alternative],
    closed: set[int],
    degraded: dict[int, float],
    factor: float,
) -> tuple[Alternative | None, float | None]:
    """Cheapest still-usable road between one node pair, and its cost.

    Returns (None, None) when every parallel alternative is closed -- which
    is what makes the edge disappear from the graph for this scenario.
    """
    best_alt: Alternative | None = None
    best_w: float | None = None
    for alt in alternatives:
        if alt.road_id in closed:
            continue
        w = alt.travel_time_min * degraded.get(alt.road_id, 1.0)
        if best_w is None or w < best_w:
            best_alt, best_w = alt, w
    return best_alt, best_w


def _make_weight(closed: set[int], degraded: dict[int, float], factor: float):
    def weight(u: int, v: int, data: dict) -> float | None:
        # networkx reads a None weight as "edge not traversable", which is
        # exactly the semantics we want -- and it means a scenario never
        # has to mutate or copy the cached 47k-node graph.
        return _resolve_edge(data["alternatives"], closed, degraded, factor)[1]

    return weight


def _has_usable_edge(g, node: int, closed, degraded, factor, *, outbound: bool) -> bool:
    edges = g.out_edges(node, data=True) if outbound else g.in_edges(node, data=True)
    for *_ends, data in edges:
        if _resolve_edge(data["alternatives"], closed, degraded, factor)[1] is not None:
            return True
    return False


def _diagnose_no_path(g, source, target, closed, degraded, factor) -> dict:
    """Say *why* there is no route, not just that there isn't one.

    An operator needs to tell these apart. "The corridor is severed somewhere
    between you and your destination" is a different problem from "the road
    you are standing on is reported blocked" -- the second is often solved by
    walking to the next street, and reporting both as a bare "cut off" would
    overstate the first and hide the second.

    This matters most for conditions derived from live reports: a report
    lands at somebody's location, which snaps to the road right next to them,
    so the origin's own access road is exactly the one most likely to be
    reported blocked.
    """
    origin_stuck = not _has_usable_edge(
        g, source, closed, degraded, factor, outbound=True
    )
    destination_stuck = not _has_usable_edge(
        g, target, closed, degraded, factor, outbound=False
    )

    if origin_stuck and destination_stuck:
        return dict(
            unreachable_kind="both_isolated",
            unreachable_reason=(
            "Every road leaving the origin and every road reaching the "
            "destination is closed under this scenario. Both ends are isolated "
            "at their own junctions, which is a narrower problem than the "
            "corridor being severed between them."
            ),
        )
    if origin_stuck:
        return dict(
            unreachable_kind="origin_isolated",
            unreachable_reason=(
            "Every road leaving the origin's own junction is closed under this "
            "scenario, so nothing can set out at all. This is a local blockage "
            "at the starting point, not the corridor being severed -- in "
            "practice a vehicle would start from an adjacent street."
            ),
        )
    if destination_stuck:
        return dict(
            unreachable_kind="destination_isolated",
            unreachable_reason=(
            "Every road reaching the destination's own junction is closed "
            "under this scenario. The corridor itself may still be intact; the "
            "final approach is not."
            ),
        )
    return dict(
        unreachable_kind="severed",
        unreachable_reason=(
            "No route exists between these points with the requested closures "
            "applied. The corridor is severed somewhere between origin and "
            "destination -- not merely blocked at either end."
        ),
    )


def route(
    cgraph: CorridorGraph,
    source: int,
    target: int,
    *,
    closed: set[int] | None = None,
    degraded=None,
    degrade_factor: float = 2.0,
) -> RouteResult:
    """Fastest path between two graph junctions under a set of closures.

    `degraded` may be a set of road ids (all slowed by `degrade_factor`) or a
    mapping of road id to its own factor.
    """
    closed = closed or set()
    degraded = _as_factor_map(degraded, degrade_factor)
    g = cgraph.graph

    if source == target:
        return RouteResult(
            reachable=True,
            travel_time_min=0.0,
            distance_km=0.0,
            road_ids=[],
            node_ids=[source],
            bridges_crossed=0,
        )

    try:
        path = nx.shortest_path(
            g, source, target, weight=_make_weight(closed, degraded, degrade_factor)
        )
    except nx.NetworkXNoPath:
        return RouteResult(
            reachable=False,
            **_diagnose_no_path(g, source, target, closed, degraded, degrade_factor),
        )
    except nx.NodeNotFound:
        return RouteResult(
            reachable=False,
            unreachable_reason="Origin or destination is not in the road graph.",
        )

    road_ids: list[int] = []
    total_time = 0.0
    total_km = 0.0
    bridges = 0
    for u, v in zip(path, path[1:]):
        alt, w = _resolve_edge(
            g[u][v]["alternatives"], closed, degraded, degrade_factor
        )
        if alt is None or w is None:
            # Unreachable in practice: shortest_path only traverses edges
            # the same weight function already scored as usable.
            raise RuntimeError(f"Route crossed a closed edge {u}->{v}")
        road_ids.append(alt.road_id)
        total_time += w
        total_km += alt.length_km
        if alt.is_bridge:
            bridges += 1

    return RouteResult(
        reachable=True,
        travel_time_min=total_time,
        distance_km=total_km,
        road_ids=road_ids,
        node_ids=path,
        bridges_crossed=bridges,
    )


def select_bridge_ids(db: Session, district: str) -> list[int]:
    """Every bridge road_id in a district -- the "what if this district's
    crossings go" scenario, which is the corridor's real failure mode."""
    rows = db.execute(
        text("SELECT id FROM roads WHERE is_bridge AND district = :d"),
        {"d": district},
    )
    return [int(r.id) for r in rows]


def expand_bidirectional(cgraph: CorridorGraph, road_ids: set[int]) -> set[int]:
    """Add the reverse twin of each road.

    build_road_graph.py wrote two rows for a two-way road, one per
    direction. Closing only the row the client named would leave the
    opposite carriageway of a collapsed bridge standing -- a quietly wrong
    answer that still looks plausible. Twins are matched on reversed
    (osm_u, osm_v) endpoints.
    """
    index = cgraph.road_id_index
    expanded = set(road_ids)
    for rid in road_ids:
        endpoints = index.get(rid)
        if endpoints is None:
            continue
        u, v = endpoints
        if cgraph.graph.has_edge(v, u):
            for alt in cgraph.graph[v][u]["alternatives"]:
                expanded.add(alt.road_id)
    return expanded


def route_geometry(db: Session, road_ids: list[int]) -> list[list[float]]:
    """The route as one flat coordinate list, ready for the map to draw.

    Ordered along the route, not by the database -- segments in query order
    would render as a scribble.
    """
    if not road_ids:
        return []
    rows = db.execute(
        text(
            "SELECT id, ST_AsGeoJSON(geometry::geometry) AS gj "
            "FROM roads WHERE id = ANY(:ids)"
        ),
        {"ids": road_ids},
    )
    by_id = {int(r.id): json.loads(r.gj)["coordinates"] for r in rows}

    coords: list[list[float]] = []
    for rid in road_ids:
        seg = by_id.get(rid)
        if not seg:
            continue
        # Drop the junction duplicated between consecutive segments.
        coords.extend(seg[1:] if coords and coords[-1] == seg[0] else seg)
    return coords


def simulate(
    db: Session,
    cgraph: CorridorGraph,
    *,
    label: str,
    origin: tuple[float, float, str],
    destination: tuple[float, float, str],
    close_road_ids: set[int],
    degrade_road_ids,
    degrade_factor: float,
) -> dict:
    """Baseline vs scenario, plus the delta and its causal audit trail."""
    degrade_map = _as_factor_map(degrade_road_ids, degrade_factor)
    o_lon, o_lat, o_label = origin
    d_lon, d_lat, d_label = destination
    src, src_km = cgraph.snap(o_lon, o_lat)
    dst, dst_km = cgraph.snap(d_lon, d_lat)

    baseline = route(cgraph, src, dst)
    scenario = route(
        cgraph,
        src,
        dst,
        closed=close_road_ids,
        degraded=degrade_map,
        degrade_factor=degrade_factor,
    )

    baseline_set = set(baseline.road_ids)
    on_route = sorted(baseline_set & close_road_ids)
    degraded_on_route = sorted(baseline_set & set(degrade_map))

    delta: dict = {"severed": not scenario.reachable}
    if baseline.reachable and scenario.reachable:
        added = scenario.travel_time_min - baseline.travel_time_min
        delta.update(
            {
                "added_minutes": round(added, 1),
                "percent_slower": (
                    round(100 * added / baseline.travel_time_min, 1)
                    if baseline.travel_time_min > 0
                    else None
                ),
                "added_km": round(scenario.distance_km - baseline.distance_km, 2),
                "detour_taken": scenario.road_ids != baseline.road_ids,
            }
        )

    if not baseline.reachable:
        verdict = "No baseline route exists -- check the origin and destination."
    elif not scenario.reachable:
        # The headline has to match the diagnosis. Calling a blocked access
        # road at the origin "the corridor is cut off" would overstate it in
        # exactly the direction that costs trust.
        if scenario.unreachable_kind == "origin_isolated":
            verdict = (
                f"Nothing can set out from {o_label}: every road leaving its "
                f"junction is closed under this scenario. This is a local "
                f"blockage, not the corridor being severed."
            )
        elif scenario.unreachable_kind == "destination_isolated":
            verdict = (
                f"{d_label} cannot be reached: every road into it is closed "
                f"under this scenario. The corridor between may still be intact."
            )
        elif scenario.unreachable_kind == "both_isolated":
            verdict = (
                f"Both {o_label} and {d_label} are isolated at their own "
                f"junctions under this scenario."
            )
        else:
            verdict = (
                f"{o_label} is CUT OFF from {d_label} under this scenario. "
                f"No alternative route exists on the modelled network."
            )
    elif not on_route and not degraded_on_route:
        verdict = (
            f"No change. None of the {len(close_road_ids)} affected roads lie "
            f"on the {o_label}-{d_label} route, so this scenario does not "
            f"touch it."
        )
    elif delta.get("added_minutes", 0) <= 0.05:
        verdict = (
            "Route effectively unchanged -- a parallel road absorbed the "
            "closure at no measurable cost."
        )
    else:
        verdict = (
            f"{o_label} to {d_label} takes {delta['added_minutes']:+.1f} min "
            f"longer ({delta['percent_slower']:+.1f}%), detouring via a "
            f"different path."
        )

    return {
        "scenario": label,
        "origin": {"place": o_label, "snapped_km_away": round(src_km, 3)},
        "destination": {"place": d_label, "snapped_km_away": round(dst_km, 3)},
        "verdict": verdict,
        "baseline": baseline.as_dict(),
        "scenario_result": scenario.as_dict(),
        "delta": delta,
        "explanation": {
            "roads_closed": len(close_road_ids),
            "roads_degraded": len(degrade_map),
            "closed_roads_on_baseline_route": on_route,
            "degraded_roads_on_baseline_route": degraded_on_route,
            "note": (
                "closed_roads_on_baseline_route is the causal link: only "
                "these actually forced the change. A large closure count "
                "with an empty list here means the scenario missed the route."
            ),
        },
        "caveats": {
            "travel_time": MODELLED_TIME_CAVEAT,
            "snapping": (
                "Origin and destination are snapped to the nearest road-graph "
                "junction; snapped_km_away reports how far. Anything above "
                "~2 km means the place coordinate or the graph coverage is "
                "suspect, and the result should not be trusted."
            ),
            "not_a_logistics_plan": (
                "This is a routing what-if. It does not estimate demand or "
                "allocate resources -- that is Phase 4, and it is not built."
            ),
        },
    }


def expand_bidirectional_map(
    cgraph: CorridorGraph, factors: dict[int, float]
) -> dict[int, float]:
    """Bidirectional expansion that preserves each road's own factor.

    The set-based version above is fine for closures, where every road gets
    the same treatment. Degradation is graded, so the reverse carriageway has
    to inherit the same multiplier rather than a default -- otherwise a road
    slowed sixfold in one direction is slowed twofold coming back, for no
    reason anybody could defend.
    """
    index = cgraph.road_id_index
    expanded = dict(factors)
    for road_id, factor in factors.items():
        endpoints = index.get(road_id)
        if endpoints is None:
            continue
        u, v = endpoints
        if cgraph.graph.has_edge(v, u):
            for alt in cgraph.graph[v][u]["alternatives"]:
                expanded.setdefault(alt.road_id, factor)
    return expanded
