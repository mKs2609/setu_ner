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


def _resolve_edge(
    alternatives: list[Alternative],
    closed: set[int],
    degraded: set[int],
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
        w = alt.travel_time_min
        if alt.road_id in degraded:
            w *= factor
        if best_w is None or w < best_w:
            best_alt, best_w = alt, w
    return best_alt, best_w


def _make_weight(closed: set[int], degraded: set[int], factor: float):
    def weight(u: int, v: int, data: dict) -> float | None:
        # networkx reads a None weight as "edge not traversable", which is
        # exactly the semantics we want -- and it means a scenario never
        # has to mutate or copy the cached 47k-node graph.
        return _resolve_edge(data["alternatives"], closed, degraded, factor)[1]

    return weight


def route(
    cgraph: CorridorGraph,
    source: int,
    target: int,
    *,
    closed: set[int] | None = None,
    degraded: set[int] | None = None,
    degrade_factor: float = 2.0,
) -> RouteResult:
    """Fastest path between two graph junctions under a set of closures."""
    closed = closed or set()
    degraded = degraded or set()
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
            unreachable_reason=(
                "No route exists between these points with the requested "
                "closures applied. In corridor terms, the origin and "
                "destination are severed from each other."
            ),
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
    degrade_road_ids: set[int],
    degrade_factor: float,
) -> dict:
    """Baseline vs scenario, plus the delta and its causal audit trail."""
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
        degraded=degrade_road_ids,
        degrade_factor=degrade_factor,
    )

    baseline_set = set(baseline.road_ids)
    on_route = sorted(baseline_set & close_road_ids)
    degraded_on_route = sorted(baseline_set & degrade_road_ids)

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
            "roads_degraded": len(degrade_road_ids),
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
