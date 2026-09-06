"""
Routable graph for the corridor, built from the roads table in PostGIS.

WHY THIS IS ITS OWN LAYER
The scenario engine (Phase 5) and, later, the logistics optimizer (Phase 4)
both need to answer "how long from A to B, given these roads are unusable".
That needs a routable graph, not a table of edges. Both callers share this
module rather than each growing their own copy.

WHAT THE WEIGHTS ACTUALLY MEAN -- READ BEFORE TRUSTING A TRAVEL TIME
Edge weight is `baseline_travel_time_min`, which build_road_graph.py
computed as length_km / assumed_speed_kmh. `assumed_speed_kmh` is a
per-road-class ASSUMPTION (trunk 60 km/h, residential 25), not an
observation -- there is no measured speed data for this corridor, and
there won't be until a live traffic/condition source exists. So every
travel time here is a modelled free-flow, dry-conditions time.

The honest way to use it is as a RELATIVE measure. The difference between
two routes is far more trustworthy than either absolute number, because
the speed assumption largely cancels out in the delta. The scenario engine
is built on exactly that property: it leads with deltas and labels every
absolute as modelled. Same discipline as
compute_baseline_accessibility.py -- state the assumption in the output,
not just in a docstring.

PARALLEL EDGES
OSM gives multiple ways between the same node pair (110,266 rows collapse
to 109,522 node pairs). We keep EVERY alternative rather than collapsing
to the fastest, because collapsing would silently break closures: closing
the fastest of two parallel roads would sever the connection even though
a real parallel road is still standing. Each graph edge therefore carries
all its alternatives, and is only unusable when all of them are closed.

DIRECTIONALITY
Directed graph. build_road_graph.py wrote both directions for two-way
roads, so most edges have a reverse twin. One-way tags come straight from
OSM and have NOT been hand-verified (same open item as bridge tags in
docs/decisions/0002).

COST
~0.5s to build for the current 110k-edge corridor, cached process-wide.
Paid once per API process, not per request.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field

import networkx as nx
import numpy as np
from sqlalchemy import text
from sqlalchemy.orm import Session

EDGE_QUERY = text(
    """
    SELECT id, osm_u, osm_v,
           baseline_travel_time_min, length_km, is_bridge,
           road_class, district,
           ST_X(ST_StartPoint(geometry::geometry)) AS ux,
           ST_Y(ST_StartPoint(geometry::geometry)) AS uy,
           ST_X(ST_EndPoint(geometry::geometry))   AS vx,
           ST_Y(ST_EndPoint(geometry::geometry))   AS vy
    FROM roads
    WHERE osm_u IS NOT NULL
      AND osm_v IS NOT NULL
      AND baseline_travel_time_min IS NOT NULL
    """
)


@dataclass(frozen=True)
class Alternative:
    """One real road segment offering a connection between two junctions."""

    road_id: int
    travel_time_min: float
    length_km: float
    is_bridge: bool
    road_class: str | None
    district: str | None


@dataclass
class CorridorGraph:
    graph: nx.DiGraph
    node_ids: np.ndarray = field(repr=False)
    node_coords: np.ndarray = field(repr=False)  # (N, 2) lon/lat
    road_id_index: dict[int, tuple[int, int]] = field(repr=False)

    @property
    def node_count(self) -> int:
        return self.graph.number_of_nodes()

    @property
    def edge_count(self) -> int:
        return self.graph.number_of_edges()

    @property
    def road_count(self) -> int:
        return len(self.road_id_index)

    def snap(self, lon: float, lat: float) -> tuple[int, float]:
        """
        Nearest graph junction to a coordinate, plus how far off it was in km.

        The caller is expected to surface that distance rather than swallow
        it: a landmark that snaps 8 km to the nearest junction is telling
        you the coordinate or the graph coverage is wrong, and silently
        routing from the wrong place would be exactly the kind of quiet
        fabrication this project has committed to avoiding.
        """
        dlon = self.node_coords[:, 0] - lon
        dlat = self.node_coords[:, 1] - lat
        # Local-scale equirectangular approximation. Fine at this latitude
        # over these distances, and we only need argmin, not a precise km.
        km = np.hypot(dlon * 111.32 * np.cos(np.radians(lat)), dlat * 110.57)
        idx = int(np.argmin(km))
        return int(self.node_ids[idx]), float(km[idx])


_cache: CorridorGraph | None = None
_lock = threading.Lock()


def build_corridor_graph(db: Session) -> CorridorGraph:
    """Build the graph from PostGIS. Prefer get_corridor_graph() -- this
    always does the full read, and exists so a caller can force a rebuild."""
    graph = nx.DiGraph()
    coords: dict[int, tuple[float, float]] = {}
    road_id_index: dict[int, tuple[int, int]] = {}

    for row in db.execute(EDGE_QUERY):
        u, v = int(row.osm_u), int(row.osm_v)
        coords[u] = (row.ux, row.uy)
        coords[v] = (row.vx, row.vy)

        alt = Alternative(
            road_id=int(row.id),
            travel_time_min=float(row.baseline_travel_time_min),
            length_km=float(row.length_km) if row.length_km is not None else 0.0,
            is_bridge=bool(row.is_bridge),
            road_class=row.road_class,
            district=row.district,
        )
        road_id_index[alt.road_id] = (u, v)

        if graph.has_edge(u, v):
            graph[u][v]["alternatives"].append(alt)
        else:
            graph.add_edge(u, v, alternatives=[alt])

    node_ids = np.fromiter(coords.keys(), dtype=np.int64, count=len(coords))
    node_coords = np.array([coords[n] for n in node_ids], dtype=np.float64)

    return CorridorGraph(
        graph=graph,
        node_ids=node_ids,
        node_coords=node_coords,
        road_id_index=road_id_index,
    )


def get_corridor_graph(db: Session, *, rebuild: bool = False) -> CorridorGraph:
    """Process-wide cached graph. Thread-safe: FastAPI runs sync endpoints
    in a threadpool, so two concurrent first-requests could otherwise both
    pay the build cost."""
    global _cache
    if _cache is not None and not rebuild:
        return _cache
    with _lock:
        if _cache is None or rebuild:
            _cache = build_corridor_graph(db)
    return _cache


def reset_corridor_graph() -> None:
    """Drop the cache -- for tests, and for after a data reload."""
    global _cache
    with _lock:
        _cache = None
