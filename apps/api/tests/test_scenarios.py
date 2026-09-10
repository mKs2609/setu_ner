"""
Tests for the Phase 5 scenario engine.

Split deliberately in two:

UNIT TESTS build a tiny synthetic graph by hand and need no database, so
they run in CI. They cover the logic that is easy to get subtly wrong and
impossible to eyeball on a 110k-edge graph: parallel-road fallback,
bidirectional closure, severance, degradation.

INTEGRATION TESTS hit the real corridor in PostGIS and skip when no
database is reachable. CI has no Postgres service and, more to the point,
no corridor data (the geo outputs are gitignored), so these are local-only
by design rather than by accident.
"""

import numpy as np
import networkx as nx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.routing.graph import Alternative, CorridorGraph
from app.services.scenario import engine

client = TestClient(app)


# --------------------------------------------------------------------------
# Unit tests -- synthetic graph, no database
# --------------------------------------------------------------------------

# A -> B -> D is the fast way (10 + 10 = 20 min).
# A -> C -> D is the slow detour (30 + 10 = 40 min).
# A -> B has TWO parallel roads: id 1 at 10 min and id 5 at 12 min, so
# closing id 1 alone must fall back to id 5 rather than severing the link.
NODES = {"A": (92.0, 24.0), "B": (92.1, 24.0), "C": (92.0, 24.1), "D": (92.1, 24.1)}
EDGES = [
    ("A", "B", 1, 10.0, 5.0, False),
    ("A", "B", 5, 12.0, 6.0, False),
    ("B", "D", 3, 10.0, 5.0, True),   # the bridge
    ("A", "C", 2, 30.0, 20.0, False),
    ("C", "D", 4, 10.0, 5.0, False),
    ("B", "A", 6, 10.0, 5.0, False),  # reverse twin of road 1
]


@pytest.fixture
def toy() -> CorridorGraph:
    g = nx.DiGraph()
    road_id_index = {}
    key_to_id = {k: i for i, k in enumerate(NODES)}

    for u, v, rid, tt, km, is_bridge in EDGES:
        alt = Alternative(
            road_id=rid,
            travel_time_min=tt,
            length_km=km,
            is_bridge=is_bridge,
            road_class="trunk",
            district="Cachar",
        )
        un, vn = key_to_id[u], key_to_id[v]
        road_id_index[rid] = (un, vn)
        if g.has_edge(un, vn):
            g[un][vn]["alternatives"].append(alt)
        else:
            g.add_edge(un, vn, alternatives=[alt])

    node_ids = np.array(list(key_to_id.values()), dtype=np.int64)
    node_coords = np.array([NODES[k] for k in key_to_id], dtype=np.float64)
    return CorridorGraph(
        graph=g,
        node_ids=node_ids,
        node_coords=node_coords,
        road_id_index=road_id_index,
    )


A, B, C, D = 0, 1, 2, 3


def test_baseline_takes_the_fast_route(toy):
    r = engine.route(toy, A, D)
    assert r.reachable
    assert r.travel_time_min == pytest.approx(20.0)
    assert r.road_ids == [1, 3]
    assert r.bridges_crossed == 1


def test_closing_one_of_two_parallel_roads_falls_back_not_severs(toy):
    """The bug this guards against: collapsing parallel roads to the fastest
    would make closing road 1 sever A->B, even though road 5 still stands."""
    r = engine.route(toy, A, D, closed={1})
    assert r.reachable
    assert r.road_ids == [5, 3]
    assert r.travel_time_min == pytest.approx(22.0)


def test_closing_all_parallel_roads_forces_the_detour(toy):
    r = engine.route(toy, A, D, closed={1, 5})
    assert r.reachable
    assert r.road_ids == [2, 4]
    assert r.travel_time_min == pytest.approx(40.0)


def test_closing_the_bridge_forces_the_detour(toy):
    r = engine.route(toy, A, D, closed={3})
    assert r.reachable
    assert r.road_ids == [2, 4]
    assert r.bridges_crossed == 0


def test_severance_is_reported_not_raised(toy):
    """Unreachability is a result, not an exception."""
    r = engine.route(toy, A, D, closed={3, 4})
    assert not r.reachable
    assert r.travel_time_min is None
    assert r.unreachable_reason


def test_isolated_destination_is_named_as_such(toy):
    """Closing both roads into D isolates the destination's own junction.
    Reporting that as "the corridor is severed" would overstate it."""
    r = engine.route(toy, A, D, closed={3, 4})
    assert "destination" in r.unreachable_reason
    assert "final approach" in r.unreachable_reason


def test_isolated_origin_is_named_as_such(toy):
    """Closing every road out of A. This is the case live conditions hit most
    often: a report lands at somebody's location, so the road it snaps to is
    the origin's own access road."""
    r = engine.route(toy, A, D, closed={1, 5, 2})
    assert "origin" in r.unreachable_reason
    assert "adjacent street" in r.unreachable_reason


