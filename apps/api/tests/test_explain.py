"""
Tests for Phase 6: explanations and the audit trail.

An explanation that disagrees with the number it explains is worse than none,
so the central test is arithmetic: the per-feature contributions must add up
to the model's own prediction. The narrative tests check that every sentence
comes from the plan's figures, and the audit tests that records cannot be
changed and overrides cannot be anonymous noise.
"""

import math

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.explain import forecast as fx
from app.services.explain import plan as px
from app.services.model import district_model as dm
from app.services.model.dataset import FEATURES

client = TestClient(app)


def _logistic_payload(seed: int = 0) -> dict:
    rng = np.random.default_rng(seed)
    return {
        "horizon_days": 1,
        "kind": "logistic",
        "version": "test",
        "features": list(FEATURES),
        "params": {
            "scaler_mean": rng.normal(0, 1, len(FEATURES)).tolist(),
            "scaler_scale": rng.uniform(0.5, 2, len(FEATURES)).tolist(),
            "coef": rng.normal(0, 1, len(FEATURES)).tolist(),
            "intercept": -2.5,
        },
    }


def _features(**overrides) -> dict:
    f = {
        "affected": 1.0, "log_population": math.log1p(80028), "affected_frac_7d": 0.7,
        "run_length": 5 / 14, "population_trend": 0.2, "relief_camps_open": 1.0,
        "infra_damage_7d": 1.0, "affected_frac_60d": 0.3,
        "state_log_affected": math.log1p(19), "state_trend": 0.1,
    }
    f.update(overrides)
    return f


# ---------------------------------------------------------------------------
# Forecast explanations
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("seed", range(5))
def test_contributions_add_up_exactly_to_the_prediction(seed):
    payload = _logistic_payload(seed)
    e = fx.explain(payload, _features(), "Cachar")
    logit = payload["params"]["intercept"] + sum(c["log_odds"] for c in e["contributions"])
    p = 1 / (1 + math.exp(-logit))
    assert p == pytest.approx(dm.predict_one(payload, _features()), abs=1e-3)
    assert e["check"]["matches_prediction"] is True


def test_every_feature_is_accounted_for():
    e = fx.explain(_logistic_payload(), _features(), "Cachar")
    assert {c["feature"] for c in e["contributions"]} == set(FEATURES)


def test_sentences_state_the_actual_values():
    e = fx.explain(_logistic_payload(), _features(), "Cachar")
    text = {c["feature"]: c["sentence"] for c in e["contributions"]}
    assert "80,028 people" in text["log_population"]
    assert "19 district(s)" in text["state_log_affected"]
    assert "5 report day(s)" in text["run_length"]


def test_explanation_warns_it_is_not_causal():
    e = fx.explain(_logistic_payload(), _features(), "Cachar")
    assert "does not mean the input causes flooding" in e["how_to_read"]


def test_persistence_is_explained_as_its_rule():
    payload = {
        "horizon_days": 3, "kind": "persistence", "version": "t", "features": list(FEATURES),
        "params": {"p_given_affected": 0.48, "p_given_not_affected": 0.04},
    }
    e = fx.explain(payload, _features(affected=0.0), "Cachar")
    assert e["method"] == "rule" and "not affected" in e["headline"] and "4%" in e["headline"]
    assert e["contributions"] == []


# ---------------------------------------------------------------------------
# Plan narrative
# ---------------------------------------------------------------------------


def _plan(**over) -> dict:
    plan = {
        "as_of": "2025-06-01", "is_replay": True, "example_inputs": True,
        "demand": {
            "horizon_days": 1,
            "totals": {"people_to_supply": 7121, "needs": {"water": 106815.0, "food": 7121.0}},
            "norms": {"water": {"per_person_per_day": 15}, "food": {"per_person_per_day": 1}},
            "unattributed_by_district": {"Karimganj": {"relief_camp_inmates": 40.0}},
        },
        "plan": {
            "status": "optimal", "policy": "coverage_first",
            "person_days_needed_all_commodities": 14242.0,
            "person_days_covered_all_commodities": 14107.5,
            "worst_shortfall_fraction": 0.0207, "truck_hours": 26.8,
            "runs": [{}, {}],
            "limits": [{"kind": "fleet", "depot": "Haflong", "plain": "Trucks at Haflong are binding."}],
            "shortfalls": [{"circle": "Borkhola", "commodity": "water", "reason": "no depot has a route to this circle"}],
            "people_outside_plan": 220, "omitted_residue_kg": 0.4,
        },
        "routes": [{
            "depot": "Haflong", "circle": "Udharbond", "used_in_plan": True, "routes_diverge": True,
            "fastest": {"travel_min": 160.1, "exposure_km": 29.8, "bridges": 32},
            "lower_exposure": {"travel_min": 214.3, "exposure_km": 16.14, "bridges": 11},
        }],
        "risk": {"risk_minutes_per_exposure_km": 30, "accessibility_source": "model",
                 "live_conditions_applied": False, "closed_roads": 0, "degraded_roads": 0},
        "problems": [],
    }
    plan.update(over)
    return plan


def _all_text(n: dict) -> str:
    return " ".join(s["text"] for sec in n["sections"] for s in sec["statements"])


def test_narrative_uses_the_plans_own_figures():
    text = _all_text(px.narrate(_plan()))
    assert "7,121 people" in text
    assert "99%" in text                      # 14107.5 / 14242
    assert "+54 min for 13.7 fewer exposure-km (32 → 11 bridges)" in text


