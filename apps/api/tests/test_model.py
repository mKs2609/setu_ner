"""
Tests for the Phase 3 accessibility model.

Most of what could go wrong here is silent: a day with no report quietly
becoming a "not flooded" label, a validation split leaking tomorrow into
yesterday, coefficients applied to reordered features. None of those crash.
They just produce a model that looks better than it is. So those are what is
tested, without a database.
"""

from datetime import date, timedelta

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.services.model import damage_matching
from app.services.model import district_model as dm
from app.services.model import score as scoring
from app.services.model.dataset import (
    FEATURES,
    RAIN_FEATURES,
    build_examples,
    build_history,
    district_key,
    features_for,
    rain_features,
)

client = TestClient(app)
D0 = date(2025, 7, 1)


def day(n: int) -> date:
    return D0 + timedelta(days=n)


# ---------------------------------------------------------------------------
# Labels
# ---------------------------------------------------------------------------


def test_pdf_line_breaks_do_not_split_a_district_in_two():
    assert district_key("Bongaigao n") == district_key("Bongaigaon")
    assert district_key("Lakhimpu r") == district_key("Lakhimpur")


def test_renamed_corridor_district_joins_the_road_graph():
    assert district_key("Sribhumi") == "Karimganj"


def test_a_day_without_a_report_is_unknown_not_quiet():
    """The single most important rule: if the portal was down, the district
    was not therefore dry."""
    history = build_history(
        [day(0), day(2)],
        [(day(0), "Cachar", "district_reported_affected", 1.0)],
    )
    assert history.state("Cachar", day(0)).affected is True
    assert history.state("Cachar", day(1)) is None
    assert history.state("Cachar", day(2)).affected is False


def test_observations_on_unpublished_days_are_ignored():
    history = build_history(
        [day(0)],
        [(day(1), "Cachar", "population_affected", 500.0)],
    )
    assert history.state("Cachar", day(1)) is None


def test_examples_skip_targets_with_no_report():
    history = build_history(
        [day(0), day(1), day(3)],
        [(day(0), "Cachar", "population_affected", 10.0)],
    )
    examples = build_examples(history, horizon_days=1)
    # day(0)->day(1) exists; day(1)->day(2) has no report and must be skipped
    assert {(e.as_of, e.target_date) for e in examples} == {(day(0), day(1))}


def test_features_never_look_past_the_as_of_day():
    history = build_history(
        [day(0), day(1)],
        [(day(1), "Cachar", "population_affected", 1000.0)],
    )
    f = features_for(history, "Cachar", day(0))
    assert f["affected"] == 0.0
    assert f["log_population"] == 0.0


def test_a_missing_report_neither_extends_nor_breaks_a_run():
    history = build_history(
        [day(0), day(2)],
        [
            (day(0), "Cachar", "district_reported_affected", 1.0),
            (day(2), "Cachar", "district_reported_affected", 1.0),
        ],
    )
    assert features_for(history, "Cachar", day(2))["run_length"] == pytest.approx(2 / 14)


def test_feature_vector_order_matches_features():
    history = build_history([day(0), day(1)], [(day(0), "Cachar", "villages_affected", 3.0)])
    (e,) = [x for x in build_examples(history, 1) if x.district == "Cachar"]
    assert len(e.x) == len(FEATURES)
    assert e.x[FEATURES.index("affected")] == 1.0


# ---------------------------------------------------------------------------
# Validation and selection
# ---------------------------------------------------------------------------


def _synthetic(days: int = 80, districts: int = 6, seed: int = 0):
    """Sticky floods with occasional onsets -- the shape of the real data."""
    rng = np.random.default_rng(seed)
    published = [day(i) for i in range(days)]
    obs = []
    for d in range(districts):
        affected = False
        for i in range(days):
            affected = rng.random() < (0.85 if affected else 0.05)
            if affected:
                obs.append((day(i), f"District{d}", "population_affected", 100.0))
    return build_history(published, obs)


def test_rolling_validation_never_trains_on_the_future():
    examples = build_examples(_synthetic(), 1)
    splits = dm.rolling_validation(examples)
    assert splits
    for train, val in splits:
        assert max(e.target_date for e in train) < min(e.as_of for e in val)


def test_selection_never_sees_the_test_season():
    history = _synthetic(days=120)
    examples = build_examples(history, 1)
    test_from = day(90)
    payload = dm.train_and_evaluate(examples, 1, test_from)
    assert date.fromisoformat(payload["train_period"]["to"]) < test_from
    assert date.fromisoformat(payload["test_period"]["from"]) >= test_from