def test_a_genuine_mid_corridor_severance_says_so(toy):
    """Both ends fine, no path between them -- the real severance case."""
    r = engine.route(toy, A, D, closed={3, 4, 6})
    assert not r.reachable
    assert "destination" in r.unreachable_reason or "severed" in r.unreachable_reason


def test_degradation_slows_without_severing(toy):
    r = engine.route(toy, A, D, degraded={1, 5}, degrade_factor=3.0)
    assert r.reachable
    # Road 1 at 3x (30) beats road 5 at 3x (36); B->D unchanged at 10.
    assert r.travel_time_min == pytest.approx(40.0)


def test_degrade_factor_can_make_the_detour_win(toy):
    r = engine.route(toy, A, D, degraded={1, 5, 3}, degrade_factor=10.0)
    assert r.road_ids == [2, 4]


def test_bidirectional_expansion_adds_the_reverse_twin(toy):
    expanded = engine.expand_bidirectional(toy, {1})
    assert 6 in expanded, "reverse twin of road 1 should be closed too"
    assert 1 in expanded


def test_bidirectional_expansion_ignores_unknown_ids(toy):
    assert engine.expand_bidirectional(toy, {999}) == {999}


def test_same_origin_and_destination_is_zero_not_an_error(toy):
    r = engine.route(toy, A, A)
    assert r.reachable
    assert r.travel_time_min == 0.0
    assert r.road_ids == []


def test_simulate_reports_the_causal_link(toy):
    result = engine.simulate(
        None,  # simulate only touches the db for geometry, which we skip
        toy,
        label="bridge down",
        origin=(92.0, 24.0, "A"),
        destination=(92.1, 24.1, "D"),
        close_road_ids={3},
        degrade_road_ids=set(),
        degrade_factor=2.0,
    )
    assert result["delta"]["added_minutes"] == pytest.approx(20.0)
    assert result["delta"]["percent_slower"] == pytest.approx(100.0)
    assert result["explanation"]["closed_roads_on_baseline_route"] == [3]
    assert "longer" in result["verdict"]


def test_simulate_is_honest_when_the_closure_misses_the_route(toy):
    """Closing a road that is not on the route must say so, rather than
    implying the scenario did something."""
    result = engine.simulate(
        None,
        toy,
        label="irrelevant closure",
        origin=(92.0, 24.0, "A"),
        destination=(92.1, 24.1, "D"),
        close_road_ids={2},  # the detour leg, not on the baseline route
        degrade_road_ids=set(),
        degrade_factor=2.0,
    )
    assert result["delta"]["added_minutes"] == 0.0
    assert result["explanation"]["closed_roads_on_baseline_route"] == []
    assert "No change" in result["verdict"]


def test_simulate_reports_severance(toy):
    result = engine.simulate(
        None,
        toy,
        label="cut off",
        origin=(92.0, 24.0, "A"),
        destination=(92.1, 24.1, "D"),
        close_road_ids={3, 4},
        degrade_road_ids=set(),
        degrade_factor=2.0,
    )
    assert result["delta"]["severed"] is True
    # Closing both roads into D isolates the destination's own junction, which
    # is a narrower claim than the corridor being cut. The verdict has to say
    # which one it is -- overstating it here is what costs an operator's trust.
    assert "cannot be reached" in result["verdict"]
    assert "may still be intact" in result["verdict"]


def test_every_response_carries_the_modelled_time_caveat(toy):
    result = engine.simulate(
        None,
        toy,
        label="x",
        origin=(92.0, 24.0, "A"),
        destination=(92.1, 24.1, "D"),
        close_road_ids=set(),
        degrade_road_ids=set(),
        degrade_factor=2.0,
    )
    assert "MODELLED" in result["caveats"]["travel_time"]
    assert "not built" in result["caveats"]["not_a_logistics_plan"]


def test_snap_returns_distance_so_a_bad_coordinate_is_visible(toy):
    node, km = toy.snap(92.0, 24.0)
    assert node == A
    assert km == pytest.approx(0.0, abs=0.01)

    _, far_km = toy.snap(93.0, 25.0)
    assert far_km > 100, "a wildly wrong coordinate must report a large snap"


# --------------------------------------------------------------------------
# Integration tests -- real corridor, skipped without a database
# --------------------------------------------------------------------------


def _db_available() -> bool:
    try:
        from sqlalchemy import text

        from app.db.session import SessionLocal

        with SessionLocal() as db:
            db.execute(text("SELECT 1 FROM roads LIMIT 1"))
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(
    not _db_available(), reason="no corridor database reachable (expected in CI)"
)


