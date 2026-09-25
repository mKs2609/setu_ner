"""
Tests for demand, gazetteer, routing exposure, and the optimiser.

The optimiser tests use small problems whose right answer can be worked out
by hand, because an LP that is subtly mis-specified still returns "optimal".
The gazetteer tests pin the refusal rules: a destination resolved by guesswork
would send a truck to the wrong town with full confidence.
"""

from datetime import date

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.logistics import gazetteer
from app.services.logistics.demand import NORMS, CircleDemand
from app.services.logistics.optimize import DepotInput, FleetInput, solve

client = TestClient(app)


# ---------------------------------------------------------------------------
# Gazetteer
# ---------------------------------------------------------------------------

PLACES = [
    gazetteer.Place("Silchar", "city", 92.797, 24.830, 1),
    gazetteer.Place("Katigora", "village", 92.573, 24.879, 2),
    gazetteer.Place("Jirighāt", "village", 93.110, 24.807, 3),
    gazetteer.Place("Algapur", "village", 92.600, 24.762, 4),
    gazetteer.Place("Algāpur", "village", 92.592, 24.752, 5),
    gazetteer.Place("Twin", "village", 92.0, 24.5, 6),
    gazetteer.Place("Twin", "village", 92.5, 25.0, 7),
    gazetteer.Place("Lala", "village", 92.7, 24.6, 8),
    gazetteer.Place("Lala", "town", 92.608, 24.560, 9),
]


def test_exact_match_ignores_case_and_diacritics():
    r = gazetteer.resolve("jirighat", PLACES)
    assert r.how == "exact" and r.place.osm_id == 3


def test_alias_is_used_and_explains_itself():
    r = gazetteer.resolve("Katigorah", PLACES)
    assert r.how == "alias" and r.place.name == "Katigora"
    assert r.note


def test_unknown_place_is_not_located_rather_than_guessed():
    r = gazetteer.resolve("Borkhola", PLACES)
    assert r.place is None and r.how == "not_located"


def test_same_named_places_far_apart_are_refused():
    r = gazetteer.resolve("Twin", PLACES)
    assert r.place is None
    assert "refusing" in r.note


def test_same_named_places_close_together_are_one_place():
    r = gazetteer.resolve("Algapur", PLACES)
    assert r.place is not None
    assert 92.592 < r.place.lon < 92.600
    assert "averaged" in r.note


def test_a_town_beats_a_village_of_the_same_name():
    assert gazetteer.resolve("Lala", PLACES).place.place == "town"


def test_committed_gazetteer_carries_osm_attribution():
    import json

    payload = json.loads(gazetteer.GAZETTEER_PATH.read_text(encoding="utf-8"))
    assert "OpenStreetMap" in payload["attribution"]
    assert len(payload["places"]) > 100


# ---------------------------------------------------------------------------
# Demand arithmetic
# ---------------------------------------------------------------------------


def test_demand_counts_people_being_supplied_not_everyone_affected():
    c = CircleDemand("Cachar", "Silchar", camp_inmates=4146, centre_inmates=0, affected=57000)
    assert c.people == 4146
    q = c.quantities(NORMS, horizon_days=2)
    assert q["water"] == 4146 * 15 * 2
    assert q["food"] == 4146 * 2


def test_every_norm_states_its_source_and_basis():
    for n in NORMS.values():
        assert n.source and n.basis in {"cited", "derived", "judgement"}


# ---------------------------------------------------------------------------
# Optimiser -- cases small enough to solve by hand
# ---------------------------------------------------------------------------

NEEDS = {"near": {"water": 30000, "food": 2000}, "far": {"water": 15000, "food": 1000}}
TIMES = {("d", "near"): 30.0, ("d", "far"): 120.0}


def test_enough_of_everything_means_no_shortfall():
    r = solve([DepotInput("d", "D", {"water": 1e6, "food": 1e6}, 50)], NEEDS, TIMES, NORMS, FleetInput())
    assert r.status == "optimal"
    assert r.shortfalls == []
    assert r.covered_person_days == r.needed_person_days


def test_scarce_stock_is_shared_evenly():
    """30,000 L for 45,000 L of need: each circle one third short, not one
    circle fully supplied and the other starved."""
    r = solve([DepotInput("d", "D", {"water": 30000, "food": 1e6}, 50)], NEEDS, TIMES, NORMS, FleetInput())
    fractions = {s["circle"]: s["fraction"] for s in r.shortfalls if s["commodity"] == "water"}
    assert fractions == pytest.approx({"near": 1 / 3, "far": 1 / 3}, abs=1e-3)


def test_binding_stock_is_explained_with_its_marginal_value():
    r = solve([DepotInput("d", "D", {"water": 30000, "food": 1e6}, 50)], NEEDS, TIMES, NORMS, FleetInput())
    stock_limits = [l for l in r.limits if l["kind"] == "stock"]
    assert stock_limits and stock_limits[0]["commodity"] == "water"
    # urgency 3 per 15 litres
    assert stock_limits[0]["weighted_person_days_per_extra_unit"] == pytest.approx(0.2, abs=1e-3)