def test_every_result_is_reported_against_baselines():
    payload = dm.train_and_evaluate(build_examples(_synthetic(days=120), 1), 1, day(90))
    tm = payload["test_metrics"]
    assert {"served", "persistence", "climatology"} <= set(tm)
    assert "onset" in tm["served"] and "recession" in tm["served"]
    assert "skill_vs_persistence" in payload["verdict"]


def test_persistence_is_blind_to_onset_by_construction():
    """If this ever fails, the onset metric is not measuring what the docs say."""
    examples = build_examples(_synthetic(days=120), 1)
    p = dm.fit_persistence(examples)
    onset = dm.evaluate(p, examples)["onset"]
    assert onset["roc_auc"] in (None, 0.5)


def test_too_little_history_falls_back_to_a_baseline_not_an_unvalidated_model():
    history = _synthetic(days=4, districts=3, seed=3)
    examples = build_examples(history, 1)
    chosen, info = dm.select(examples)
    assert info["validation_folds"] == 0
    assert chosen.kind == "persistence"


def test_probabilities_are_never_certain():
    p = dm.Predictor("persistence", {"p_given_affected": 1.0, "p_given_not_affected": 0.0})
    out = p.predict(np.zeros((2, len(FEATURES))), np.array([1, 0]))
    assert 0 < out.min() and out.max() < 1


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------


def test_auc_matches_a_hand_computed_case():
    y = np.array([0, 0, 1, 1])
    p = np.array([0.1, 0.4, 0.35, 0.8])
    assert dm._auc(y, p) == pytest.approx(0.75)


def test_auc_is_none_with_one_class():
    assert dm._auc(np.array([1, 1]), np.array([0.2, 0.9])) is None


def test_brier_of_a_perfect_forecast_is_near_zero():
    y = np.array([0, 1, 1, 0])
    assert dm.score(y, y.astype(float))["brier"] < 1e-5


# ---------------------------------------------------------------------------
# Rainfall
# ---------------------------------------------------------------------------


def _with_rain(history, key, mm_by_day):
    history.rainfall.update({(key, d): mm for d, mm in mm_by_day.items()})
    return history


def test_rain_is_lagged_one_day_to_match_what_exists_at_scoring_time():
    """Report D is scored at 07:30 on D+1; rain for D is published at 20:00
    on D+1. Training on same-day rain would test better than it can run."""
    h = build_history([day(10)], [(day(10), "Cachar", "population_affected", 1.0)])
    _with_rain(h, "Cachar", {day(10 - b): 0.0 for b in range(8)})
    h.rainfall[("Cachar", day(10))] = 500.0  # same-day: must not be used
    h.rainfall[("Cachar", day(9))] = 20.0    # yesterday: is the newest used
    f = rain_features(h, "Cachar", day(10))
    assert np.expm1(f["rain_1d"]) == pytest.approx(20.0)
    assert np.expm1(f["rain_7d"]) == pytest.approx(20.0)


def test_rain_windows_sum_the_right_days():
    h = build_history([day(10)], [])
    _with_rain(h, "Cachar", {day(9 - b): float(b + 1) for b in range(7)})  # 1..7 mm
    f = rain_features(h, "Cachar", day(10))
    assert np.expm1(f["rain_1d"]) == pytest.approx(1.0)
    assert np.expm1(f["rain_3d"]) == pytest.approx(1 + 2 + 3)
    assert np.expm1(f["rain_7d"]) == pytest.approx(sum(range(1, 8)))


def test_a_gap_in_rainfall_is_missing_not_dry():
    """Summing the days that happen to exist would teach the model that a
    satellite outage is a dry spell."""
    h = build_history([day(10)], [])
    _with_rain(h, "Cachar", {day(9 - b): 50.0 for b in range(7) if b != 4})
    assert rain_features(h, "Cachar", day(10)) == {}
    assert not set(RAIN_FEATURES) & features_for(h, "Cachar", day(10)).keys()