def test_every_statement_carries_evidence():
    for sec in px.narrate(_plan())["sections"]:
        for s in sec["statements"]:
            assert s["evidence"], s["text"]


def test_narrative_never_hides_what_the_plan_left_out():
    text = _all_text(px.narrate(_plan()))
    assert "example figures" in text
    assert "Borkhola" in text
    assert "220 people" in text
    assert "Karimganj reports 40 people" in text


def test_limits_are_repeated_verbatim_not_reworded():
    n = px.narrate(_plan())
    limits = next(s for s in n["sections"] if s["title"] == "What limits it")
    assert limits["statements"][0]["text"] == "Trucks at Haflong are binding."


# ---------------------------------------------------------------------------
# API validation (no database needed)
# ---------------------------------------------------------------------------


def test_override_needs_a_reason():
    r = client.post(
        f"/api/v1/recommendations/{'a' * 32}/overrides",
        json={"operator_id": "operator-1", "action": "rejected", "reason_category": "other", "reason": ""},
    )
    assert r.status_code == 422


def test_override_rejects_unknown_actions_and_categories():
    base = {"operator_id": "operator-1", "reason": "the bridge is out", "action": "rejected",
            "reason_category": "other"}
    for bad in ({"action": "deleted"}, {"reason_category": "vibes"}):
        r = client.post(f"/api/v1/recommendations/{'a' * 32}/overrides", json={**base, **bad})
        assert r.status_code == 422


def test_there_is_no_way_to_edit_or_delete_a_record():
    rid = "a" * 32
    assert client.put(f"/api/v1/recommendations/{rid}", json={}).status_code == 405
    assert client.patch(f"/api/v1/recommendations/{rid}", json={}).status_code == 405
    assert client.delete(f"/api/v1/recommendations/{rid}").status_code == 405


# ---------------------------------------------------------------------------
# Integration -- needs the corridor database
# ---------------------------------------------------------------------------


def _db_available() -> bool:
    try:
        from sqlalchemy import text

        from app.db.session import SessionLocal

        with SessionLocal() as db:
            db.execute(text("SELECT 1 FROM recommendations LIMIT 1"))
            n = db.execute(
                text("SELECT count(*) FROM hazard_observations WHERE metric = 'relief_camp_inmates'")
            ).scalar()
        return bool(n) and dm.load(1) is not None
    except Exception:
        return False


needs_db = pytest.mark.skipif(not _db_available(), reason="no corridor database (expected in CI)")


@needs_db
def test_district_explanation_matches_the_stored_forecast_model():
    body = client.get("/api/v1/model/explain/Cachar").json()
    for e in body["explanations"]:
        if e["method"] == "exact_linear_attribution":
            assert e["check"]["matches_prediction"]


@needs_db
def test_unknown_district_is_a_404():
    assert client.get("/api/v1/model/explain/Atlantis").status_code == 404


@needs_db
def test_road_explanation_reconstructs_the_stored_value():
    from sqlalchemy import select

    from app.db.models import Road
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        road_id = db.execute(
            select(Road.id).where(Road.current_accessibility.isnot(None)).limit(1)
        ).scalar()
    if road_id is None:
        pytest.skip("roads not scored")
    e = client.get(f"/api/v1/accessibility/{road_id}/explanation").json()
    if not e["explains_stored_value"]:
        pytest.skip("model retrained since scoring")
    p = e["district_forecast"]["probability"]
    stored = client.get(f"/api/v1/accessibility/{road_id}").json()["model"]["current_accessibility"]
    assert 1 - p * e["terrain"]["exposure"] == pytest.approx(stored, abs=2e-3)


@needs_db
def test_saved_plan_is_frozen_and_overrides_are_appended():
    days = client.get("/api/v1/logistics/supply-days").json()["days"]
    if not days:
        pytest.skip("no supply days")
    ex = client.get("/api/v1/logistics/example-inputs").json()
    plan = client.post(
        "/api/v1/logistics/plan",
        json={"as_of": days[0]["date"], "depots": ex["depots"][:1], "example_inputs": True,
              "save": True, "label": "pytest"},
    ).json()
    rid = plan["recommendation_id"]
    assert rid and plan["explanation"]["summary"]

    before = client.get(f"/api/v1/recommendations/{rid}").json()
    r = client.post(
        f"/api/v1/recommendations/{rid}/overrides",
        json={"operator_id": "pytest-operator", "action": "modified",
              "reason_category": "road_condition_differs", "reason": "approach road under water"},
    )
    assert r.status_code == 201
    after = client.get(f"/api/v1/recommendations/{rid}").json()
    assert after["outputs"] == before["outputs"], "an override must never change the record"
    overrides = client.get(f"/api/v1/recommendations/{rid}/overrides").json()["overrides"]
    assert overrides[-1]["reason"] == "approach road under water"


@needs_db
def test_unsaved_plans_leave_no_record():
    from sqlalchemy import func, select

    from app.db.models import Recommendation
    from app.db.session import SessionLocal

    days = client.get("/api/v1/logistics/supply-days").json()["days"]
    if not days:
        pytest.skip("no supply days")
    with SessionLocal() as db:
        n0 = db.execute(select(func.count(Recommendation.id))).scalar_one()
    ex = client.get("/api/v1/logistics/example-inputs").json()
    plan = client.post(
        "/api/v1/logistics/plan",
        json={"as_of": days[0]["date"], "depots": ex["depots"][:1]},
    ).json()
    assert plan["recommendation_id"] is None
    with SessionLocal() as db:
        assert db.execute(select(func.count(Recommendation.id))).scalar_one() == n0