def test_fairness_first_trades_coverage_for_a_better_worst_case():
    depots = [DepotInput("d", "D", {"water": 1e6, "food": 1e6}, 1)]
    cover = solve(depots, NEEDS, TIMES, NORMS, FleetInput(), fairness_first=False)
    fair = solve(depots, NEEDS, TIMES, NORMS, FleetInput(), fairness_first=True)
    assert fair.worst_shortfall_fraction < cover.worst_shortfall_fraction
    assert fair.covered_person_days <= cover.covered_person_days + 1e-6


def test_fleet_hours_are_never_exceeded():
    fleet = FleetInput(truck_capacity_kg=8000, hours_per_day=10, loading_hours_per_trip=1)
    r = solve([DepotInput("d", "D", {"water": 1e6, "food": 1e6}, 1)], NEEDS, TIMES, NORMS, fleet)
    use = r.depot_use[0]
    assert use["truck_hours_used"] <= use["truck_hours_available"] + 1e-3


def test_a_circle_with_no_route_is_reported_as_unreachable_not_supplied():
    r = solve(
        [DepotInput("d", "D", {"water": 1e6, "food": 1e6}, 50)],
        NEEDS, {("d", "near"): 30.0}, NORMS, FleetInput(),
    )
    far = [s for s in r.shortfalls if s["circle"] == "far"]
    assert far and all(s["reason"] == "no depot has a route to this circle" for s in far)
    assert not any(s["circle"] == "far" for s in r.shipments)


def test_commodities_for_one_circle_share_a_truck():
    r = solve([DepotInput("d", "D", {"water": 1e6, "food": 1e6}, 50)],
              {"near": {"water": 240, "food": 16}}, {("d", "near"): 20.0}, NORMS, FleetInput())
    assert len(r.runs) == 1 and r.runs[0]["truckloads"] == 1


def test_nothing_to_supply_is_a_status_not_an_error():
    r = solve([DepotInput("d", "D", {"water": 1, "food": 1}, 1)],
              {"near": {"water": 0, "food": 0}}, TIMES, NORMS, FleetInput())
    assert r.status == "nothing_to_supply"


# ---------------------------------------------------------------------------
# API validation (no database needed)
# ---------------------------------------------------------------------------


def _depot(**kw):
    d = {"name": "Silchar", "place": "Silchar", "stock": {"water": 1000, "food": 100}, "trucks": 1}
    d.update(kw)
    return d


def test_plan_rejects_too_many_depots():
    r = client.post("/api/v1/logistics/plan", json={"depots": [_depot()] * 11})
    assert r.status_code == 422


def test_plan_rejects_negative_stock():
    r = client.post("/api/v1/logistics/plan", json={"depots": [_depot(stock={"water": -5, "food": 0})]})
    assert r.status_code == 422


def test_plan_rejects_half_a_coordinate():
    r = client.post("/api/v1/logistics/plan", json={"depots": [_depot(lon=92.8)]})
    assert r.status_code == 422


def test_example_inputs_say_they_are_examples():
    body = client.get("/api/v1/logistics/example-inputs").json()
    assert "not real" in body["note"]


# ---------------------------------------------------------------------------
# Integration -- needs the corridor database
# ---------------------------------------------------------------------------


def _db_available() -> bool:
    try:
        from sqlalchemy import text

        from app.db.session import SessionLocal

        with SessionLocal() as db:
            n = db.execute(
                text("SELECT count(*) FROM hazard_observations WHERE metric = 'relief_camp_inmates'")
            ).scalar()
        return bool(n)
    except Exception:
        return False


needs_db = pytest.mark.skipif(
    not _db_available(), reason="no corridor database with relief-camp data (expected in CI)"
)


def _busiest_day() -> str | None:
    days = client.get("/api/v1/logistics/supply-days").json()["days"]
    return max(days, key=lambda d: d["people"])["date"] if days else None


@needs_db
def test_demand_never_plans_for_more_people_than_are_being_supplied():
    day = _busiest_day()
    if day is None:
        pytest.skip("no supply days")
    body = client.get("/api/v1/logistics/demand", params={"as_of": day}).json()
    t = body["totals"]
    assert t["people_to_supply"] == t["people_located"] + t["people_unlocated"]
    for c in body["circles"]:
        assert c["people_to_supply"] == c["camp_inmates"] + c["centre_inmates"]


@needs_db
def test_a_real_plan_is_optimal_and_labels_example_inputs():
    day = _busiest_day()
    if day is None:
        pytest.skip("no supply days")
    ex = client.get("/api/v1/logistics/example-inputs").json()
    body = client.post(
        "/api/v1/logistics/plan",
        json={"as_of": day, "depots": ex["depots"], "risk_minutes_per_exposure_km": 30,
              "example_inputs": True},
    ).json()
    assert body["plan"]["status"] in {"optimal", "nothing_to_supply"}
    assert body["example_inputs"] is True and body["example_note"]
    assert body["is_replay"] == (body["as_of"] != body["latest_report"])
    for r in body["routes"]:
        if r["used_in_plan"]:
            assert r["geometry"] or r["local_delivery"]