def test_a_rain_model_without_rain_falls_back_to_persistence_and_says_so():
    """A late NASA file must neither crash the morning run nor be read as a
    dry week. The row is served by persistence and labelled."""
    h = _synthetic(days=120)
    for key in h.districts:
        for d in range(-8, 120):
            h.rainfall[(key, day(d))] = 3.0
    feats_all = FEATURES + RAIN_FEATURES
    payload = dm.train_and_evaluate(build_examples(h, 1, features=feats_all), 1, day(90), feats_all)
    assert payload["kind"] == "logistic"

    feats = features_for(h, h.districts[0], day(100))
    assert dm.for_inputs(payload, feats) is payload  # everything present: the model

    no_rain = {k: v for k, v in feats.items() if k not in RAIN_FEATURES}
    served = dm.for_inputs(payload, no_rain)
    assert served["kind"] == "persistence"
    assert "rain_1d" in served["fallback_reason"]
    persistence = dm.Predictor("persistence", payload["baselines"]["persistence"])
    expected = persistence.predict(np.zeros((1, 1)), np.array([int(feats["affected"])]))[0]
    assert dm.predict_one(served, no_rain) == pytest.approx(expected)

    rows = scoring.forecast_districts(
        _drop_rain_for(h, day(100)), day(100), {1: payload}
    )
    assert {r["model_kind"] for r in rows} == {"persistence_fallback"}


def _drop_rain_for(history, as_of):
    history.rainfall = {k: v for k, v in history.rainfall.items() if k[1] < as_of - timedelta(days=3)}
    return history


def test_feature_sets_can_be_compared_on_identical_rows():
    h = _synthetic(days=40)
    for d in range(20, 40):  # rain for only the second half
        h.rainfall[("Cachar", day(d))] = 5.0
    with_rain = build_examples(h, 1, features=FEATURES + RAIN_FEATURES)
    base_same_rows = build_examples(h, 1, features=FEATURES, only_where=RAIN_FEATURES)
    assert [(e.district, e.as_of) for e in with_rain] == [
        (e.district, e.as_of) for e in base_same_rows
    ]
    assert len(base_same_rows) < len(build_examples(h, 1))
    with pytest.raises(ValueError, match="unknown"):
        build_examples(h, 1, features=("snowfall",))


# ---------------------------------------------------------------------------
# Artifacts
# ---------------------------------------------------------------------------


def test_artifact_round_trips_as_json(tmp_path):
    payload = dm.train_and_evaluate(build_examples(_synthetic(days=120), 1), 1, day(90))
    path = dm.save(payload, tmp_path / "m.json")
    assert path.read_text(encoding="utf-8").lstrip().startswith("{")
    assert dm.load(1, path)["version"] == payload["version"]


def test_an_artifact_using_a_feature_the_code_no_longer_computes_is_refused():
    """There is nothing correct to feed a renamed or removed feature."""
    payload = {"features": [*FEATURES, "river_level"], "kind": "logistic", "params": {}}
    with pytest.raises(ValueError, match="river_level"):
        dm.predictor_from(payload)


def test_coefficients_follow_the_artifacts_own_feature_order():
    """Reordering must not change the answer. Applying coefficients to
    features in a different order than they were fitted in gives confident
    nonsense with no error, so the order is read from the artifact."""
    payload = dm.train_and_evaluate(build_examples(_synthetic(days=120), 1), 1, day(90))
    assert payload["kind"] == "logistic"
    feats = features_for(_synthetic(days=120), "Cachar", day(60))

    order = list(reversed(payload["features"]))
    params = payload["params"]
    idx = [payload["features"].index(n) for n in order]
    reordered = {
        **payload,
        "features": order,
        "params": {
            **params,
            "scaler_mean": [params["scaler_mean"][i] for i in idx],
            "scaler_scale": [params["scaler_scale"][i] for i in idx],
            "coef": [params["coef"][i] for i in idx],
        },
    }
    assert dm.predict_one(reordered, feats) == pytest.approx(dm.predict_one(payload, feats))


def test_a_model_trained_before_rainfall_still_loads_and_predicts():
    """The deployed artifacts predate rainfall. Adding features to the code
    must not break them."""
    payload = dm.train_and_evaluate(build_examples(_synthetic(days=120), 1), 1, day(90))
    assert payload["features"] == list(FEATURES)
    feats = features_for(_synthetic(days=120), "Cachar", day(60))
    assert 0 < dm.predict_one(payload, feats) < 1
    for h in dm.HORIZONS:
        deployed = dm.load(h)
        if deployed is not None:
            dm.predictor_from(deployed)  # raises if the shipped files stopped loading


# ---------------------------------------------------------------------------
# Per-road scoring and damage matching
# ---------------------------------------------------------------------------


