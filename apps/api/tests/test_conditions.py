"""
Tests for routing from current reported conditions.

Two things are being guarded here, and both are easy to break silently.

The first is the graduated response: evidence strength decides whether a road
is removed from the network or merely slowed. If those factors get flattened
to one number somewhere in the pipeline, every road ends up slowed by the
same amount and the grading is gone with no error anywhere. That happened
twice while building this, so it is tested at every layer it passes through.

The second is that district-level hazard data must never close a road.
"""

import numpy as np
import networkx as nx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.routing.graph import Alternative, CorridorGraph
from app.services.scenario import conditions as live
from app.services.scenario import engine

client = TestClient(app)


NODES = {"A": (92.0, 24.0), "B": (92.1, 24.0), "C": (92.0, 24.1), "D": (92.1, 24.1)}
EDGES = [
    ("A", "B", 1, 10.0, 5.0),
    ("B", "D", 3, 10.0, 5.0),
    ("A", "C", 2, 30.0, 20.0),
    ("C", "D", 4, 10.0, 5.0),
    ("B", "A", 6, 10.0, 5.0),
]
A, B, C, D = 0, 1, 2, 3


@pytest.fixture
def toy() -> CorridorGraph:
    g = nx.DiGraph()
    index = {}
    keys = {k: i for i, k in enumerate(NODES)}
    for u, v, rid, tt, km in EDGES:
        alt = Alternative(rid, tt, km, False, "trunk", "Cachar")
        un, vn = keys[u], keys[v]
        index[rid] = (un, vn)
        if g.has_edge(un, vn):
            g[un][vn]["alternatives"].append(alt)
        else:
            g.add_edge(un, vn, alternatives=[alt])
    return CorridorGraph(
        graph=g,
        node_ids=np.array(list(keys.values()), dtype=np.int64),
        node_coords=np.array([NODES[k] for k in keys], dtype=np.float64),
        road_id_index=index,
    )


# ---------------------------------------------------------------------------
# Per-road factors survive the whole pipeline
# ---------------------------------------------------------------------------


def test_a_set_of_roads_all_get_the_uniform_factor():
    assert engine._as_factor_map({1, 2}, 3.0) == {1: 3.0, 2: 3.0}


def test_a_mapping_keeps_each_roads_own_factor():
    assert engine._as_factor_map({1: 6.0, 2: 1.8}, 3.0) == {1: 6.0, 2: 1.8}


def test_none_degrades_nothing():
    assert engine._as_factor_map(None, 3.0) == {}


def test_different_roads_can_be_slowed_by_different_amounts(toy):
    """The whole point of grading. Road 1 slowed 6x (60 min) must lose to the
    C detour (40 min), where slowing it 1.5x (15 min) must not."""
    heavy = engine.route(toy, A, D, degraded={1: 6.0})
    assert heavy.road_ids == [2, 4], "a heavily slowed road should be avoided"

    light = engine.route(toy, A, D, degraded={1: 1.5})
    assert light.road_ids == [1, 3], "a lightly slowed road is still the best way"


def test_bidirectional_expansion_preserves_each_factor(toy):
    """A road slowed sixfold one way must not be slowed twofold coming back."""
    expanded = engine.expand_bidirectional_map(toy, {1: 6.0})
    assert expanded[1] == 6.0
    assert expanded[6] == 6.0, "the reverse twin inherits the same factor"


def test_expansion_leaves_an_explicit_factor_alone(toy):
    expanded = engine.expand_bidirectional_map(toy, {1: 6.0, 6: 2.0})
    assert expanded[6] == 2.0, "an explicitly given factor is not overwritten"


# ---------------------------------------------------------------------------
# The graduated response
# ---------------------------------------------------------------------------


def test_closing_needs_more_evidence_than_slowing():
    """Removing a road from the network is a strong claim. One person saying
    'blocked' is real evidence and should be visible, but it should not by
    itself delete a highway from the map."""
    assert live.CLOSE_WEIGHT > live.CLOSE_WEIGHT_WITH_CORROBORATION


def test_corroboration_lowers_the_bar_to_a_single_credible_report():
    """0.5 is one fresh report from a neutral-trust reporter."""
    assert live.CLOSE_WEIGHT_WITH_CORROBORATION <= 0.5
    assert live.CLOSE_WEIGHT > 0.5


def test_a_weakly_reported_blockage_is_slowed_hard_not_deleted():
    assert live.DEGRADE_FACTOR_WEAK_BLOCKED > live.DEGRADE_FACTOR_SLOW


def test_reported_slow_outranks_mere_proximity_to_damage():
    """Somebody actually on the road beats a damage point nearby."""
    assert live.DEGRADE_FACTOR_SLOW > live.DEGRADE_FACTOR_HAZARD_NEARBY


def test_hazard_proximity_still_slows_something():
    assert live.DEGRADE_FACTOR_HAZARD_NEARBY > 1.0


def test_report_window_matches_the_fusion_window():
    """Current conditions and the fused status must not disagree about what
    counts as current."""
    from app.services.fusion.reports import FUSION_WINDOW_HOURS

    assert live.REPORT_WINDOW_HOURS == FUSION_WINDOW_HOURS


# ---------------------------------------------------------------------------
# Integration
# ---------------------------------------------------------------------------


def _db_available() -> bool:
    try:
        from sqlalchemy import text

        from app.db.session import SessionLocal

        with SessionLocal() as db:
            db.execute(text("SELECT 1 FROM field_reports LIMIT 1"))
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(
    not _db_available(), reason="no corridor database reachable (expected in CI)"
)


@needs_db
def test_current_conditions_endpoint_explains_every_road_it_touches():
    r = client.get("/api/v1/scenarios/current-conditions")
    assert r.status_code == 200
    body = r.json()
    for road in body["affected_roads"]:
        assert road["effect"] in {"closed", "degraded"}
        assert road["reason"], "every affected road must say why"
        assert road["source"] in {
            "field_reports",
            "field_reports+hazard_data",
            "hazard_data",
        }
    assert "not_a_prediction" in body["caveats"]
    assert "coverage" in body["caveats"]


@needs_db
def test_district_hazard_data_never_closes_a_road():
    """District counts cannot name a road, so letting them close one would be
    inventing specificity the source does not have."""
    body = client.get("/api/v1/scenarios/current-conditions").json()
    closed_from_hazard = [
        r
        for r in body["affected_roads"]
        if r["effect"] == "closed" and r["source"] == "hazard_data"
    ]
    assert closed_from_hazard == []


@needs_db
def test_clean_and_current_conditions_are_different_modes():
    payload = {
        "label": "mode check",
        "origin": "silchar",
        "destination": "haflong",
    }
    clean = client.post(
        "/api/v1/scenarios/simulate", json={**payload, "start_from": "clean"}
    ).json()
    live_run = client.post(
        "/api/v1/scenarios/simulate",
        json={**payload, "start_from": "current_conditions"},
    ).json()

    assert clean["start_from"] == "clean"
    assert "starting_conditions" not in clean
    assert live_run["start_from"] == "current_conditions"
    assert "starting_conditions" in live_run
    assert "baseline_is_still_clean" in live_run["caveats"]