def test_landmarks_endpoint_needs_no_database():
    r = client.get("/api/v1/scenarios/landmarks")
    assert r.status_code == 200
    keys = {lm["key"] for lm in r.json()["landmarks"]}
    assert {"silchar", "haflong", "kalain"} <= keys


def test_unknown_place_is_a_400_not_a_500():
    r = client.post(
        "/api/v1/scenarios/simulate",
        json={"label": "typo", "origin": "silchr", "destination": "haflong"},
    )
    assert r.status_code == 400
    assert "Unknown place" in r.json()["detail"]


@needs_db
def test_baseline_route_silchar_to_haflong():
    r = client.get("/api/v1/scenarios/route?origin=silchar&destination=haflong")
    assert r.status_code == 200
    body = r.json()
    assert body["route"]["reachable"]
    assert body["route"]["travel_time_min"] > 0
    assert body["origin"]["snapped_km_away"] < 2.0
    assert body["destination"]["snapped_km_away"] < 2.0


@needs_db
def test_closing_cachar_bridges_severs_the_corridor():
    """The corridor's real dependency: with Cachar's crossings gone,
    Silchar cannot reach Haflong on the modelled network."""
    r = client.post(
        "/api/v1/scenarios/simulate",
        json={
            "label": "all Cachar bridges down",
            "origin": "silchar",
            "destination": "haflong",
            "close_bridges_in_district": "Cachar",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["delta"]["severed"] is True
    assert "CUT OFF" in body["verdict"]


@needs_db
def test_closing_a_district_off_the_route_changes_nothing():
    r = client.post(
        "/api/v1/scenarios/simulate",
        json={
            "label": "Karimganj bridges down",
            "origin": "silchar",
            "destination": "haflong",
            "close_bridges_in_district": "Karimganj",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["delta"]["added_minutes"] == 0.0
    assert body["explanation"]["closed_roads_on_baseline_route"] == []


@needs_db
def test_unknown_district_is_a_404():
    r = client.post(
        "/api/v1/scenarios/simulate",
        json={
            "label": "nowhere",
            "origin": "silchar",
            "destination": "haflong",
            "close_bridges_in_district": "Atlantis",
        },
    )
    assert r.status_code == 404


@needs_db
def test_degrading_a_district_slows_without_severing():
    """The 'flooded but passable' case, which the scenario UI exposes next to
    closure. Same district that severs the corridor when closed outright --
    so this also pins down that degrade and close are genuinely different."""
    r = client.post(
        "/api/v1/scenarios/simulate",
        json={
            "label": "Cachar bridges flooded",
            "origin": "silchar",
            "destination": "haflong",
            "degrade_bridges_in_district": "Cachar",
            "degrade_factor": 3.0,
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["delta"]["severed"] is False, "degrading must not sever"
    assert body["delta"]["added_minutes"] > 0
    assert body["scenario_result"]["reachable"] is True
    assert body["explanation"]["roads_degraded"] > 0
    assert body["explanation"]["degraded_roads_on_baseline_route"]


@needs_db
def test_unknown_district_is_a_404_for_degrade_too():
    r = client.post(
        "/api/v1/scenarios/simulate",
        json={
            "label": "nowhere",
            "origin": "silchar",
            "destination": "haflong",
            "degrade_bridges_in_district": "Atlantis",
        },
    )
    assert r.status_code == 404


@needs_db
def test_closing_beats_degrading_when_a_road_is_named_by_both():
    """Closure is the stronger claim, so a road in both sets must be closed
    rather than merely slowed -- otherwise a scenario could quietly downgrade
    a severed road into a passable one."""
    r = client.post(
        "/api/v1/scenarios/simulate",
        json={
            "label": "same district closed and flooded",
            "origin": "silchar",
            "destination": "haflong",
            "close_bridges_in_district": "Cachar",
            "degrade_bridges_in_district": "Cachar",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["delta"]["severed"] is True
    assert body["explanation"]["roads_degraded"] == 0


@needs_db
def test_simulate_returns_geometry_for_both_routes():
    """The scenario UI draws baseline and scenario as two lines, so both keys
    have to be present -- scenario is null only when the corridor is severed."""
    r = client.post(
        "/api/v1/scenarios/simulate",
        json={
            "label": "geometry check",
            "origin": "silchar",
            "destination": "haflong",
            "close_bridges_in_district": "Karimganj",
            "include_geometry": True,
        },
    )
    assert r.status_code == 200
    geom = r.json()["geometry"]
    assert len(geom["baseline"]) > 100
    assert geom["scenario"] is not None and len(geom["scenario"]) > 100


@needs_db
def test_geometry_is_returned_when_asked_for():
    r = client.get(
        "/api/v1/scenarios/route"
        "?origin=silchar&destination=haflong&include_geometry=true"
    )
    assert r.status_code == 200
    coords = r.json()["geometry"]["coordinates"]
    assert len(coords) > 100
    assert all(len(c) == 2 for c in coords)