def test_exposure_prior_is_bounded_and_monotone():
    assert scoring.exposure(0) == 1.0
    assert scoring.exposure(-20) == 1.0  # below the floor is still the floor
    assert scoring.exposure(50) == pytest.approx(0.5)
    assert scoring.exposure(500) == scoring.EXPOSURE_FLOOR
    assert scoring.exposure(None) is None
    heights = [0, 10, 40, 80, 150]
    values = [scoring.exposure(h) for h in heights]
    assert values == sorted(values, reverse=True)


def test_a_high_road_is_never_declared_perfectly_safe():
    assert scoring.accessibility(0.99, scoring.exposure(1000)) < 1.0


def test_damage_far_from_any_road_is_not_snapped():
    assert damage_matching.quality_for(35) == "confident"
    assert damage_matching.quality_for(250) == "approximate"
    assert damage_matching.quality_for(10_970) == "none"
    assert damage_matching.quality_for(None) == "none"


# ---------------------------------------------------------------------------
# Integration -- needs the corridor database
# ---------------------------------------------------------------------------


def _db_available() -> bool:
    try:
        from sqlalchemy import text

        from app.db.session import SessionLocal

        with SessionLocal() as db:
            db.execute(text("SELECT accessibility_model_version FROM roads LIMIT 1"))
            db.execute(text("SELECT 1 FROM district_flood_forecasts LIMIT 1"))
        return True
    except Exception:
        return False


needs_db = pytest.mark.skipif(
    not _db_available(), reason="no corridor database with the Phase 3 schema (expected in CI)"
)


@needs_db
def test_current_accessibility_never_appears_without_provenance():
    from sqlalchemy import func, or_, select

    from app.db.models import Road
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        orphans = db.execute(
            select(func.count(Road.id)).where(
                Road.current_accessibility.isnot(None),
                or_(
                    Road.accessibility_model_version.is_(None),
                    Road.current_accessibility_as_of.is_(None),
                ),
            )
        ).scalar_one()
    assert orphans == 0


@needs_db
def test_scored_values_are_valid_probabilities_of_access():
    from sqlalchemy import func, select

    from app.db.models import Road
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        lo, hi = db.execute(
            select(func.min(Road.current_accessibility), func.max(Road.current_accessibility))
        ).one()
        elo, ehi = db.execute(
            select(func.min(Road.hazard_exposure), func.max(Road.hazard_exposure))
        ).one()
    if lo is None:
        pytest.skip("roads not scored yet")
    assert 0.0 <= lo <= hi <= 1.0
    assert scoring.EXPOSURE_FLOOR - 1e-9 <= elo <= ehi <= 1.0


@needs_db
def test_scoring_refuses_a_stale_report():
    result = scoring.run(today=date.today() + timedelta(days=60))
    assert result["status"] in {"stale", "no_model"}


@needs_db
def test_status_reports_baselines_and_caveats():
    r = client.get("/api/v1/model/status")
    assert r.status_code == 200
    body = r.json()
    assert "no_rainfall" in body["caveats"]
    assert "per_road_is_a_prior" in body["caveats"]
    assert body["exposure_prior"]["fitted"] is False
    for h, art in body["artifacts"].items():
        if art is None:
            continue
        assert "persistence" in art["test_metrics"]
        assert art["verdict"]["summary"]


@needs_db
def test_district_forecasts_are_probabilities_with_a_persistence_reference():
    body = client.get("/api/v1/model/districts").json()
    if not body["districts"]:
        pytest.skip("no forecasts stored yet")
    for d in body["districts"]:
        # Every horizon must survive the "latest forecast wins" filter -- an
        # earlier version dropped every 1-day forecast.
        assert {f["horizon_days"] for f in d["forecasts"]} == set(dm.HORIZONS)
        for f in d["forecasts"]:
            assert 0 < f["probability"] < 1
            assert 0 < f["persistence_probability"] < 1


@needs_db
def test_accessibility_endpoint_separates_model_from_baseline():
    from sqlalchemy import select

    from app.db.models import Road
    from app.db.session import SessionLocal

    with SessionLocal() as db:
        road_id = db.execute(
            select(Road.id).where(Road.current_accessibility.isnot(None)).limit(1)
        ).scalar()
    if road_id is None:
        pytest.skip("roads not scored yet")
    body = client.get(f"/api/v1/accessibility/{road_id}").json()
    assert body["model"]["model_version"]
    assert body["model"]["as_of"]
    assert "terrain_exposure_prior" in body["model"]["components"]
    assert "baseline_accessibility" in body
