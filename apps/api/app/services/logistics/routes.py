"""
Routes from depots to demand, aware of how much of each route is at risk.

TWO ROUTES, ALWAYS BOTH
`0001` Tier 1 item 3 asked for the fastest route and the safer one side by
side whenever they differ. Every depot-to-circle pair gets:

  fastest         least travel time, under live closures and slowdowns
  lower-exposure  least of  travel time + penalty x exposure-km

`exposure-km` is kilometres driven weighted by how inaccessible the Phase 3
model says each road is: a kilometre at accessibility 0.26 counts 0.74, a
kilometre at 0.98 counts 0.02. The penalty (minutes per exposure-km) is the
operator's stated trade-off -- how many minutes of detour they would accept
to avoid one kilometre of fully at-risk road. It is a preference, not a
probability, and it is shown as one.

WHY NOT A ROUTE "RELIABILITY" PROBABILITY
Multiplying per-road accessibilities along a route treats every road as an
independent coin flip. They are not: roads in one district flood in the same
event, so the product would be wildly pessimistic and look precise. Exposure-km
makes no independence claim, and the route's weakest link is reported beside
it.

WHAT ACCESSIBILITY IS USED
The Phase 3 forecast made from the plan's report day:
1 - P(district affected next day) x terrain exposure. For today's report that
is the stored value; for a past report day it is recomputed from that day's
features with the same model artifacts, so a replay of 1 June 2025 plans
against what the model would have said on 1 June 2025. Roads outside Assam's
reporting have no forecast; their kilometres are counted as unscored, not
treated as safe.

Live closures and slowdowns from field reports and damage points (0007) apply
only when planning from the latest report -- they describe now, not June 2025.

Trucks are assumed to return the way they came: round trip = 2 x one way.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import numpy as np
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra
from sqlalchemy import select

from app.db.models import Road
from app.services.model import district_model as dm
from app.services.model import score as scoring
from app.services.model.history import load_history
from app.services.routing.graph import Alternative, CorridorGraph
from app.services.scenario import conditions as live_conditions
from app.services.scenario import engine


@dataclass
class RiskContext:
    accessibility: dict[int, float]
    source: str
    closed: set[int] = field(default_factory=set)
    degraded: dict[int, float] = field(default_factory=dict)
    live_conditions_applied: bool = False
    district_probability: dict[str, float] = field(default_factory=dict)
    # Sparse cost matrices by penalty, shared by every depot in one plan.
    matrix_cache: dict = field(default_factory=dict, repr=False)


def risk_context(db, cgraph: CorridorGraph, as_of: date, latest: date) -> RiskContext:
    history = load_history(db)
    artifacts = {h: dm.load(h) for h in dm.HORIZONS}

    stored_as_of = db.execute(
        select(Road.current_accessibility_as_of)
        .where(Road.current_accessibility.isnot(None))
        .limit(1)
    ).scalar()

    district_p: dict[str, float] = {}
    if all(artifacts.values()) and as_of in set(history.published):
        for f in scoring.forecast_districts(history, as_of, artifacts):
            if f["in_corridor"] and f["horizon_days"] == 1:
                district_p[f["district_key"]] = f["probability"]

    if stored_as_of == as_of:
        rows = db.execute(
            select(Road.id, Road.current_accessibility).where(Road.current_accessibility.isnot(None))
        ).all()
        acc = {int(i): float(a) for i, a in rows}
        source = f"stored Phase 3 scores as of {as_of}"
    elif district_p:
        rows = db.execute(
            select(Road.id, Road.district, Road.hazard_exposure).where(
                Road.hazard_exposure.isnot(None)
            )
        ).all()
        acc = {
            int(i): round(1.0 - district_p[d] * float(e), 4)
            for i, d, e in rows
            if d in district_p
        }
        source = f"Phase 3 model recomputed from the {as_of} report"
    else:
        acc, source = {}, "no model available; exposure not scored"

    ctx = RiskContext(accessibility=acc, source=source, district_probability=district_p)
    if as_of == latest:
        cond = live_conditions.derive(db)
        closed = engine.expand_bidirectional(cgraph, set(cond.closed_road_ids))
        degraded = engine.expand_bidirectional_map(cgraph, dict(cond.degraded))
        ctx.closed = closed
        ctx.degraded = {k: v for k, v in degraded.items() if k not in closed}
        ctx.live_conditions_applied = True
    return ctx


def _edge_cost(alt: Alternative, ctx: RiskContext, penalty: float) -> float | None:
    if alt.road_id in ctx.closed:
        return None
    minutes = alt.travel_time_min * ctx.degraded.get(alt.road_id, 1.0)
    access = ctx.accessibility.get(alt.road_id)
    risk = 0.0 if access is None else penalty * alt.length_km * (1.0 - access)
    return minutes + risk


def _best_alternative(alts: list[Alternative], ctx: RiskContext, penalty: float):
    best, best_cost = None, None
    for alt in alts:
        c = _edge_cost(alt, ctx, penalty)
        if c is not None and (best_cost is None or c < best_cost):
            best, best_cost = alt, c
    return best, best_cost


@dataclass
class RouteOption:
    reachable: bool
    travel_min: float | None = None
    distance_km: float | None = None
    exposure_km: float | None = None
    unscored_km: float | None = None
    weakest_accessibility: float | None = None
    bridges: int = 0
    road_ids: list[int] = field(default_factory=list)

    def as_dict(self) -> dict:
        if not self.reachable:
            return {"reachable": False}
        return {
            "reachable": True,
            "travel_min": round(self.travel_min, 1),
            "distance_km": round(self.distance_km, 1),
            "exposure_km": round(self.exposure_km, 2),
            "unscored_km": round(self.unscored_km, 1),
            "weakest_accessibility": self.weakest_accessibility,
            "bridges": self.bridges,
        }


# Edge costs can be exactly zero (a junction pair a few metres apart rounds to
# 0 minutes). scipy's csgraph keeps an explicitly stored zero as an edge, but
# any operation that calls eliminate_zeros -- several conversions and
# arithmetic on sparse matrices do -- silently deletes it, and the link with
# it. A tiny floor makes the matrix immune to that rather than relying on
# nothing ever touching it.
_MIN_COST = 1e-9


@dataclass
class _EdgeArrays:
    """The corridor graph flattened into arrays, built once per graph.

    One row per junction, one entry per road alternative, so per-plan costs
    are a vectorised calculation instead of ~725,000 Python function calls.
    """

    nodes: np.ndarray        # row -> junction id
    index: dict[int, int]    # junction id -> row
    edge_u: np.ndarray       # edge -> row of its start
    edge_v: np.ndarray       # edge -> row of its end
    alt_edge: np.ndarray     # alternative -> its edge
    alt_road: np.ndarray     # alternative -> road id
    alt_time: np.ndarray     # alternative -> baseline minutes
    alt_len: np.ndarray      # alternative -> km


_arrays_cache: tuple[int, _EdgeArrays] | None = None


def _edge_arrays(cgraph: CorridorGraph) -> _EdgeArrays:
    global _arrays_cache
    if _arrays_cache is not None and _arrays_cache[0] == id(cgraph):
        return _arrays_cache[1]
    g = cgraph.graph
    nodes = np.fromiter(g.nodes, dtype=np.int64, count=g.number_of_nodes())
    index = {int(n): i for i, n in enumerate(nodes)}
    eu, ev, ae, ar, at, al = [], [], [], [], [], []
    for e, (u, v, data) in enumerate(g.edges(data=True)):
        eu.append(index[u])
        ev.append(index[v])
        for alt in data["alternatives"]:
            ae.append(e)
            ar.append(alt.road_id)
            at.append(alt.travel_time_min)
            al.append(alt.length_km)
    arrays = _EdgeArrays(
        nodes, index,
        np.asarray(eu, dtype=np.int64), np.asarray(ev, dtype=np.int64),
        np.asarray(ae, dtype=np.int64), np.asarray(ar, dtype=np.int64),
        np.asarray(at, dtype=float), np.asarray(al, dtype=float),
    )
    _arrays_cache = (id(cgraph), arrays)
    return arrays


def _cost_matrix(cgraph: CorridorGraph, ctx: RiskContext, penalty: float):
    """Sparse junction-to-junction cost matrix for one risk setting.

    Same rule as `_edge_cost` / `_best_alternative`: minutes (slowed by live
    reports) plus penalty x km x (1 - accessibility), closed roads removed,
    and the cheapest alternative per junction pair -- the first in list order
    on a tie, which is also what `_best_alternative` picks. Cached on the
    context, because every depot in one plan shares it.
    """
    cache = ctx.matrix_cache
    if penalty in cache:
        return cache[penalty]
    a = _edge_arrays(cgraph)
    roads = a.alt_road.tolist()
    access = np.fromiter(
        (ctx.accessibility.get(r, np.nan) for r in roads), dtype=float, count=len(roads)
    )
    slow = (
        np.fromiter((ctx.degraded.get(r, 1.0) for r in roads), dtype=float, count=len(roads))
        if ctx.degraded else 1.0
    )
    risk = np.where(np.isnan(access), 0.0, penalty * a.alt_len * (1.0 - np.nan_to_num(access)))
    cost = a.alt_time * slow + risk
    if ctx.closed:
        closed = np.fromiter((r in ctx.closed for r in roads), dtype=bool, count=len(roads))
        cost[closed] = np.inf

    order = np.lexsort((cost, a.alt_edge))  # stable: ties keep list order
    edges_sorted = a.alt_edge[order]
    first = np.r_[True, edges_sorted[1:] != edges_sorted[:-1]]
    best = order[first]
    edge_cost = cost[best]
    edge = a.alt_edge[best]
    usable = np.isfinite(edge_cost)

    n = len(a.nodes)
    matrix = csr_matrix(
        (np.maximum(edge_cost[usable], _MIN_COST), (a.edge_u[edge[usable]], a.edge_v[edge[usable]])),
        shape=(n, n),
    )
    cache[penalty] = matrix
    return matrix


def _path_to(target_row: int, source_row: int, pred: np.ndarray) -> list[int] | None:
    if target_row == source_row:
        return [source_row]
    if pred[target_row] < 0:
        return None
    path = [target_row]
    while path[-1] != source_row:
        path.append(int(pred[path[-1]]))
    path.reverse()
    return path


def routes_from(
    cgraph: CorridorGraph,
    source: int,
    targets: list[int],
    ctx: RiskContext,
    penalty: float,
) -> dict[int, RouteOption]:
    """One Dijkstra from a depot to every target at once."""
    g = cgraph.graph
    if source not in g:
        return {t: RouteOption(False) for t in targets}

    # scipy's compiled Dijkstra over a per-plan cost matrix. The first
    # deployment ran networkx's, which stored a full path to every one of the
    # 47,424 junctions (~109 MB per depot -- the 502 on a 512 MB host); a
    # pure-Python replacement fixed the memory but still made ~725,000 cost
    # calls per plan, which took 25 s on a free-tier CPU share. Here the costs
    # are one vectorised pass and the search runs in C. Each path is then
    # walked with `_best_alternative`, so the road chosen on every edge is
    # exactly the one the cost rule picks.
    a = _edge_arrays(cgraph)
    src = a.index[source]
    _, pred = dijkstra(
        _cost_matrix(cgraph, ctx, penalty), directed=True, indices=src, return_predecessors=True
    )

    out: dict[int, RouteOption] = {}
    for t in targets:
        rows = _path_to(a.index[t], src, pred) if t in a.index else None
        if rows is None:
            out[t] = RouteOption(False)
            continue
        path = [int(a.nodes[r]) for r in rows]
        opt = RouteOption(True, 0.0, 0.0, 0.0, 0.0, None, 0, [])
        for u, v in zip(path, path[1:]):
            alt, _ = _best_alternative(g[u][v]["alternatives"], ctx, penalty)
            opt.road_ids.append(alt.road_id)
            opt.travel_min += alt.travel_time_min * ctx.degraded.get(alt.road_id, 1.0)
            opt.distance_km += alt.length_km
            opt.bridges += int(alt.is_bridge)
            access = ctx.accessibility.get(alt.road_id)
            if access is None:
                opt.unscored_km += alt.length_km
            else:
                opt.exposure_km += alt.length_km * (1.0 - access)
                if opt.weakest_accessibility is None or access < opt.weakest_accessibility:
                    opt.weakest_accessibility = access
        out[t] = opt
    return out


def geometry(db, road_ids: list[int]) -> list[list[float]]:
    return engine.route_geometry(db, road_ids)