@needs_db
def test_lower_exposure_route_never_has_more_exposure_than_fastest():
    day = _busiest_day()
    if day is None:
        pytest.skip("no supply days")
    ex = client.get("/api/v1/logistics/example-inputs").json()
    body = client.post(
        "/api/v1/logistics/plan",
        json={"as_of": day, "depots": ex["depots"][:1], "risk_minutes_per_exposure_km": 120},
    ).json()
    for r in body["routes"]:
        f, s = r["fastest"], r["lower_exposure"]
        if f["reachable"] and s["reachable"]:
            assert s["exposure_km"] <= f["exposure_km"] + 1e-6
            assert s["travel_min"] >= f["travel_min"] - 1e-6


@needs_db
def test_unknown_report_day_is_a_404():
    r = client.get("/api/v1/logistics/demand", params={"as_of": date(1999, 1, 1).isoformat()})
    assert r.status_code == 404


# ---------------------------------------------------------------------------
# Compiled routing equals the reference algorithm (no database)
# ---------------------------------------------------------------------------


def _toy_corridor():
    """A small graph with the awkward cases: parallel roads, a zero-minute
    link, a closed road, a slowed road, and an unreachable junction."""
    import networkx as nx
    import numpy as np

    from app.services.routing.graph import Alternative, CorridorGraph

    def alt(rid, minutes, km):
        return Alternative(rid, minutes, km, False, "primary", "Cachar")

    edges = {
        (1, 2): [alt(10, 5.0, 4.0), alt(11, 4.0, 4.0)],   # parallel: 11 is faster
        (2, 3): [alt(12, 0.0, 0.01)],                      # zero-minute link
        (3, 4): [alt(13, 6.0, 5.0)],
        (1, 4): [alt(14, 12.0, 9.0)],                      # longer but safe
        (4, 5): [alt(15, 3.0, 2.0)],
        (2, 5): [alt(16, 1.0, 1.0)],                       # closed below
        (6, 1): [alt(17, 1.0, 1.0)],                       # 6 reaches in, nothing reaches 6
    }
    g = nx.DiGraph()
    index = {}
    for (u, v), alts in edges.items():
        g.add_edge(u, v, alternatives=alts)
        for a in alts:
            index[a.road_id] = (u, v)
    nodes = np.array(sorted(g.nodes), dtype=np.int64)
    return CorridorGraph(g, nodes, np.zeros((len(nodes), 2)), index)


@pytest.mark.parametrize("penalty", [0.0, 30.0, 120.0])
def test_compiled_routing_matches_networkx(penalty):
    import networkx as nx

    from app.services.logistics import routes

    cg = _toy_corridor()
    ctx = routes.RiskContext(
        accessibility={13: 0.2, 15: 0.9, 11: 0.5},   # 13 badly at risk
        source="test",
        closed={16},
        degraded={10: 2.0},
    )
    targets = [3, 4, 5, 6]
    got = routes.routes_from(cg, 1, targets, ctx, penalty)

    def weight(u, v, data):
        return routes._best_alternative(data["alternatives"], ctx, penalty)[1]

    dist, paths = nx.single_source_dijkstra(cg.graph, 1, weight=weight)
    for t in targets:
        if t not in dist:
            assert not got[t].reachable, "an unreachable junction must stay unreachable"
            continue
        expected = [
            routes._best_alternative(cg.graph[u][v]["alternatives"], ctx, penalty)[0].road_id
            for u, v in zip(paths[t], paths[t][1:])
        ]
        assert got[t].road_ids == expected


def test_zero_minute_links_survive_sparse_matrix_cleanup():
    """The toy graph has a 0-minute link (2 -> 3), the only way to reach 3.
    A stored zero is an edge to scipy until something calls eliminate_zeros,
    after which it is gone. The cost floor means there is no zero to lose."""
    from app.services.logistics import routes

    cg = _toy_corridor()
    ctx = routes.RiskContext(accessibility={}, source="test", closed={16})
    matrix = routes._cost_matrix(cg, ctx, 0.0).copy()
    before = matrix.nnz
    matrix.eliminate_zeros()
    assert matrix.nnz == before, "a zero-cost link would have been deleted"
    got = routes.routes_from(cg, 1, [3], ctx, 0.0)
    assert got[3].reachable and 12 in got[3].road_ids


def test_closed_roads_are_never_used():
    from app.services.logistics import routes

    cg = _toy_corridor()
    ctx = routes.RiskContext(accessibility={}, source="test", closed={16})
    got = routes.routes_from(cg, 1, [5], ctx, 0.0)
    assert 16 not in got[5].road_ids
